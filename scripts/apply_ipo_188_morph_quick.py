"""快速完成 #188 morph 选参并落库（覆盖旧参数）。BaoStock 禁用。不 commit。"""
from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.enhance_ipo_188_morph import (  # noqa: E402
    BASE,
    FACTOR_ID,
    FACTOR_NAME,
    OUT_DIR,
    OUT_STEM,
    START,
    _bs_disabled,
    _entries_cache,
    _rank_key,
    _sig_key,
    apply_best,
    attach_list_dates,
    eval_params,
    load_list_dates,
    make_desc,
)
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.runner import prepare_shared_panel  # noqa: E402

# 基于先前 phase1 高分形态 + 用户要求的 hold/mp 网格
MORPHS: List[Dict[str, Any]] = [
    # phase1 #15 重建：tw≈1.48
    dict(
        ipo_age_lo=2.4,
        ipo_age_hi=3.0,
        ipo_crash_months=18,
        ipo_crash_dd=-0.45,
        consol_window=100,
        consol_amp_max=0.32,
        consol_ma_band=0.08,
        entry_mode="stabilize",
        break_days=40,
        brk_soft=0.985,
    ),
    dict(
        ipo_age_lo=2.4,
        ipo_age_hi=3.0,
        ipo_crash_months=18,
        ipo_crash_dd=-0.40,
        consol_window=120,
        consol_amp_max=0.35,
        consol_ma_band=0.08,
        entry_mode="soft",
        break_days=40,
        brk_soft=0.985,
    ),
    dict(
        ipo_age_lo=2.4,
        ipo_age_hi=3.0,
        ipo_crash_months=12,
        ipo_crash_dd=-0.40,
        consol_window=100,
        consol_amp_max=0.32,
        consol_ma_band=0.08,
        entry_mode="soft",
        break_days=55,
        brk_soft=0.98,
    ),
    dict(
        ipo_age_lo=2.5,
        ipo_age_hi=3.0,
        ipo_crash_months=18,
        ipo_crash_dd=-0.40,
        consol_window=120,
        consol_amp_max=0.35,
        consol_ma_band=0.08,
        entry_mode="soft",
        break_days=40,
        brk_soft=0.985,
    ),
    dict(
        ipo_age_lo=2.4,
        ipo_age_hi=3.0,
        ipo_crash_months=18,
        ipo_crash_dd=-0.50,
        consol_window=120,
        consol_amp_max=0.35,
        consol_ma_band=0.08,
        entry_mode="soft",
        break_days=55,
        brk_soft=0.98,
    ),
]

EXITS = [
    dict(hold_days=100, max_positions=14, stop_loss=0.12, take_profit=0.40),
    dict(hold_days=100, max_positions=14, stop_loss=0.12, take_profit=0.45),
    dict(hold_days=120, max_positions=15, stop_loss=0.12, take_profit=0.45),
    dict(hold_days=120, max_positions=14, stop_loss=0.15, take_profit=0.45),
    dict(hold_days=80, max_positions=12, stop_loss=0.12, take_profit=0.35),
    dict(hold_days=100, max_positions=15, stop_loss=0.15, take_profit=0.40),
]


def main() -> None:
    t0 = time.time()
    kit.login_baostock = _bs_disabled  # type: ignore
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    list_map = load_list_dates()
    print(f"[list_date] n={len(list_map)}", flush=True)
    params0 = {
        **BASE,
        **MORPHS[0],
        "hold_days": 100,
        "max_positions": 14,
        "stop_loss": 0.12,
        "take_profit": 0.40,
    }
    print("[panel] prepare", flush=True)
    panel = prepare_shared_panel(params0, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        str(params0.get("price_start") or "2010-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache,
    )

    results: List[Dict[str, Any]] = []
    entries_memo: Dict[str, Dict] = {}
    n = 0
    for mi, morph in enumerate(MORPHS, 1):
        base_p = {**BASE, **morph}
        sk = _sig_key(base_p)
        if sk not in entries_memo:
            print(f"[entries] morph#{mi} ...", flush=True)
            entries_memo[sk] = _entries_cache(panel, base_p)
            n_ent = sum(len(v) for v in entries_memo[sk].values())
            print(f"  entries={n_ent} codes={len(entries_memo[sk])}", flush=True)
        for ei, ex in enumerate(EXITS, 1):
            n += 1
            p = {**base_p, **ex}
            row = eval_params(f"m{mi}_e{ei}", p, panel, bench, entries_memo[sk])
            results.append(row)
            print(
                f"  [{n}] tw={row.get('tw_score')} sh={row.get('sharpe')} "
                f"r2y={row.get('recent2y_sharpe')}/{row.get('recent2y_return')} "
                f"legs={row.get('n_legs_accepted')} flags={row.get('tw_flags')}",
                flush=True,
            )

    ranked = sorted(results, key=_rank_key, reverse=True)
    best = ranked[0]
    print(
        f"[best] tw={best.get('tw_score')} sh={best.get('sharpe')} "
        f"ret={best.get('total_return')} r2y_sh={best.get('recent2y_sharpe')} "
        f"r2y_ret={best.get('recent2y_return')} legs={best.get('n_legs_accepted')}",
        flush=True,
    )
    print(json.dumps(best.get("params"), ensure_ascii=False, indent=2), flush=True)

    applied = apply_best(best, list_map)
    payload = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "factor_id": FACTOR_ID,
        "n_cfgs": len(results),
        "best": best,
        "top5": ranked[:5],
        "apply": applied,
        "elapsed_sec": round(time.time() - t0, 1),
        "description": make_desc(best["params"]),
    }
    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    OUT_STEM.with_suffix(".md").write_text(
        f"# #188 morph quick apply\n\n```json\n{json.dumps(payload.get('apply'), ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    print(f"[done] {OUT_STEM}.json elapsed={payload['elapsed_sec']}s", flush=True)
    print(json.dumps(applied.get("summary"), ensure_ascii=False), flush=True)
    print(json.dumps(applied.get("late"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
