"""把内置因子同步到本机可能在用的多个 Mongo 库。"""
from datetime import datetime
import sys
from pathlib import Path

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
        for f in BUILTIN_FACTORS:
            payload = {**f, "status": "active", "builtin": True, "updated_at": now}
            if f.get("created_at") is None:
                payload["created_at"] = now
            db["factors"].update_one(
                {"factor_id": f["factor_id"]},
                {"$set": payload},
                upsert=True,
            )
        ids = [
            x.get("factor_id")
            for x in db["factors"].find({}, {"factor_id": 1, "created_at": 1}).sort(
                [("created_at", 1), ("factor_id", 1)]
            )
        ]
        print(f"{name} => {ids}")
    print("current settings.MONGO_DB =", settings.MONGO_DB)


if __name__ == "__main__":
    main()
