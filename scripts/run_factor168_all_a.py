"""因子168 gross_expand_m16_tp35 在核心宽基宇宙上回测。

宇宙 csi_core = 沪深300 ∪ 中证100 ∪ 中证200 ∪ 中证500 ∪ 中证800（中证官网成分并集）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import run_factor_pipeline  # noqa: E402

FACTOR_ID = "gross_expand_m16_tp35"
TITLE = "Gross expand m16 tp35"
UNIVERSE = "csi_core"


def _base_params(universe: str) -> dict:
    return {
        "universe": universe,
        "exclude_st": True,
        "price_start": "2016-01-01",
        "max_positions": 8,
        "commission_rate": 0.0001,
        "stamp_tax_sell": 0.001,
        "request_interval_sec": 0.35,
        "bench_code": "sh.000300",
        "margin_improve": 0.006,
        "margin_min": 0.16,
        "np_min": 0.1,
        "funda_lag": 29,
        "break_days": 60,
        "hold_days": 51,
        "stop_loss": 0.12,
        "take_profit": 0.35,
    }


def _sync_mongo(summary: dict, params: dict) -> None:
    uri = "mongodb://admin:lahm123@localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "params": params,
        "updated_at": now,
        "backtest_summary": {
            "available": True,
            "logics": {FACTOR_ID: summary},
            "updated_at": now,
        },
        "last_backtest_error": summary.get("error"),
    }
    for dbn in ("lahm", "lahm_v0_gaozx-laptop-rren219t"):
        if dbn not in client.list_database_names():
            continue
        client[dbn].factors.update_one({"factor_id": FACTOR_ID}, {"$set": payload}, upsert=False)
        print(f"[mongo] updated {dbn}.factors/{FACTOR_ID}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=UNIVERSE, help="默认 csi_core（300∪100∪200∪500∪800）")
    ap.add_argument("--force-universe", action="store_true", help="强制重拉中证成分")
    args = ap.parse_args()

    cache = kit.shared_cache_dir()
    st_n = len(kit.load_st_codes())
    codes = kit.fetch_universe_codes(
        args.universe, kit.RateLimiter(0.01), cache, force=bool(args.force_universe)
    )
    print(f"[universe] {args.universe} codes={len(codes)} (ST名单约{st_n}只已剔除)", flush=True)

    profit_dir = cache / "profit"
    stats = fin_db.export_profit_cache_from_fin_db(profit_dir, codes=codes, only_missing=True)
    print(f"[profit-export] {stats}", flush=True)

    params = _base_params(args.universe)
    summary = run_factor_pipeline(
        FACTOR_ID,
        TITLE,
        sig.signal_gross_expand_break,
        params,
        need_profit=True,
        need_growth=False,
        limit=0,
        start="2018-01-01",
    )
    out = ROOT / "data" / "factors" / f"{FACTOR_ID}_{args.universe}_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] summary -> {out}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    _sync_mongo(summary if isinstance(summary, dict) else {"error": str(summary)}, params)


if __name__ == "__main__":
    main()
