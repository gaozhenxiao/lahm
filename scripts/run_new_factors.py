"""批量刷新/回测新因子（共享行情面板，避免重复拉取）。

用法:
  python scripts/run_new_factors.py --limit 40
  python scripts/run_new_factors.py --only pb_low_ma_reclaim,cheap_roe_bounce
  python scripts/run_new_factors.py --limit 0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40, help="每因子股票数，0=全量")
    parser.add_argument("--only", default="", help="逗号分隔 factor_id")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--no-shared-panel", action="store_true", help="每个因子单独拉数")
    args = parser.parse_args()

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]
        missing = [x for x in ids if x not in FACTOR_IMPL]
        if missing:
            raise SystemExit(f"unknown factor ids: {missing}")

    need_profit = any(FACTOR_IMPL[i]["need_profit"] for i in ids)
    need_growth = any(FACTOR_IMPL[i]["need_growth"] for i in ids)
    base_params = dict(next(iter(FACTOR_IMPL.values()))["params"])

    price_map = None
    if not args.no_shared_panel:
        price_map = prepare_shared_panel(
            base_params,
            need_profit=need_profit,
            need_growth=need_growth,
            limit=args.limit,
        )

    results = {}
    for fid in ids:
        meta = FACTOR_IMPL[fid]
        print(f"\n======== {fid} / {meta['name']} ========", flush=True)
        try:
            summary = run_factor_pipeline(
                fid,
                meta["title"],
                meta["signal"],
                meta["params"],
                need_profit=meta["need_profit"],
                need_growth=meta["need_growth"],
                limit=args.limit,
                start=args.start,
                price_map=price_map,
            )
            results[fid] = summary
        except Exception as exc:  # noqa: BLE001
            print(f"[fail] {fid}: {exc}", flush=True)
            results[fid] = {"error": str(exc)}

    out = ROOT / "data" / "factors" / "new_factors_batch_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] batch summary -> {out}", flush=True)
    for k, v in results.items():
        if isinstance(v, dict) and "total_return" in v:
            print(
                f"  {k}: ret={v['total_return']} sharpe={v.get('sharpe')} legs={v.get('n_legs_accepted')}",
                flush=True,
            )
        else:
            print(f"  {k}: {v}", flush=True)


if __name__ == "__main__":
    main()
