"""Leads API."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.response import ok
from app.models.leads import LeadBulkFromScreening, LeadCreate, LeadUpdate
from app.routers.auth_db import get_current_user
from app.services.leads_service import leads_service
from app.services.investments_service import investments_service

logger = logging.getLogger("webapi")
router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/")
async def list_leads(
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    data = await leads_service.list_leads(current_user["id"], status, keyword, limit, offset)
    return ok(data)


@router.post("/")
async def create_lead(payload: LeadCreate, current_user: dict = Depends(get_current_user)):
    item = await leads_service.create_lead(current_user["id"], payload)
    return ok(item)


@router.post("/from-screening")
async def bulk_from_screening(payload: LeadBulkFromScreening, current_user: dict = Depends(get_current_user)):
    data = await leads_service.bulk_from_screening(
        current_user["id"], payload.items, payload.reason, payload.tags, payload.score
    )
    return ok(data)


@router.patch("/{lead_id}")
async def update_lead(lead_id: str, payload: LeadUpdate, current_user: dict = Depends(get_current_user)):
    try:
        item = await leads_service.update_lead(current_user["id"], lead_id, payload)
        return ok(item)
    except LookupError:
        raise HTTPException(status_code=404, detail="lead not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{lead_id}")
async def delete_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    try:
        ok_del = await leads_service.delete_lead(current_user["id"], lead_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok_del:
        raise HTTPException(status_code=404, detail="lead not found")
    return ok({"deleted": True})


@router.post("/{lead_id}/to-investment")
async def lead_to_investment(lead_id: str, current_user: dict = Depends(get_current_user)):
    data = await leads_service.list_leads(current_user["id"], limit=500)
    lead = next((x for x in data["items"] if x["id"] == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="lead not found")
    inv = await investments_service.create_from_lead(current_user["id"], lead)
    await leads_service.update_lead(
        current_user["id"], lead_id, LeadUpdate(status="invested")  # type: ignore[arg-type]
    )
    return ok(inv)
