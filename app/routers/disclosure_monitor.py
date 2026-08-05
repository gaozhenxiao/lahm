# -*- coding: utf-8 -*-
"""公告/业绩预告/快报监控 API。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.disclosure_monitor_service import (
    CATEGORY_META,
    in_poll_window,
    list_recent_disclosures,
    run_disclosure_poll,
)

router = APIRouter(prefix="/api/disclosures", tags=["disclosure-monitor"])


@router.get("/meta")
async def disclosure_meta(current_user=Depends(get_current_user)):
    return ok(
        data={
            "categories": CATEGORY_META,
            "in_window": in_poll_window(),
            "windows": ["07:00-08:00", "11:30-13:00", "19:00-21:00"],
            "interval_minutes": 10,
            "note": "只采当天公告（1个交易日有效）；东财 API，栏目对齐同花顺 URL",
        }
    )


@router.get("/recent")
async def recent_disclosures(
    useful_only: bool = Query(False),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
):
    rows = await list_recent_disclosures(
        useful_only=useful_only, limit=limit, category=category
    )
    return ok(data={"records": rows, "total": len(rows)})


@router.post("/poll")
async def poll_now(
    background_tasks: BackgroundTasks,
    force: bool = Query(True),
    lookback_days: int = Query(1, ge=1, le=7),
    trigger_factors: bool = Query(False, description="是否同步触发因子（默认否，避免卡住请求）"),
    current_user=Depends(get_current_user),
):
    def _run():
        return run_disclosure_poll(
            force=force,
            lookback_days=lookback_days,
            trigger_factors=trigger_factors,
        )

    if trigger_factors:
        background_tasks.add_task(_run)
        return ok(data={"queued": True}, message="已后台启动轮询+因子重算")
    try:
        stats = _run()
        return ok(data=stats, message="轮询完成")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
