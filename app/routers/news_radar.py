# -*- coding: utf-8 -*-
"""新闻雷达 API。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services import news_radar_service

logger = logging.getLogger("webapi.news_radar")

router = APIRouter(prefix="/api/news-radar", tags=["news-radar"])


@router.get("/scan")
async def scan_news(
    refresh: bool = Query(False),
    limit: int = Query(40, ge=10, le=80),
    use_llm: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    """扫描财联社快讯，DeepSeek 评估重要性与标的影响。"""
    try:
        data = await asyncio.to_thread(
            news_radar_service.get_latest,
            refresh=refresh,
            limit=limit,
            use_llm=use_llm,
        )
        return ok(data)
    except Exception as e:  # noqa: BLE001
        logger.exception("news radar failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
