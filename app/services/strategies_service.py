# -*- coding: utf-8 -*-
"""策略中心服务门面。"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

from app.services.strategies import (
    bond_etf_arb,
    cm_big4_grid,
    covered_call,
    dual_low,
    etf_grid,
    futures_basis,
    lof_arb,
    pairs,
    treasury_basis,
)
from app.services.strategies import qmt_bridge
from app.services.strategies import registry as reg

_SCANNERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "dual_low": dual_low.get_scan,
    "etf_grid": etf_grid.get_scan,
    "cm_big4_grid": cm_big4_grid.get_scan,
    "lof_arb": lof_arb.get_scan,
    "futures_basis": futures_basis.get_scan,
    "bond_etf_arb": bond_etf_arb.get_scan,
    "treasury_basis": treasury_basis.get_scan,
    "covered_call": covered_call.get_scan,
    "pairs": pairs.get_scan,
}


class StrategiesService:
    def list_strategies(self) -> Dict[str, Any]:
        items = reg.list_strategies()
        return {"total": len(items), "items": items}

    def meta(self) -> Dict[str, Any]:
        return {
            "module": "strategies",
            "name": "策略中心",
            "description": "多资产扫描：双低 / 红利倾斜网格 / 移动核电四大行网格 / LOF / 股指基差 / 债券ETF / 国债基差 / 备兑 / 配对；期现不做。",
            "strategies": reg.list_strategies(),
            "excluded": ["cash_futures_arb"],
        }

    async def scan(self, strategy_id: str, *, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
        if strategy_id == "cb_stock_arb":
            from app.services.cb_service import cb_service

            data = await cb_service.stock_arb(refresh=refresh, ttl_sec=ttl_sec)
            data["strategy_id"] = "cb_stock_arb"
            data["redirect"] = "/multi-asset/cb"
            return data
        fn = _SCANNERS.get(strategy_id)
        if not fn:
            raise ValueError(f"unknown strategy: {strategy_id}")
        return await asyncio.to_thread(fn, refresh=refresh, ttl_sec=ttl_sec)

    def qmt_status(self) -> Dict[str, Any]:
        return qmt_bridge.get_status()

    def qmt_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        return qmt_bridge.save_config(patch)


strategies_service = StrategiesService()
