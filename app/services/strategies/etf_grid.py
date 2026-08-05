# -*- coding: utf-8 -*-
"""ETF 网格：为流动性好的宽基/红利 ETF 生成网格档位。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.etf_grid")

# code, name, grid_step_pct 默认步长
UNIVERSE = [
    ("510300", "沪深300ETF", 0.012),
    ("510500", "中证500ETF", 0.015),
    ("159915", "创业板ETF", 0.018),
    ("510050", "上证50ETF", 0.012),
    ("512890", "红利低波ETF", 0.010),
    ("515080", "中证红利ETF", 0.010),
    ("588000", "科创50ETF", 0.020),
]


def _fetch_etf_spot() -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_spot_em()


def _grid_levels(price: float, step_pct: float, n: int = 4) -> Dict[str, List[float]]:
    buys = [round(price * (1 - step_pct * i), 4) for i in range(1, n + 1)]
    sells = [round(price * (1 + step_pct * i), 4) for i in range(1, n + 1)]
    return {"buy_levels": buys, "sell_levels": sells}


def _scan() -> Dict[str, Any]:
    df = _fetch_etf_spot()
    code_col = "代码" if "代码" in df.columns else "code"
    by_code = {str(r[code_col]).zfill(6): r for _, r in df.iterrows()}

    items: List[Dict[str, Any]] = []
    for code, name, step in UNIVERSE:
        r = by_code.get(code)
        if r is None:
            items.append({"code": code, "name": name, "available": False})
            continue
        px = safe_float(r.get("最新价"))
        iopv = safe_float(r.get("IOPV实时估值"))
        disc = safe_float(r.get("基金折价率"))
        chg = safe_float(r.get("涨跌幅"))
        amount = safe_float(r.get("成交额"))
        if px is None or px <= 0:
            items.append({"code": code, "name": name, "available": False})
            continue
        # 振幅大时略放宽步长
        amp = safe_float(r.get("振幅"))
        adj_step = step
        if amp is not None and amp > 2.5:
            adj_step = step * 1.25
        levels = _grid_levels(px, adj_step, n=4)
        items.append(
            {
                "code": code,
                "name": str(r.get("名称") or name),
                "available": True,
                "price": px,
                "iopv": iopv,
                "discount_pct": disc,
                "change_pct": chg,
                "amount": amount,
                "step_pct": round(adj_step * 100, 2),
                **levels,
                "hint": "震荡挂网格；单边突破连续两档可暂停加仓",
            }
        )

    return {
        "asof": now_iso(),
        "source": "akshare.fund_etf_spot_em",
        "summary": {"n_universe": len(UNIVERSE), "n_ready": sum(1 for x in items if x.get("available"))},
        "items": items,
        "notes": [
            "网格步长按标的波动预设，可按自身风险偏好调整。",
            "趋势市减少层数或扩大步长，避免逆势摊平过多。",
            "QMT 就绪后可按 buy/sell_levels 自动挂单（接口已预留）。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    return cached_scan("etf_grid", _scan, refresh=refresh, ttl_sec=ttl_sec)
