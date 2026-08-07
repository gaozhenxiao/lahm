"""增量回测：近窗重算信号腿，与历史腿合并后重建净值（替代日常全量 rebacktest）。

比 rebacktest_all_factors 快的原因：
- 面板只加载最近 warmup+lookback 根（默认约 2~3 年），不扫 2016 至今全历史信号
- 历史已平仓腿直接复用
- 净值用合并后的 legs 重建（便宜）

用法:
  .venv/bin/python scripts/incremental_backtest_factors.py
  .venv/bin/python scripts/incremental_backtest_factors.py --lookback-days 180 --plot
  .venv/bin/python scripts/incremental_backtest_factors.py --only a,b --no-mongo
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROGRESS_JSONL = ROOT / "data" / "factors" / "incremental_backtest_progress.jsonl"
PROGRESS_JSON = ROOT / "data" / "factors" / "incremental_backtest_progress.json"
SUMMARY_JSON = ROOT / "data" / "factors" / "incremental_backtest_summary.json"


def _block_baostock() -> None:
    import app.services.factors.bs_kit as kit

    def _blocked():
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _blocked  # type: ignore[assignment]
    kit.BAOSTOCK_DOWNLOAD_BLACKLIST = True


def _append_progress(row: Dict[str, Any]) -> None:
    PROGRESS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        f.flush()


def _write_status(payload: Dict[str, Any]) -> None:
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    PROGRESS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _patch_plot(plot: bool) -> None:
    if plot:
        return
    import app.services.factors.bs_kit as kit

    if getattr(kit.write_factor_artifacts, "_incr_no_plot", False):
        return

    _orig = kit.write_factor_artifacts

    def _write_no_plot(*args, **kwargs):
        kwargs["plot"] = False
        return _orig(*args, **kwargs)

    _write_no_plot._incr_no_plot = True  # type: ignore[attr-defined]
    kit.write_factor_artifacts = _write_no_plot  # type: ignore[assignment]


def _tail_panel(
    price_map: Dict[str, pd.DataFrame],
    *,
    keep_from: pd.Timestamp,
) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for code, df in price_map.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d[d["date"] >= keep_from]
        if not d.empty:
            out[code] = d.reset_index(drop=True)
    return out


def _build_panel(
    universe: str,
    *,
    need_profit: bool,
    need_growth: bool,
    need_balance: bool,
    need_fin_db: bool,
    base_params: Dict[str, Any],
    keep_from: pd.Timestamp,
) -> Dict[str, Any]:
    from app.services.factors import bs_kit as kit
    from app.services.factors.runner import (
        enrich_with_ashare_fin,
        enrich_with_balance,
        enrich_with_growth,
        enrich_with_profit,
        prepare_price_panel,
    )

    cache = kit.shared_cache_dir()
    kit.clear_proxy()
    params = dict(base_params)
    params["universe"] = universe
    params["request_interval_sec"] = 0.01
    limiter = kit.RateLimiter(0.01)
    codes = kit.fetch_universe_codes(universe, limiter, cache)
    price_map: Dict[str, Any] = {}
    daily_dir = cache / "daily"
    for i, code in enumerate(codes, 1):
        fp = daily_dir / f"{code.replace('.', '_')}.parquet"
        if not fp.exists():
            continue
        try:
            raw = pd.read_parquet(fp)
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw[raw["date"] >= keep_from]
            if raw.empty:
                continue
            raw = prepare_price_panel(raw, params)
            raw["code"] = code
            price_map[code] = raw
        except Exception as exc:  # noqa: BLE001
            print(f"[panel] skip {code}: {exc}", flush=True)
        if i % 400 == 0:
            print(f"[panel] {universe} {i}/{len(codes)} loaded={len(price_map)}", flush=True)
    print(f"[panel] {universe} loaded={len(price_map)} from={keep_from.date()}", flush=True)
    if need_profit:
        price_map = enrich_with_profit(price_map, params, cache)
        price_map = _tail_panel(price_map, keep_from=keep_from)
    if need_growth:
        price_map = enrich_with_growth(price_map, params, cache)
        price_map = _tail_panel(price_map, keep_from=keep_from)
    if need_fin_db:
        price_map = enrich_with_ashare_fin(price_map, params, cache)
        price_map = _tail_panel(price_map, keep_from=keep_from)
    if need_balance:
        sample = next(iter(price_map.values()), None)
        if sample is None or "contract_liab" not in getattr(sample, "columns", []):
            price_map = enrich_with_balance(price_map, params, cache)
            price_map = _tail_panel(price_map, keep_from=keep_from)
    return price_map


def _merge_legs(old: pd.DataFrame, new: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    if old is not None and not old.empty:
        o = old.copy()
        o["entry_date"] = pd.to_datetime(o["entry_date"], errors="coerce")
        o["exit_date"] = pd.to_datetime(o["exit_date"], errors="coerce")
        # 截止日前已完全平仓的腿复用；未平仓/近窗腿丢弃，由新算覆盖
        keep = (o["entry_date"] < cutoff) & (o["exit_date"] < cutoff) & (o.get("reason", "") != "open")
        if "reason" in o.columns:
            keep = (o["entry_date"] < cutoff) & (o["exit_date"] < cutoff) & (o["reason"].astype(str) != "open")
        else:
            keep = (o["entry_date"] < cutoff) & (o["exit_date"] < cutoff)
        o = o.loc[keep]
        if not o.empty:
            frames.append(o)
    if new is not None and not new.empty:
        n = new.copy()
        n["entry_date"] = pd.to_datetime(n["entry_date"], errors="coerce")
        n["exit_date"] = pd.to_datetime(n["exit_date"], errors="coerce")
        n = n[n["entry_date"] >= cutoff]
        if not n.empty:
            frames.append(n)
    if not frames:
        return pd.DataFrame(
            columns=["code", "entry_date", "entry_price", "exit_date", "exit_price", "reason", "note"]
        )
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["entry_date", "code"]).sort_values(["entry_date", "code"])
    out = out.drop_duplicates(subset=["code", "entry_date"], keep="last").reset_index(drop=True)
    return out


def _run_one(
    fid: str,
    price_map: Dict[str, Any],
    *,
    start: str,
    cutoff: pd.Timestamp,
    plot: bool,
) -> Dict[str, Any]:
    from app.services.factors import bs_kit as kit
    from app.services.factors.factor_registry import FACTOR_IMPL
    from app.services.factors.runner import (
        collect_legs,
        legs_to_trade_history,
        _trade_history_weight_mode,
    )

    _patch_plot(plot)
    meta = FACTOR_IMPL[fid]
    params = dict(meta["params"])
    params["position_logic"] = fid
    title = str(meta.get("title") or fid)
    params["note"] = title
    cache_dir = kit.shared_cache_dir()
    params["_cache_dir"] = str(cache_dir)
    factor_dir = kit.factor_cache_dir(fid)

    new_legs = collect_legs(price_map, meta["signal"], params)
    old_path = factor_dir / "trade_legs.parquet"
    old = pd.read_parquet(old_path) if old_path.exists() else pd.DataFrame()
    legs = _merge_legs(old, new_legs, cutoff)
    print(
        f"[{fid}] new_legs={0 if new_legs is None else len(new_legs)} "
        f"merged={len(legs)} cutoff={cutoff.date()}",
        flush=True,
    )
    if not legs.empty:
        legs.to_parquet(old_path, index=False)

    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        str(params.get("bench_code") or "sh.000300"),
        str(params.get("price_start") or "2016-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
        cache_only=True,
    )
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=start
    )
    if daily is None or daily.empty:
        return summary if isinstance(summary, dict) else {"error": "empty_backtest"}
    trades = legs_to_trade_history(
        accepted,
        max_positions=int(params.get("max_positions") or 8),
        weight_mode=_trade_history_weight_mode(params),
    )
    kit.write_factor_artifacts(fid, daily, summary, trades, params=params, title=title, plot=plot)
    return summary if isinstance(summary, dict) else {"error": str(summary)}


def _worker_batch(
    batch_id: int,
    ids: Sequence[str],
    *,
    start: str,
    lookback_days: int,
    warmup_days: int,
    plot: bool,
) -> Dict[str, Any]:
    _block_baostock()
    from app.services.factors.factor_registry import FACTOR_IMPL

    today = pd.Timestamp(datetime.now().date())
    cutoff = today - pd.Timedelta(days=int(lookback_days))
    keep_from = cutoff - pd.Timedelta(days=int(warmup_days))

    results: Dict[str, Any] = {}
    ok = fail = 0
    by_uni: Dict[str, List[str]] = defaultdict(list)
    needs_by_uni: Dict[str, Dict[str, bool]] = defaultdict(
        lambda: {
            "need_profit": False,
            "need_growth": False,
            "need_balance": False,
            "need_fin_db": False,
        }
    )
    for fid in ids:
        meta = FACTOR_IMPL[fid]
        u = str((meta.get("params") or {}).get("universe") or "hs300")
        by_uni[u].append(fid)
        needs_by_uni[u]["need_profit"] |= bool(meta.get("need_profit"))
        needs_by_uni[u]["need_growth"] |= bool(meta.get("need_growth"))
        needs_by_uni[u]["need_balance"] |= bool(meta.get("need_balance"))
        needs_by_uni[u]["need_fin_db"] |= bool(meta.get("need_fin_db"))

    base_params = dict(next(iter(FACTOR_IMPL.values()))["params"])
    total = len(ids)
    done = 0

    for u, fids in sorted(by_uni.items(), key=lambda x: -len(x[1])):
        t_panel = time.time()
        try:
            panel = _build_panel(
                u,
                base_params=base_params,
                keep_from=keep_from,
                **needs_by_uni[u],
            )
        except Exception as exc:  # noqa: BLE001
            for fid in fids:
                fail += 1
                done += 1
                err = {"error": f"panel_fail:{u}:{exc}"}
                results[fid] = err
                _append_progress(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "batch": batch_id,
                        "factor_id": fid,
                        "status": "fail",
                        "error": err["error"],
                        "done": done,
                        "total_batch": total,
                    }
                )
            continue
        print(
            f"[batch {batch_id}] panel {u} n={len(panel)} "
            f"sec={time.time() - t_panel:.1f} factors={len(fids)}",
            flush=True,
        )
        for fid in fids:
            t0 = time.time()
            try:
                summary = _run_one(fid, panel, start=start, cutoff=cutoff, plot=plot)
                if summary.get("error") and "total_return" not in summary:
                    status = "fail"
                    fail += 1
                else:
                    status = "ok"
                    ok += 1
                results[fid] = {
                    k: summary.get(k)
                    for k in (
                        "total_return",
                        "annual_return",
                        "sharpe",
                        "max_drawdown",
                        "n_legs_accepted",
                        "n_legs_raw",
                        "start",
                        "end",
                        "error",
                    )
                    if k in summary or k == "error"
                }
            except Exception as exc:  # noqa: BLE001
                status = "fail"
                fail += 1
                results[fid] = {"error": str(exc), "traceback": traceback.format_exc()[-800:]}
            done += 1
            _append_progress(
                {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "batch": batch_id,
                    "factor_id": fid,
                    "status": status,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "done": done,
                    "total_batch": total,
                    "summary": results[fid],
                }
            )
            print(f"[batch {batch_id}] {status} {fid} {time.time() - t0:.1f}s", flush=True)

    return {"ok": ok, "fail": fail, "results": results}


def _chunk(ids: List[str], n: int) -> List[List[str]]:
    n = max(1, int(n))
    buckets: List[List[str]] = [[] for _ in range(n)]
    for i, fid in enumerate(ids):
        buckets[i % n].append(fid)
    return [b for b in buckets if b]


def _update_mongo(results: Dict[str, Any]) -> Tuple[int, int]:
    try:
        from dotenv import dotenv_values
        from pymongo import MongoClient
    except Exception:
        return 0, 0
    cfg = dotenv_values(ROOT / ".env")
    host = cfg.get("MONGODB_HOST") or "127.0.0.1"
    port = int(cfg.get("MONGODB_PORT") or 27017)
    user = cfg.get("MONGODB_USERNAME")
    pwd = cfg.get("MONGODB_PASSWORD")
    auth = cfg.get("MONGODB_AUTH_SOURCE") or "admin"
    db_name = cfg.get("MONGODB_DATABASE") or "lahm"
    client = MongoClient(host=host, port=port, username=user, password=pwd, authSource=auth)
    db = client[db_name]
    updated = missing = 0
    now = datetime.now()
    for fid, row in results.items():
        if not isinstance(row, dict) or row.get("error") and "total_return" not in row:
            continue
        metrics = {k: row.get(k) for k in ("total_return", "annual_return", "sharpe", "max_drawdown", "start", "end") if k in row}
        for k in ("n_legs_accepted", "n_legs_raw"):
            if k in row:
                metrics[k] = row[k]
        r = db["factors"].update_one(
            {"factor_id": fid},
            {"$set": {"backtest_summary": metrics, "updated_at": now}},
            upsert=False,
        )
        if r.matched_count:
            updated += 1
        else:
            missing += 1
    return updated, missing


def main() -> None:
    ap = argparse.ArgumentParser(description="增量回测（近窗信号 + 历史腿合并）")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--lookback-days", type=int, default=180, help="重算信号的近窗天数")
    ap.add_argument("--warmup-days", type=int, default=800, help="指标预热天数（百分位/均线）")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--no-mongo", action="store_true")
    ap.add_argument("--batch-worker", type=int, default=-1, help=argparse.SUPPRESS)
    ap.add_argument("--batch-ids", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.batch_worker >= 0:
        ids = [x.strip() for x in args.batch_ids.split(",") if x.strip()]
        out = _worker_batch(
            args.batch_worker,
            ids,
            start=args.start,
            lookback_days=args.lookback_days,
            warmup_days=args.warmup_days,
            plot=bool(args.plot),
        )
        out_path = ROOT / "data" / "factors" / f"_incr_batch_{args.batch_worker}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"batch_done": args.batch_worker, "ok": out["ok"], "fail": out["fail"]}))
        return

    _block_baostock()
    from app.services.factors.factor_registry import FACTOR_IMPL
    from app.services.factors_service import RETIRED_FACTOR_IDS

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]
    ids = [x for x in ids if x not in RETIRED_FACTOR_IDS]

    PROGRESS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_JSONL.write_text("", encoding="utf-8")
    t0 = time.time()
    _write_status(
        {
            "phase": "start",
            "mode": "incremental",
            "n_factors": len(ids),
            "workers": args.workers,
            "lookback_days": args.lookback_days,
            "warmup_days": args.warmup_days,
            "start": args.start,
        }
    )
    print(
        f"[incremental] factors={len(ids)} workers={args.workers} "
        f"lookback={args.lookback_days}d warmup={args.warmup_days}d",
        flush=True,
    )

    chunks = _chunk(ids, args.workers)
    py = sys.executable
    procs: List[subprocess.Popen] = []
    batch_outs: List[Path] = []
    for bi, chunk in enumerate(chunks):
        out_path = ROOT / "data" / "factors" / f"_incr_batch_{bi}.json"
        if out_path.exists():
            out_path.unlink()
        batch_outs.append(out_path)
        cmd = [
            py,
            str(ROOT / "scripts" / "incremental_backtest_factors.py"),
            "--batch-worker",
            str(bi),
            "--batch-ids",
            ",".join(chunk),
            "--start",
            args.start,
            "--lookback-days",
            str(args.lookback_days),
            "--warmup-days",
            str(args.warmup_days),
        ]
        if args.plot:
            cmd.append("--plot")
        log_path = ROOT / "data" / "factors" / f"_incr_batch_{bi}.log"
        log_f = log_path.open("w", encoding="utf-8")
        p = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        procs.append(p)
        print(f"[incremental] spawned batch={bi} n={len(chunk)} pid={p.pid}", flush=True)

    while True:
        alive = sum(1 for p in procs if p.poll() is None)
        done_lines = 0
        if PROGRESS_JSONL.exists():
            done_lines = sum(1 for _ in PROGRESS_JSONL.open(encoding="utf-8") if _.strip())
        _write_status(
            {
                "phase": "running",
                "mode": "incremental",
                "n_factors": len(ids),
                "progress_lines": done_lines,
                "alive_workers": alive,
                "elapsed_sec": round(time.time() - t0, 1),
            }
        )
        if alive == 0:
            break
        time.sleep(10)

    merged: Dict[str, Any] = {}
    ok = fail = 0
    for path in batch_outs:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ok += int(payload.get("ok") or 0)
        fail += int(payload.get("fail") or 0)
        merged.update(payload.get("results") or {})

    mongo_ops = 0
    if not args.no_mongo:
        mongo_ops, _ = _update_mongo(merged)

    summary = {
        "phase": "done",
        "mode": "incremental",
        "ok": ok,
        "fail": fail,
        "total": len(ids),
        "lookback_days": args.lookback_days,
        "warmup_days": args.warmup_days,
        "elapsed_sec": round(time.time() - t0, 1),
        "mongo_update_ops": mongo_ops,
        "fails": [k for k, v in merged.items() if isinstance(v, dict) and v.get("error") and "total_return" not in v],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_status(summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()