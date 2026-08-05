# -*- coding: utf-8 -*-
"""股指期货主力升贴水（基差）监控。不含期现一篮子套利执行。"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.futures_basis")

# 期货品种 -> 现货指数代码
INDEX_MAP = {
    "IF": ("000300", "沪深300"),
    "IH": ("000016", "上证50"),
    "IC": ("000905", "中证500"),
    "IM": ("000852", "中证1000"),
}


def _index_spots() -> Dict[str, float]:
    import akshare as ak

    # 尝试多个 symbol 参数
    for symbol in ("沪深重要指数", "主要指数"):
        try:
            df = ak.stock_zh_index_spot_em(symbol=symbol)
            out: Dict[str, float] = {}
            for _, r in df.iterrows():
                code = str(r.get("代码") or "").zfill(6)
                px = safe_float(r.get("最新价"))
                if px is not None:
                    out[code] = px
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("index spot %s failed: %s", symbol, exc)
    # sina fallback
    try:
        import akshare as ak

        df = ak.stock_zh_index_spot_sina()
        out = {}
        for _, r in df.iterrows():
            code = str(r.get("代码") or "")
            # sina often like sh000300
            m = re.search(r"(\d{6})", code)
            if not m:
                continue
            px = safe_float(r.get("最新价") or r.get("trade"))
            if px is not None:
                out[m.group(1)] = px
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("index sina failed: %s", exc)
        return {}


def _futures_mains() -> List[Dict[str, Any]]:
    import akshare as ak

    rows: List[Dict[str, Any]] = []
    # 新浪主力连续
    try:
        df = ak.futures_main_sina()
        # 列名可能是 代码/名称/最新价 等
        for _, r in df.iterrows():
            text = " ".join(str(r.get(c) or "") for c in df.columns)
            for prefix in INDEX_MAP:
                if re.search(rf"\b{prefix}\b|{prefix}\d{{3,4}}|{prefix}主力", text, re.I):
                    # 找价格列
                    px = None
                    for col in ("最新价", "settle", "trade", "price", "现价"):
                        if col in df.columns:
                            px = safe_float(r.get(col))
                            if px is not None:
                                break
                    if px is None:
                        for col in df.columns:
                            px = safe_float(r.get(col))
                            if px is not None and px > 100:
                                break
                    name = str(r.get("名称") or r.get("symbol") or text[:20])
                    code = str(r.get("代码") or r.get("symbol") or prefix)
                    rows.append({"prefix": prefix, "code": code, "name": name, "price": px})
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warning("futures_main_sina failed: %s", exc)

    # 补充：逐品种实时
    if len(rows) < 4:
        for prefix in INDEX_MAP:
            if any(x["prefix"] == prefix for x in rows):
                continue
            for symbol in (f"{prefix}0", f"{prefix}主力", prefix):
                try:
                    spot = ak.futures_zh_spot(symbol=symbol, market="CF", adjust="0")
                    if spot is not None and not spot.empty:
                        r = spot.iloc[0]
                        px = safe_float(r.get("current_price") or r.get("最新价") or r.get("trade"))
                        rows.append(
                            {
                                "prefix": prefix,
                                "code": str(r.get("symbol") or symbol),
                                "name": str(r.get("symbol") or symbol),
                                "price": px,
                            }
                        )
                        break
                except Exception:  # noqa: BLE001
                    continue
    return rows


def _annualize_basis(basis_pct: float, days_to_expiry: Optional[int] = 30) -> Optional[float]:
    if days_to_expiry is None or days_to_expiry <= 0:
        return None
    return round(basis_pct * (365.0 / days_to_expiry), 2)


def _scan() -> Dict[str, Any]:
    spots = _index_spots()
    futs = _futures_mains()
    items: List[Dict[str, Any]] = []
    for fut in futs:
        prefix = fut["prefix"]
        idx_code, idx_name = INDEX_MAP[prefix]
        spot = spots.get(idx_code)
        fpx = fut.get("price")
        if spot is None or fpx is None or spot <= 0:
            items.append(
                {
                    "prefix": prefix,
                    "futures_code": fut.get("code"),
                    "futures_name": fut.get("name"),
                    "index_code": idx_code,
                    "index_name": idx_name,
                    "available": False,
                }
            )
            continue
        basis = fpx - spot
        basis_pct = (fpx / spot - 1.0) * 100.0
        regime = "升水" if basis_pct > 0.15 else ("贴水" if basis_pct < -0.15 else "近乎平水")
        items.append(
            {
                "prefix": prefix,
                "futures_code": fut.get("code"),
                "futures_name": fut.get("name"),
                "futures_price": round(fpx, 2),
                "index_code": idx_code,
                "index_name": idx_name,
                "index_price": round(spot, 2),
                "basis": round(basis, 2),
                "basis_pct": round(basis_pct, 3),
                "annualized_pct_approx": _annualize_basis(basis_pct, 30),
                "regime": regime,
                "available": True,
                "signal": (
                    "贴水偏深·可关注多期货/空现货对冲思路"
                    if basis_pct <= -1.0
                    else ("升水偏高·谨慎追多期货" if basis_pct >= 1.0 else "中性观察")
                ),
            }
        )

    items.sort(key=lambda x: (x.get("basis_pct") is None, x.get("basis_pct") or 0))
    deep = [x for x in items if x.get("available") and (x.get("basis_pct") or 0) <= -0.8]

    return {
        "asof": now_iso(),
        "source": "akshare index spot + futures_main/zh_spot",
        "summary": {
            "n_contracts": len(items),
            "n_deep_discount": len(deep),
        },
        "items": items,
        "notes": [
            "基差%=(期货-现货)/现货；负值为贴水。",
            "年化按约 30 日临近交割粗估，实盘请按真实到期日计算。",
            "本模块只做监控与信号，不包含期现一篮子套利执行。",
            "下单需期货权限与足够保证金；建议经 QMT 期货通道。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 120) -> Dict[str, Any]:
    return cached_scan("futures_basis", _scan, refresh=refresh, ttl_sec=ttl_sec)
