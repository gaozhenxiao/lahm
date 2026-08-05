"""沪深300 PIT：毛利>=18% + 归母净利>=10亿（net_profit_min=1e9）。

信号 signal_gross_expand_break；PIT 成分来自 510300 ETF 季报近似。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

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
)

# 复用基脚本的 PIT 工具，避免重复实现
_BASE = ROOT / "scripts" / "expt_hs300_pit_m18.py"
_spec = importlib.util.spec_from_file_location("expt_hs300_pit_m18", _BASE)
_base = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_base)

MEM_FP = _base.MEM_FP
META_FP = _base.META_FP
BT_START = _base.BT_START
BT_END = _base.BT_END
load_membership = _base.load_membership
apply_pit_legs = _base.apply_pit_legs
summary_metrics = _base.summary_metrics

OUT_FP = ROOT / "data" / "factors" / "hs300_pit_m18_np1e9.json"

PARAMS = {
    **_base.PARAMS,
    "margin_min": 0.18,
    "net_profit_min": 1e9,
}


def backtest_legs(factor_id: str, legs: pd.DataFrame) -> dict:
    params = dict(PARAMS)
    params["position_logic"] = factor_id
    params["note"] = factor_id
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
            summary["win_rate"] = (
                float((rets > 0).mean()) if rets.notna().any() else None
            )
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
    static_codes = kit.fetch_universe_codes("hs300", kit.RateLimiter(0.01), cache)
    print(f"[static] today hs300 codes={len(static_codes)}", flush=True)

    price_map = load_or_fetch_universe_prices(codes, PARAMS, cache)
    price_map = enrich_with_profit(price_map, PARAMS, cache)
    have = {
        c: px
        for c, px in price_map.items()
        if px is not None and not getattr(px, "empty", True)
    }
    print(f"[panel] loaded={len(have)}/{len(codes)}", flush=True)

    params = dict(PARAMS)
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

    s_pit = backtest_legs("expt_hs300_pit_m18_np1e9", legs_pit)
    print("[PIT]", summary_metrics(s_pit), flush=True)

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
    s_static = backtest_legs("expt_hs300_static_m18_np1e9", legs_static)
    print("[STATIC]", summary_metrics(s_static), flush=True)

    out: Dict[str, Any] = {
        "signal": "signal_gross_expand_break",
        "factor_family": "gross_expand_m16_tp35 / factor168",
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "note": (
            "margin_min=0.18; net_profit_min=1e9; "
            "PIT via 510300 ETF quarterly holdings (approx, not official daily)"
        ),
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
        "compare": {
            "pit_m18_noabs_sharpe": 0.0134,
            "csi_core_m16_np1e9_sharpe": 0.7078,
            "note_csi": "本地 csi_core 最佳为 margin_min=0.16+np1e9 Sharpe=0.7078；无严格 m18+np1e9 存档",
            "static_hs300_m18_np1e9_prior_sharpe": 0.8774,
        },
    }
    OUT_FP.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ok] {OUT_FP}", flush=True)


if __name__ == "__main__":
    main()
