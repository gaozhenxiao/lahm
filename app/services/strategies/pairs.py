# -*- coding: utf-8 -*-
"""配对交易：预设配对价差 z-score。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.strategies.common import cached_scan, now_iso, safe_float

logger = logging.getLogger("webapi.strategies.pairs")

# (a, b, label) — 代码用 bs_kit 风格 sh./sz.
PAIRS: List[Tuple[str, str, str]] = [
    ("sh.600036", "sh.601166", "招商银行-兴业银行"),
    ("sh.600000", "sh.601398", "浦发银行-工商银行"),
    ("sh.600519", "sz.000858", "贵州茅台-五粮液"),
    ("sz.000333", "sz.000651", "美的集团-格力电器"),
    ("sh.601318", "sh.601601", "中国平安-中国太保"),
    ("sz.300750", "sz.002594", "宁德时代-比亚迪"),
    ("sh.600276", "sz.000538", "恒瑞医药-云南白药"),
    ("sh.601888", "sz.002304", "中国中免-洋河股份"),
]


def _load_close(code: str, lookback: int = 180) -> Optional[pd.Series]:
    try:
        from app.services.factors import bs_kit as kit

        fp = kit.shared_cache_dir() / "daily" / f"{code.replace('.', '_')}.parquet"
        if not fp.exists():
            return None
        df = pd.read_parquet(fp)
        if df is None or df.empty:
            return None
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").tail(lookback)
        s = pd.to_numeric(df["close"], errors="coerce")
        s.index = df["date"]
        return s.dropna()
    except Exception as exc:  # noqa: BLE001
        logger.warning("load %s failed: %s", code, exc)
        return None


def _pair_stats(a: pd.Series, b: pd.Series, window: int = 60) -> Optional[Dict[str, Any]]:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(df) < window + 5:
        return None
    # 对数价差 + 滚动 beta 对冲
    la = np.log(df["a"])
    lb = np.log(df["b"])
    # 简易 hedge: OLS beta of la on lb over window
    beta_list = []
    spread_list = []
    idx = []
    for i in range(window, len(df)):
        sl = slice(i - window, i)
        x = lb.iloc[sl].values
        y = la.iloc[sl].values
        x = np.column_stack([np.ones(len(x)), x])
        try:
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
            beta = float(coef[1])
        except Exception:  # noqa: BLE001
            beta = 1.0
        sp = float(la.iloc[i] - beta * lb.iloc[i])
        beta_list.append(beta)
        spread_list.append(sp)
        idx.append(df.index[i])
    sp = pd.Series(spread_list, index=idx)
    mu = sp.rolling(window, min_periods=window).mean()
    sd = sp.rolling(window, min_periods=window).std()
    z = (sp - mu) / sd.replace(0, np.nan)
    z_last = safe_float(z.iloc[-1])
    beta_last = safe_float(beta_list[-1])
    if z_last is None:
        return None
    if z_last >= 2.0:
        signal = "A相对贵·空A多B"
    elif z_last <= -2.0:
        signal = "A相对便宜·多A空B"
    elif abs(z_last) <= 0.5:
        signal = "价差回归·可平仓区"
    else:
        signal = "观察"
    return {
        "zscore": round(z_last, 3),
        "beta": round(beta_last or 1.0, 3),
        "a_price": safe_float(df["a"].iloc[-1]),
        "b_price": safe_float(df["b"].iloc[-1]),
        "n_bars": int(len(df)),
        "signal": signal,
    }


def _scan() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for a, b, label in PAIRS:
        sa = _load_close(a)
        sb = _load_close(b)
        if sa is None or sb is None:
            items.append(
                {
                    "pair": label,
                    "a": a,
                    "b": b,
                    "available": False,
                    "reason": "缺本地日线，请先更新 qfq 缓存",
                }
            )
            continue
        st = _pair_stats(sa, sb)
        if st is None:
            items.append({"pair": label, "a": a, "b": b, "available": False, "reason": "样本不足"})
            continue
        items.append({"pair": label, "a": a, "b": b, "available": True, **st})

    actionable = [
        x
        for x in items
        if x.get("available") and abs(x.get("zscore") or 0) >= 2.0
    ]
    items.sort(key=lambda x: -abs(x.get("zscore") or 0) if x.get("available") else -1)

    return {
        "asof": now_iso(),
        "source": "local daily qfq (bs_kit)",
        "summary": {
            "n_pairs": len(items),
            "n_actionable": len(actionable),
        },
        "items": items,
        "notes": [
            "z-score 基于对数价格与滚动 beta 价差；|z|≥2 为统计极值提示。",
            "协整关系会失效；需止损与持有期纪律，不宜重仓。",
            "执行上尽量行业内配对，控制单边 Beta 暴露。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 600) -> Dict[str, Any]:
    return cached_scan("pairs", _scan, refresh=refresh, ttl_sec=ttl_sec)
