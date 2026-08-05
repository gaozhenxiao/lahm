"""把内置因子同步到本机可能在用的多个 Mongo 库。

序号规则：已有文档保留原 created_at（不挤占、不重排）；
仅新增因子挂到当前 max(created_at)+1h。
"""
from datetime import datetime, timedelta
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

from app.core.config import settings
from app.services.factors_service import BUILTIN_FACTORS, RETIRED_FACTOR_IDS


TARGETS = [
    settings.MONGO_DB,
    "lahm_v0_gaozx-desktop-v0c4gt8",
    "tradingagentscn_v0_gaozx-desktop-v0c4gt8",
    "lahm",
    "tradingagentscn",
]


def _next_created_at(db: Any, now: datetime) -> datetime:
    latest = db["factors"].find_one(
        {"created_at": {"$ne": None}},
        sort=[("created_at", -1)],
        projection={"created_at": 1},
    )
    if not latest or latest.get("created_at") is None:
        return now
    try:
        nxt = latest["created_at"] + timedelta(hours=1)
    except Exception:
        return now
    return now if now > nxt else nxt


def main() -> None:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    now = datetime.now()
    seen = set()
    for name in TARGETS:
        if not name or name in seen:
            continue
        seen.add(name)
        db = client[name]
        if RETIRED_FACTOR_IDS:
            db["factors"].delete_many({"factor_id": {"$in": list(RETIRED_FACTOR_IDS)}})
            db["factor_signals"].delete_many({"factor_id": {"$in": list(RETIRED_FACTOR_IDS)}})
        appended = []
        for f in BUILTIN_FACTORS:
            fid = f.get("factor_id")
            existing = db["factors"].find_one({"factor_id": fid}, {"created_at": 1}) if fid else None
            payload = {**f, "status": "active", "builtin": True, "updated_at": now}
            # 禁止用 BUILTIN 合成时间覆盖已有序号
            if existing and existing.get("created_at") is not None:
                payload["created_at"] = existing["created_at"]
            else:
                payload["created_at"] = _next_created_at(db, now)
                appended.append(fid)
            db["factors"].update_one(
                {"factor_id": fid},
                {"$set": payload},
                upsert=True,
            )
        ids = [
            x.get("factor_id")
            for x in db["factors"].find({}, {"factor_id": 1, "created_at": 1}).sort(
                [("created_at", 1), ("factor_id", 1)]
            )
        ]
        print(f"{name} n={len(ids)} appended={appended}")
        if appended:
            for a in appended:
                print(f"  -> #{ids.index(a)+1} {a}" if a in ids else f"  -> ? {a}")
    print("current settings.MONGO_DB =", settings.MONGO_DB)


if __name__ == "__main__":
    main()
