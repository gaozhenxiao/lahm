"""物理结构 · Sharpe≥0.30 行业候选入库。

- 仅 INSERT；序号挂 max(created_at)+1，不挤占
- 注册表已含 FACTOR_IMPL；本脚本回测 + 写入 Mongo
- 宇宙：ind_c35 / ind_c36 / ind_c38（需已有 universe_ind_*.parquet）

用法:
  .venv\\Scripts\\python.exe scripts/fill_phys_industry_sharpe.py
  .venv\\Scripts\\python.exe scripts/fill_phys_industry_sharpe.py --skip-backtest
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

NEW_IDS = [
    # #239/#240/#242 已删（pad 保序）；仅保留仍在册的
    "phys_cip_convert_c36",
    "phys_capex_cycle_c38",
]

TARGETS = [
    settings.MONGO_DB,
    "lahm_v0_gaozx-desktop-v0c4gt8",
    "tradingagentscn_v0_gaozx-desktop-v0c4gt8",
    "lahm",
    "tradingagentscn",
]


def _ui_docs(db) -> List[dict]:
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))

    def _key(x):
        ta = x.get("created_at") or ""
        if hasattr(ta, "isoformat"):
            ta = ta.isoformat(sep=" ")
        return (str(ta), str(x.get("factor_id") or ""))

    return sorted(docs, key=_key)


def _ui_seq(docs: List[dict], factor_id: str) -> Optional[int]:
    return next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == factor_id), None)


def _max_created_at(docs: List[dict]) -> Optional[datetime]:
    mx = None
    for d in docs:
        ca = d.get("created_at")
        if ca is None:
            continue
        if mx is None or ca > mx:
            mx = ca
    return mx


def _ensure_universes() -> None:
    cache = kit.shared_cache_dir()
    for uid in ("ind_c35", "ind_c36", "ind_c38"):
        fp = cache / f"universe_{uid}.parquet"
        if not fp.exists():
            raise SystemExit(f"missing universe cache: {fp} （先跑 mine_phys_industry_round1）")
        n = len(__import__("pandas").read_parquet(fp))
        print(f"[universe] {uid} n={n} ok", flush=True)


def _insert_all(summaries: Dict[str, Dict[str, Any]]) -> None:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    now = datetime.now()
    seen = set()
    for dbn in TARGETS:
        if not dbn or dbn in seen:
            continue
        seen.add(dbn)
        db = client[dbn]
        name = dbn
        docs = _ui_docs(db)
        for fid in NEW_IDS:
            if db.factors.find_one({"factor_id": fid}, {"_id": 1}):
                print(f"[skip] {name}.{fid} already exists", flush=True)
                continue
        # plan created_at after current max (re-read after skips)
        docs = _ui_docs(db)
        mx = _max_created_at(docs)
        base = (mx + timedelta(hours=1)) if isinstance(mx, datetime) else now
        if now > base:
            base = now
        to_insert = [fid for fid in NEW_IDS if not db.factors.find_one({"factor_id": fid}, {"_id": 1})]
        for i, fid in enumerate(to_insert):
            meta = FACTOR_IMPL[fid]
            ca = base + timedelta(hours=i)
            summary = summaries.get(fid) or {}
            payload = {
                "factor_id": fid,
                "name": meta["name"],
                "category": meta.get("category") or "fundamental",
                "description": meta.get("description") or "",
                "tags": meta.get("tags") or [],
                "status": "active",
                "builtin": True,
                "params": dict(meta["params"]),
                "created_at": ca,
                "updated_at": now,
                "backtest_summary": {
                    "available": bool(summary),
                    "primary_logic": fid,
                    "logics": {fid: summary} if summary else {},
                    "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                },
                "last_backtest_error": summary.get("error"),
            }
            db.factors.insert_one(payload)
            docs2 = _ui_docs(db)
            seq = _ui_seq(docs2, fid)
            print(f"[mongo] INSERT {name}.{fid} UI#{seq}/{len(docs2)} created_at={ca}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-backtest", action="store_true")
    args = ap.parse_args()

    missing = [x for x in NEW_IDS if x not in FACTOR_IMPL]
    if missing:
        raise SystemExit(f"not in FACTOR_IMPL: {missing}")
    _ensure_universes()

    summaries: Dict[str, Dict[str, Any]] = {}
    if not args.skip_backtest:
        # 按宇宙分组，同池共享 panel
        by_u: Dict[str, List[str]] = {}
        for fid in NEW_IDS:
            u = str(FACTOR_IMPL[fid]["params"].get("universe"))
            by_u.setdefault(u, []).append(fid)
        for u, fids in by_u.items():
            meta0 = FACTOR_IMPL[fids[0]]
            params0 = dict(meta0["params"])
            print(f"\n[panel] universe={u} factors={fids}", flush=True)
            panel = prepare_shared_panel(
                params0,
                need_profit=True,
                need_growth=False,
                need_balance=False,
                need_fin_db=True,
                limit=0,
            )
            for fid in fids:
                meta = FACTOR_IMPL[fid]
                summaries[fid] = run_factor_pipeline(
                    fid,
                    meta["title"],
                    meta["signal"],
                    dict(meta["params"]),
                    need_profit=True,
                    need_growth=False,
                    need_balance=False,
                    need_fin_db=True,
                    limit=0,
                    start="2018-01-01",
                    price_map=panel,
                )
                print(
                    f"[ok] {fid}: ret={summaries[fid].get('total_return')} "
                    f"sh={summaries[fid].get('sharpe')} legs={summaries[fid].get('n_legs_accepted')}",
                    flush=True,
                )
    else:
        print("[skip-backtest] mongo only", flush=True)

    _insert_all(summaries)
    # 主库序号确认
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    db = client[settings.MONGO_DB]
    docs = _ui_docs(db)
    print(f"\n[done] primary={settings.MONGO_DB} total={len(docs)}", flush=True)
    for fid in NEW_IDS:
        print(f"  #{_ui_seq(docs, fid)} {fid}", flush=True)


if __name__ == "__main__":
    main()
