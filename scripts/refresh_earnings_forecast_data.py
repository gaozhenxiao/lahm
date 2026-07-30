"""刷新业绩预告因子缓存（baostock，限速）。

用法:
  python scripts/refresh_earnings_forecast_data.py --limit 40
  python scripts/refresh_earnings_forecast_data.py --universe hs300 --backtest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="hs300", choices=["hs300", "zz500"])
    parser.add_argument("--limit", type=int, default=0, help="仅取前 N 只（冒烟用）")
    parser.add_argument("--forecast-start", default="2018-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--interval", type=float, default=0.4, help="baostock 请求间隔秒")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()

    from app.services.factors.earnings_forecast import (  # noqa: WPS433
        DEFAULT_PARAMS,
        build_trade_legs,
        collect_positive_events,
        fetch_universe_codes,
        run_portfolio_backtest,
        _RateLimiter,
        _data_dir,
    )

    params = {
        **DEFAULT_PARAMS,
        "universe": args.universe,
        "forecast_start": args.forecast_start,
        "request_interval_sec": args.interval,
    }
    limiter = _RateLimiter(args.interval)
    print(f"[refresh] universe={args.universe} end={args.end} interval={args.interval}s")
    codes = fetch_universe_codes(args.universe, limiter)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]
    print(f"[refresh] codes={len(codes)}")

    events = collect_positive_events(
        codes, params, end_date=args.end, force=args.force, progress_every=10
    )
    print(f"[refresh] positive events={len(events)}")
    if events.empty:
        print("[warn] no events; stop")
        return

    legs = build_trade_legs(
        events,
        params,
        price_start="2017-06-01",
        price_end=args.end,
        force_price=args.force,
    )
    print(f"[refresh] trade legs (raw)={len(legs)}")

    if args.backtest:
        from scripts.backtest_earnings_forecast_factor import run_backtest  # noqa: WPS433

        run_backtest(params=params, start="2018-01-01", end=args.end)

    meta = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "universe": args.universe,
        "n_codes": len(codes),
        "n_events": int(len(events)),
        "n_legs": int(len(legs)),
        "params": params,
    }
    out = _data_dir() / "refresh_meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {out}")


if __name__ == "__main__":
    main()
