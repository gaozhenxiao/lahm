"""将本轮已重算因子的净值摘要增量同步到 Mongo。

UI/API 的 Sharpe/收益实际来自本地 data/factors/{id}_backtest.json
（factors_service._build_backtest_summary），不读 Mongo。
本脚本仍把摘要写入 factors 文档的 backtest_summary 字段，并刷新 updated_at，
便于排查与后续消费；可在全量重算进行中反复跑。

用法:
  python scripts/sync_rebuilt_factor_nav_to_mongo.py
  python scripts/sync_rebuilt_factor_nav_to_mongo.py --since 2026-08-02T02:53:42
  python scripts/sync_rebuilt_factor_nav_to_mongo.py --from-log
  python scripts/sync_rebuilt_factor_nav_to_mongo.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors_service import (  # noqa: E402
    BUILTIN_FACTORS,
    RETIRED_FACTOR_IDS,
    _build_backtest_summary,
    _metric_slice,
)

FACTORS_DATA = kit.FACTORS_DATA
FOLLOWUP_LOG = FACTORS_DATA / "nav_bug_followup.log"
FOLLOWUP_SUMMARY = FACTORS_DATA / "nav_bug_followup_summary.json"
OK_RE = re.compile(r"\[rebuild\s+\d+/\d+\]\s+ok\s+(\S+):")


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def _default_since_from_log() -> Optional[datetime]:
    if not FOLLOWUP_LOG.exists():
        return None
    for line in FOLLOWUP_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "start registered=" in line:
            # [02:53:42] start ...  — 用文件 mtime 日 + 日志时分秒
            m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", line)
            if not m:
                return datetime.fromtimestamp(FOLLOWUP_LOG.stat().st_mtime)
            day = datetime.fromtimestamp(FOLLOWUP_LOG.stat().st_ctime).date()
            # 日志从本次写入开始；用文件创建/修改日更稳：取 mtime 的日期回退到 start 时刻
            base = datetime.fromtimestamp(FOLLOWUP_LOG.stat().st_mtime).replace(
                hour=int(m.group(1)),
                minute=int(m.group(2)),
                second=int(m.group(3)),
                microsecond=0,
            )
            # 若当前已跨日且 start 时刻 > 现在，回退一天
            now = datetime.now()
            if base > now:
                base = base.replace(year=day.year, month=day.month, day=day.day)
                if base > now:
                    from datetime import timedelta

                    base = base - timedelta(days=1)
            return base
    return None


def _ids_from_log() -> Set[str]:
    if not FOLLOWUP_LOG.exists():
        return set()
    out: Set[str] = set()
    for line in FOLLOWUP_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = OK_RE.search(line)
        if m:
            out.add(m.group(1))
    return out


def _ids_from_summary_json() -> Set[str]:
    if not FOLLOWUP_SUMMARY.exists():
        return set()
    try:
        data = json.loads(FOLLOWUP_SUMMARY.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    rebuild = data.get("rebuild") or {}
    out: Set[str] = set()
    for fid, row in rebuild.items():
        if isinstance(row, dict) and not row.get("error"):
            out.add(str(fid))
    return out


def _ids_from_mtime(since: datetime) -> Set[str]:
    since_ts = since.timestamp()
    out: Set[str] = set()
    for path in FACTORS_DATA.glob("*_backtest.json"):
        if path.stat().st_mtime < since_ts:
            continue
        fid = path.name[: -len("_backtest.json")]
        if fid in RETIRED_FACTOR_IDS:
            continue
        out.add(fid)
    return out


def _load_metrics(fid: str) -> Optional[Dict[str, Any]]:
    path = FACTORS_DATA / f"{fid}_backtest.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    results = raw.get("results") or {}
    row: Optional[Dict[str, Any]] = None
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
        return None
    metrics = _metric_slice(row)
    metrics["updated_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    metrics["source"] = path.name
    # 额外保留回测常用字段
    for k in ("n_legs_accepted", "n_legs_raw", "avg_position", "position_logic"):
        if k in row:
            metrics[k] = row[k]
    return metrics


def _db_targets() -> List[str]:
    return list(dict.fromkeys([settings.MONGO_DB, "lahm"]))


def sync(
    ids: Iterable[str],
    *,
    dry_run: bool = False,
) -> Tuple[int, List[Tuple[str, Dict[str, Any]]]]:
    ids = sorted(set(ids))
    prepared: List[Tuple[str, Dict[str, Any]]] = []
    for fid in ids:
        metrics = _load_metrics(fid)
        if not metrics:
            continue
        prepared.append((fid, metrics))

    if dry_run:
        return len(prepared), prepared

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    now = datetime.now()
    builtin_by_id = {f["factor_id"]: f for f in BUILTIN_FACTORS}

    synced = 0
    for db_name in _db_targets():
        db = client[db_name]
        n = 0
        for fid, metrics in prepared:
            payload: Dict[str, Any] = {
                "backtest_summary": metrics,
                "updated_at": now,
            }
            # 若是内置因子，顺带补齐元数据（不覆盖已有 description 以外的空缺时可 upsert）
            meta = builtin_by_id.get(fid)
            if meta:
                for k in ("name", "category", "description", "tags", "params"):
                    if k in meta and meta[k] is not None:
                        payload.setdefault(k, meta[k])
                payload["builtin"] = True
                payload["status"] = "active"
            r = db["factors"].update_one(
                {"factor_id": fid},
                {"$set": payload},
                upsert=bool(meta),
            )
            if r.matched_count or r.upserted_id:
                n += 1
        print(f"{db_name}: synced={n} candidates={len(prepared)}")
        synced = max(synced, n)
    return synced, prepared


def verify(sample_ids: List[str]) -> None:
    print("--- verify ---")
    for fid in sample_ids:
        local = _load_metrics(fid)
        api_view = _build_backtest_summary(fid)
        logics = (api_view or {}).get("logics") or {}
        primary = (api_view or {}).get("primary_logic")
        api_m = logics.get(primary) if primary else None
        if api_m is None and logics:
            api_m = next(iter(logics.values()))
        print(
            f"{fid}: local sharpe={local and local.get('sharpe')} ret={local and local.get('total_return')} "
            f"| service sharpe={api_m and api_m.get('sharpe')} ret={api_m and api_m.get('total_return')} "
            f"| match={bool(local and api_m and local.get('sharpe') == api_m.get('sharpe') and local.get('total_return') == api_m.get('total_return'))}"
        )
        # Mongo
        try:
            client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=3000)
            doc = client[settings.MONGO_DB]["factors"].find_one({"factor_id": fid}, {"backtest_summary": 1})
            bs = (doc or {}).get("backtest_summary") or {}
            print(
                f"  mongo sharpe={bs.get('sharpe')} ret={bs.get('total_return')} "
                f"match_local={bool(local and bs.get('sharpe') == local.get('sharpe') and bs.get('total_return') == local.get('total_return'))}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  mongo verify skip: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="增量同步已重算因子净值摘要到 Mongo")
    ap.add_argument("--since", default="", help="只同步 *_backtest.json mtime >= 该时间的因子")
    ap.add_argument("--from-log", action="store_true", help="优先用 nav_bug_followup.log 里 ok 的 id")
    ap.add_argument("--all-mtime-today", action="store_true", help="忽略日志，仅按 --since/默认 since 的 mtime")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", default="", help="逗号分隔 factor_id，同步后校验")
    args = ap.parse_args()

    since = _parse_dt(args.since) if args.since.strip() else _default_since_from_log()
    if since is None:
        # 回退：今天 0 点
        since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"since={since.isoformat(timespec='seconds')}")

    if args.from_log and not args.all_mtime_today:
        ids = _ids_from_log() | _ids_from_summary_json()
        # 与 mtime 取交，避免日志旧残留；若日志空则退回 mtime
        mtime_ids = _ids_from_mtime(since)
        if ids:
            ids = ids & mtime_ids if mtime_ids else ids
        else:
            ids = mtime_ids
        print(f"source=log+mtime candidates={len(ids)}")
    else:
        ids = _ids_from_mtime(since)
        print(f"source=mtime candidates={len(ids)}")

    synced, prepared = sync(ids, dry_run=args.dry_run)
    print(f"{'dry_run ' if args.dry_run else ''}prepared={len(prepared)} synced={synced}")

    sample = [x.strip() for x in args.verify.split(",") if x.strip()]
    if not sample and prepared:
        # 默认抽最新写入的两个
        sample = [fid for fid, _ in sorted(prepared, key=lambda x: x[1].get("updated_at") or "")[-2:]]
    if sample and not args.dry_run:
        verify(sample)


if __name__ == "__main__":
    main()
