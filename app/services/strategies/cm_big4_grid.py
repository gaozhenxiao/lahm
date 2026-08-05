# -*- coding: utf-8 -*-
"""中国移动 + 四大行（工农中建）等权分仓 · 向上倾斜网格。

口径：
- 每标的独立网格，资金等权 1/5，再汇总组合净值
- 不复权成交；现金分红入账并可再投入；空闲现金约 1.4% 计息
- 个股卖出印花税千一；佣金万一
- 默认参数同红利倾斜网格：步长 0.8% / 10 档 / 底仓≥2 / MA90
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.factors.dividend_etf_swing import (
    FACTORS_DATA,
    _fetch_etf_via_baostock,
    load_or_fetch_etf,
)
from app.services.strategies.common import cached_scan, now_iso, safe_float
from app.services.strategies.etf_grid import _slope_levels
from app.services.strategies.etf_grid_backtest import (
    DEFAULT_PARAMS_V3,
    _metrics,
    run_grid_backtest_slope_up,
)

logger = logging.getLogger("webapi.strategies.cm_big4_grid")

ROOT = Path(__file__).resolve().parents[3]
BT_JSON = ROOT / "data" / "strategies" / "cm_big4_slope_grid_backtest.json"
BT_CSV = ROOT / "data" / "strategies" / "cm_big4_slope_grid_daily.csv"

UNIVERSE: List[Tuple[str, str]] = [
    ("600941", "中国移动"),
    ("601398", "工商银行"),
    ("601939", "建设银行"),
    ("601288", "农业银行"),
    ("601988", "中国银行"),
]

STEP_PCT = float(DEFAULT_PARAMS_V3["step_pct"])
N_GRIDS = int(DEFAULT_PARAMS_V3["n_grids"])
MIN_LAYERS = int(DEFAULT_PARAMS_V3["min_layers"])
MA_CENTER = int(DEFAULT_PARAMS_V3["ma_center"])
DEFAULT_START = "2022-01-05"

DEFAULT_PARAMS: Dict[str, Any] = {
    **DEFAULT_PARAMS_V3,
    "stamp_tax_sell": 0.001,
    "start": DEFAULT_START,
    "dividend_reinvest": True,
    "price_adjust": "",
}


def load_stock_raw(
    symbol: str,
    *,
    start: str = "20160101",
    end: Optional[str] = None,
    force: bool = False,
) -> pd.DataFrame:
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    path = FACTORS_DATA / f"{symbol}_daily.parquet"
    if path.exists() and not force:
        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            out = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
            if len(out) >= 60:
                return out
        except Exception:  # noqa: BLE001
            pass

    hist = _fetch_etf_via_baostock(symbol, start=start, end=end, adjust="")
    if hist is None or getattr(hist, "empty", True) or "date" not in getattr(hist, "columns", []):
        try:
            hist = load_or_fetch_etf(symbol, start=start, end=end, force=force, adjust="")
        except Exception:  # noqa: BLE001
            hist = pd.DataFrame()
    if hist is None or getattr(hist, "empty", True) or "date" not in getattr(hist, "columns", []):
        return pd.DataFrame()
    hist = hist.copy()
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
    hist = hist.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    try:
        FACTORS_DATA.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache write %s failed: %s", path, exc)
    return hist


def fetch_stock_dividends(symbol: str, *, force: bool = False) -> pd.Series:
    path = FACTORS_DATA / f"{symbol}_dividends.parquet"
    if path.exists() and not force:
        try:
            cached = pd.read_parquet(path)
            cached["date"] = pd.to_datetime(cached["date"], errors="coerce")
            cached["dps"] = pd.to_numeric(cached["dps"], errors="coerce")
            out = cached.dropna(subset=["date", "dps"])
            out = out[out["dps"] > 0].sort_values("date")
            if not out.empty:
                return out.set_index("date")["dps"].astype(float)
        except Exception:  # noqa: BLE001
            pass

    import os

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"

    rows: List[dict] = []
    try:
        import akshare as ak

        raw = ak.stock_fhps_detail_em(symbol=str(symbol))
        if raw is not None and not raw.empty:
            cols = list(raw.columns)
            ex_col = next((c for c in cols if "除权除息" in str(c)), None)
            dps_col = next(
                (c for c in cols if "现金分红比例" in str(c) and "描述" not in str(c)),
                None,
            )
            if ex_col is None:
                ex_col = cols[-3] if len(cols) >= 3 else None
            if dps_col is None:
                dps_col = next((c for c in cols if "现金分红" in str(c) and "描述" not in str(c)), None)
            if ex_col and dps_col:
                for _, r in raw.iterrows():
                    dt = pd.to_datetime(r[ex_col], errors="coerce")
                    px10 = pd.to_numeric(r[dps_col], errors="coerce")
                    if pd.isna(dt) or pd.isna(px10) or float(px10) <= 0:
                        continue
                    rows.append({"date": dt, "dps": float(px10) / 10.0})
    except Exception as exc:  # noqa: BLE001
        logger.warning("dividend em %s: %s", symbol, exc)

    if not rows:
        try:
            import akshare as ak

            raw = ak.stock_history_dividend_detail(symbol=str(symbol), indicator="分红")
            if raw is not None and not raw.empty:
                cols = list(raw.columns)
                px_col = next((c for c in cols if "派息" in str(c)), cols[3] if len(cols) > 3 else None)
                ex_col = next((c for c in cols if "除权除息" in str(c)), cols[5] if len(cols) > 5 else None)
                if px_col and ex_col:
                    for _, r in raw.iterrows():
                        dt = pd.to_datetime(r[ex_col], errors="coerce")
                        px10 = pd.to_numeric(r[px_col], errors="coerce")
                        if pd.isna(dt) or pd.isna(px10) or float(px10) <= 0:
                            continue
                        rows.append({"date": dt, "dps": float(px10) / 10.0})
        except Exception as exc:  # noqa: BLE001
            logger.warning("dividend hist %s: %s", symbol, exc)

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows).dropna().drop_duplicates("date").sort_values("date")
    try:
        FACTORS_DATA.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    except Exception:  # noqa: BLE001
        pass
    return df.set_index("date")["dps"].astype(float)


def _combine_sleeves(sleeves: Dict[str, pd.DataFrame], *, weight: float) -> pd.DataFrame:
    frames = []
    for code, daily in sleeves.items():
        if daily is None or daily.empty:
            continue
        s = daily[["date", "equity", "bh_equity", "exposure"]].copy()
        s["date"] = pd.to_datetime(s["date"])
        s = s.set_index("date").sort_index()
        s["equity"] = s["equity"].astype(float) * weight
        s["bh_equity"] = s["bh_equity"].astype(float) * weight
        s = s.rename(
            columns={
                "equity": f"eq_{code}",
                "bh_equity": f"bh_{code}",
                "exposure": f"exp_{code}",
            }
        )
        frames.append(s)
    if not frames:
        return pd.DataFrame()
    m = frames[0]
    for f in frames[1:]:
        m = m.join(f, how="outer")
    m = m.sort_index().ffill().dropna(how="all")
    eq_cols = [c for c in m.columns if c.startswith("eq_")]
    bh_cols = [c for c in m.columns if c.startswith("bh_")]
    exp_cols = [c for c in m.columns if c.startswith("exp_")]
    out = pd.DataFrame(
        {
            "date": m.index,
            "equity": m[eq_cols].sum(axis=1),
            "bh_equity": m[bh_cols].sum(axis=1),
            "exposure": m[exp_cols].mean(axis=1),
        }
    ).reset_index(drop=True)
    if len(out) and out["equity"].iloc[0] > 0:
        scale_g = 1.0 / float(out["equity"].iloc[0])
        scale_b = 1.0 / float(out["bh_equity"].iloc[0]) if out["bh_equity"].iloc[0] > 0 else 1.0
        out["equity"] *= scale_g
        out["bh_equity"] *= scale_b
    return out


def run_basket(
    *,
    start: str = DEFAULT_START,
    end: Optional[str] = None,
    force: bool = False,
    params: Optional[Dict[str, Any]] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    p["stamp_tax_sell"] = float(p.get("stamp_tax_sell") or 0.001)
    start_ts = pd.Timestamp(start)
    weight = 1.0 / len(UNIVERSE)

    sleeves: Dict[str, pd.DataFrame] = {}
    details: Dict[str, Any] = {}
    for code, name in UNIVERSE:
        px = load_stock_raw(code, start="20160101", end=end, force=force)
        if px.empty:
            details[code] = {"name": name, "error": "no_price"}
            continue
        px = px[px["date"] >= start_ts]
        if end:
            px = px[px["date"] <= pd.Timestamp(end)]
        px = px.reset_index(drop=True)
        if len(px) < max(int(p["ma_center"]) + 5, 80):
            details[code] = {"name": name, "error": "insufficient_bars", "n": len(px)}
            continue
        divs = fetch_stock_dividends(code, force=force)
        daily, _trades, summary = run_grid_backtest_slope_up(
            px,
            step_pct=float(p["step_pct"]),
            n_grids=int(p["n_grids"]),
            min_layers=int(p["min_layers"]),
            ma_center=int(p["ma_center"]),
            drift_daily=float(p.get("drift_daily") or 0.0),
            commission_rate=float(p["commission_rate"]),
            stamp_tax_sell=float(p["stamp_tax_sell"]),
            cash_annual=float(p.get("cash_annual") or 0.014),
            dividends=divs,
            dividend_reinvest=bool(p.get("dividend_reinvest", True)),
        )
        if summary.get("error") or daily.empty:
            details[code] = {"name": name, "error": summary.get("error") or "empty"}
            continue
        sleeves[code] = daily
        g, b = summary.get("grid") or {}, summary.get("buy_hold") or {}
        details[code] = {
            "code": code,
            "name": name,
            "start": str(daily["date"].iloc[0].date()),
            "end": str(daily["date"].iloc[-1].date()),
            "n_bars": len(daily),
            "n_div": int(summary.get("n_dividend_events") or 0),
            "div_cash": summary.get("total_dividend_cash"),
            "interest": summary.get("total_cash_interest"),
            "grid_cagr": g.get("cagr"),
            "bh_cagr": b.get("cagr"),
            "grid_sharpe": g.get("sharpe"),
            "bh_sharpe": b.get("sharpe"),
            "grid_max_dd": g.get("max_dd"),
            "bh_max_dd": b.get("max_dd"),
            "excess_cagr": summary.get("excess_cagr"),
            "n_trades": summary.get("n_trades"),
            "avg_exposure": round(float(daily["exposure"].mean()), 4),
        }
        if not quiet:
            logger.info(
                "%s %s grid_cagr=%s bh=%s divN=%s",
                code,
                name,
                g.get("cagr"),
                b.get("cagr"),
                summary.get("n_dividend_events"),
            )

    combined = _combine_sleeves(sleeves, weight=weight)
    if combined.empty:
        return {"error": "no_sleeves", "details": details}

    combined_ix = combined.set_index("date", drop=False)
    grid_m = _metrics(combined_ix["equity"], ann_cash=float(p.get("cash_annual") or 0.014))
    bh_m = _metrics(combined_ix["bh_equity"], ann_cash=float(p.get("cash_annual") or 0.014))
    summary_table = [
        {
            "code": "PORT",
            "name": "组合(等权)",
            "grid_cagr": grid_m.get("cagr"),
            "bh_cagr": bh_m.get("cagr"),
            "excess_cagr": round(grid_m.get("cagr", 0) - bh_m.get("cagr", 0), 4),
            "grid_sharpe": grid_m.get("sharpe"),
            "bh_sharpe": bh_m.get("sharpe"),
            "grid_max_dd": grid_m.get("max_dd"),
            "bh_max_dd": bh_m.get("max_dd"),
            "n_trades": None,
        }
    ]
    for code, _name in UNIVERSE:
        row = details.get(code) or {}
        if row.get("error"):
            continue
        summary_table.append(
            {
                "code": code,
                "name": row.get("name"),
                "grid_cagr": row.get("grid_cagr"),
                "bh_cagr": row.get("bh_cagr"),
                "excess_cagr": row.get("excess_cagr"),
                "grid_sharpe": row.get("grid_sharpe"),
                "bh_sharpe": row.get("bh_sharpe"),
                "grid_max_dd": row.get("grid_max_dd"),
                "bh_max_dd": row.get("bh_max_dd"),
                "n_trades": row.get("n_trades"),
            }
        )

    payload = {
        "asof": pd.Timestamp.now().isoformat(timespec="seconds"),
        "universe": [{"code": c, "name": n} for c, n in UNIVERSE],
        "rule": "等权分仓·向上倾斜网格；不复权+现金分红再投入+现金1.4%计息；个股印花税千一",
        "params": {
            **{
                k: p[k]
                for k in (
                    "n_grids",
                    "step_pct",
                    "min_layers",
                    "ma_center",
                    "commission_rate",
                    "stamp_tax_sell",
                    "cash_annual",
                    "dividend_reinvest",
                )
            },
            "start": start,
            "end": end,
            "weighting": "equal_sleeve",
        },
        "portfolio": {
            "start": str(combined["date"].iloc[0].date()),
            "end": str(combined["date"].iloc[-1].date()),
            "bars": len(combined),
            "avg_exposure": round(float(combined["exposure"].mean()), 4),
            "grid": grid_m,
            "buy_hold": bh_m,
            "excess_cagr": round(grid_m.get("cagr", 0) - bh_m.get("cagr", 0), 4),
            "excess_sharpe": round(grid_m.get("sharpe", 0) - bh_m.get("sharpe", 0), 3),
        },
        "per_name": details,
        "summary_table": summary_table,
        "notes": [
            "组合=中国移动600941 + 工农中建 等权五袖口独立网格后再汇总",
            "共同样本受中国移动A股上市日约束（约2022-01）",
            "个股印花税千一；与红利ETF网格比绝对收益时注意税率差异",
        ],
    }
    return {"payload": payload, "combined": combined.reset_index(drop=True), "sleeves": sleeves}


def save_batch_outputs(batch: Dict[str, Any], *, out_dir: Optional[Path] = None) -> Path:
    out_dir = Path(out_dir or (ROOT / "data" / "strategies"))
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = batch["payload"]
    path = out_dir / "cm_big4_slope_grid_backtest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    combined = batch.get("combined")
    if isinstance(combined, pd.DataFrame) and not combined.empty:
        combined.to_csv(out_dir / "cm_big4_slope_grid_daily.csv", index=False, encoding="utf-8-sig")
    return path


def _ma_center(code: str) -> Optional[float]:
    try:
        df = load_stock_raw(code, start="20180101", force=False)
        if df is None or df.empty or "close" not in df.columns:
            return None
        s = df.sort_values("date")["close"].astype(float)
        if len(s) < MA_CENTER:
            return float(s.iloc[-1])
        return float(s.rolling(MA_CENTER).mean().iloc[-1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("ma_center %s failed: %s", code, exc)
        return None


def _last_close(code: str) -> Optional[float]:
    df = load_stock_raw(code, start="20180101", force=False)
    if df is None or df.empty:
        return None
    return float(df.sort_values("date")["close"].iloc[-1])


def _fetch_stock_spot() -> Dict[str, Dict[str, Any]]:
    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        code_col = "代码" if "代码" in spot.columns else "code"
        out: Dict[str, Dict[str, Any]] = {}
        want = {c for c, _ in UNIVERSE}
        for _, r in spot.iterrows():
            code = str(r[code_col]).zfill(6)
            if code in want:
                out[code] = r.to_dict()
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock spot failed: %s", exc)
        return {}


def _load_backtest(*, refresh: bool = False) -> Dict[str, Any]:
    if refresh or not BT_JSON.exists():
        try:
            batch = run_basket(start=DEFAULT_START, force=False, params=dict(DEFAULT_PARAMS), quiet=True)
            if not batch.get("error"):
                save_batch_outputs(batch)
        except Exception as exc:  # noqa: BLE001
            logger.exception("cm_big4 backtest refresh failed: %s", exc)
            if not BT_JSON.exists():
                return {"error": str(exc), "summary_table": []}
    try:
        return json.loads(BT_JSON.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "summary_table": []}


def _scan(*, refresh_bt: bool = False) -> Dict[str, Any]:
    by_code = _fetch_stock_spot()
    bt = _load_backtest(refresh=refresh_bt)
    bt_by_code = {
        str(r.get("code")).zfill(6) if str(r.get("code")) != "PORT" else "PORT": r
        for r in (bt.get("summary_table") or [])
        if isinstance(r, dict) and r.get("code")
    }
    per_name = bt.get("per_name") or {}

    items: List[Dict[str, Any]] = []
    for code, name in UNIVERSE:
        r = by_code.get(code)
        center = _ma_center(code)
        px = safe_float(r.get("最新价")) if r else _last_close(code)
        bt_row = bt_by_code.get(code) or per_name.get(code) or {}

        item: Dict[str, Any] = {
            "code": code,
            "name": str((r or {}).get("名称") or name),
            "available": bool(px and px > 0 and center),
            "price": px,
            "change_pct": safe_float((r or {}).get("涨跌幅")),
            "amount": safe_float((r or {}).get("成交额")),
        }
        if center and px and px > 0:
            item.update(_slope_levels(center, float(px), STEP_PCT, N_GRIDS))
            item["step_pct"] = round(STEP_PCT * 100, 2)
            item["n_grids"] = N_GRIDS
            item["min_layers"] = MIN_LAYERS
            item["ma_center"] = MA_CENTER
            item["style"] = "slope_up"
        elif center:
            item["center"] = round(center, 4)
            item["hint"] = "无现价，仅给出中枢参考"
            item["available"] = False
        else:
            item["hint"] = "行情/均线不足"
            item["available"] = False

        if bt_row and not bt_row.get("error"):
            item["bt_cagr"] = bt_row.get("grid_cagr")
            item["bt_bh_cagr"] = bt_row.get("bh_cagr")
            item["bt_excess"] = bt_row.get("excess_cagr")
            item["bt_sharpe"] = bt_row.get("grid_sharpe")
            item["bt_max_dd"] = bt_row.get("grid_max_dd")
            item["bt_bh_max_dd"] = bt_row.get("bh_max_dd")

        items.append(item)

    port = bt.get("portfolio") or {}
    g, b = port.get("grid") or {}, port.get("buy_hold") or {}
    ready = sum(1 for x in items if x.get("available"))
    return {
        "asof": now_iso(),
        "strategy": "cm_big4_grid",
        "variant": "slope_up_equal_sleeve",
        "source": "akshare.stock_zh_a_spot_em + baostock daily",
        "params": {
            "step_pct": STEP_PCT,
            "n_grids": N_GRIDS,
            "min_layers": MIN_LAYERS,
            "ma_center": MA_CENTER,
            "stamp_tax_sell": 0.001,
            "cash_annual": DEFAULT_PARAMS.get("cash_annual"),
            "start": DEFAULT_START,
        },
        "summary": {
            "n_universe": len(UNIVERSE),
            "n_ready": ready,
            "组合CAGR": f"{(g.get('cagr') or 0)*100:.1f}%" if g else "—",
            "持有CAGR": f"{(b.get('cagr') or 0)*100:.1f}%" if b else "—",
            "Sharpe": f"{g.get('sharpe'):.2f}" if g.get("sharpe") is not None else "—",
            "最大回撤": f"{(g.get('max_dd') or 0)*100:.1f}%" if g else "—",
        },
        "items": items,
        "backtest": {
            "rule": bt.get("rule"),
            "asof": bt.get("asof"),
            "summary_table": bt.get("summary_table") or [],
            "portfolio": port,
            "notes": bt.get("notes") or [],
        },
        "notes": [
            "中国移动 + 工农中建：等权五袖口独立倾斜网格。",
            f"参数：步长 {STEP_PCT*100:.1f}% · {N_GRIDS} 档 · 底仓≥{MIN_LAYERS} · MA{MA_CENTER}。",
            "分红再投入 + 空闲现金约1.4%计息；个股印花税千一。",
            "回测共同起点约 2022-01（移动上市）；强制刷新可重算。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    if refresh:
        return cached_scan("cm_big4_grid_v1", lambda: _scan(refresh_bt=True), refresh=True, ttl_sec=0)
    return cached_scan("cm_big4_grid_v1", lambda: _scan(refresh_bt=False), refresh=False, ttl_sec=ttl_sec)
