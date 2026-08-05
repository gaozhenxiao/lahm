# -*- coding: utf-8 -*-
"""LOF / 场内基金折溢价扫描。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.lof_arb")


def _scan_lof() -> pd.DataFrame:
    import akshare as ak

    return ak.fund_lof_spot_em()


def _scan_etf_as_fallback() -> pd.DataFrame:
    """LOF 接口失败时，用 ETF 折溢价作补充扫描（同类逻辑）。"""
    import akshare as ak

    return ak.fund_etf_spot_em()


def _normalize(df: pd.DataFrame, kind: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return items
    for _, r in df.iterrows():
        code = str(r.get("代码") or "").zfill(6)
        name = str(r.get("名称") or "")
        px = safe_float(r.get("最新价"))
        iopv = safe_float(r.get("IOPV实时估值"))
        disc = safe_float(r.get("基金折价率"))  # 东财：负=溢价？需以字段含义为准
        # 东财「基金折价率」：正数多为折价（净值高于市价）。统一成「溢价率」= -折价率
        premium = None
        if disc is not None:
            premium = round(-disc, 3)
        elif px is not None and iopv is not None and iopv > 0:
            premium = round((px / iopv - 1.0) * 100.0, 3)
        amount = safe_float(r.get("成交额"))
        if px is None or premium is None:
            continue
        if amount is not None and amount < 3e5:
            continue
        # 明显折溢价
        if abs(premium) < 0.5:
            continue
        side = "溢价(可申购卖出)" if premium >= 0.5 else "折价(可买入赎回)"
        items.append(
            {
                "code": code,
                "name": name,
                "kind": kind,
                "price": px,
                "iopv": iopv,
                "premium_pct": premium,
                "amount": amount,
                "change_pct": safe_float(r.get("涨跌幅")),
                "side": side,
                "flags": ["高成交"] if (amount or 0) >= 1e7 else [],
            }
        )
    items.sort(key=lambda x: abs(x["premium_pct"]), reverse=True)
    return items


def _scan() -> Dict[str, Any]:
    source_parts = []
    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        lof = _scan_lof()
        items.extend(_normalize(lof, "LOF"))
        source_parts.append("fund_lof_spot_em")
    except Exception as exc:  # noqa: BLE001
        logger.warning("lof spot failed: %s", exc)
        errors.append(f"LOF接口失败: {exc}")

    # ETF 折溢价也列出（用户可一并看）
    try:
        etf = _scan_etf_as_fallback()
        etf_items = _normalize(etf, "ETF")
        # 只保留 |溢价|>=0.8 的 ETF，避免刷屏
        etf_items = [x for x in etf_items if abs(x["premium_pct"]) >= 0.8][:40]
        items.extend(etf_items)
        source_parts.append("fund_etf_spot_em")
    except Exception as exc:  # noqa: BLE001
        logger.warning("etf spot failed: %s", exc)
        errors.append(f"ETF接口失败: {exc}")

    items.sort(key=lambda x: abs(x["premium_pct"]), reverse=True)
    premium = [x for x in items if x["premium_pct"] >= 0.5]
    discount = [x for x in items if x["premium_pct"] <= -0.5]

    return {
        "asof": now_iso(),
        "source": " + ".join(source_parts) or "unavailable",
        "summary": {
            "n_items": len(items),
            "n_premium": len(premium),
            "n_discount": len(discount),
        },
        "items": items[:80],
        "errors": errors,
        "notes": [
            "溢价率≈(市价-IOPV)/IOPV；东财折价率取反后统一口径。",
            "溢价：场外申购→场内卖出（看申购限额与T+N）；折价：场内买→赎回。",
            "机会常被秒平；请核申购/赎回状态与冲击成本。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 180) -> Dict[str, Any]:
    return cached_scan("lof_arb", _scan, refresh=refresh, ttl_sec=ttl_sec)
