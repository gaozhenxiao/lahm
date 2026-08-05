# -*- coding: utf-8 -*-
"""卫星/套利策略目录（不含期现套利）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

STRATEGIES: List[Dict[str, Any]] = [
    {
        "id": "dual_low",
        "name": "可转债双低",
        "status": "active",
        "difficulty": "中",
        "capital": "1万+",
        "best_regime": "震荡/慢牛",
        "description": "债价+转股溢价率双低轮动；债性保护，日频即可。",
        "exec": "qmt_or_manual",
    },
    {
        "id": "etf_grid",
        "name": "ETF网格",
        "status": "active",
        "difficulty": "低",
        "capital": "5千+",
        "best_regime": "震荡",
        "description": "宽基/红利 ETF 网格挂单；震荡增收，趋势市降频。",
        "exec": "qmt",
    },
    {
        "id": "lof_arb",
        "name": "LOF套利",
        "status": "active",
        "difficulty": "低",
        "capital": "1千+",
        "best_regime": "折溢价明显",
        "description": "场内价 vs 净值/IOPV；机会稀疏，作资金效率插件。",
        "exec": "manual_or_qmt",
    },
    {
        "id": "futures_basis",
        "name": "股指基差",
        "status": "active",
        "difficulty": "中",
        "capital": "50万+",
        "best_regime": "贴水扩大",
        "description": "股指期货主力相对现货指数的升贴水监控与信号。",
        "exec": "qmt_futures",
    },
    {
        "id": "bond_etf_arb",
        "name": "债券ETF折溢价",
        "status": "active",
        "difficulty": "低",
        "capital": "1千+",
        "best_regime": "折溢价明显",
        "description": "利率/信用/转债等债券ETF场内价 vs IOPV。",
        "exec": "manual_or_qmt",
    },
    {
        "id": "treasury_basis",
        "name": "国债期货基差",
        "status": "active",
        "difficulty": "中高",
        "capital": "50万+",
        "best_regime": "基差异常/曲线陡峭",
        "description": "T/TF/TS/TL 相对债基ETF代理升贴水，及跨期价差。",
        "exec": "qmt_futures",
    },
    {
        "id": "covered_call",
        "name": "高股息备兑",
        "status": "active",
        "difficulty": "中",
        "capital": "5万+",
        "best_regime": "慢牛/震荡",
        "description": "持有红利/宽基 ETF，卖出虚值认购；看 QVIX 与标的位置。",
        "exec": "qmt_options",
    },
    {
        "id": "pairs",
        "name": "配对交易",
        "status": "active",
        "difficulty": "中高",
        "capital": "10万+",
        "best_regime": "震荡/弱市",
        "description": "预设配对价差 z-score；市场中性试点。",
        "exec": "qmt",
    },
    {
        "id": "cb_stock_arb",
        "name": "转债-正股套利",
        "status": "active",
        "difficulty": "中",
        "capital": "1万+",
        "best_regime": "折价/强赎窗口",
        "description": "见可转债模块；薄折价适合盘中实时。",
        "exec": "qmt_or_cats",
        "redirect": "/multi-asset/cb",
    },
]


def list_strategies() -> List[Dict[str, Any]]:
    return [dict(s) for s in STRATEGIES]


def get_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    for s in STRATEGIES:
        if s["id"] == strategy_id:
            return dict(s)
    return None
