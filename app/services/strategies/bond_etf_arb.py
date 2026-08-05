# -*- coding: utf-8 -*-
"""债券 ETF 折溢价扫描（独立行情源；东财 ETF 列表常不含债基）。"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.bond_etf_arb")

UNIVERSE: List[Tuple[str, str]] = [
    ("511010", "国债ETF国泰"),
    ("511260", "十年国债ETF"),
    ("511090", "30年国债ETF"),
    ("511130", "30年国债ETF博时"),
    ("511100", "基准做市国债ETF"),
    ("511220", "城投债ETF"),
    ("511270", "十年地方债ETF"),
    ("511360", "短融ETF"),
    ("511030", "公司债ETF"),
    ("511060", "5年地方债ETF"),
    ("511380", "可转债ETF博时"),
    ("511180", "可转债等权ETF"),
    ("159649", "国债ETF"),
    ("511520", "政金债券ETF"),
]


def _tencent_quotes(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """腾讯行情：price / name / amount。"""
    out: Dict[str, Dict[str, Any]] = {}
    if not codes:
        return out
    qs = []
    for c in codes:
        pref = "sz" if c.startswith(("15", "16")) else "sh"
        qs.append(f"{pref}{c}")
    try:
        r = requests.get(
            "https://qt.gtimg.cn/q=" + ",".join(qs),
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.encoding = "gbk"
        text = r.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("tencent quotes failed: %s", exc)
        return out

    for line in text.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        # v_sh511010="..."
        m = re.search(r"v_(?:sh|sz)(\d{6})=\"(.*)\"", line)
        if not m:
            continue
        code, payload = m.group(1), m.group(2)
        parts = payload.split("~")
        if len(parts) < 40:
            continue
        # 腾讯: 1名称 3现价 6成交量 37成交额(万)? — 常见格式 name~code~...
        name = parts[1] if len(parts) > 1 else code
        px = safe_float(parts[3]) if len(parts) > 3 else None
        amount = safe_float(parts[37]) if len(parts) > 37 else None
        if amount is not None and amount < 1e6:
            # 有时单位是元
            pass
        out[code] = {"name": name, "price": px, "amount": amount}
    return out


def _nav_map() -> Dict[str, float]:
    """同花顺/东财债券型列表中的单位净值。"""
    import akshare as ak

    out: Dict[str, float] = {}
    for fn_name in ("fund_etf_spot_ths", "fund_etf_category_ths"):
        try:
            if fn_name == "fund_etf_category_ths":
                df = ak.fund_etf_category_ths(symbol="债券型")
            else:
                df = ak.fund_etf_spot_ths()
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s failed: %s", fn_name, exc)
            continue
        if df is None or df.empty:
            continue
        code_col = "基金代码" if "基金代码" in df.columns else None
        nav_col = None
        for c in ("当前-单位净值", "最新-单位净值", "单位净值"):
            if c in df.columns:
                nav_col = c
                break
        if not code_col or not nav_col:
            continue
        for _, r in df.iterrows():
            code = str(r.get(code_col) or "").zfill(6)
            nav = safe_float(r.get(nav_col))
            if code and nav and nav > 0:
                out[code] = nav
        if out:
            break
    return out


def _scan() -> Dict[str, Any]:
    codes = [c for c, _ in UNIVERSE]
    quotes = _tencent_quotes(codes)
    navs = _nav_map()
    items: List[Dict[str, Any]] = []
    for code, hint in UNIVERSE:
        q = quotes.get(code) or {}
        px = q.get("price")
        nav = navs.get(code)
        if px is None or nav is None or nav <= 0:
            continue
        premium = round((float(px) / float(nav) - 1.0) * 100.0, 3)
        items.append(
            {
                "code": code,
                "name": q.get("name") or hint,
                "price": px,
                "iopv": nav,  # 此处为净值代理（非盘中 IOPV）
                "premium_pct": premium,
                "amount": q.get("amount"),
                "change_pct": None,
                "side": "溢价(可申购卖出)" if premium >= 0.05 else (
                    "折价(可买入赎回)" if premium <= -0.05 else "近似平价"
                ),
                "flags": [],
            }
        )

    items.sort(key=lambda x: abs(x["premium_pct"]), reverse=True)
    return {
        "asof": now_iso(),
        "source": "tencent qt + ths bond NAV",
        "summary": {
            "n_items": len(items),
            "n_premium": sum(1 for x in items if x["premium_pct"] >= 0.05),
            "n_discount": sum(1 for x in items if x["premium_pct"] <= -0.05),
        },
        "items": items,
        "notes": [
            "市价来自腾讯行情；估值为同花顺债券型单位净值（非盘中 IOPV），盘中请再核 IOPV。",
            "债券 ETF 折溢价通常很薄，需覆盖申赎与冲击。",
            "可转债 ETF 也在池中，与个券转债策略互补。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 180) -> Dict[str, Any]:
    return cached_scan("bond_etf_arb", _scan, refresh=refresh, ttl_sec=ttl_sec)
