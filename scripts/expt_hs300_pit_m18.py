"""用历史当期沪深300成分（510300 ETF 季报近似 PIT）回测：毛利>=18%、无绝对净利。

对比：今天成分的静态沪深300（本地 universe_hs300 缓存 / 中证）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    collect_legs,
    enrich_with_profit,
    legs_to_trade_history,
    load_or_fetch_universe_prices,
    run_factor_pipeline,
)

MEM_FP = ROOT / "data" / "factors" / "_shared" / "hs300_pit_etf510300_membership.csv"
META_FP = MEM_FP.with_suffix(".json")
OUT_FP = ROOT / "data" / "factors" / "hs300_pit_vs_static_m18_noabs.json"

# 因子168 族：毛利门槛改为 18%；不设 net_profit_min（绝对净利）
PARAMS = {
    "universe": "hs300",
    "exclude_st": True,
    "price_start": "2016-01-01",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.006,
    "margin_min": 0.18,
    "np_min": 0.1,
    "funda_lag": 29,
    "break_days": 60,
    "hold_days": 51,
    "stop_loss": 0.12,
    "take_profit": 0.35,
}

BT_START = "2018-01-01"
BT_END = "2026-07-31"


def load_membership() -> pd.DataFrame:
    if not MEM_FP.exists():
        raise SystemExit(
            f"missing {MEM_FP}; run scripts/build_hs300_pit_from_etf.py first"
        )
    df = pd.read_csv(MEM_FP)
    df["in_date"] = pd.to_datetime(df["in_date"], errors="coerce")
    df["out_date"] = pd.to_datetime(df["out_date"], errors="coerce")
    df["code"] = df["code"].astype(str)
    df["out_date"] = df["out_date"].fillna(pd.Timestamp("2100-01-01"))
    return df.dropna(subset=["code", "in_date"])


def _exit_px_on_or_before(
    px: pd.DataFrame, dt: pd.Timestamp, fallback: float
) -> tuple[pd.Timestamp, float]:
    if px is None or getattr(px, "empty", True):
        return dt, float(fallback)
    d = px.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date", "close"]).sort_values("date")
    sub = d[d["date"] <= dt]
    if sub.empty:
        return dt, float(fallback)
    row = sub.iloc[-1]
    return pd.Timestamp(row["date"]), float(row["close"])


def apply_pit_legs(
    legs: pd.DataFrame,
    mem: pd.DataFrame,
    price_map: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """开仓日须在成分内；持有期间若调出则提前平仓。"""
    if legs is None or legs.empty:
        return legs
    L = legs.copy()
    L["entry_date"] = pd.to_datetime(L["entry_date"], errors="coerce")
    L["exit_date"] = pd.to_datetime(L["exit_date"], errors="coerce")
    L["code"] = L["code"].astype(str)
    m = mem.rename(columns={"in_date": "m_in", "out_date": "m_out"})
    merged = L.merge(m[["code", "m_in", "m_out"]], on="code", how="inner")
    ok = (merged["entry_date"] >= merged["m_in"]) & (merged["entry_date"] < merged["m_out"])
    hit = merged.loc[ok].copy()
    if hit.empty:
        return L.iloc[0:0].copy()
    # 同一腿可能匹配多段 membership；取覆盖入场日的那段，并截断持有至 out_date
    hit = hit.sort_values(["code", "entry_date", "m_in"]).drop_duplicates(
        ["code", "entry_date"], keep="first"
    )
    rows = []
    for _, r in hit.iterrows():
        out = r.to_dict()
        exit_dt = pd.Timestamp(r["exit_date"])
        m_out = pd.Timestamp(r["m_out"])
        if exit_dt > m_out:
            new_dt, new_px = _exit_px_on_or_before(
                price_map.get(str(r["code"])),
                m_out - pd.Timedelta(days=1),
                float(r.get("exit_price") or r.get("entry_price") or 0.0),
            )
            # 若调出日不晚于入场，丢弃
            if new_dt <= pd.Timestamp(r["entry_date"]):
                continue
            out["exit_date"] = new_dt
            out["exit_price"] = new_px
            out["reason"] = "index_exit"
        out.pop("m_in", None)
        out.pop("m_out", None)
        rows.append(out)
    if not rows:
        return L.iloc[0:0].copy()
    return pd.DataFrame(rows).reset_index(drop=True)


def summary_metrics(s: dict) -> dict:
    keys = [
        "sharpe",
        "total_return",
        "annual_return",
        "max_drawdown",
        "win_rate",
        "n_trades",
        "n_legs_raw",
        "n_legs_input",
        "n_legs_accepted",
    ]
    return {k: s.get(k) for k in keys if k in s or True}


def backtest_legs(factor_id: str, legs: pd.DataFrame) -> dict:
    params = dict(PARAMS)
    params["position_logic"] = factor_id
    params["note"] = factor_id
    # 明确不设绝对净利
    params.pop("net_profit_min", None)
    cache_dir = kit.shared_cache_dir()
    params["_cache_dir"] = str(cache_dir)
    factor_dir = kit.factor_cache_dir(factor_id)
    factor_dir.mkdir(parents=True, exist_ok=True)
    if not legs.empty:
        legs.to_parquet(factor_dir / "trade_legs.parquet", index=False)

    limiter = kit.RateLimiter(0.2)
    bench = kit.fetch_daily_valuation(
        str(params["bench_code"]),
        str(params["price_start"]),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
        cache_only=True,
    )
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=BT_START, end=BT_END
    )
    if daily is None or daily.empty:
        return dict(summary) if isinstance(summary, dict) else {"error": str(summary)}
    trades = legs_to_trade_history(
        accepted, max_positions=int(params["max_positions"])
    )
    kit.write_factor_artifacts(
        factor_id, daily, summary, trades, params=params, title=factor_id
    )
    summary = dict(summary)
    summary["n_legs_input"] = int(len(legs))
    summary["n_legs_accepted"] = (
        int(len(accepted)) if accepted is not None else summary.get("n_legs_accepted")
    )
    if trades is not None and not trades.empty:
        sells = trades[trades["action"].astype(str).str.contains("清仓", na=False)]
        if not sells.empty and "day_ret" in sells.columns:
            rets = (
                sells["day_ret"]
                .astype(str)
                .str.replace("%", "", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
            )
            summary["n_trades"] = int(len(sells))
            summary["win_rate"] = float((rets > 0).mean()) if rets.notna().any() else None
    return summary


def main() -> None:
    mem = load_membership()
    start = pd.Timestamp(BT_START)
    end = pd.Timestamp(BT_END)
    active = mem[(mem["in_date"] <= end) & (mem["out_date"] > start)]
    codes = sorted(active["code"].astype(str).unique().tolist())
    print(f"[pit] historical union codes={len(codes)} file={MEM_FP}", flush=True)
    if META_FP.exists():
        meta = json.loads(META_FP.read_text(encoding="utf-8"))
        print(
            f"[pit] used_periods={meta.get('n_periods')} "
            f"unique={meta.get('n_unique_codes')} "
            f"sizes={meta.get('period_sizes')}",
            flush=True,
        )

    cache = kit.shared_cache_dir()
    # 静态今天沪深300（缓存，不触发 BaoStock）
    static_codes = kit.fetch_universe_codes("hs300", kit.RateLimiter(0.01), cache)
    print(f"[static] today hs300 codes={len(static_codes)}", flush=True)

    # PIT 宇宙 = 历史并集；价格/利润缓存复用
    price_map = load_or_fetch_universe_prices(codes, PARAMS, cache)
    price_map = enrich_with_profit(price_map, PARAMS, cache)
    have = {
        c: px
        for c, px in price_map.items()
        if px is not None and not getattr(px, "empty", True)
    }
    print(f"[panel] loaded={len(have)}/{len(codes)}", flush=True)

    params = dict(PARAMS)
    params.pop("net_profit_min", None)
    legs_all = collect_legs(have, sig.signal_gross_expand_break, params)
    print(f"[legs] union_signals={len(legs_all)}", flush=True)
    legs_pit = apply_pit_legs(legs_all, mem, have)
    print(f"[legs] after_pit={len(legs_pit)}", flush=True)
    n_index_exit = (
        int((legs_pit["reason"] == "index_exit").sum())
        if not legs_pit.empty and "reason" in legs_pit.columns
        else 0
    )
    print(f"[legs] index_exit_clipped={n_index_exit}", flush=True)

    s_pit = backtest_legs("expt_hs300_pit_m18_noabs", legs_pit)
    print("[PIT]", summary_metrics(s_pit), flush=True)

    # 对照组：仅用今天静态成分的价格面板再扫信号（避免 PIT 并集幸存者）
    static_have = {c: have[c] for c in static_codes if c in have}
    missing_static = [c for c in static_codes if c not in have]
    if missing_static:
        more = load_or_fetch_universe_prices(missing_static, params, cache)
        more = enrich_with_profit(more, params, cache)
        for c, px in more.items():
            if px is not None and not getattr(px, "empty", True):
                static_have[c] = px
    print(f"[static panel] loaded={len(static_have)}/{len(static_codes)}", flush=True)
    legs_static = collect_legs(static_have, sig.signal_gross_expand_break, params)
    print(f"[legs] static={len(legs_static)}", flush=True)
    s_static = backtest_legs("expt_hs300_static_m18_noabs", legs_static)
    print("[STATIC]", summary_metrics(s_static), flush=True)

    # 也跑一遍 pipeline 校验（同静态宇宙）
    s_pipe: Optional[Dict[str, Any]] = None
    try:
        s_pipe = run_factor_pipeline(
            "expt_hs300_static_m18_noabs_pipe",
            "static today hs300 m18 noabs",
            sig.signal_gross_expand_break,
            params,
            need_profit=True,
            limit=0,
            start=BT_START,
            price_map=static_have,
        )
        print("[STATIC_PIPE]", summary_metrics(s_pipe), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[STATIC_PIPE] skip: {exc}", flush=True)

    out = {
        "signal": "signal_gross_expand_break",
        "factor_family": "gross_expand_m16_tp35 / factor168",
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "note": "margin_min=0.18; no net_profit_min; PIT via 510300 ETF quarterly holdings",
        "sample": {"start": BT_START, "end": BT_END},
        "pit_membership_file": str(MEM_FP),
        "pit_meta_file": str(META_FP) if META_FP.exists() else None,
        "pit_union_codes": len(codes),
        "static_today_codes": len(static_codes),
        "panel_loaded_pit": len(have),
        "panel_loaded_static": len(static_have),
        "legs_union": int(len(legs_all)),
        "legs_pit": int(len(legs_pit)),
        "legs_static": int(len(legs_static)),
        "legs_index_exit_clipped": n_index_exit,
        "pit": s_pit,
        "static_today_hs300": s_static,
        "static_pipeline_check": s_pipe,
    }
    OUT_FP.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ok] {OUT_FP}", flush=True)


if __name__ == "__main__":
    main()
