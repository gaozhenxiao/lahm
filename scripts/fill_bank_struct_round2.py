"""银行业结构特色 Round2 Top 入库（仅 INSERT）。

来源：mine_bank_struct_round2（2018–2025）
主逻辑：资产质量拐点 / 中收占比 / 净息+中收双增（非纯估值）

用法:
  .venv\\Scripts\\python.exe scripts/fill_bank_struct_round2.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
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

NEW_IDS = [
    "bank_aq_turn_j66",
    "bank_fee_mix_j66",
    "bank_dual_int_fee_j66",
]

START = "2018-01-01"
END = "2025-12-31"

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


def _backtest_one(fid: str, panel: Dict[str, pd.DataFrame], bench: pd.DataFrame) -> Dict[str, Any]:
    meta = FACTOR_IMPL[fid]
    params = dict(meta["params"])
    params["_cache_dir"] = str(kit.shared_cache_dir())
    params["position_logic"] = fid
    params["price_end"] = END
    legs = collect_legs(panel, meta["signal"], params)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=START, end=END
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    if daily is not None and not daily.empty:
        trades = legs_to_trade_history(
            accepted,
            max_positions=int(params.get("max_positions") or 6),
            weight_mode=_trade_history_weight_mode(params),
        )
        kit.write_factor_artifacts(
            fid, daily, summary, trades, params=params, title=meta.get("title") or fid
        )
    return summary


def _insert_all(summaries: Dict[str, Dict[str, Any]]) -> None:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    now = datetime.now()
    seen = set()
    for dbn in TARGETS:
        if not dbn or dbn in seen:
            continue
        seen.add(dbn)
        db = client[dbn]
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
                    "available": bool(summary) and summary.get("error") is None,
                    "primary_logic": fid,
                    "logics": {fid: summary} if summary else {},
                    "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "window": {"start": START, "end": END},
                },
                "last_backtest_error": summary.get("error"),
            }
            db.factors.insert_one(payload)
            docs2 = _ui_docs(db)
            print(f"[mongo] INSERT {dbn}.{fid} UI#{_ui_seq(docs2, fid)}/{len(docs2)}", flush=True)
        for fid in NEW_IDS:
            if fid not in to_insert:
                print(f"[skip] {dbn}.{fid} already exists", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-backtest", action="store_true")
    args = ap.parse_args()

    missing = [x for x in NEW_IDS if x not in FACTOR_IMPL]
    if missing:
        raise SystemExit(f"not in FACTOR_IMPL: {missing}")
    fp = kit.shared_cache_dir() / "universe_ind_j66.parquet"
    if not fp.exists():
        raise SystemExit(f"missing {fp}")

    summaries: Dict[str, Dict[str, Any]] = {}
    if not args.skip_backtest:
        params0 = dict(FACTOR_IMPL[NEW_IDS[0]]["params"])
        params0["price_end"] = END
        print(f"[panel] factors={NEW_IDS}", flush=True)
        panel = prepare_shared_panel(
            params0,
            need_profit=True,
            need_growth=False,
            need_fin_db=True,
            limit=0,
        )
        bench = pd.read_parquet(kit.shared_cache_dir() / "daily" / "sh_000300.parquet")
        bench["date"] = pd.to_datetime(bench["date"], errors="coerce")
        for fid in NEW_IDS:
            summaries[fid] = _backtest_one(fid, panel, bench)
            s = summaries[fid]
            print(
                f"[ok] {fid}: ret={s.get('total_return')} sh={s.get('sharpe')} "
                f"legs={s.get('n_legs_accepted')}",
                flush=True,
            )

    _insert_all(summaries)
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    db = client[settings.MONGO_DB]
    docs = _ui_docs(db)
    print(f"\n[done] primary={settings.MONGO_DB} total={len(docs)}", flush=True)
    for fid in NEW_IDS:
        print(f"  #{_ui_seq(docs, fid)} {fid}", flush=True)


if __name__ == "__main__":
    main()
