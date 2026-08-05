# -*- coding: utf-8 -*-
"""国债期货基差 / 跨期（CFFEX 日线主力近似 + 债基 ETF 代理）。"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.services.strategies.common import cached_scan, now_iso, safe_float
from app.services.strategies.bond_etf_arb import _tencent_quotes

logger = logging.getLogger("webapi.strategies.treasury_basis")

PROXY_MAP: Dict[str, Tuple[str, str, str]] = {
    "T": ("511260", "十年国债ETF", "10年"),
    "TF": ("511010", "国债ETF国泰", "5年代理"),
    "TS": ("511360", "短融ETF", "2年/短端代理"),
    "TL": ("511090", "30年国债ETF", "超长期"),
}


def _near_cffex_settles() -> Dict[str, Dict[str, Any]]:
    """取中金所最近交易日 T/TF/TS/TL 近月合约收盘/结算。"""
    import akshare as ak

    out: Dict[str, Dict[str, Any]] = {}
    last_err: Optional[Exception] = None
    for i in range(1, 10):
        dd = (date.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = ak.get_futures_daily(start_date=dd, end_date=dd, market="CFFEX")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        if df is None or df.empty:
            continue
        # variety or symbol
        for prefix in PROXY_MAP:
            sub = df[df["symbol"].astype(str).str.startswith(prefix)]
            if sub.empty and "variety" in df.columns:
                sub = df[df["variety"].astype(str) == prefix]
            if sub.empty:
                continue
            # 近月：symbol 排序取最小月份
            sub = sub.copy()
            sub["_sym"] = sub["symbol"].astype(str)
            sub = sub.sort_values("_sym")
            r = sub.iloc[0]
            px = safe_float(r.get("close")) or safe_float(r.get("settle"))
            out[prefix] = {
                "code": str(r.get("symbol")),
                "name": str(r.get("symbol")),
                "price": px,
                "date": str(r.get("date") or dd),
                "open_interest": safe_float(r.get("open_interest")),
            }
        if out:
            out["_asof"] = dd
            return out
    if last_err:
        logger.warning("cffex daily failed: %s", last_err)
    return out


def _scan() -> Dict[str, Any]:
    futs = _near_cffex_settles()
    asof_trade = futs.pop("_asof", None) if isinstance(futs, dict) else None
    proxy_codes = [v[0] for v in PROXY_MAP.values()]
    quotes = _tencent_quotes(proxy_codes)

    items: List[Dict[str, Any]] = []
    for prefix, (etf_code, etf_name, note) in PROXY_MAP.items():
        fut = futs.get(prefix) or {}
        q = quotes.get(etf_code) or {}
        fpx = fut.get("price")
        epx = q.get("price")
        available = fpx is not None
        basis = basis_pct = None
        regime, signal = "仅期货", "看跨期价差为主"
        if fpx is not None:
            regime = "近月已更新"
            signal = f"代理ETF {etf_code} 仅供参考，非CTD"
        items.append(
            {
                "prefix": prefix,
                "futures_code": fut.get("code"),
                "futures_name": fut.get("name") or prefix,
                "futures_price": fpx,
                "proxy_code": etf_code,
                "proxy_name": q.get("name") or etf_name,
                "proxy_price": epx,
                "proxy_note": note,
                "trade_date": fut.get("date") or asof_trade,
                "basis": basis,
                "basis_pct": basis_pct,
                "regime": regime,
                "signal": signal,
                "available": available,
            }
        )

    spreads: List[Dict[str, Any]] = []
    by_p = {x["prefix"]: x for x in items if x.get("futures_price")}
    for a, b, label in (("T", "TF", "T-TF 10Y-5Y"), ("TF", "TS", "TF-TS 5Y-2Y"), ("TL", "T", "TL-T 超长-10Y")):
        if a in by_p and b in by_p:
            spreads.append(
                {
                    "pair": label,
                    "spread": round(float(by_p[a]["futures_price"]) - float(by_p[b]["futures_price"]), 3),
                    "note": "仅期货腿跨期（近月合约）",
                }
            )

    return {
        "asof": now_iso(),
        "source": f"CFFEX daily({asof_trade}) + tencent bond ETF",
        "summary": {
            "n_contracts": len(items),
            "n_available": sum(1 for x in items if x.get("available")),
            "n_spreads": len(spreads),
        },
        "items": items,
        "spreads": spreads,
        "notes": [
            "核心看「跨期价差」表（T/TF/TS/TL 近月）；债基 ETF 只作对照，尺度不同勿直接减价当基差。",
            "期货价为中金所近月收盘/结算，非盘中实时；严格期现需 CTD 一篮子。",
            "需国债期货权限。可与「债券ETF折溢价」联看。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    return cached_scan("treasury_basis", _scan, refresh=refresh, ttl_sec=ttl_sec)
