#!/usr/bin/env python3
"""因子用财务（利润/成长）增量刷新。

优先从本地 A 股财务库导出；否则用 BaoStock 重拉近 N 年并与旧缓存合并。

用法:
  python scripts/download_factor_financials_incremental.py
  python scripts/download_factor_financials_incremental.py --universe hs300 --recent-years 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402

STATUS_NAME = "download_factor_financials_incremental_status.json"
PROGRESS_NAME = "download_factor_financials_incremental_progress.jsonl"


def _years_recent(n: int) -> List[int]:
    y = datetime.now().year
    return list(range(max(2015, y - n + 1), y + 1))


def _merge_quarters(old: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if fresh is None or fresh.empty:
        return old if old is not None else pd.DataFrame()
    if old is None or old.empty:
        out = fresh.copy()
    else:
        out = pd.concat([old, fresh], ignore_index=True)
    if "statDate" in out.columns:
        out["statDate"] = pd.to_datetime(out["statDate"], errors="coerce")
        out = out.dropna(subset=["statDate"]).sort_values("statDate").drop_duplicates(
            ["statDate"], keep="last"
        )
    if "pubDate" in out.columns:
        out["pubDate"] = pd.to_datetime(out["pubDate"], errors="coerce")
    return out.reset_index(drop=True)


def _fetch_recent_baostock(
    code: str,
    years: Sequence[int],
    limiter: kit.RateLimiter,
    *,
    kind: str,
    bs,
) -> pd.DataFrame:
    frames = []
    for year in years:
        for q in (1, 2, 3, 4):
            try:
                limiter.wait()
                if kind == "profit":
                    rs = bs.query_profit_data(code=code, year=year, quarter=q)
                else:
                    rs = bs.query_growth_data(code=code, year=year, quarter=q)
                part = kit.rs_to_df(rs)
                if not part.empty:
                    frames.append(part)
            except Exception:  # noqa: BLE001
                continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    for c in ("roeAvg", "npMargin", "gpMargin", "netProfit", "epsTTM", "MBRevenue", "YOYEquity", "YOYAsset", "YOYNI", "YOYEPSBasic"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "pubDate" in df.columns:
        df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")
    if "statDate" in df.columns:
        df["statDate"] = pd.to_datetime(df["statDate"], errors="coerce")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="hs300_csi500_csi1000")
    ap.add_argument("--recent-years", type=int, default=2)
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-baostock", action="store_true", help="仅用本地财务库导出")
    ap.add_argument("--skip-fin-db", action="store_true", help="跳过本地财务库")
    args = ap.parse_args()

    kit.clear_proxy()
    cache = kit.shared_cache_dir()
    (cache / "profit").mkdir(parents=True, exist_ok=True)
    (cache / "growth").mkdir(parents=True, exist_ok=True)
    codes = kit.fetch_universe_codes(args.universe, kit.RateLimiter(0.01), cache)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]
    years = _years_recent(max(1, int(args.recent_years)))

    status: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "universe": args.universe,
        "recent_years": years,
        "total": len(codes),
        "fin_db_written": 0,
        "profit_updated": 0,
        "growth_updated": 0,
        "errors": 0,
        "error_samples": [],
    }
    status_path = cache / STATUS_NAME
    progress_path = cache / PROGRESS_NAME
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[fin-inc] n={len(codes)} universe={args.universe} years={years} cache={cache}",
        flush=True,
    )

    if not args.skip_fin_db and fin_db.db_available():
        stats = fin_db.export_profit_cache_from_fin_db(
            cache / "profit", codes=codes, only_missing=False
        )
        status["fin_db_written"] = int(stats.get("written") or 0)
        status["fin_db"] = stats
        print(f"[fin-db] export profit {stats}", flush=True)

    if args.skip_baostock:
        status["finished_at"] = datetime.now().isoformat(timespec="seconds")
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
        return

    limiter = kit.RateLimiter(args.interval)
    bs = None
    t0 = time.time()
    try:
        bs = kit.bs_login()
    except Exception as exc:  # noqa: BLE001
        status["baostock_login_error"] = str(exc)
        print(f"[warn] baostock login failed: {exc}", flush=True)
        status["finished_at"] = datetime.now().isoformat(timespec="seconds")
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
        return

    try:
        for i, code in enumerate(codes, 1):
            err = None
            try:
                for kind, sub in (("profit", "profit"), ("growth", "growth")):
                    path = cache / sub / f"{code.replace('.', '_')}.parquet"
                    old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
                    fresh = _fetch_recent_baostock(code, years, limiter, kind=kind, bs=bs)
                    merged = _merge_quarters(old, fresh)
                    if merged is not None and not merged.empty:
                        merged.to_parquet(path, index=False)
                        if kind == "profit":
                            status["profit_updated"] += 1
                        else:
                            status["growth_updated"] += 1
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                status["errors"] += 1
                if len(status["error_samples"]) < 20:
                    status["error_samples"].append({"code": code, "err": err})

            rec = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "i": i,
                "n": len(codes),
                "code": code,
                "err": err,
                "elapsed_min": round((time.time() - t0) / 60, 2),
            }
            with progress_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 20 == 0 or i == len(codes) or err:
                status["updated_at"] = rec["ts"]
                status["elapsed_min"] = rec["elapsed_min"]
                status_path.write_text(
                    json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    f"[{i}/{len(codes)}] {code} err={err} "
                    f"profit={status['profit_updated']} growth={status['growth_updated']}",
                    flush=True,
                )
    finally:
        try:
            if bs is not None:
                bs.logout()
        except Exception:  # noqa: BLE001
            pass

    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
