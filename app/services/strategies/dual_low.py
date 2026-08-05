# -*- coding: utf-8 -*-
"""可转债双低：复用 CB 扫描中的 dual_low 池。"""
from __future__ import annotations

from typing import Any, Dict

from app.services.cb import stock_arb
from app.services.strategies.common import cached_scan, now_iso


def _scan() -> Dict[str, Any]:
    raw = stock_arb.get_stock_arb(refresh=True, ttl_sec=0)
    items = list(raw.get("dual_low") or [])
    return {
        "asof": now_iso(),
        "source": raw.get("source"),
        "summary": {
            "n_items": len(items),
            "n_traded": (raw.get("summary") or {}).get("n_traded"),
        },
        "items": items,
        "notes": [
            "双低分 = 债价 + 转股溢价率；越低越偏债性便宜。",
            "建议等权持有 Top N（如 10～20），按周/双周再平衡。",
            "非无风险套利；正股大跌时转债仍可能回撤。",
        ],
        "actions": [
            {"type": "rebalance_hint", "top_n": 15, "text": "建议关注双低分最低的前 15 只作为候选池"}
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    return cached_scan("dual_low", _scan, refresh=refresh, ttl_sec=ttl_sec)
