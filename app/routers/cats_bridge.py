# -*- coding: utf-8 -*-
"""WCATS 行情桥 API：本地策略推送 / lahm 查询。"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services import cats_bridge_service as svc

router = APIRouter(prefix="/api/cats/bridge", tags=["cats-bridge"])

BRIDGE_TOKEN = os.getenv("CATS_BRIDGE_TOKEN", "lahm-local")


class QuoteIn(BaseModel):
    symbol: str
    last: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    volume: Optional[float] = None
    turnover: Optional[float] = None
    bid1: Optional[float] = None
    ask1: Optional[float] = None
    time: Optional[str] = None


class QuoteBatchIn(BaseModel):
    quotes: List[QuoteIn] = Field(default_factory=list)


class HeartbeatIn(BaseModel):
    rows: Optional[int] = None
    symbols: Optional[List[str]] = None
    note: Optional[str] = None


def _assert_local_bridge(request: Request, token: Optional[str]) -> None:
    host = (request.client.host if request.client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="bridge ingest only from localhost")
    if (token or "") != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="bad bridge token")


@router.post("/quote")
async def push_quote(
    body: QuoteIn,
    request: Request,
    x_cats_bridge_token: Optional[str] = Header(None),
):
    _assert_local_bridge(request, x_cats_bridge_token)
    row = svc.upsert_quote(body.model_dump())
    return ok(data=row)


@router.post("/quotes")
async def push_quotes(
    body: QuoteBatchIn,
    request: Request,
    x_cats_bridge_token: Optional[str] = Header(None),
):
    _assert_local_bridge(request, x_cats_bridge_token)
    rows = [svc.upsert_quote(q.model_dump()) for q in body.quotes]
    return ok(data={"count": len(rows)})


@router.post("/heartbeat")
async def bridge_heartbeat(
    body: HeartbeatIn,
    request: Request,
    x_cats_bridge_token: Optional[str] = Header(None),
):
    _assert_local_bridge(request, x_cats_bridge_token)
    st = svc.heartbeat(body.model_dump())
    return ok(data=st)


@router.get("/quotes")
async def list_quotes(
    symbols: Optional[str] = Query(None, description="逗号分隔；空=全部"),
    current_user=Depends(get_current_user),
):
    syms = [s.strip() for s in (symbols or "").split(",") if s.strip()] or None
    return ok(data=svc.get_quotes(syms))


@router.get("/status")
async def bridge_status(current_user=Depends(get_current_user)):
    return ok(data=svc.status())


@router.get("/watchlist")
async def get_watchlist(current_user=Depends(get_current_user)):
    return ok(data={"symbols": svc.read_watchlist()})
