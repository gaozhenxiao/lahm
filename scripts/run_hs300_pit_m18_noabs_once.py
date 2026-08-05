"""单次口径：沪深300 PIT + 毛利>=18% + 无绝对净利。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    collect_legs,
    enrich_with_profit,
    load_or_fetch_universe_prices,
)
from scripts.expt_hs300_pit_m18 import (  # noqa: E402
    BT_END,
    BT_START,
    MEM_FP,
    META_FP,
    PARAMS,
    apply_pit_legs,
    backtest_legs,
    load_membership,
    summary_metrics,
)

OUT_FP = ROOT / "data" / "factors" / "hs300_pit_m18_noabs.json"


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
            f"unique={meta.get('n_unique_codes')}",
            flush=True,
        )

    cache = kit.shared_cache_dir()
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

    out = {
        "signal": "signal_gross_expand_break",
        "factor_family": "gross_expand_m16_tp35 / factor168",
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "note": (
            "margin_min=0.18; no net_profit_min; "
            "universe=HS300 PIT via 510300 ETF quarterly holdings"
        ),
        "sample": {"start": BT_START, "end": BT_END},
        "pit_membership_file": str(MEM_FP),
        "pit_meta_file": str(META_FP) if META_FP.exists() else None,
        "pit_union_codes": len(codes),
        "panel_loaded": len(have),
        "legs_union": int(len(legs_all)),
        "legs_pit": int(len(legs_pit)),
        "legs_index_exit_clipped": n_index_exit,
        "metrics": summary_metrics(s_pit),
        "raw": s_pit,
    }
    OUT_FP.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ok] {OUT_FP}", flush=True)


if __name__ == "__main__":
    main()
