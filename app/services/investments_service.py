"""Investments CRUD service."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.investments import InvestmentCreate, InvestmentUpdate
from app.utils.timezone import now_tz

COLLECTION = "investments"


def _norm_code(code: str) -> str:
    c = (code or "").strip().upper()
    if "." in c:
        return c
    if c.isdigit() and len(c) == 6:
        return c + (".SH" if c.startswith(("5", "6", "9")) else ".SZ")
    return c


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "user_id": doc.get("user_id", ""),
        "code": doc.get("code", ""),
        "name": doc.get("name", ""),
        "market": doc.get("market", "CN"),
        "status": doc.get("status", "planned"),
        "side": doc.get("side", "long"),
        "target_weight": doc.get("target_weight"),
        "quantity": doc.get("quantity"),
        "entry_price": doc.get("entry_price"),
        "exit_price": doc.get("exit_price"),
        "exit_reason": doc.get("exit_reason"),
        "thesis": doc.get("thesis", ""),
        "lead_id": doc.get("lead_id"),
        "analysis_id": doc.get("analysis_id"),
        "factor_ids": doc.get("factor_ids") or [],
        "tags": doc.get("tags") or [],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class InvestmentsService:
    async def list_items(self, user_id: str, status: Optional[str] = None) -> Dict[str, Any]:
        db = get_mongo_db()
        q: Dict[str, Any] = {"user_id": user_id}
        if status:
            q["status"] = status
        total = await db[COLLECTION].count_documents(q)
        cursor = db[COLLECTION].find(q).sort("updated_at", -1)
        items = [_serialize(d) async for d in cursor]
        return {"total": total, "items": items}

    async def create(self, user_id: str, payload: InvestmentCreate) -> Dict[str, Any]:
        db = get_mongo_db()
        now = now_tz()
        doc = {
            **payload.model_dump(),
            "user_id": user_id,
            "code": _norm_code(payload.code),
            "status": payload.status.value if hasattr(payload.status, "value") else payload.status,
            "created_at": now,
            "updated_at": now,
        }
        res = await db[COLLECTION].insert_one(doc)
        doc["_id"] = res.inserted_id
        return _serialize(doc)

    async def create_from_lead(self, user_id: str, lead: Dict[str, Any], thesis: str = "") -> Dict[str, Any]:
        return await self.create(
            user_id,
            InvestmentCreate(
                code=lead.get("code", ""),
                name=lead.get("name", ""),
                market=lead.get("market", "CN"),
                status="planned",  # type: ignore[arg-type]
                thesis=thesis or lead.get("reason", ""),
                lead_id=lead.get("id"),
                analysis_id=lead.get("analysis_id"),
                factor_ids=[lead["factor_id"]] if lead.get("factor_id") else [],
                tags=list(set((lead.get("tags") or []) + ["from_lead"])),
            ),
        )

    async def update(self, user_id: str, item_id: str, payload: InvestmentUpdate) -> Dict[str, Any]:
        db = get_mongo_db()
        if not ObjectId.is_valid(item_id):
            raise ValueError("invalid id")
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if "status" in updates and hasattr(updates["status"], "value"):
            updates["status"] = updates["status"].value
        updates["updated_at"] = now_tz()
        doc = await db[COLLECTION].find_one_and_update(
            {"_id": ObjectId(item_id), "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )
        if not doc:
            raise LookupError("not found")
        return _serialize(doc)

    async def delete(self, user_id: str, item_id: str) -> bool:
        db = get_mongo_db()
        if not ObjectId.is_valid(item_id):
            raise ValueError("invalid id")
        r = await db[COLLECTION].delete_one({"_id": ObjectId(item_id), "user_id": user_id})
        return r.deleted_count > 0


investments_service = InvestmentsService()
