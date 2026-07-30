"""因子（Factors）数据模型"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FactorCategory(str, Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    CUSTOM = "custom"


class FactorStatus(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    DISABLED = "disabled"


class FactorCreate(BaseModel):
    factor_id: str = Field(..., description="唯一 ID，如 national_team")
    name: str
    category: FactorCategory = FactorCategory.CUSTOM
    description: str = ""
    status: FactorStatus = FactorStatus.ACTIVE
    params: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class FactorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[FactorStatus] = None
    params: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class FactorOut(BaseModel):
    factor_id: str
    name: str
    category: str
    description: str
    status: str
    params: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    builtin: bool = False
    latest_signal: Optional[str] = None
    latest_value: Optional[float] = None
    latest_asof: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FactorSignalOut(BaseModel):
    factor_id: str
    asof: datetime
    signal: str  # buy / sell / neutral
    value: float
    components: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""
