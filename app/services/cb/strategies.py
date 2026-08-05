# -*- coding: utf-8 -*-
"""可转债策略目录：当前启用正股套利，日内套利占位。"""
from __future__ import annotations

from typing import Any, Dict, List

STRATEGIES: List[Dict[str, Any]] = [
    {
        "id": "stock_arb",
        "name": "转债-正股套利",
        "status": "active",
        "description": "多资产·可转债：扫描转股溢价率折价/平价/双低，捕捉转债与正股联动套利机会。",
        "endpoint": "/api/cb/arb/stock",
    },
    {
        "id": "intraday_arb",
        "name": "转债日内套利",
        "status": "coming_soon",
        "description": "多资产·可转债：日内盘口/分钟级价差与跟随滞后（规划中）。",
        "endpoint": None,
    },
]


def list_strategies() -> List[Dict[str, Any]]:
    return list(STRATEGIES)


def get_strategy(strategy_id: str) -> Dict[str, Any] | None:
    for s in STRATEGIES:
        if s["id"] == strategy_id:
            return dict(s)
    return None
