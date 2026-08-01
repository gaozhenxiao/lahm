"""Bootstrap local MongoDB for lahm (no-auth or create admin)."""
from __future__ import annotations

from pymongo import MongoClient


def main() -> None:
    c = MongoClient("localhost", 27017, serverSelectionTimeoutMS=8000)
    print("ping", c.admin.command("ping"))
    try:
        c.admin.command(
            "createUser",
            "admin",
            pwd="lahm123",
            roles=[{"role": "root", "db": "admin"}],
        )
        print("created admin/lahm123")
    except Exception as exc:  # noqa: BLE001
        print("createUser:", exc)

    c["lahm"]["_bootstrap"].update_one(
        {"_id": "init"},
        {"$set": {"ok": True, "note": "lahm local bootstrap"}},
        upsert=True,
    )
    print("dbs", c.list_database_names())
    print("lahm cols", c["lahm"].list_collection_names())

    try:
        c2 = MongoClient(
            "mongodb://admin:lahm123@localhost:27017/lahm?authSource=admin",
            serverSelectionTimeoutMS=5000,
        )
        print("auth ping", c2.admin.command("ping"))
    except Exception as exc:  # noqa: BLE001
        print("auth conn note:", exc)


if __name__ == "__main__":
    main()
