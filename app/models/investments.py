"""Investments（投资列表）轻量模型：研究仓/决策台账"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class InvestmentStatus(str, Enum):
    PLANNED = "planned"
    OPEN = "open"
    CLOSED = "closed"


class InvestmentCreate(BaseModel):
    code: str
    name: str = ""
    market: str = "CN"
    status: InvestmentStatus = InvestmentStatus.PLANNED
    side: str = Field("long", description="long/short")
    target_weight: Optional[float] = None
    quantity: Optional[int] = None
    entry_price: Optional[float] = None
    thesis: str = Field("", description="投资逻辑")
    lead_id: Optional[str] = None
    analysis_id: Optional[str] = None
    factor_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class InvestmentUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[InvestmentStatus] = None
    target_weight: Optional[float] = None
    quantity: Optional[int] = None
    entry_price: Optional[float] = None
    thesis: Optional[str] = None
    tags: Optional[List[str]] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None


class InvestmentOut(BaseModel):
    id: str
    user_id: str
    code: str
    name: str
    market: str
    status: str
    side: str
    target_weight: Optional[float] = None
    quantity: Optional[int] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    thesis: str = ""
    lead_id: Optional[str] = None
    analysis_id: Optional[str] = None
    factor_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
