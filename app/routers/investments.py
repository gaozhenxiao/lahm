"""Investments API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.response import ok
from app.models.investments import InvestmentCreate, InvestmentUpdate
from app.routers.auth_db import get_current_user
from app.services.investments_service import investments_service

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/")
async def list_investments(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    return ok(await investments_service.list_items(current_user["id"], status))


@router.post("/")
async def create_investment(payload: InvestmentCreate, current_user: dict = Depends(get_current_user)):
    return ok(await investments_service.create(current_user["id"], payload))


@router.patch("/{item_id}")
async def update_investment(
    item_id: str, payload: InvestmentUpdate, current_user: dict = Depends(get_current_user)
):
    try:
        return ok(await investments_service.update(current_user["id"], item_id, payload))
    except LookupError:
        raise HTTPException(status_code=404, detail="not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{item_id}")
async def delete_investment(item_id: str, current_user: dict = Depends(get_current_user)):
    try:
        deleted = await investments_service.delete(current_user["id"], item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")
    return ok({"deleted": True})
