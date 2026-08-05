# -*- coding: utf-8 -*-
"""从 #189 宽网格已扫结果强制入库最优 morph（不改 #189）。

默认取日志高点 morph#50；也可 --idx 指定；多候选时按 _rank_key 选最优。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.runner import prepare_shared_panel  # noqa: E402
from scripts.enhance_ipo_188_morph import (  # noqa: E402
    _bs_disabled,
    _entries_cache,
    _rank_key,
    attach_list_dates,
    eval_params,
    load_list_dates,
)
from scripts.opt_ipo_189_wide_new import (  # noqa: E402
    BASELINE,
    OUT_DIR,
    _improved,
    build_wide_morphs,
    insert_new_factor,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--idx",
        type=int,
        nargs="*",
        default=[10, 40, 50, 80, 90],
        help="1-based morph indices to compare (default: log highlights)",
    )
    args = ap.parse_args()

    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    list_map = load_list_dates()
    morphs = build_wide_morphs()
    print(f"[morphs] total={len(morphs)} pick={args.idx}", flush=True)

    print("[panel] prepare", flush=True)
    panel = prepare_shared_panel(BASELINE, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        str(BASELINE.get("price_start") or "2010-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache,
    )

    base_ents = _entries_cache(panel, BASELINE)
    baseline = eval_params("baseline_189", BASELINE, panel, bench, base_ents)
    print(
        f"[baseline] tw={baseline.get('tw_score')} sh={baseline.get('sharpe')} "
        f"r2y={baseline.get('recent2y_sharpe')}",
        flush=True,
    )

    rows = []
    for idx in args.idx:
        if idx < 1 or idx > len(morphs):
            print(f"[skip] idx={idx}", flush=True)
            continue
        sp = morphs[idx - 1]
        ents = _entries_cache(panel, sp)
        row = eval_params(f"morph_{idx}", sp, panel, bench, ents)
        rows.append(row)
        print(
            f"  [morph#{idx}] tw={row.get('tw_score')} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('tw_flags')}",
            flush=True,
        )

    if not rows:
        raise SystemExit("no candidate rows")
    best = max(rows, key=_rank_key)
    ok, reason = _improved(best, baseline)
    print(
        f"[best] {best.get('cfg_id')} tw={best.get('tw_score')} sh={best.get('sharpe')} "
        f"r2y={best.get('recent2y_sharpe')} improved={ok} ({reason}) -> FORCE INSERT",
        flush=True,
    )

    applied = insert_new_factor(best, list_map)
    report = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "force": True,
        "improved_gate": {"ok": ok, "reason": reason},
        "baseline": {
            k: baseline.get(k)
            for k in ("tw_score", "sharpe", "recent2y_sharpe", "n_legs_accepted")
        },
        "best_eval": {
            k: best.get(k)
            for k in (
                "cfg_id",
                "tw_score",
                "sharpe",
                "recent2y_sharpe",
                "recent2y_return",
                "n_legs_accepted",
                "total_return",
                "max_drawdown",
                "params",
            )
        },
        "apply": applied,
    }
    out = OUT_DIR / "force_insert_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[wrote] {out}", flush=True)
    print(
        f"[DONE] factor_id={applied.get('factor_id')} "
        f"mongo={applied.get('mongo')} summary={applied.get('summary')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
