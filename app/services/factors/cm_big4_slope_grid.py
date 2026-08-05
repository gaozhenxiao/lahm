"""中国移动 + 四大行等权倾斜网格因子。

与策略「移动四大行网格」同源：五袖口独立 v3 倾斜网格后汇总。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from app.services.strategies.cm_big4_grid import (
    DEFAULT_PARAMS,
    DEFAULT_START,
    UNIVERSE,
    _ma_center,
    load_stock_raw,
    run_basket,
)

logger = logging.getLogger("webapi.factors.cm_big4_slope_grid")

FACTORS_DATA = Path(__file__).resolve().parents[3] / "data" / "factors"
FACTOR_ID = "cm_big4_slope_grid"

FACTOR_DEFAULTS: Dict[str, Any] = {
    **DEFAULT_PARAMS,
    "position_logic": "cm_big4_slope_grid",
    "start": DEFAULT_START,
}


def run_backtest(
    params: Optional[Dict[str, Any]] = None,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force_fetch: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    p = {**FACTOR_DEFAULTS, **(params or {})}
    start = start or str(p.get("start") or DEFAULT_START)
    batch = run_basket(start=start, end=end, force=force_fetch, params=p, quiet=True)
    if batch.get("error"):
        return pd.DataFrame(), {"error": batch.get("error"), **(batch.get("details") or {})}, pd.DataFrame()

    combined = batch["combined"]
    payload = batch["payload"]
    port = payload.get("portfolio") or {}
    g, b = port.get("grid") or {}, port.get("buy_hold") or {}

    daily = combined.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["position"] = daily["exposure"]
    daily["n_pos"] = (daily["exposure"] > 0.05).astype(int)
    daily["bench_ret"] = daily["bh_equity"].astype(float).pct_change().fillna(0.0)
    daily["strategy_ret"] = daily["equity"].astype(float).pct_change().fillna(0.0)

    summary = {
        "position_logic": "cm_big4_slope_grid",
        "bars": int(port.get("bars") or len(daily)),
        "start": port.get("start"),
        "end": port.get("end"),
        "total_return": g.get("total_return"),
        "annual_return": g.get("cagr"),
        "annual_vol": g.get("vol"),
        "sharpe": g.get("sharpe"),
        "max_drawdown": g.get("max_dd"),
        "calmar": g.get("calmar"),
        "buy_hold_return": b.get("total_return"),
        "buy_hold_cagr": b.get("cagr"),
        "buy_hold_sharpe": b.get("sharpe"),
        "avg_position": port.get("avg_exposure"),
        "excess_cagr": port.get("excess_cagr"),
        "excess_sharpe": port.get("excess_sharpe"),
        "stamp_tax_sell": p.get("stamp_tax_sell"),
        "cash_annual": p.get("cash_annual"),
        "dividend_reinvest": True,
        "universe": [c for c, _ in UNIVERSE],
        "per_name": payload.get("per_name"),
        "note": "移动+工农中建等权倾斜网格 · 分红再投入 · 现金1.4%计息 · 印花税千一",
    }
    return daily, summary, pd.DataFrame()


def compute_cm_big4_slope_grid_signal(
    params: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    p = {**FACTOR_DEFAULTS, **(params or {})}
    step = float(p.get("step_pct") or 0.008)
    zones = []
    components: Dict[str, Any] = {}
    last_date = None
    for code, name in UNIVERSE:
        df = load_stock_raw(code, start="20180101", force=False)
        if asof and not df.empty:
            df = df[df["date"] <= pd.Timestamp(asof)]
        if df.empty:
            continue
        price = float(df["close"].iloc[-1])
        last_date = pd.Timestamp(df["date"].iloc[-1]).strftime("%Y-%m-%d")
        center = _ma_center(code) or price
        dist = price / center - 1.0 if center > 0 else 0.0
        if dist <= -step:
            zone = "buy"
        elif dist >= step:
            zone = "sell"
        else:
            zone = "hold"
        zones.append(zone)
        components[code] = {
            "name": name,
            "close": price,
            "center": round(center, 4),
            "dist_pct": round(dist * 100, 2),
            "zone": zone,
        }
    if not zones:
        return {
            "factor_id": FACTOR_ID,
            "asof": asof or datetime.now().isoformat(timespec="seconds"),
            "signal": "neutral",
            "value": 0.0,
            "components": {"error": "no_data"},
            "note": "无行情",
        }
    buy_n = zones.count("buy")
    sell_n = zones.count("sell")
    if buy_n >= 3:
        signal = "buy"
    elif sell_n >= 3:
        signal = "sell"
    elif buy_n + sell_n == 0:
        signal = "hold"
    else:
        signal = "neutral"
    return {
        "factor_id": FACTOR_ID,
        "asof": asof or last_date or datetime.now().isoformat(timespec="seconds"),
        "signal": signal,
        "value": round(buy_n / len(zones), 4),
        "components": {
            "step_pct": step,
            "names": components,
            "buy_n": buy_n,
            "sell_n": sell_n,
        },
        "note": f"移动+四大行 加仓区{buy_n}/减仓区{sell_n}/共{len(zones)}",
    }
