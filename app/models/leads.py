"""机会（Leads）数据模型"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LeadStatus(str, Enum):
    NEW = "new"  # 新建
    WATCHING = "watching"  # 观察中
    ANALYZING = "analyzing"  # 分析中
    INVESTED = "invested"  # 已转入投资
    CLOSED = "closed"  # 关闭/废弃


class LeadSource(str, Enum):
    SCREENING = "screening"
    MANUAL = "manual"
    ANALYSIS = "analysis"
    FACTOR = "factor"
    OTHER = "other"


class LeadCreate(BaseModel):
    code: str = Field(..., description="股票代码，如 600519 或 600519.SH")
    name: str = Field("", description="股票名称")
    market: str = Field("CN", description="市场 CN/HK/US")
    source: LeadSource = LeadSource.MANUAL
    status: LeadStatus = LeadStatus.NEW
    score: Optional[float] = Field(None, description="机会评分 0-100")
    reason: str = Field("", description="机会理由/备注")
    tags: List[str] = Field(default_factory=list)
    screening_snapshot: Optional[Dict[str, Any]] = Field(None, description="筛选时字段快照")
    analysis_id: Optional[str] = None
    factor_id: Optional[str] = None


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[LeadStatus] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    tags: Optional[List[str]] = None
    analysis_id: Optional[str] = None
    factor_id: Optional[str] = None


class LeadBulkFromScreening(BaseModel):
    items: List[Dict[str, Any]] = Field(..., description="筛选结果 items")
    reason: str = Field("来自股票筛选", description="统一备注")
    tags: List[str] = Field(default_factory=lambda: ["screening"])
    score: Optional[float] = None


class LeadOut(BaseModel):
    id: str
    user_id: str
    code: str
    name: str
    market: str
    source: str
    status: str
    score: Optional[float] = None
    reason: str = ""
    tags: List[str] = Field(default_factory=list)
    screening_snapshot: Optional[Dict[str, Any]] = None
    analysis_id: Optional[str] = None
    factor_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
