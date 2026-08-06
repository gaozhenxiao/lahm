"""Factors API."""
from __future__ import annotations

import logging
import mimetypes
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.response import ok
from app.models.factors import FactorCreate, FactorUpdate
from app.routers.auth_db import get_current_user
from app.services.factors_service import factors_service

logger = logging.getLogger("webapi")
router = APIRouter(prefix="/factors", tags=["factors"])


@router.get("")
@router.get("/")
async def list_factors(current_user: dict = Depends(get_current_user)):
    """同时挂 '' 与 '/'，避免 /api/factors → /api/factors/ 的 307 丢掉 Authorization。"""
    items = await factors_service.list_factors()
    return ok({"total": len(items), "items": items})


@router.get("/{factor_id}")
async def get_factor(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_factor(factor_id)
    if not item:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/backtest")
async def get_factor_backtest(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_backtest(factor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/guide")
async def get_factor_guide(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_guide(factor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/artifacts/{artifact_id}")
async def get_factor_artifact(
    factor_id: str,
    artifact_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        path, meta = factors_service.resolve_artifact(factor_id, artifact_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="artifact not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="artifact file missing; run backtest first")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline" if meta.get("kind") == "image" else "attachment",
    )


@router.post("/")
async def create_factor(payload: FactorCreate, current_user: dict = Depends(get_current_user)):
    try:
        item = await factors_service.create_factor(payload)
        return ok(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{factor_id}")
async def update_factor(factor_id: str, payload: FactorUpdate, current_user: dict = Depends(get_current_user)):
    try:
        item = await factors_service.update_factor(factor_id, payload)
        return ok(item)
    except LookupError:
        raise HTTPException(status_code=404, detail="factor not found")


@router.post("/{factor_id}/compute")
async def compute_factor(
    factor_id: str,
    asof: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await factors_service.compute_signal(factor_id, asof=asof)
        return ok(result)
    except LookupError:
        raise HTTPException(status_code=404, detail="factor not found")
    except Exception as e:  # noqa: BLE001
        logger.exception("compute factor failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{factor_id}/portfolio")
async def get_factor_portfolio(factor_id: str, current_user: dict = Depends(get_current_user)):
    """回测持仓/近期回合 + 交易摘要，供因子详情页。"""
    item = await factors_service.get_portfolio(factor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/signals")
async def list_signals(
    factor_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    items = await factors_service.list_signals(factor_id, limit=limit)
    return ok({"total": len(items), "items": items})
