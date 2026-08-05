"""红利 ETF 向上倾斜网格因子。

与策略「红利倾斜网格」同源（v3）：
- 中枢 center = max(旧中枢, MA90)，只升不降
- 相对中枢跌超 step → 加一档；涨超 step → 减一档
- 至少保留 min_layers 档底仓；默认 10 档 / 步长 0.8% / 底仓 2

默认标的 515080；佣金万一、ETF 免印花税。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.factors.dividend_etf_swing import (
    dividends_as_series,
    fetch_etf_dividends,
    load_or_fetch_etf,
    resolve_etf_panel,
)
from app.services.strategies.etf_grid_backtest import (
    DEFAULT_PARAMS_V3,
    run_grid_backtest_slope_up,
)

logger = logging.getLogger("webapi.factors.dividend_etf_slope_grid")

FACTORS_DATA = Path(__file__).resolve().parents[3] / "data" / "factors"
FACTOR_ID = "dividend_etf_slope_grid"

DEFAULT_PARAMS: Dict[str, Any] = {
    "etf_code": "515080",
    "fallback_etfs": ["512890", "510880", "515180"],
    # 不复权成交；现金分红按持仓份额入账并再投入
    "price_adjust": "",
    "dividend_reinvest": True,
    "n_grids": int(DEFAULT_PARAMS_V3["n_grids"]),
    "step_pct": float(DEFAULT_PARAMS_V3["step_pct"]),
    "min_layers": int(DEFAULT_PARAMS_V3["min_layers"]),
    "ma_center": int(DEFAULT_PARAMS_V3["ma_center"]),
    "drift_daily": float(DEFAULT_PARAMS_V3.get("drift_daily") or 0.0),
    "commission_rate": float(DEFAULT_PARAMS_V3["commission_rate"]),
    "stamp_tax_sell": float(DEFAULT_PARAMS_V3["stamp_tax_sell"]),
    "cash_annual": float(DEFAULT_PARAMS_V3["cash_annual"]),
    "start": str(DEFAULT_PARAMS_V3["start"]),
    "position_logic": "slope_up_grid",
}


def _to_ui_trades(
    raw: pd.DataFrame,
    *,
    code: str,
    daily: pd.DataFrame,
    n_grids: int,
) -> pd.DataFrame:
    """把引擎 side=buy/sell 流水转成因子页可读的加仓/减仓流水。"""
    if raw is None or raw.empty:
        return pd.DataFrame()

    eq_map: Dict[str, float] = {}
    if daily is not None and not daily.empty:
        for _, r in daily.iterrows():
            d = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
            eq_map[d] = float(r["equity"])

    unit = 1.0 / max(int(n_grids), 1)
    rows: List[dict] = []
    prev_exp = 0.0
    for _, t in raw.iterrows():
        dt = pd.Timestamp(t["date"]).strftime("%Y-%m-%d")
        side = str(t.get("side") or "").lower()
        price = float(t["price"])
        layers = int(t.get("layers") or 0)
        center = t.get("center")
        if side == "dividend":
            action = "分红"
            exp = prev_exp
        elif side == "buy":
            action = "加仓"
            exp = round(layers * unit, 4)
        else:
            action = "减仓"
            exp = round(layers * unit, 4)
        eq = float(eq_map.get(dt, np.nan))
        note = str(t.get("note") or "")
        if not note:
            note = (
                f"倾斜网格·中枢{float(center):.4f}·当前{layers}档"
                if center is not None and pd.notna(center)
                else f"倾斜网格·当前{layers}档"
            )
        rows.append(
            {
                "date": dt,
                "code": code,
                "name": "红利ETF倾斜网格",
                "action": action,
                "side": side,
                "price": round(price, 4),
                "close": round(price, 4) if side != "dividend" else "",
                "layers": layers,
                "center": round(float(center), 4) if center is not None and pd.notna(center) else "",
                "buy_position": round(unit, 4) if side != "dividend" else "",
                "position_before": round(prev_exp, 4),
                "position_after": exp,
                "delta": round(exp - prev_exp, 4),
                "equity": round(eq, 4) if np.isfinite(eq) else "",
                "nav_pnl": "",
                "note": note,
            }
        )
        prev_exp = exp
    return pd.DataFrame(rows)


def _normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    out = daily.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    if "exposure" in out.columns and "position" not in out.columns:
        out["position"] = out["exposure"]
    if "layers" in out.columns:
        out["n_pos"] = out["layers"].astype(int)
    else:
        out["n_pos"] = (out["position"] > 0.05).astype(int)
    # 基准日收益：买入持有净值差分
    if "bh_equity" in out.columns:
        bh = out["bh_equity"].astype(float)
        out["bench_ret"] = bh.pct_change().fillna(0.0)
    else:
        out["bench_ret"] = out["close"].astype(float).pct_change().fillna(0.0)
    # 策略日收益（供展示）
    eq = out["equity"].astype(float)
    out["strategy_ret"] = eq.pct_change().fillna(0.0)
    cols = [
        "date",
        "close",
        "center",
        "position",
        "n_pos",
        "layers",
        "equity",
        "bh_equity",
        "bench_ret",
        "strategy_ret",
        "cash",
        "position_value",
        "exposure",
    ]
    keep = [c for c in cols if c in out.columns]
    return out[keep].reset_index(drop=True)


def run_backtest(
    params: Optional[Dict[str, Any]] = None,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force_fetch: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    code = str(p.get("etf_code") or "515080")
    start = start or str(p.get("start") or "2018-01-01")

    adjust = str(p.get("price_adjust") or "")
    # 优先走 resolve（含 fallback），再按指定代码强制拉取；倾斜网格用未复权价
    resolved_code, raw = resolve_etf_panel({**p, "price_adjust": adjust}, force=force_fetch)
    if raw.empty:
        raw = load_or_fetch_etf(
            code,
            start=start.replace("-", ""),
            end=(end or datetime.now().strftime("%Y%m%d")).replace("-", ""),
            force=force_fetch,
            adjust=adjust,
        )
        resolved_code = code
    else:
        code = resolved_code or code

    if raw is None or raw.empty:
        return pd.DataFrame(), {"error": "no_etf_data", "etf_code": code}, pd.DataFrame()

    px = raw.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date")
    px = px[px["date"] >= pd.Timestamp(start)]
    if end:
        px = px[px["date"] <= pd.Timestamp(end)]
    px = px.reset_index(drop=True)

    div_series = None
    if bool(p.get("dividend_reinvest", True)):
        # 代码里若带代理后缀，取数字代码拉分红
        div_code = "".join(ch for ch in str(code) if ch.isdigit())[:6] or str(p.get("etf_code") or "515080")
        div_series = dividends_as_series(fetch_etf_dividends(div_code, force=force_fetch))

    daily_raw, trades_raw, eng = run_grid_backtest_slope_up(
        px,
        step_pct=float(p["step_pct"]),
        n_grids=int(p["n_grids"]),
        min_layers=int(p["min_layers"]),
        ma_center=int(p["ma_center"]),
        drift_daily=float(p.get("drift_daily") or 0.0),
        commission_rate=float(p["commission_rate"]),
        stamp_tax_sell=float(p["stamp_tax_sell"]),
        cash_annual=float(p.get("cash_annual") or 0.014),
        dividends=div_series,
        dividend_reinvest=bool(p.get("dividend_reinvest", True)),
    )
    if eng.get("error") or daily_raw is None or daily_raw.empty:
        return pd.DataFrame(), {**eng, "etf_code": code, "error": eng.get("error") or "empty"}, pd.DataFrame()

    daily = _normalize_daily(daily_raw)
    trades = _to_ui_trades(trades_raw, code=code, daily=daily, n_grids=int(p["n_grids"]))

    grid = eng.get("grid") or {}
    bh = eng.get("buy_hold") or {}
    summary = {
        "position_logic": "slope_up_grid",
        "etf_code": code,
        "bars": int(grid.get("n_days") or len(daily)),
        "start": pd.Timestamp(daily["date"].iloc[0]).strftime("%Y-%m-%d"),
        "end": pd.Timestamp(daily["date"].iloc[-1]).strftime("%Y-%m-%d"),
        "total_return": grid.get("total_return"),
        "annual_return": grid.get("cagr"),
        "annual_vol": grid.get("vol"),
        "sharpe": grid.get("sharpe"),
        "max_drawdown": grid.get("max_dd"),
        "calmar": grid.get("calmar"),
        "buy_hold_return": bh.get("total_return"),
        "buy_hold_cagr": bh.get("cagr"),
        "buy_hold_sharpe": bh.get("sharpe"),
        "avg_position": round(float(daily["position"].mean()), 4),
        "n_trades": eng.get("n_trades"),
        "n_buys": eng.get("n_buys"),
        "n_sells": eng.get("n_sells"),
        "final_layers": eng.get("final_layers"),
        "final_center": eng.get("final_center"),
        "step_pct": eng.get("step_pct"),
        "n_grids": eng.get("n_grids"),
        "min_layers": eng.get("min_layers"),
        "ma_center": eng.get("ma_center"),
        "commission_rate": float(p["commission_rate"]),
        "stamp_tax_sell": float(p["stamp_tax_sell"]),
        "price_adjust": adjust or "raw",
        "dividend_reinvest": bool(p.get("dividend_reinvest", True)),
        "n_dividend_events": eng.get("n_dividend_events"),
        "total_dividend_cash": eng.get("total_dividend_cash"),
        "total_cash_interest": eng.get("total_cash_interest"),
        "cash_annual": eng.get("cash_annual"),
        "excess_cagr": eng.get("excess_cagr"),
        "excess_sharpe": eng.get("excess_sharpe"),
        "note": (
            f"红利ETF倾斜网格 · {code} · 不复权+分红再投入+现金约{float(p.get('cash_annual') or 0)*100:.1f}%计息 · "
            f"step{float(p['step_pct'])*100:.1f}%/档{p['n_grids']}/底仓≥{p['min_layers']}/MA{p['ma_center']}"
        ),
    }
    return daily, summary, trades


def compute_dividend_etf_slope_grid_signal(
    params: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    code, raw = resolve_etf_panel(p)
    if raw.empty:
        return {
            "factor_id": FACTOR_ID,
            "asof": asof or datetime.now().isoformat(timespec="seconds"),
            "signal": "neutral",
            "value": 0.0,
            "components": {"etf": code, "error": "no_data"},
            "note": "无红利ETF行情",
        }
    if asof:
        raw = raw[raw["date"] <= pd.Timestamp(asof)]
    daily, summary, _ = run_backtest(p, start=str(p.get("start") or "2018-01-01"), end=asof)
    if daily.empty or summary.get("error"):
        return {
            "factor_id": FACTOR_ID,
            "asof": asof or datetime.now().isoformat(timespec="seconds"),
            "signal": "neutral",
            "value": 0.0,
            "components": {"etf": code, "error": summary.get("error")},
            "note": "回测/信号计算失败",
        }
    last = daily.iloc[-1]
    price = float(last["close"])
    center = float(last["center"]) if "center" in last and pd.notna(last["center"]) else price
    step = float(p["step_pct"])
    layers = int(last["n_pos"]) if "n_pos" in last else int(last.get("layers") or 0)
    dist = price / center - 1.0 if center > 0 else 0.0
    if dist <= -step and layers < int(p["n_grids"]):
        signal = "buy"
    elif dist >= step and layers > int(p["min_layers"]):
        signal = "sell"
    elif layers > int(p["min_layers"]):
        signal = "hold"
    else:
        signal = "neutral"
    return {
        "factor_id": FACTOR_ID,
        "asof": pd.Timestamp(last["date"]).strftime("%Y-%m-%d"),
        "signal": signal,
        "value": round(float(last["position"]), 4),
        "components": {
            "etf": summary.get("etf_code") or code,
            "close": price,
            "center": round(center, 4),
            "dist_to_center_pct": round(dist * 100, 2),
            "layers": layers,
            "step_pct": step,
            "n_grids": int(p["n_grids"]),
            "min_layers": int(p["min_layers"]),
            "ma_center": int(p["ma_center"]),
            "position_logic": "slope_up_grid",
        },
        "note": f"{code} 倾斜网格仓位={float(last['position']):.0%}·{layers}档·距中枢{dist*100:.1f}%",
    }
