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


class LeadKind(str, Enum):
    """因子持仓书条目语义。"""
    OPPORTUNITY = "opportunity"  # 优质因子持仓（主机会）
    MIXED = "mixed"  # 既有优质又有弱势/中性
    ALERT = "alert"  # 仅弱势因子持仓（警醒）
    WATCH = "watch"  # 仅中性因子持仓


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
    kind: Optional[str] = Field(None, description="opportunity|mixed|alert|watch")
    factors_good: List[Dict[str, Any]] = Field(default_factory=list)
    factors_warn: List[Dict[str, Any]] = Field(default_factory=list)
    factors_neutral: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[str] = None
    weights: List[Dict[str, Any]] = Field(default_factory=list)


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[LeadStatus] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    tags: Optional[List[str]] = None
    analysis_id: Optional[str] = None
    factor_id: Optional[str] = None
    kind: Optional[str] = None
    factors_good: Optional[List[Dict[str, Any]]] = None
    factors_warn: Optional[List[Dict[str, Any]]] = None
    factors_neutral: Optional[List[Dict[str, Any]]] = None
    as_of: Optional[str] = None


class LeadBulkFromScreening(BaseModel):
    items: List[Dict[str, Any]] = Field(..., description="筛选结果 items")
    reason: str = Field("来自股票筛选", description="统一备注")
    tags: List[str] = Field(default_factory=lambda: ["screening"])
    score: Optional[float] = None


class FactorRef(BaseModel):
    factor_id: str
    name: str = ""
    sharpe: Optional[float] = None
    quality: str = "unknown"
    weight: Optional[float] = None
    buy_date: Optional[str] = None
    buy_price: Optional[float] = None
    as_of: Optional[str] = None
    is_champion: bool = False
    note: str = ""


class LeadOut(BaseModel):
    id: str
    user_id: str = ""
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
    kind: Optional[str] = None
    factors_good: List[Dict[str, Any]] = Field(default_factory=list)
    factors_warn: List[Dict[str, Any]] = Field(default_factory=list)
    factors_neutral: List[Dict[str, Any]] = Field(default_factory=list)
    weights: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
