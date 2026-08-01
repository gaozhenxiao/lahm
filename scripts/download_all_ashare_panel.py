"""后台下载全 A（或指定宇宙）日线 + 利润/成长财务到 data/factors/_shared。

可断点续跑：已有 parquet 且覆盖足够区间会跳过。

用法:
  python scripts/download_all_ashare_panel.py
  python scripts/download_all_ashare_panel.py --universe all_a --interval 0.25
  python scripts/download_all_ashare_panel.py --universe zz500 --skip-growth
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402


def _years_from(start_year: int) -> list[int]:
    y = datetime.now().year
    return list(range(start_year, y + 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="all_a", help="all_a / hs300 / zz500")
    ap.add_argument("--price-start", default="2016-01-01")
    ap.add_argument("--funda-start-year", type=int, default=2015)
    ap.add_argument("--interval", type=float, default=0.28)
    ap.add_argument("--skip-daily", action="store_true")
    ap.add_argument("--skip-profit", action="store_true")
    ap.add_argument("--skip-growth", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="调试用截断股票数，0=全量")
    args = ap.parse_args()

    cache = kit.shared_cache_dir()
    log_path = cache / "download_all_ashare_progress.jsonl"
    status_path = cache / "download_all_ashare_status.json"
    limiter = kit.RateLimiter(args.interval)
    end = datetime.now().strftime("%Y-%m-%d")
    years = _years_from(args.funda_start_year)

    codes = kit.fetch_universe_codes(args.universe, limiter, cache)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]
    print(f"[download] universe={args.universe} n={len(codes)} cache={cache}", flush=True)

    status = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "universe": args.universe,
        "total": len(codes),
        "daily_done": 0,
        "profit_done": 0,
        "growth_done": 0,
        "errors": 0,
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    kit.clear_proxy()
    bs = kit.bs_login()
    t0 = time.time()
    try:
        for i, code in enumerate(codes, 1):
            err = None
            try:
                if not args.skip_daily:
                    kit.fetch_daily_valuation(
                        code, args.price_start, end, limiter, cache, bs=bs
                    )
                    status["daily_done"] = i
                if not args.skip_profit:
                    kit.fetch_profit_quarters(code, years, limiter, cache, bs=bs)
                    status["profit_done"] = i
                if not args.skip_growth:
                    kit.fetch_growth_quarters(code, years, limiter, cache, bs=bs)
                    status["growth_done"] = i
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                status["errors"] = int(status["errors"]) + 1

            rec = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "i": i,
                "n": len(codes),
                "code": code,
                "err": err,
                "elapsed_min": round((time.time() - t0) / 60, 2),
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 10 == 0 or i == len(codes) or err:
                status["updated_at"] = rec["ts"]
                status_path.write_text(
                    json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    f"[download] {i}/{len(codes)} {code} err={err} "
                    f"elapsed={rec['elapsed_min']}m",
                    flush=True,
                )
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass

    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[download] DONE {status}", flush=True)


if __name__ == "__main__":
    main()
