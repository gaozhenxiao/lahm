"""回测并入库：120日新低买入（HS300 / CSI500）。

仅 INSERT；主库挂到 max UI 之后；BaoStock 禁用。
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

FIDS = ["new_low_120_hs300", "new_low_120_csi500"]


def _ui_docs(db) -> List[dict]:
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1, "name": 1}))

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


def _insert_primary(summaries: Dict[str, dict]) -> None:
    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    dbn = settings.MONGO_DB
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    mx = _max_created_at(docs)
    base = (mx + timedelta(hours=1)) if isinstance(mx, datetime) else datetime.now()
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[mongo] {dbn} max_ui={max_ui} max_ca={mx}", flush=True)

    for i, fid in enumerate(FIDS):
        meta = FACTOR_IMPL[fid]
        params = dict(meta["params"])
        params["position_logic"] = fid
        summary = dict(summaries[fid])
        summary["position_logic"] = fid
        existing = db.factors.find_one({"factor_id": fid}, {"created_at": 1})
        created_at = existing.get("created_at") if existing else (base + timedelta(hours=i))
        payload = {
            "factor_id": fid,
            "name": meta["name"],
            "category": meta.get("category") or "technical",
            "description": meta.get("description") or "",
            "tags": meta.get("tags") or [],
            "status": "active",
            "builtin": True,
            "params": params,
            "created_at": created_at,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": fid,
                "logics": {fid: summary},
                "updated_at": now_s,
            },
            "last_backtest_error": summary.get("error"),
            "mine_meta": {
                "source": "research_new_high_low_by_type",
                "signal": "signal_new_low_first_buy",
                "low_window": 120,
                "confirm": True,
                "note": "新低后站上MA20；OOS 大/中盘事件胜率更高",
            },
        }
        if existing:
            db.factors.update_one({"factor_id": fid}, {"$set": payload})
            op = "UPDATE"
        else:
            db.factors.insert_one(payload)
            op = "INSERT"
        docs2 = _ui_docs(db)
        seq = _ui_seq(docs2, fid)
        print(
            f"[mongo] {op} {fid} UI#{seq}/{len(docs2)} sharpe={summary.get('sharpe')} "
            f"ret={summary.get('total_return')}",
            flush=True,
        )


def main() -> None:
    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    summaries: Dict[str, dict] = {}
    for fid in FIDS:
        if fid not in FACTOR_IMPL:
            raise SystemExit(f"missing registry {fid}")
        meta = FACTOR_IMPL[fid]
        params = deepcopy(meta["params"])
        print(f"======== PANEL+BT {fid} ========", flush=True)
        panel = prepare_shared_panel(
            params,
            need_profit=False,
            need_growth=False,
            need_balance=False,
            need_fin_db=False,
            limit=0,
        )
        print(f"[panel] {fid} n={len(panel)}", flush=True)
        summary = run_factor_pipeline(
            fid,
            meta["title"],
            meta["signal"],
            params,
            need_profit=False,
            need_growth=False,
            need_balance=False,
            need_fin_db=False,
            limit=0,
            start="2018-01-01",
            price_map=panel,
            shared=True,
        )
        if summary.get("error"):
            raise SystemExit(f"bt error {fid}: {summary.get('error')}")
        summaries[fid] = summary
        print(
            f"[bt] {fid} sharpe={summary.get('sharpe')} ret={summary.get('total_return')} "
            f"legs={summary.get('n_legs_accepted')} end={summary.get('end')}",
            flush=True,
        )
        for name in (
            f"{fid}_backtest.json",
            f"{fid}_equity_curve.png",
            f"{fid}_trade_history.csv",
        ):
            p = ROOT / "data" / "factors" / name
            print(f"[art] {'YES' if p.exists() else 'NO '} {name}", flush=True)

    _insert_primary(summaries)
    out = ROOT / "data" / "factors" / "fill_new_low_120.json"
    out.write_text(
        json.dumps(
            {"asof": datetime.now().isoformat(timespec="seconds"), "summaries": summaries},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[ok] -> {out}", flush=True)


if __name__ == "__main__":
    main()
