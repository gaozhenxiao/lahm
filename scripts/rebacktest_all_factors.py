"""全量活跃因子完整重跑回测（腾讯 qfq 本地缓存；禁用 BaoStock）。

按各因子 params.universe 准备面板，重算 legs / equity / trades，并 UPDATE Mongo 摘要。
不改因子编号（不碰 created_at）；跳过 RETIRED。

用法:
  .venv\\Scripts\\python.exe scripts/rebacktest_all_factors.py
  .venv\\Scripts\\python.exe scripts/rebacktest_all_factors.py --workers 4
  .venv\\Scripts\\python.exe scripts/rebacktest_all_factors.py --only a,b --no-mongo
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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROGRESS_JSONL = ROOT / "data" / "factors" / "rebacktest_all_progress.jsonl"
PROGRESS_JSON = ROOT / "data" / "factors" / "rebacktest_all_progress.json"
SUMMARY_JSON = ROOT / "data" / "factors" / "rebacktest_all_summary.json"


def _block_baostock() -> None:
    """禁用 BaoStock 登录；缺缓存时走空表/已有 parquet，不联网拉数。"""
    import app.services.factors.bs_kit as kit

    def _blocked():
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _blocked  # type: ignore[assignment]
    kit.BAOSTOCK_DOWNLOAD_BLACKLIST = True


def _append_progress(row: Dict[str, Any]) -> None:
    PROGRESS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str)
    with PROGRESS_JSONL.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def _write_status(payload: Dict[str, Any]) -> None:
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    PROGRESS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_panel(
    universe: str,
    *,
    need_profit: bool,
    need_growth: bool,
    need_balance: bool,
    need_fin_db: bool,
    base_params: Dict[str, Any],
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
    print(
        f"[panel] universe={universe} codes={len(codes)} "
        f"profit={need_profit} growth={need_growth} balance={need_balance} fin={need_fin_db}",
        flush=True,
    )
    price_map: Dict[str, Any] = {}
    daily_dir = cache / "daily"
    for i, code in enumerate(codes, 1):
        fp = daily_dir / f"{code.replace('.', '_')}.parquet"
        if not fp.exists():
            continue
        try:
            import pandas as pd

            raw = pd.read_parquet(fp)
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
            raw = prepare_price_panel(raw, params)
            raw["code"] = code
            if not raw.empty:
                price_map[code] = raw
        except Exception as exc:  # noqa: BLE001
            print(f"[panel] skip {code}: {exc}", flush=True)
        if i % 200 == 0:
            print(
                f"[panel] {universe} daily {i}/{len(codes)} loaded={len(price_map)}",
                flush=True,
            )
    print(f"[panel] {universe} loaded={len(price_map)}", flush=True)
    if need_profit:
        price_map = enrich_with_profit(price_map, params, cache)
    if need_growth:
        price_map = enrich_with_growth(price_map, params, cache)
    if need_fin_db:
        price_map = enrich_with_ashare_fin(price_map, params, cache)
    if need_balance:
        sample = next(iter(price_map.values()), None)
        if sample is None or "contract_liab" not in getattr(sample, "columns", []):
            price_map = enrich_with_balance(price_map, params, cache)
    return price_map


def _subset_panel(price_map: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """共享最大面板时，按因子需求裁切列不是必须；直接复用全量面板即可。"""
    return price_map


def _patch_plot(plot: bool) -> None:
    if plot:
        return
    from app.services.factors import bs_kit as kit

    if getattr(kit.write_factor_artifacts, "_rebacktest_no_plot", False):
        return
    _orig = kit.write_factor_artifacts

    def _write_no_plot(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["plot"] = False
        return _orig(*args, **kwargs)

    _write_no_plot._rebacktest_no_plot = True  # type: ignore[attr-defined]
    kit.write_factor_artifacts = _write_no_plot  # type: ignore[assignment]


def run_one_factor(
    fid: str,
    price_map: Dict[str, Any],
    *,
    start: str,
    plot: bool,
) -> Dict[str, Any]:
    from app.services.factors.factor_registry import FACTOR_IMPL
    from app.services.factors.runner import run_factor_pipeline

    _patch_plot(plot)
    meta = FACTOR_IMPL[fid]
    summary = run_factor_pipeline(
        fid,
        meta["title"],
        meta["signal"],
        meta["params"],
        need_profit=bool(meta.get("need_profit")),
        need_growth=bool(meta.get("need_growth")),
        need_balance=bool(meta.get("need_balance")),
        need_fin_db=bool(meta.get("need_fin_db")),
        limit=0,
        start=start,
        price_map=_subset_panel(price_map, meta),
    )
    return summary if isinstance(summary, dict) else {"error": str(summary)}


def _worker_batch(
    batch_id: int,
    ids: Sequence[str],
    *,
    start: str,
    plot: bool,
) -> Dict[str, Any]:
    """子进程：按宇宙建面板，串行跑本批因子。"""
    _block_baostock()
    from app.services.factors.factor_registry import FACTOR_IMPL

    t_batch = time.time()
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
            panel = _build_panel(u, base_params=base_params, **needs_by_uni[u])
        except Exception as exc:  # noqa: BLE001
            for fid in fids:
                err = {"error": f"panel_fail:{u}:{exc}"}
                results[fid] = err
                fail += 1
                done += 1
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
                summary = run_one_factor(fid, panel, start=start, plot=plot)
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
                if summary.get("error"):
                    results[fid]["error"] = summary.get("error")
            except Exception as exc:  # noqa: BLE001
                status = "fail"
                fail += 1
                results[fid] = {"error": str(exc), "traceback": traceback.format_exc()[-800:]}
            done += 1
            elapsed = round(time.time() - t0, 2)
            row = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "batch": batch_id,
                "factor_id": fid,
                "status": status,
                "elapsed_sec": elapsed,
                "done": done,
                "total_batch": total,
                "summary": results[fid],
            }
            _append_progress(row)
            print(
                f"[batch {batch_id}] [{done}/{total}] {status} {fid} "
                f"sec={elapsed} sharpe={results[fid].get('sharpe')}",
                flush=True,
            )

    return {
        "batch_id": batch_id,
        "ok": ok,
        "fail": fail,
        "elapsed_sec": round(time.time() - t_batch, 2),
        "results": results,
    }


def _chunk(ids: List[str], n: int) -> List[List[str]]:
    n = max(1, min(n, len(ids) or 1))
    # 轮询分片，避免同一宇宙全挤在一个 worker
    buckets: List[List[str]] = [[] for _ in range(n)]
    for i, fid in enumerate(ids):
        buckets[i % n].append(fid)
    return [b for b in buckets if b]


def _sync_mongo(ids: Sequence[str]) -> Tuple[int, int]:
    """仅 UPDATE 已有 factors 文档的 backtest_summary；不改 created_at / 编号。"""
    from pymongo import MongoClient

    from app.core.config import settings
    from app.services.factors_service import _metric_slice

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    db_names = list(dict.fromkeys([settings.MONGO_DB, "lahm"]))
    updated = 0
    missing = 0
    now = datetime.now()
    for fid in ids:
        path = ROOT / "data" / "factors" / f"{fid}_backtest.json"
        if not path.exists():
            missing += 1
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            missing += 1
            continue
        results = raw.get("results") or {}
        row = None
        if isinstance(results, dict):
            for key in (fid, "main"):
                if isinstance(results.get(key), dict):
                    row = results[key]
                    break
            if row is None:
                for v in results.values():
                    if isinstance(v, dict) and ("sharpe" in v or "total_return" in v):
                        row = v
                        break
        if not row:
            missing += 1
            continue
        metrics = _metric_slice(row)
        metrics["updated_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(
            timespec="seconds"
        )
        metrics["source"] = path.name
        for k in ("n_legs_accepted", "n_legs_raw", "avg_position", "position_logic"):
            if k in row:
                metrics[k] = row[k]
        payload = {"backtest_summary": metrics, "updated_at": now}
        for db_name in db_names:
            r = client[db_name]["factors"].update_one(
                {"factor_id": fid},
                {"$set": payload},
                upsert=False,  # 严禁新建/改号
            )
            if r.matched_count:
                updated += 1
    return updated, missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4, help="并行进程数")
    ap.add_argument("--only", default="", help="逗号分隔 factor_id")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--plot", action="store_true", help="重画净值图（默认跳过加速）")
    ap.add_argument("--no-mongo", action="store_true")
    ap.add_argument(
        "--batch-worker",
        type=int,
        default=-1,
        help=argparse.SUPPRESS,  # 内部：子进程入口
    )
    ap.add_argument("--batch-ids", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # 子进程模式
    if args.batch_worker >= 0:
        ids = [x.strip() for x in args.batch_ids.split(",") if x.strip()]
        out = _worker_batch(
            args.batch_worker,
            ids,
            start=args.start,
            plot=bool(args.plot),
        )
        out_path = ROOT / "data" / "factors" / f"_rebacktest_batch_{args.batch_worker}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"batch_done": args.batch_worker, "ok": out["ok"], "fail": out["fail"]}))
        return

    _block_baostock()
    from app.services.factors.factor_registry import FACTOR_IMPL
    from app.services.factors_service import RETIRED_FACTOR_IDS

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]
        bad = [x for x in ids if x not in FACTOR_IMPL]
        if bad:
            raise SystemExit(f"unknown factor ids: {bad}")
    ids = [x for x in ids if x not in RETIRED_FACTOR_IDS]

    # 清空进度日志
    PROGRESS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_JSONL.write_text("", encoding="utf-8")
    t0 = time.time()
    _write_status(
        {
            "phase": "start",
            "n_factors": len(ids),
            "workers": args.workers,
            "start": args.start,
            "baostock": "disabled",
            "ids_preview": ids[:20],
        }
    )
    print(
        f"[rebacktest] factors={len(ids)} workers={args.workers} start={args.start}",
        flush=True,
    )

    chunks = _chunk(ids, args.workers)
    # 用子进程隔离内存；Windows 友好
    py = sys.executable
    procs: List[subprocess.Popen] = []
    batch_outs: List[Path] = []
    for bi, chunk in enumerate(chunks):
        out_path = ROOT / "data" / "factors" / f"_rebacktest_batch_{bi}.json"
        if out_path.exists():
            out_path.unlink()
        batch_outs.append(out_path)
        cmd = [
            py,
            str(ROOT / "scripts" / "rebacktest_all_factors.py"),
            "--batch-worker",
            str(bi),
            "--batch-ids",
            ",".join(chunk),
            "--start",
            args.start,
        ]
        if args.plot:
            cmd.append("--plot")
        log_path = ROOT / "data" / "factors" / f"_rebacktest_batch_{bi}.log"
        log_f = log_path.open("w", encoding="utf-8")
        p = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        procs.append(p)
        print(f"[rebacktest] spawned batch={bi} n={len(chunk)} pid={p.pid}", flush=True)

    # 轮询进度
    while True:
        alive = sum(1 for p in procs if p.poll() is None)
        done_lines = 0
        if PROGRESS_JSONL.exists():
            done_lines = sum(1 for _ in PROGRESS_JSONL.open(encoding="utf-8") if _.strip())
        _write_status(
            {
                "phase": "running",
                "n_factors": len(ids),
                "progress_lines": done_lines,
                "alive_workers": alive,
                "elapsed_sec": round(time.time() - t0, 1),
            }
        )
        if alive == 0:
            break
        time.sleep(15)

    rcodes = [p.wait() for p in procs]
    merged: Dict[str, Any] = {}
    ok = fail = 0
    for path in batch_outs:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for fid, row in (data.get("results") or {}).items():
            merged[fid] = row
            if isinstance(row, dict) and row.get("error") and "total_return" not in row:
                fail += 1
            elif isinstance(row, dict) and "total_return" in row:
                ok += 1
            elif isinstance(row, dict) and not row.get("error"):
                ok += 1
            else:
                fail += 1

    # 未出现在 merged 的视为失败
    for fid in ids:
        if fid not in merged:
            merged[fid] = {"error": "missing_batch_result"}
            fail += 1

    mongo_updated = mongo_missing = 0
    if not args.no_mongo:
        ok_ids = [
            fid
            for fid, row in merged.items()
            if isinstance(row, dict) and ("total_return" in row or not row.get("error"))
        ]
        try:
            mongo_updated, mongo_missing = _sync_mongo(ok_ids)
        except Exception as exc:  # noqa: BLE001
            print(f"[mongo] sync fail: {exc}", flush=True)

    elapsed = round(time.time() - t0, 1)
    fails = sorted(
        [
            fid
            for fid, row in merged.items()
            if not (isinstance(row, dict) and ("total_return" in row or not row.get("error")))
        ]
    )
    summary = {
        "ok": ok,
        "fail": fail,
        "total": len(ids),
        "elapsed_sec": elapsed,
        "worker_returncodes": rcodes,
        "mongo_update_ops": mongo_updated,
        "mongo_missing_json": mongo_missing,
        "fails": fails,
        "results": merged,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_status(
        {
            "phase": "done",
            "ok": ok,
            "fail": fail,
            "total": len(ids),
            "elapsed_sec": elapsed,
            "fails": fails,
            "mongo_update_ops": mongo_updated,
        }
    )
    print(
        f"\n[rebacktest] DONE ok={ok} fail={fail} total={len(ids)} "
        f"elapsed={elapsed}s mongo_ops={mongo_updated}",
        flush=True,
    )
    if fails:
        print(f"[rebacktest] fails: {fails}", flush=True)


if __name__ == "__main__":
    # Windows spawn 安全
    main()
