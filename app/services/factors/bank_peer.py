"""银行业同行截面标注：在 J66 面板上附加相对排名/超额。

用于捕捉「银行内部分化」——同一行业里强弱差异很大时，
绝对阈值信号不够，需要相对同行的质量与动量。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

# 国有大行（含交行、邮储）
BIG_BANKS = {
    "sh.601398",
    "sh.601939",
    "sh.601288",
    "sh.601988",
    "sh.601328",
    "sh.601658",
}

# 全国性股份行（常见名单）
JOINT_BANKS = {
    "sh.600000",
    "sh.600015",
    "sh.600016",
    "sh.600036",
    "sh.601166",
    "sh.601818",
    "sh.601998",
    "sh.600919",
    "sh.601229",
    "sz.000001",
    "sz.002142",
}


def bank_tier(code: str) -> str:
    c = str(code)
    if c in BIG_BANKS:
        return "big"
    if c in JOINT_BANKS:
        return "joint"
    return "city"


def _pct_rank(s: pd.Series) -> pd.Series:
    """截面百分位 [0,1]；全 NaN 保持 NaN。"""
    if s.notna().sum() < 3:
        return pd.Series(np.nan, index=s.index)
    return s.rank(pct=True, method="average")


def annotate_bank_peer_panel(
    panel: Dict[str, pd.DataFrame],
    *,
    cols: Optional[Sequence[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """给每只银行日线附加同行截面特征。

    新增列（示例）：
      cs_ret_60 / cs_pb_pct / cs_roeAvg / cs_fin_fee_share / …
      x_ret_60 = ret_60 - 同行中位数
      tier / cs_tier_ret_60（分层内排名）
    """
    if not panel:
        return panel

    default_cols = [
        "ret_20",
        "ret_60",
        "pb_pct",
        "pe_pct",
        "pbMRQ",
        "roeAvg",
        "fin_nim_proxy",
        "fin_fee_share",
        "fin_loan_growth",
        "fin_impair_to_op",
        "fin_prov_loan",
        "fin_net_int_yoy",
        "fin_fee_yoy",
        "fin_int_spread",
    ]
    use_cols = [c for c in (cols or default_cols)]

    frames: List[pd.DataFrame] = []
    for code, px in panel.items():
        if px is None or px.empty or "date" not in px.columns:
            continue
        d = px[["date"]].copy()
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d["code"] = str(code)
        d["tier"] = bank_tier(code)
        for c in use_cols:
            if c in px.columns:
                d[c] = pd.to_numeric(px[c], errors="coerce")
            else:
                d[c] = np.nan
        frames.append(d)

    if not frames:
        return panel

    long = pd.concat(frames, ignore_index=True).dropna(subset=["date"])
    long = long.sort_values(["date", "code"]).reset_index(drop=True)

    # 全样本同行排名
    for c in use_cols:
        if c not in long.columns:
            continue
        long[f"cs_{c}"] = long.groupby("date", sort=False)[c].transform(_pct_rank)
        med = long.groupby("date", sort=False)[c].transform("median")
        long[f"x_{c}"] = long[c] - med

    # 分层内动量排名（大行/股份/城商各自比）
    if "ret_60" in long.columns:
        long["cs_tier_ret_60"] = long.groupby(["date", "tier"], sort=False)["ret_60"].transform(_pct_rank)
    if "roeAvg" in long.columns:
        # ROE 可能是百分数，统一到小数再排名更稳；排名对单调变换不敏感，直接用原值
        long["cs_tier_roe"] = long.groupby(["date", "tier"], sort=False)["roeAvg"].transform(_pct_rank)
    if "pb_pct" in long.columns:
        long["cs_tier_pb_pct"] = long.groupby(["date", "tier"], sort=False)["pb_pct"].transform(_pct_rank)

    # 质量综合分：高 ROE + 低减值 + 高中收（缺列则跳过）
    q_parts = []
    if "cs_roeAvg" in long.columns:
        q_parts.append(long["cs_roeAvg"])
    if "cs_fin_impair_to_op" in long.columns:
        q_parts.append(1.0 - long["cs_fin_impair_to_op"])
    if "cs_fin_fee_share" in long.columns:
        q_parts.append(long["cs_fin_fee_share"])
    if q_parts:
        q = pd.concat(q_parts, axis=1).mean(axis=1, skipna=True)
        long["_q_raw"] = q
        long["cs_quality"] = long.groupby("date", sort=False)["_q_raw"].transform(_pct_rank)
        long.drop(columns=["_q_raw"], inplace=True)

    attach_cols = [c for c in long.columns if c.startswith("cs_") or c.startswith("x_") or c == "tier"]
    out: Dict[str, pd.DataFrame] = {}
    for code, px in panel.items():
        sub = long.loc[long["code"] == str(code), ["date"] + attach_cols]
        if sub.empty:
            out[code] = px
            continue
        m = px.copy()
        m["date"] = pd.to_datetime(m["date"], errors="coerce")
        # 去掉旧列避免重复
        drop = [c for c in attach_cols if c in m.columns]
        if drop:
            m = m.drop(columns=drop)
        m = m.merge(sub, on="date", how="left")
        out[code] = m
    return out
