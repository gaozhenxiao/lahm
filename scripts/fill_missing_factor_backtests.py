#!/usr/bin/env python3
"""补跑并填充缺回测的因子（builtin + 银行 J66）。

- 写 data/factors 产物
- UPDATE Mongo backtest_summary（不改 created_at）

用法:
  python scripts/fill_missing_factor_backtests.py
  python scripts/fill_missing_factor_backtests.py --only bank
  python scripts/fill_missing_factor_backtests.py --only builtins
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    collect_legs,
    legs_to_trade_history,
    prepare_shared_panel,
    _trade_history_weight_mode,
)
from app.services.factors_service import _metric_slice  # noqa: E402

BANK_IDS = [
    "bank_pe_low_reclaim_j66",
    "bank_dual_gv_j66",
    "bank_pb_below_j66",
]
BUILTIN_SCRIPTS = [
    ("national_team", ["scripts/backtest_national_team_factor.py", "--logic", "compare"]),
    ("dip_buy", ["scripts/backtest_dip_buy_factor.py"]),
    ("earnings_forecast", ["scripts/backtest_earnings_forecast_factor.py"]),
    ("dividend_etf_swing", ["scripts/backtest_dividend_etf_swing.py", "--force-fetch"]),
    ("dividend_etf_slope_grid", ["scripts/backtest_dividend_etf_slope_grid.py", "--force-fetch"]),
    ("cm_big4_slope_grid", ["scripts/backtest_cm_big4_slope_grid.py", "--also-factor", "--force-fetch"]),
]
START = "2018-01-01"


def _load_summary_from_json(fid: str) -> Dict[str, Any]:
    path = ROOT / "data" / "factors" / f"{fid}_backtest.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = raw.get("results") or {}
    # prefer exact key
    if fid in results and isinstance(results[fid], dict):
        return results[fid]
    # national_team / dip_buy may have multiple logics
    out: Dict[str, Any] = {}
    for k, v in results.items():
        if isinstance(v, dict) and ("sharpe" in v or "total_return" in v or "position_logic" in v):
            out[str(v.get("position_logic") or k)] = v
    if len(out) == 1:
        return next(iter(out.values()))
    if out:
        return {"_multi": out}
    # sometimes results is itself the summary
    if isinstance(results, dict) and ("sharpe" in results or "total_return" in results):
        return results
    return {}


def _update_mongo(fid: str, summary: Dict[str, Any], *, window_end: Optional[str] = None) -> int:
    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    now = datetime.now()
    updated = 0
    multi = summary.get("_multi") if isinstance(summary, dict) else None
    if multi:
        logics = {k: _metric_slice(v) for k, v in multi.items() if isinstance(v, dict)}
        primary = next(iter(logics.keys()), fid)
        err = None
        available = bool(logics)
    else:
        err = summary.get("error") if isinstance(summary, dict) else "empty"
        available = bool(summary) and not err and (
            summary.get("sharpe") is not None or summary.get("total_return") is not None
        )
        logics = {fid: _metric_slice(summary)} if available else {}
        primary = fid

    end = window_end or (summary.get("end") if isinstance(summary, dict) else None) or "2026-08-05"
    payload = {
        "backtest_summary": {
            "available": available,
            "primary_logic": primary,
            "logics": logics,
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "window": {"start": START, "end": str(end)[:10]},
        },
        "last_backtest_error": err,
        "updated_at": now,
    }
    for dbn in dict.fromkeys([settings.MONGO_DB, "lahm"]):
        db = client[dbn]
        res = db.factors.update_one({"factor_id": fid}, {"$set": payload})
        if res.matched_count:
            updated += 1
            print(f"[mongo] UPDATE {dbn}.{fid} available={available} err={err}", flush=True)
        else:
            print(f"[mongo] MISS {dbn}.{fid}", flush=True)
    return updated


def fill_banks() -> Dict[str, Dict[str, Any]]:
    cache = kit.shared_cache_dir()
    uni = cache / "universe_ind_j66.parquet"
    if not uni.exists():
        raise SystemExit(f"missing {uni}")
    codes = pd.read_parquet(uni)["code"].astype(str).tolist()
    print(f"[bank] universe n={len(codes)}", flush=True)
    missing = [x for x in BANK_IDS if x not in FACTOR_IMPL]
    if missing:
        raise SystemExit(f"not in FACTOR_IMPL: {missing}")

    # 禁用 BaoStock：只用已有 parquet（qfq daily + profit/growth 缓存），避免登录挂死
    def _blocked_bs_login():
        raise RuntimeError("BaoStock disabled for fill_banks (local-cache only)")

    kit.bs_login = _blocked_bs_login  # type: ignore[assignment]
    if hasattr(kit, "BAOSTOCK_DOWNLOAD_BLACKLIST"):
        kit.BAOSTOCK_DOWNLOAD_BLACKLIST = True  # type: ignore[attr-defined]

    meta0 = FACTOR_IMPL[BANK_IDS[0]]
    params0 = dict(meta0["params"])
    params0["price_end"] = datetime.now().strftime("%Y-%m-%d")
    params0["request_interval_sec"] = 0.01
    params0["_codes"] = codes
    panel = prepare_shared_panel(
        params0,
        need_profit=True,
        need_growth=True,
        need_balance=False,
        need_fin_db=False,
        limit=0,
        codes=codes,
    )
    print(f"[bank] panel n={len(panel)}", flush=True)
    bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    out: Dict[str, Dict[str, Any]] = {}
    for fid in BANK_IDS:
        meta = FACTOR_IMPL[fid]
        params = dict(meta["params"])
        params["_cache_dir"] = str(cache)
        params["position_logic"] = fid
        params["price_end"] = params0["price_end"]
        params["_codes"] = codes
        legs = collect_legs(panel, meta["signal"], params)
        daily, summary, accepted = kit.run_equal_weight_backtest(
            legs, params=params, bench_daily=bench, start=START
        )
        if not isinstance(summary, dict):
            summary = {"error": str(summary)}
        if daily is not None and not daily.empty and not summary.get("error"):
            trades = legs_to_trade_history(
                accepted,
                max_positions=int(params.get("max_positions") or 6),
                weight_mode=_trade_history_weight_mode(params),
            )
            kit.write_factor_artifacts(
                fid, daily, summary, trades, params=params, title=meta.get("title") or fid
            )
        out[fid] = summary
        print(
            f"[bank] {fid} sh={summary.get('sharpe')} ret={summary.get('total_return')} "
            f"legs={summary.get('n_legs_accepted')} err={summary.get('error')}",
            flush=True,
        )
        _update_mongo(fid, summary, window_end=summary.get("end"))
    return out


def fill_builtins(*, skip_run: bool = False) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    py = sys.executable
    for fid, args in BUILTIN_SCRIPTS:
        if not skip_run:
            cmd = [py, *args]
            print("[run]", " ".join(cmd), flush=True)
            p = subprocess.run(cmd, cwd=str(ROOT))
            results[fid] = {"returncode": p.returncode}
            if p.returncode != 0:
                print(f"[warn] {fid} script failed rc={p.returncode}", flush=True)
                continue
        summary = _load_summary_from_json(fid)
        if not summary:
            # try reading nested results for national_team style
            path = ROOT / "data" / "factors" / f"{fid}_backtest.json"
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                results_map = raw.get("results") or {}
                if results_map:
                    summary = {"_multi": {str(k): v for k, v in results_map.items() if isinstance(v, dict)}}
        if summary:
            end = None
            if "_multi" not in summary:
                end = summary.get("end")
            _update_mongo(fid, summary, window_end=end)
            results[fid] = {**(results.get(fid) or {}), "summary_ok": True, "sharpe": summary.get("sharpe")}
        else:
            results[fid] = {**(results.get(fid) or {}), "summary_ok": False}
            print(f"[warn] no summary json for {fid}", flush=True)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["all", "bank", "builtins"], default="all")
    ap.add_argument("--builtins-skip-run", action="store_true", help="只同步已有产物到 Mongo")
    args = ap.parse_args()

    report: Dict[str, Any] = {"started_at": datetime.now().isoformat(timespec="seconds")}
    try:
        if args.only in ("all", "bank"):
            report["bank"] = fill_banks()
        if args.only in ("all", "builtins"):
            report["builtins"] = fill_builtins(skip_run=args.builtins_skip_run)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-2000:]
        print(report["traceback"], flush=True)
        raise
    finally:
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        out = ROOT / "data" / "factors" / "fill_missing_factor_backtests_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[ok] report -> {out}", flush=True)


if __name__ == "__main__":
    main()
