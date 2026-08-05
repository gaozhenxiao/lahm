# -*- coding: utf-8 -*-
"""可转债模块 API（与 factors 并列）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.cb_service import cb_service

logger = logging.getLogger("webapi.cb")

router = APIRouter(prefix="/cb", tags=["convertible-bonds"])


@router.get("")
@router.get("/")
async def module_home(current_user: dict = Depends(get_current_user)):
    """模块元信息 + 策略目录。"""
    return ok(cb_service.module_meta())


@router.get("/strategies")
async def list_strategies(current_user: dict = Depends(get_current_user)):
    return ok(cb_service.list_strategies())


@router.get("/arb/stock")
async def stock_arb_scan(
    refresh: bool = Query(False, description="强制刷新，忽略缓存"),
    ttl_sec: int = Query(300, ge=0, le=3600, description="缓存秒数"),
    discount_max: float = Query(-0.3, description="折价阈值（溢价率≤该值）"),
    near_parity_max: float = Query(3.0, description="平价附近上限%"),
    current_user: dict = Depends(get_current_user),
):
    """转债-正股套利扫描：折价 / 平价 / 双低。"""
    try:
        data = await cb_service.stock_arb(
            refresh=refresh,
            ttl_sec=ttl_sec,
            discount_max=discount_max,
            near_parity_max=near_parity_max,
        )
        return ok(data)
    except Exception as e:  # noqa: BLE001
        logger.exception("stock arb scan failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/arb/stock/refresh")
async def stock_arb_refresh(current_user: dict = Depends(get_current_user)):
    """强制刷新正股套利扫描缓存。"""
    try:
        data = await cb_service.stock_arb(refresh=True, ttl_sec=0)
        return ok(data)
    except Exception as e:  # noqa: BLE001
        logger.exception("stock arb refresh failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
