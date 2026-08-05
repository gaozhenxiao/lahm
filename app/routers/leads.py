"""Leads API."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.response import ok
from app.models.leads import LeadBulkFromScreening, LeadCreate, LeadUpdate
from app.routers.auth_db import get_current_user
from app.services.leads_service import leads_service
from app.services.investments_service import investments_service
from app.services.factor_book_service import (
    DEFAULT_GOOD_SHARPE,
    DEFAULT_WEAK_SHARPE,
    factor_book_service,
)

logger = logging.getLogger("webapi")
router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/factor-book")
async def factor_book(
    refresh: bool = Query(False, description="强制重算并刷新缓存"),
    filter_mode: str = Query(
        "all",
        description="all|good|alert|alert_only|watch — good=仅含优质机会(含混合)；alert=含警醒；alert_only=纯警醒",
    ),
    keyword: Optional[str] = None,
    good_sharpe: float = Query(DEFAULT_GOOD_SHARPE, description="优质因子 Sharpe 下限"),
    weak_sharpe: float = Query(DEFAULT_WEAK_SHARPE, description="弱势/警醒 Sharpe 上限（不含）"),
    current_user: dict = Depends(get_current_user),
):
    """汇总各因子回测末日持仓（含当日买入），按标的聚合并标注优质/警醒来源因子。"""
    data = await asyncio.to_thread(
        factor_book_service.build,
        refresh=refresh,
        good_sharpe=good_sharpe,
        weak_sharpe=weak_sharpe,
        filter_mode=filter_mode,
        keyword=keyword,
    )
    return ok(data)


@router.post("/factor-book/to-investment")
async def factor_book_to_investment(payload: dict, current_user: dict = Depends(get_current_user)):
    """从因子持仓书条目转入投资列表（不依赖 Mongo lead id）。"""
    code = (payload or {}).get("code")
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    inv = await investments_service.create_from_lead(current_user["id"], payload)
    return ok(inv)


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
