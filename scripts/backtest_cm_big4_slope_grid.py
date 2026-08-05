# -*- coding: utf-8 -*-
"""中国移动 + 四大行（工农中建）等权分仓 · 向上倾斜网格回测。

口径与红利ETF倾斜网格对齐：
- 不复权价成交；现金分红按持仓份额入账并可再投入
- 空闲现金约 1.4% 年化计息
- 个股卖出印花税千一；佣金万一
- 每标的独立网格（资金等权 1/5），再汇总组合净值

用法:
  python scripts/backtest_cm_big4_slope_grid.py
  python scripts/backtest_cm_big4_slope_grid.py --start 2022-01-05
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors.dividend_etf_swing import (  # noqa: E402
    FACTORS_DATA,
    _fetch_etf_via_baostock,
    load_or_fetch_etf,
)
from app.services.strategies.etf_grid_backtest import (  # noqa: E402
    DEFAULT_PARAMS_V3,
    _metrics,
    run_grid_backtest_slope_up,
)

OUT = ROOT / "data" / "strategies"

# 中国移动 + 工农中建（四大行）
UNIVERSE: List[Tuple[str, str]] = [
    ("600941", "中国移动"),
    ("601398", "工商银行"),
    ("601939", "建设银行"),
    ("601288", "农业银行"),
    ("601988", "中国银行"),
]


def _cache_stock(symbol: str) -> Path:
    return FACTORS_DATA / f"{symbol}_daily.parquet"


def load_stock_raw(
    symbol: str,
    *,
    start: str = "20160101",
    end: Optional[str] = None,
    force: bool = False,
) -> pd.DataFrame:
    """A 股不复权日线；优先本地缓存，再 baostock（与 ETF 加载同路径）。"""
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    path = _cache_stock(symbol)
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
    except Exception:  # noqa: BLE001
        pass
    return hist


def fetch_stock_dividends(symbol: str, *, force: bool = False) -> pd.Series:
    """除息日 -> 每股现金红利（税前）。东财「10派X元」→ dps=X/10。"""
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
            # 兼容列名：除权除息日、现金分红-现金分红比例
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
                    # 比例为「10派X元」
                    px10 = pd.to_numeric(r[dps_col], errors="coerce")
                    if pd.isna(dt) or pd.isna(px10) or float(px10) <= 0:
                        continue
                    rows.append({"date": dt, "dps": float(px10) / 10.0})
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] dividend em {symbol}: {exc}")

    if not rows:
        try:
            import akshare as ak

            raw = ak.stock_history_dividend_detail(symbol=str(symbol), indicator="分红")
            if raw is not None and not raw.empty:
                cols = list(raw.columns)
                # 派息、除权除息日
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
            print(f"[warn] dividend hist {symbol}: {exc}")

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows).dropna().drop_duplicates("date").sort_values("date")
    try:
        FACTORS_DATA.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    except Exception:  # noqa: BLE001
        pass
    return df.set_index("date")["dps"].astype(float)


def _combine_sleeves(
    sleeves: Dict[str, pd.DataFrame],
    *,
    weight: float,
) -> pd.DataFrame:
    """各袖口净值按权重外连 + ffill 汇总。"""
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
    # 归一：首日净值≈1
    if len(out) and out["equity"].iloc[0] > 0:
        scale_g = 1.0 / float(out["equity"].iloc[0])
        scale_b = 1.0 / float(out["bh_equity"].iloc[0]) if out["bh_equity"].iloc[0] > 0 else 1.0
        out["equity"] *= scale_g
        out["bh_equity"] *= scale_b
    return out


def run_basket(
    *,
    start: str,
    end: Optional[str],
    force: bool,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    p = {**DEFAULT_PARAMS_V3, **(params or {})}
    # 个股印花税千一
    p["stamp_tax_sell"] = float(p.get("stamp_tax_sell") if p.get("stamp_tax_sell") not in (None, 0.0) else 0.001)
    # 组合起点：默认中国移动上市后
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
        daily, trades, summary = run_grid_backtest_slope_up(
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
        print(
            f"[ok] {code} {name}: grid_cagr={g.get('cagr')} bh={b.get('cagr')} "
            f"divN={summary.get('n_dividend_events')} trades={summary.get('n_trades')}"
        )

    combined = _combine_sleeves(sleeves, weight=weight)
    if combined.empty:
        return {"error": "no_sleeves", "details": details}

    combined = combined.set_index("date", drop=False)
    grid_m = _metrics(combined["equity"], ann_cash=float(p.get("cash_annual") or 0.014))
    bh_m = _metrics(combined["bh_equity"], ann_cash=float(p.get("cash_annual") or 0.014))
    payload = {
        "asof": pd.Timestamp.now().isoformat(timespec="seconds"),
        "universe": [{"code": c, "name": n} for c, n in UNIVERSE],
        "rule": "等权分仓·向上倾斜网格；不复权+现金分红再投入+现金1.4%计息；个股印花税千一",
        "params": {
            **{k: p[k] for k in (
                "n_grids", "step_pct", "min_layers", "ma_center",
                "commission_rate", "stamp_tax_sell", "cash_annual", "dividend_reinvest",
            )},
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
        "notes": [
            "组合=中国移动600941 + 工农中建 等权五袖口独立网格后再汇总",
            "共同样本受中国移动A股上市日约束（约2022-01）",
            "个股印花税千一；ETF对照勿直接比绝对收益时需注意税率差异",
        ],
    }
    return {"payload": payload, "combined": combined.reset_index(drop=True), "sleeves": sleeves}


def _plot(combined: pd.DataFrame, path: Path, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(combined["date"], combined["equity"], label="grid basket", color="#1f4e79", lw=1.8)
    axes[0].plot(combined["date"], combined["bh_equity"], label="buy&hold basket", color="#999", alpha=0.9)
    axes[0].legend(loc="upper left")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[1].fill_between(combined["date"], 0, combined["exposure"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("avg exposure")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-01-05", help="默认中国移动上市附近")
    ap.add_argument("--end", default=None)
    ap.add_argument("--force-fetch", action="store_true")
    ap.add_argument("--step", type=float, default=None)
    ap.add_argument("--min-layers", type=int, default=None)
    args = ap.parse_args()

    params = dict(DEFAULT_PARAMS_V3)
    params["stamp_tax_sell"] = 0.001
    if args.step is not None:
        params["step_pct"] = args.step
    if args.min_layers is not None:
        params["min_layers"] = args.min_layers

    OUT.mkdir(parents=True, exist_ok=True)
    batch = run_basket(start=args.start, end=args.end, force=args.force_fetch, params=params)
    if batch.get("error"):
        raise SystemExit(batch)

    payload = batch["payload"]
    path = OUT / "cm_big4_slope_grid_backtest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] summary -> {path}")

    combined = batch["combined"]
    combined.to_csv(OUT / "cm_big4_slope_grid_daily.csv", index=False, encoding="utf-8-sig")
    _plot(
        combined,
        OUT / "cm_big4_slope_grid_equity.png",
        "CM + Big4 equal sleeves · slope-up grid vs buy&hold",
    )

    port = payload["portfolio"]
    g, b = port["grid"], port["buy_hold"]
    print("\n=== 组合：中国移动+工农中建 等权 ===")
    print(
        json.dumps(
            {
                "start": port["start"],
                "end": port["end"],
                "grid_cagr": g.get("cagr"),
                "bh_cagr": b.get("cagr"),
                "excess_cagr": port["excess_cagr"],
                "grid_sharpe": g.get("sharpe"),
                "bh_sharpe": b.get("sharpe"),
                "grid_max_dd": g.get("max_dd"),
                "bh_max_dd": b.get("max_dd"),
                "grid_total": g.get("total_return"),
                "bh_total": b.get("total_return"),
                "avg_exposure": port["avg_exposure"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\n=== 分标的 ===")
    for code, row in payload["per_name"].items():
        print(json.dumps({"code": code, **row}, ensure_ascii=False))


if __name__ == "__main__":
    main()
