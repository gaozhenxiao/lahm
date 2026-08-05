# -*- coding: utf-8 -*-
"""可转债模块服务门面。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.services.cb import strategies as strat
from app.services.cb import stock_arb


class CbService:
    def list_strategies(self) -> Dict[str, Any]:
        items = strat.list_strategies()
        return {"total": len(items), "items": items}

    def module_meta(self) -> Dict[str, Any]:
        return {
            "module": "convertible_bonds",
            "name": "可转债",
            "description": "与多因子并列的可转债研究/套利模块；当前支持转债-正股套利，日内套利规划中。",
            "strategies": strat.list_strategies(),
        }

    async def stock_arb(
        self,
        *,
        refresh: bool = False,
        ttl_sec: int = 300,
        discount_max: float = -0.3,
        near_parity_max: float = 3.0,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            stock_arb.get_stock_arb,
            refresh=refresh,
            ttl_sec=ttl_sec,
            discount_max=discount_max,
            near_parity_max=near_parity_max,
        )


cb_service = CbService()
