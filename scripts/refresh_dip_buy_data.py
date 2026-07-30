"""刷新暴跌抄底因子所需指数行情与估值缓存。

用法:
  python scripts/refresh_dip_buy_data.py
  python scripts/refresh_dip_buy_data.py --backtest
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _clear_proxy() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()
    _clear_proxy()
    os.environ["DIP_FORCE_VAL_LIVE"] = "1"

    from datetime import datetime

    from app.services.factors.dip_buy import (  # noqa: WPS433
        DEFAULT_PARAMS,
        UNIVERSES,
        fetch_and_cache_index_price,
        load_or_refresh_valuation,
    )
    from app.services.factors.national_team import fetch_etf_hist  # noqa: WPS433
    from scripts.refresh_national_team_data import _merge_daily  # noqa: WPS433

    for uid, meta in UNIVERSES.items():
        price = fetch_and_cache_index_price(meta["price_symbol"], meta["ak_price"], start=args.start)
        if price.empty:
            print(f"[warn] price {uid} empty")
        else:
            print(f"[ok] {meta['price_symbol']}_daily -> {price['date'].max().date()} n={len(price)}")
        val = load_or_refresh_valuation(uid, force=True)
        if val.empty:
            print(f"[warn] valuation {uid} empty")
        else:
            print(f"[ok] {uid}_valuation -> {val['date'].max().date()} n={len(val)}")

    # 交易 ETF 行情（回测成交标的）；缺日会导致指数绝对价误拼入收益
    end = datetime.now().strftime("%Y%m%d")
    start_etf = args.start.replace("-", "")
    etf_map = DEFAULT_PARAMS.get("etf_map") or {}
    etf_codes = sorted({str(c) for c in etf_map.values() if c})
    print("\n== trade ETFs ==")
    out_dir = ROOT / "data" / "factors"
    for code in etf_codes:
        path = out_dir / f"{code}_daily.parquet"
        try:
            raw = fetch_etf_hist(code, start=start_etf, end=end)
            merged = _merge_daily(path, raw)
            if merged.empty:
                print(f"[warn] {code}_daily empty")
            else:
                print(f"[ok] {code}_daily -> {merged['date'].max().date()} n={len(merged)}")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {code}_daily failed: {exc}")

    if args.backtest:
        from scripts.backtest_dip_buy_factor import run_backtest  # noqa: WPS433

        run_backtest()


if __name__ == "__main__":
    main()
