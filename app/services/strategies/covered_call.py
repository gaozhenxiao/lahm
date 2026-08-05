# -*- coding: utf-8 -*-
"""高股息/宽基备兑：标的位置 + QVIX 权利金环境。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.covered_call")

# ETF 标的与对应 QVIX 接口名
TARGETS = [
    {
        "code": "510050",
        "name": "上证50ETF",
        "style": "宽基",
        "qvix_fn": "index_option_50etf_qvix",
        "option_hint": "50ETF 期权流动性最好，优先备兑",
    },
    {
        "code": "510300",
        "name": "沪深300ETF",
        "style": "宽基",
        "qvix_fn": "index_option_300etf_qvix",
        "option_hint": "300ETF 期权备兑",
    },
    {
        "code": "159915",
        "name": "创业板ETF",
        "style": "成长",
        "qvix_fn": "index_option_cyb_qvix",
        "option_hint": "波动高，权利金厚但方向风险大",
    },
    {
        "code": "512890",
        "name": "红利低波ETF",
        "style": "红利",
        "qvix_fn": None,
        "option_hint": "无直接期权时可改用 50/300 备兑作替代覆盖",
    },
    {
        "code": "515080",
        "name": "中证红利ETF",
        "style": "红利",
        "qvix_fn": None,
        "option_hint": "红利底仓 + 50/300 虚值认购作组合备兑（不完全对冲）",
    },
]


def _latest_qvix(fn_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not fn_name:
        return None
    try:
        import akshare as ak

        fn = getattr(ak, fn_name, None)
        if fn is None:
            return None
        df = fn()
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        # 常见列：date / qvix 或类似
        val = None
        for c in df.columns:
            if str(c).lower() in ("qvix", "close", "value", "iVIX", "ivix"):
                val = safe_float(last.get(c))
                if val is not None:
                    break
        if val is None:
            # 取最后一个数值列
            for c in df.columns[::-1]:
                val = safe_float(last.get(c))
                if val is not None:
                    break
        date = str(last.get("date") or last.get("日期") or "")[:10]
        return {"qvix": val, "date": date or None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("qvix %s failed: %s", fn_name, exc)
        return None


def _etf_prices() -> Dict[str, Dict[str, Any]]:
    import akshare as ak

    df = ak.fund_etf_spot_em()
    out: Dict[str, Dict[str, Any]] = {}
    for _, r in df.iterrows():
        code = str(r.get("代码") or "").zfill(6)
        out[code] = {
            "price": safe_float(r.get("最新价")),
            "change_pct": safe_float(r.get("涨跌幅")),
            "amount": safe_float(r.get("成交额")),
            "name": str(r.get("名称") or ""),
        }
    return out


def _score(change_pct: Optional[float], qvix: Optional[float], style: str) -> tuple[str, str]:
    """返回 (环境, 建议)。"""
    chg = change_pct or 0.0
    qx = qvix
    if style == "成长" and chg > 2.5:
        return "偏强趋势", "暂缓卖call或只卖更虚值，防被指派"
    if qx is not None and qx >= 25 and abs(chg) < 1.5:
        return "权利金偏厚+震荡", "适合卖虚值认购（备兑）"
    if qx is not None and qx < 15:
        return "权利金偏薄", "备兑性价比一般，可降仓或观望"
    if style == "红利" and abs(chg) < 1.2:
        return "红利慢牛/震荡", "可持底仓，用50/300期权做覆盖增强"
    return "中性", "小仓试点，卖近月虚值一档"


def _scan() -> Dict[str, Any]:
    prices = _etf_prices()
    items: List[Dict[str, Any]] = []
    for t in TARGETS:
        pxinfo = prices.get(t["code"], {})
        q = _latest_qvix(t.get("qvix_fn"))
        qvix = (q or {}).get("qvix")
        env, advice = _score(pxinfo.get("change_pct"), qvix, t["style"])
        items.append(
            {
                "code": t["code"],
                "name": pxinfo.get("name") or t["name"],
                "style": t["style"],
                "price": pxinfo.get("price"),
                "change_pct": pxinfo.get("change_pct"),
                "amount": pxinfo.get("amount"),
                "qvix": qvix,
                "qvix_date": (q or {}).get("date"),
                "environment": env,
                "advice": advice,
                "option_hint": t["option_hint"],
                "available": pxinfo.get("price") is not None,
            }
        )

    good = [x for x in items if "适合" in (x.get("advice") or "")]
    return {
        "asof": now_iso(),
        "source": "fund_etf_spot_em + index_option_*_qvix",
        "summary": {"n_targets": len(items), "n_favorable": len(good)},
        "items": items,
        "notes": [
            "备兑=持有标的 + 卖出认购期权；赚权利金，上档收益被盖帽。",
            "QVIX 高且标的震荡时，卖 call 性价比通常更好。",
            "需期权合约账户；具体行权价/到期日请在 QMT 期权链上确认。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    return cached_scan("covered_call", _scan, refresh=refresh, ttl_sec=ttl_sec)
