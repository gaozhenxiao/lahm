"""删除 UI#239/#240/#242，同 created_at 挂 pad 保序（#241/#243 不动）。"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

from app.core.config import settings

# 主库序号 → 原 factor_id
DELETE = {
    239: "phys_cip_convert_c35",
    240: "phys_cip_convert_c35_ry05",
    242: "phys_cash_collect_c38",
}

TARGETS = [
    settings.MONGO_DB,
    "lahm_v0_gaozx-desktop-v0c4gt8",
    "tradingagentscn_v0_gaozx-desktop-v0c4gt8",
    "lahm",
    "tradingagentscn",
]


def _ui_docs(db):
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1, "name": 1}))

    def _key(x):
        ta = x.get("created_at") or ""
        if hasattr(ta, "isoformat"):
            ta = ta.isoformat(sep=" ")
        return (str(ta), str(x.get("factor_id") or ""))

    return sorted(docs, key=_key)


def _seq(docs, fid: str):
    return next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == fid), None)


def _rm_local(fid: str) -> None:
    data = ROOT / "data" / "factors"
    for p in [
        data / f"{fid}_backtest.csv",
        data / f"{fid}_backtest.json",
        data / f"{fid}_trade_history.csv",
        data / f"{fid}_equity_curve.png",
        data / fid,
    ]:
        if p.is_file():
            p.unlink()
            print(f"[local] rm {p.name}", flush=True)
        elif p.is_dir():
            shutil.rmtree(p)
            print(f"[local] rm dir {p.name}", flush=True)


def main() -> None:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    now = datetime.now()
    primary = settings.MONGO_DB
    print(f"[db] primary={primary}", flush=True)

    for fid in DELETE.values():
        _rm_local(fid)

    seen = set()
    for dbn in TARGETS:
        if not dbn or dbn in seen:
            continue
        seen.add(dbn)
        if dbn not in client.list_database_names():
            print(f"[skip] no db {dbn}", flush=True)
            continue
        db = client[dbn]
        docs = _ui_docs(db)
        print(f"\n=== {dbn} n={len(docs)} ===", flush=True)

        # 按 factor_id 删（镜像库序号可能不同），保 created_at
        for ui_primary, fid in DELETE.items():
            pad_id = f"_gen_pad_ui{ui_primary}"
            doc = db.factors.find_one({"factor_id": fid}, {"created_at": 1, "factor_id": 1})
            if not doc:
                # 可能已是 pad
                pad = db.factors.find_one({"factor_id": pad_id}, {"created_at": 1})
                if pad:
                    print(f"[ok] {dbn} already pad {pad_id}", flush=True)
                    continue
                print(f"[skip] {dbn} missing {fid}", flush=True)
                continue
            ca = doc.get("created_at")
            if ca is None:
                raise SystemExit(f"ABORT {dbn}.{fid}: no created_at")

            before_241 = _seq(docs, "phys_cip_convert_c36")
            before_243 = _seq(docs, "phys_capex_cycle_c38")

            db.factors.delete_many({"factor_id": {"$in": [fid, pad_id]}})
            db.factor_signals.delete_many({"factor_id": {"$in": [fid, pad_id]}})
            db.factors.insert_one(
                {
                    "factor_id": pad_id,
                    "name": f"[PAD] UI#{ui_primary} deleted {fid}",
                    "category": "meta",
                    "description": (
                        f"占位保序：原 `{fid}` 已删。硬删会导致后续序号前移。"
                    ),
                    "tags": ["gen_seq_pad", "deleted_slot"],
                    "status": "retired",
                    "builtin": False,
                    "params": {},
                    "created_at": ca,
                    "updated_at": now,
                }
            )
            docs = _ui_docs(db)
            seq = _seq(docs, pad_id)
            print(
                f"[pad] {dbn} {fid} -> {pad_id} UI#{seq} ca={ca}",
                flush=True,
            )
            if dbn == primary and seq != ui_primary:
                raise SystemExit(f"ABORT primary UI drift {fid}: planned={ui_primary} got={seq}")

            after_241 = _seq(docs, "phys_cip_convert_c36")
            after_243 = _seq(docs, "phys_capex_cycle_c38")
            if before_241 and after_241 and before_241 != after_241:
                raise SystemExit(f"ABORT {dbn}: #241 drifted {before_241}->{after_241}")
            if before_243 and after_243 and before_243 != after_243:
                raise SystemExit(f"ABORT {dbn}: #243 drifted {before_243}->{after_243}")

        docs = _ui_docs(db)
        print(
            f"[check] {dbn} #241={_seq(docs,'phys_cip_convert_c36')} "
            f"#243={_seq(docs,'phys_capex_cycle_c38')} "
            f"pads={[ _seq(docs, f'_gen_pad_ui{u}') for u in DELETE ]}",
            flush=True,
        )


if __name__ == "__main__":
    main()
