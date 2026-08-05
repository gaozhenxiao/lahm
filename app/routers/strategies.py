# -*- coding: utf-8 -*-
"""策略中心 API。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.strategies_service import strategies_service

logger = logging.getLogger("webapi.strategies")

router = APIRouter(prefix="/strategies", tags=["strategies"])


class QmtConfigIn(BaseModel):
    userdata_path: Optional[str] = None
    session_id: Optional[str] = None
    account_id: Optional[str] = None
    account_type: Optional[str] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None


@router.get("")
@router.get("/")
async def module_home(current_user: dict = Depends(get_current_user)):
    return ok(strategies_service.meta())


@router.get("/qmt/status")
async def qmt_status(current_user: dict = Depends(get_current_user)):
    return ok(strategies_service.qmt_status())


@router.post("/qmt/config")
async def qmt_config(body: QmtConfigIn, current_user: dict = Depends(get_current_user)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return ok(strategies_service.qmt_config(patch))


@router.get("/{strategy_id}/scan")
async def scan_strategy(
    strategy_id: str,
    refresh: bool = Query(False),
    ttl_sec: int = Query(300, ge=0, le=3600),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = await strategies_service.scan(strategy_id, refresh=refresh, ttl_sec=ttl_sec)
        return ok(data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("scan %s failed", strategy_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{strategy_id}/refresh")
async def refresh_strategy(strategy_id: str, current_user: dict = Depends(get_current_user)):
    try:
        data = await strategies_service.scan(strategy_id, refresh=True, ttl_sec=0)
        return ok(data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("refresh %s failed", strategy_id)
        raise HTTPException(status_code=500, detail=str(e)) from e
