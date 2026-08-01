"""重算「不在 FACTOR_IMPL、但仍有 trade_legs」的因子：交易起点过滤 + 交易史入账腿。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import legs_to_trade_history  # noqa: E402


def has_pre2018_opens(fid: str) -> bool:
    th = kit.FACTORS_DATA / f"{fid}_trade_history.csv"
    if not th.exists():
        return False
    try:
        df = pd.read_csv(th, usecols=["date", "action"])
    except Exception:
        return False
    opens = df[df["action"].astype(str).str.contains("开")]
    if opens.empty:
        return False
    return bool((opens["date"].astype(str) < "2018-01-01").any())


def load_params(fid: str) -> dict:
    params: dict = {}
    jp = kit.FACTORS_DATA / f"{fid}_backtest.json"
    if jp.exists():
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(payload.get("params"), dict):
                params = dict(payload["params"])
        except Exception:
            pass
    if fid in FACTOR_IMPL:
        params = {**(FACTOR_IMPL[fid].get("params") or {}), **params}
    params.setdefault("universe", "hs300")
    params.setdefault("max_positions", 8)
    params.setdefault("commission_rate", 0.0001)
    params.setdefault("stamp_tax_sell", 0.001)
    params["position_logic"] = fid
    return params


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--all-orphans", action="store_true", help="不限 pre2018，重算全部孤儿 legs")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔 factor_id")
    args = ap.parse_args()

    ids = []
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]
    else:
        for p in sorted(kit.FACTORS_DATA.glob("*/trade_legs.parquet")):
            fid = p.parent.name
            if fid.startswith("_") or fid in FACTOR_IMPL:
                continue
            if args.all_orphans or has_pre2018_opens(fid):
                ids.append(fid)

    # 也收录有 pre2018 历史但命名不在子目录的？legs 都在子目录
    print(f"[plan] rebuild orphans n={len(ids)} start={args.start}", flush=True)

    cache_dir = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        "2016-01-01",
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
    )
    ok = fail = skip = 0
    for i, fid in enumerate(ids, 1):
        legs_path = kit.factor_cache_dir(fid) / "trade_legs.parquet"
        if not legs_path.exists():
            skip += 1
            print(f"[{i}/{len(ids)}] skip {fid}: no legs", flush=True)
            continue
        try:
            legs = pd.read_parquet(legs_path)
            params = load_params(fid)
            params["_cache_dir"] = str(cache_dir)
            title = str(params.get("note") or fid)
            daily, summary, accepted = kit.run_equal_weight_backtest(
                legs, params=params, bench_daily=bench, start=args.start
            )
            if daily.empty:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {fid}: {summary}", flush=True)
                continue
            trades = legs_to_trade_history(
                accepted, max_positions=int(params.get("max_positions") or 8)
            )
            kit.write_factor_artifacts(
                fid, daily, summary, trades, params=params, title=title, plot=bool(args.plot)
            )
            ok += 1
            print(
                f"[{i}/{len(ids)}] ok {fid}: ret={summary.get('total_return')} "
                f"sharpe={summary.get('sharpe')} legs={summary.get('n_legs_accepted')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{len(ids)}] fail {fid}: {exc}", flush=True)
    print(f"[done] ok={ok} skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
