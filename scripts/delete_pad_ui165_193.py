"""删除主库 UI#165 / #193 占位文档，并以相同 created_at 重挂占位保序。

查清：二者均为 pad（非真实因子），对应已删的 struct_catchup_gp28_lag26_csi500_r3。
硬删且不占位会导致 #166 起全部前移——按项目保序策略：删旧 pad → 同刻 created_at 重挂。
不 git commit；不动其它号。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

from app.core.config import settings

OLD_PADS = {
    165: "_gen_pad_catchup_gp28_r3",
    193: "_gen_pad_ui192",
}
# 刷新后统一命名，仍占同一 created_at 槽
NEW_PADS = {
    165: {
        "factor_id": "_gen_pad_ui165",
        "name": "[PAD] UI#165 slot (deleted catchup/struct placeholder)",
        "description": (
            "占位保序：原 #165 `_gen_pad_catchup_gp28_r3`（已删真实因子 "
            "struct_catchup_gp28_lag26_csi500_r3 的槽位）。硬删会令 #166 起前移。"
        ),
    },
    193: {
        "factor_id": "_gen_pad_ui193",
        "name": "[PAD] UI#193 slot (deleted UI#192 catchup placeholder)",
        "description": (
            "占位保序：原 #193 `_gen_pad_ui192`（已删真实因子 "
            "struct_catchup_gp28_lag26_csi500_r3 的槽位）。硬删会令 #194 起前移。"
        ),
    },
}


def _ui_docs(db):
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1, "name": 1, "status": 1}))

    def _key(x):
        ta = x.get("created_at") or ""
        if hasattr(ta, "isoformat"):
            ta = ta.isoformat(sep=" ")
        return (str(ta), str(x.get("factor_id") or ""))

    return sorted(docs, key=_key)


def _seq(docs, fid: str):
    return next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == fid), None)


def main() -> None:
    uri = settings.MONGO_URI or "mongodb://admin:lahm123@localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    primary = settings.MONGO_DB
    print(f"[db] primary={primary}", flush=True)

    # 仅主库；镜像库若无这些 pad 则跳过
    targets = [primary]
    for extra in ("lahm", "lahm_v0"):
        if extra != primary and extra in client.list_database_names():
            if "factors" in client[extra].list_collection_names():
                targets.append(extra)

    data = ROOT / "data" / "factors"
    for old_fid in OLD_PADS.values():
        for p in [
            data / f"{old_fid}_backtest.csv",
            data / f"{old_fid}_backtest.json",
            data / f"{old_fid}_trade_history.csv",
            data / f"{old_fid}_equity_curve.png",
            data / old_fid,
        ]:
            if p.is_file():
                p.unlink()
                print(f"[local] rm file {p}", flush=True)
            elif p.is_dir():
                import shutil

                shutil.rmtree(p)
                print(f"[local] rm dir {p}", flush=True)

    for dbn in targets:
        db = client[dbn]
        docs = _ui_docs(db)
        print(f"\n=== {dbn} count={len(docs)} ===", flush=True)
        for ui, old_fid in OLD_PADS.items():
            if ui > len(docs):
                print(f"[skip] {dbn} has no UI#{ui}", flush=True)
                continue
            cur = docs[ui - 1]
            cur_fid = cur.get("factor_id")
            ca = cur.get("created_at")
            print(f"[find] UI#{ui} factor_id={cur_fid!r} ca={ca}", flush=True)
            if cur_fid not in (old_fid, NEW_PADS[ui]["factor_id"]):
                # 主库必须是预期 pad；其它库可能序号不同
                if dbn == primary:
                    raise SystemExit(
                        f"ABORT {dbn} UI#{ui}: expected pad {old_fid!r} or "
                        f"{NEW_PADS[ui]['factor_id']!r}, got {cur_fid!r}"
                    )
                print(f"[skip] {dbn} UI#{ui} not the pad we manage ({cur_fid})", flush=True)
                continue

            # 收集要删的旧 id（含新旧命名）
            del_ids = {old_fid, NEW_PADS[ui]["factor_id"], cur_fid}
            # 保留 created_at
            if ca is None:
                raise SystemExit(f"ABORT {dbn} UI#{ui}: missing created_at")

            # 邻号快照（删前）
            before_neighbors = {}
            for nui in (ui - 1, ui + 1):
                if 1 <= nui <= len(docs):
                    before_neighbors[nui] = docs[nui - 1].get("factor_id")

            r = db.factors.delete_many({"factor_id": {"$in": list(del_ids)}})
            db.factor_signals.delete_many({"factor_id": {"$in": list(del_ids)}})
            print(f"[del] {dbn} ids={sorted(del_ids)} deleted_factors={r.deleted_count}", flush=True)

            meta = NEW_PADS[ui]
            pad_doc = {
                "factor_id": meta["factor_id"],
                "name": meta["name"],
                "category": "meta",
                "description": meta["description"],
                "tags": ["gen_seq_pad", "deleted_slot"],
                "status": "retired",
                "builtin": False,
                "params": {},
                "created_at": ca,
                "updated_at": datetime.now(),
            }
            if db.factors.find_one({"factor_id": meta["factor_id"]}):
                raise SystemExit(f"ABORT race: {meta['factor_id']} still exists")
            db.factors.insert_one(pad_doc)

            docs2 = _ui_docs(db)
            seq = _seq(docs2, meta["factor_id"])
            print(
                f"[pad] {dbn} reinsert {meta['factor_id']} created_at={ca} "
                f"actual_UI#{seq} count={len(docs2)}",
                flush=True,
            )
            if seq != ui:
                raise SystemExit(f"ABORT {dbn}: UI drift planned={ui} actual={seq}")
            for nui, nfid in before_neighbors.items():
                got = docs2[nui - 1].get("factor_id") if 1 <= nui <= len(docs2) else None
                if got != nfid:
                    raise SystemExit(
                        f"ABORT {dbn}: neighbor UI#{nui} changed {nfid!r} -> {got!r}"
                    )
            print(f"[ok] {dbn} UI#{ui} neighbors unchanged", flush=True)

    # 最终主库核对
    docs = _ui_docs(client[primary])
    print("\n======== VERIFY PRIMARY ========", flush=True)
    print(f"count={len(docs)}", flush=True)
    for ui in (164, 165, 166, 192, 193, 194, len(docs)):
        if 1 <= ui <= len(docs):
            d = docs[ui - 1]
            print(f"#{ui} {d.get('factor_id')} | {d.get('name')}", flush=True)
    print("[done] pads refreshed; sequence preserved", flush=True)


if __name__ == "__main__":
    main()
