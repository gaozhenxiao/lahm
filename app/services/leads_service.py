"""Leads CRUD service (MongoDB)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.leads import LeadCreate, LeadStatus, LeadUpdate
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi")
COLLECTION = "leads"


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
        "source": doc.get("source", "manual"),
        "status": doc.get("status", LeadStatus.NEW.value),
        "score": doc.get("score"),
        "reason": doc.get("reason", ""),
        "tags": doc.get("tags") or [],
        "screening_snapshot": doc.get("screening_snapshot"),
        "analysis_id": doc.get("analysis_id"),
        "factor_id": doc.get("factor_id"),
        "kind": doc.get("kind"),
        "factors_good": doc.get("factors_good") or [],
        "factors_warn": doc.get("factors_warn") or [],
        "factors_neutral": doc.get("factors_neutral") or [],
        "weights": doc.get("weights") or [],
        "as_of": doc.get("as_of"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class LeadsService:
    async def list_leads(
        self,
        user_id: str,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        db = get_mongo_db()
        q: Dict[str, Any] = {"user_id": user_id}
        if status:
            q["status"] = status
        if keyword:
            kw = keyword.strip()
            q["$or"] = [
                {"code": {"$regex": kw, "$options": "i"}},
                {"name": {"$regex": kw, "$options": "i"}},
                {"reason": {"$regex": kw, "$options": "i"}},
            ]
        total = await db[COLLECTION].count_documents(q)
        cursor = (
            db[COLLECTION]
            .find(q)
            .sort("updated_at", -1)
            .skip(max(offset, 0))
            .limit(min(max(limit, 1), 500))
        )
        items = [_serialize(d) async for d in cursor]
        return {"total": total, "items": items}

    async def create_lead(self, user_id: str, payload: LeadCreate) -> Dict[str, Any]:
        db = get_mongo_db()
        now = now_tz()
        doc = {
            "user_id": user_id,
            "code": _norm_code(payload.code),
            "name": payload.name,
            "market": payload.market,
            "source": payload.source.value if hasattr(payload.source, "value") else payload.source,
            "status": payload.status.value if hasattr(payload.status, "value") else payload.status,
            "score": payload.score,
            "reason": payload.reason,
            "tags": payload.tags or [],
            "screening_snapshot": payload.screening_snapshot,
            "analysis_id": payload.analysis_id,
            "factor_id": payload.factor_id,
            "kind": payload.kind,
            "factors_good": payload.factors_good or [],
            "factors_warn": payload.factors_warn or [],
            "factors_neutral": payload.factors_neutral or [],
            "weights": payload.weights or [],
            "as_of": payload.as_of,
            "created_at": now,
            "updated_at": now,
        }
        res = await db[COLLECTION].insert_one(doc)
        doc["_id"] = res.inserted_id
        return _serialize(doc)

    async def update_lead(self, user_id: str, lead_id: str, payload: LeadUpdate) -> Dict[str, Any]:
        db = get_mongo_db()
        if not ObjectId.is_valid(lead_id):
            raise ValueError("invalid lead id")
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if "status" in updates and hasattr(updates["status"], "value"):
            updates["status"] = updates["status"].value
        updates["updated_at"] = now_tz()
        res = await db[COLLECTION].find_one_and_update(
            {"_id": ObjectId(lead_id), "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )
        if not res:
            raise LookupError("lead not found")
        return _serialize(res)

    async def delete_lead(self, user_id: str, lead_id: str) -> bool:
        db = get_mongo_db()
        if not ObjectId.is_valid(lead_id):
            raise ValueError("invalid lead id")
        r = await db[COLLECTION].delete_one({"_id": ObjectId(lead_id), "user_id": user_id})
        return r.deleted_count > 0

    async def bulk_from_screening(
        self,
        user_id: str,
        items: List[Dict[str, Any]],
        reason: str,
        tags: List[str],
        score: Optional[float] = None,
    ) -> Dict[str, Any]:
        created = []
        skipped = 0
        for it in items:
            code = it.get("code") or it.get("symbol") or it.get("ts_code") or it.get("股票代码")
            name = it.get("name") or it.get("stock_name") or it.get("股票名称") or ""
            if not code:
                skipped += 1
                continue
            lead = await self.create_lead(
                user_id,
                LeadCreate(
                    code=str(code),
                    name=str(name),
                    market=str(it.get("market") or "CN"),
                    source="screening",  # type: ignore[arg-type]
                    reason=reason,
                    tags=tags,
                    score=score,
                    screening_snapshot=it,
                ),
            )
            created.append(lead)
        return {"created": len(created), "skipped": skipped, "items": created}


leads_service = LeadsService()
