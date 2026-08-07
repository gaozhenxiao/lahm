"""各因子入场信号（基本面闸门 + K 线确认）。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import pandas as pd


def signal_pb_low_ma_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """破净/低 PB 分位 + 收盘重新站上 MA60。"""
    cheap = float(params.get("pb_pct_max") or 0.25)
    df = px.copy()
    df["cross"] = (df["close"] > df["ma60"]) & (df["close"].shift(1) <= df["ma60"].shift(1))
    m = (
        df["pb_pct"].notna()
        & (df["pb_pct"] <= cheap)
        & df["cross"]
        & df["ma60"].notna()
    )
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = out.apply(
        lambda r: f"低PB分位回踩确认站上MA60",
        axis=1,
    )
    return out


def signal_cheap_roe_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低估值 + 高ROE + 短期大跌后收盘站上 MA20。"""
    pe_max = float(params.get("pe_pct_max") or 0.35)
    roe_min = float(params.get("roe_min") or 0.10)
    dd_need = -abs(float(params.get("dd_need") or 0.08))
    df = px.copy()
    if "roeAvg" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    # baostock roeAvg 多为小数或百分数，兼容两种
    roe = df["roeAvg"]
    roe_ok = (roe >= roe_min) | (roe >= roe_min * 100)
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = (
        df["pe_pct"].notna()
        & (df["pe_pct"] <= pe_max)
        & roe_ok
        & (df["dd_20"] <= dd_need)
        & cross
    )
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "低估高ROE急跌后站上MA20"
    return out


def signal_growth_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高增长 + 突破60日高点。"""
    # baostock growth: YOYEquity / YOYAsset / YOYNI / YOYEPSBasic etc.
    gcol = None
    for c in ("YOYNI", "YOYEPSBasic", "YOYEquity", "NIYOY"):
        if c in px.columns:
            gcol = c
            break
    if gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.25)
    g = px[gcol]
    # 可能是百分数
    g_ok = (g >= gmin) | (g >= gmin * 100)
    brk = px["close"] >= px["high_60"].shift(1)
    m = g_ok & brk & px["ma20"].notna() & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"高增长({gcol})突破60日高"
    return out


def signal_ma_trend_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """质量趋势：ROE不差 + 均线多头刚形成（MA20上穿MA60）。"""
    roe_min = float(params.get("roe_min") or 0.08)
    df = px.copy()
    if "roeAvg" in df.columns:
        roe = df["roeAvg"]
        roe_ok = (roe >= roe_min) | (roe >= roe_min * 100) | roe.isna()
    else:
        roe_ok = True
    cross = (df["ma20"] > df["ma60"]) & (df["ma20"].shift(1) <= df["ma60"].shift(1))
    m = cross & roe_ok & (df["close"] > df["ma20"])
    # 估值别太贵
    if "pe_pct" in df.columns:
        m = m & (df["pe_pct"].isna() | (df["pe_pct"] <= float(params.get("pe_pct_max") or 0.80)))
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE质量+均线金叉多头"
    return out


def signal_low_vol_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低波动回踩：60日波动处在自身低分位 + 收盘站上 MA20。"""
    df = px.copy()
    win = int(params.get("vol_pct_window") or 252)
    vol = df["vol_60"]
    vol_pct = vol.rolling(win, min_periods=80).apply(
        lambda x: float((x <= x[-1]).sum() - 1) / max(len(x) - 1, 1), raw=True
    )
    df["vol_pct"] = vol_pct
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = (df["vol_pct"] <= float(params.get("vol_pct_max") or 0.30)) & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "低波动回踩站上MA20"
    return out


def signal_pead_post_earn(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """简易 PEAD：ROE环比改善披露后，次日~5日内若缩量回踩MA20不破则买。

    无精确财报日时，用 roeAvg 的 asof 变化日近似「披露后」。
    """
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    df = px.copy()
    roe_chg = df["roeAvg"].diff()
    # 改善事件
    improve = roe_chg > abs(float(params.get("roe_improve") or 0.005))
    event_idx = df.index[improve].tolist()
    hold_wait = int(params.get("pead_wait") or 5)
    rows = []
    for ei in event_idx:
        for j in range(ei + 1, min(ei + 1 + hold_wait, len(df))):
            if pd.isna(df.loc[j, "ma20"]):
                continue
            # 回踩不破：最低靠近均线且收盘站上
            near = float(df.loc[j, "low"]) <= float(df.loc[j, "ma20"]) * 1.01
            above = float(df.loc[j, "close"]) >= float(df.loc[j, "ma20"])
            if near and above:
                rows.append(
                    {
                        "date": df.loc[j, "date"],
                        "close": df.loc[j, "close"],
                        "note": "ROE改善后回踩MA20确认",
                    }
                )
                break
    return pd.DataFrame(rows)


def signal_industry_rs_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """个股相对强势回踩：60日收益为正且高于自身一年分位中等以上，回踩MA20。

    （完整行业相对强度在 pipeline 里预计算 ind_ret60；此处兼容无行业字段时退化为个股动量）
    """
    df = px.copy()
    mom_ok = df["ret_60"] > float(params.get("mom_min") or 0.05)
    if "ind_ret60" in df.columns and "rs60" in df.columns:
        mom_ok = (df["ind_ret60"] > 0) & (df["rs60"] > 0)
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = mom_ok & cross & (df["dd_20"] <= -abs(float(params.get("dd_need") or 0.03)))
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "行业/个股动量回踩MA20"
    return out


def signal_pe_low_ma_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低PE分位 + 收盘站上 MA60。"""
    cheap = float(params.get("pe_pct_max") or 0.30)
    df = px.copy()
    cross = (df["close"] > df["ma60"]) & (df["close"].shift(1) <= df["ma60"].shift(1))
    m = df["pe_pct"].notna() & (df["pe_pct"] <= cheap) & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "低PE分位站上MA60"
    return out


def signal_double_cheap_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """PE/PB 双低估 + 站上 MA20。"""
    pe_max = float(params.get("pe_pct_max") or 0.35)
    pb_max = float(params.get("pb_pct_max") or 0.35)
    df = px.copy()
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = (
        df["pe_pct"].notna()
        & df["pb_pct"].notna()
        & (df["pe_pct"] <= pe_max)
        & (df["pb_pct"] <= pb_max)
        & cross
    )
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "PE/PB双低估站上MA20"
    return out


def signal_volume_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """放量突破60日高：成交额/均额放大 + 收盘创新高。"""
    df = px.copy()
    if "amount" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    amt_ma = df["amount"].rolling(20).mean()
    surge = df["amount"] >= amt_ma * float(params.get("vol_mult") or 1.8)
    brk = df["close"] >= df["high_60"].shift(1)
    m = surge & brk & df["ma20"].notna() & (df["close"] > df["ma20"])
    # 过滤过热：20日涨幅别太大
    m = m & (df["ret_20"].isna() | (df["ret_20"] <= float(params.get("ret20_max") or 0.25)))
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "放量突破60日高"
    return out


def signal_ma120_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """长线多头（收盘>MA120）下回踩站上 MA20。"""
    df = px.copy()
    if "ma120" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = (df["close"] > df["ma120"]) & (df["ma20"] > df["ma120"]) & cross
    m = m & (df["dd_20"] <= -abs(float(params.get("dd_need") or 0.02)))
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "MA120多头回踩MA20"
    return out


def signal_high_margin_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高净利率 + 正动量回踩 MA20。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    margin_min = float(params.get("margin_min") or 0.12)
    mgn = px["npMargin"]
    mgn_ok = (mgn >= margin_min) | (mgn >= margin_min * 100)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = mgn_ok & (px["ret_60"] > float(params.get("mom_min") or 0.0)) & cross
    m = m & (px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高净利率动量回踩MA20"
    return out


def signal_turnover_dryup_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """换手萎缩后放量站上 MA20（地量后反弹）。"""
    df = px.copy()
    if "turn" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = df["turn"]
    turn_ma = turn.rolling(20).mean()
    dry = turn.shift(1) <= turn_ma.shift(1) * float(params.get("dry_ratio") or 0.55)
    surge = turn >= turn_ma * float(params.get("surge_ratio") or 1.2)
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = dry & surge & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "地量后放量站上MA20"
    return out


def signal_oversold_roe_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """急跌超卖 + ROE 质量闸门 + 站上 MA20。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_min = float(params.get("roe_min") or 0.08)
    roe = px["roeAvg"]
    roe_ok = (roe >= roe_min) | (roe >= roe_min * 100)
    dd_need = -abs(float(params.get("dd_need") or 0.12))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & (px["dd_20"] <= dd_need) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "急跌超卖+ROE质量站上MA20"
    return out


def signal_eps_growth_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS/净利正增长 + 估值不过贵 + 站上 MA60。"""
    gcol = None
    for c in ("YOYEPSBasic", "YOYNI", "epsTTM"):
        if c in px.columns:
            gcol = c
            break
    if gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.10)
    g = px[gcol]
    if gcol == "epsTTM":
        g_ok = g.diff(60) > 0  # 粗近似：EPS上升
    else:
        g_ok = (g >= gmin) | (g >= gmin * 100)
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = g_ok & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.70)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"增长({gcol})+站上MA60"
    return out


def signal_narrow_range_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """波动收敛后向上突破：近20日振幅处在低分位 + 收盘创20日新高。"""
    df = px.copy()
    amp = (df["high"] / df["low"] - 1.0).rolling(20).mean()
    amp_pct = amp.rolling(252, min_periods=80).apply(
        lambda x: float((x <= x[-1]).sum() - 1) / max(len(x) - 1, 1), raw=True
    )
    hi20 = df["high"].rolling(20).max().shift(1)
    m = (amp_pct <= float(params.get("amp_pct_max") or 0.25)) & (df["close"] >= hi20)
    m = m & df["ma20"].notna() & (df["close"] > df["ma20"])
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "窄幅整理后向上突破"
    return out


def signal_consecutive_down_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """连续下跌后收阳站上 MA20。"""
    df = px.copy()
    n = int(params.get("down_days") or 3)
    down = df["close"] < df["close"].shift(1)
    streak = down.astype(int)
    for i in range(1, n):
        streak = streak + down.shift(i).fillna(False).astype(int)
    had_streak = streak.shift(1) >= n
    cross = (df["close"] > df["ma20"]) & (df["close"] > df["open"])
    m = had_streak & cross & df["ma20"].notna()
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = f"连跌{n}日后收阳站上MA20"
    return out


def signal_pb_below_one_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """破净（PB<1）后收盘站上 MA20。"""
    df = px.copy()
    if "pbMRQ" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = df["pbMRQ"].notna() & (df["pbMRQ"] > 0) & (df["pbMRQ"] < float(params.get("pb_max") or 1.0)) & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "破净后站上MA20"
    return out


def signal_turn_surge_ma_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """换手突然放大 + 站上 MA60（资金关注）。"""
    df = px.copy()
    if "turn" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn_ma = df["turn"].rolling(20).mean()
    surge = df["turn"] >= turn_ma * float(params.get("surge_ratio") or 2.0)
    cross = (df["close"] > df["ma60"]) & (df["close"].shift(1) <= df["ma60"].shift(1))
    m = surge & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "换手放大站上MA60"
    return out


def signal_pe_quality_cross(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """估值中等偏低 + ROE 质量 + MA20 上穿 MA60。"""
    if "roeAvg" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_min = float(params.get("roe_min") or 0.10)
    roe = px["roeAvg"]
    roe_ok = (roe >= roe_min) | (roe >= roe_min * 100)
    cross = (px["ma20"] > px["ma60"]) & (px["ma20"].shift(1) <= px["ma60"].shift(1))
    m = roe_ok & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.50)) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低估值质量金叉"
    return out


def signal_ret20_extreme_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """20日跌幅过深后收盘站上 MA20（纯价格超卖）。"""
    df = px.copy()
    thr = -abs(float(params.get("ret20_min") or 0.15))
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = df["ret_20"].notna() & (df["ret_20"] <= thr) & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "20日急跌后站上MA20"
    return out


def signal_amount_shrink_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """成交额先萎缩再放量突破20日高。"""
    df = px.copy()
    if "amount" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    amt_ma = df["amount"].rolling(20).mean()
    shrink = df["amount"].shift(1) <= amt_ma.shift(1) * float(params.get("shrink_ratio") or 0.6)
    surge = df["amount"] >= amt_ma * float(params.get("surge_ratio") or 1.5)
    hi20 = df["high"].rolling(20).max().shift(1)
    m = shrink & surge & (df["close"] >= hi20) & (df["close"] > df["ma20"])
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "缩量后放量突破20日高"
    return out


def signal_boll_lower_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """触及布林下轨后收盘重新站上 MA20。"""
    df = px.copy()
    win = int(params.get("boll_window") or 20)
    mid = df["close"].rolling(win).mean()
    std = df["close"].rolling(win).std()
    lower = mid - float(params.get("boll_k") or 2.0) * std
    touched = df["low"] <= lower
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = touched.rolling(3).max().astype(bool) & cross
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "触及布林下轨后站上MA20"
    return out


def signal_new_high_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """创120日新高后回撤，再站上MA20（强势股回踩）。"""
    df = px.copy()
    hi120 = df["close"].rolling(120).max()
    was_high = (df["close"].shift(1) >= hi120.shift(1) * 0.995).rolling(
        int(params.get("lookback") or 15)
    ).max().astype(bool)
    cross = (df["close"] > df["ma20"]) & (df["close"].shift(1) <= df["ma20"].shift(1))
    m = was_high & cross & (df["dd_20"] <= -abs(float(params.get("dd_need") or 0.04)))
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "新高后回踩站上MA20"
    return out


def signal_dual_ma_volume(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """MA20上穿MA60且当日放量。"""
    df = px.copy()
    cross = (df["ma20"] > df["ma60"]) & (df["ma20"].shift(1) <= df["ma60"].shift(1))
    if "amount" in df.columns:
        amt_ma = df["amount"].rolling(20).mean()
        surge = df["amount"] >= amt_ma * float(params.get("vol_mult") or 1.3)
    else:
        surge = True
    m = cross & surge & (df["close"] > df["ma20"])
    out = df.loc[m, ["date", "close"]].copy()
    out["note"] = "均线金叉且放量"
    return out


def signal_gap_down_recover(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低开缺口后数日内收盘收复缺口价（偏情绪修复）。"""
    df = px.copy()
    gap = df["open"] < df["close"].shift(1) * (1.0 - abs(float(params.get("gap_min") or 0.03)))
    wait = int(params.get("recover_wait") or 5)
    rows = []
    idxs = df.index[gap.fillna(False)].tolist()
    for ei in idxs:
        prev_c = float(df.loc[ei - 1, "close"]) if ei > 0 else float(df.loc[ei, "open"])
        for j in range(ei + 1, min(ei + 1 + wait, len(df))):
            ma20 = df.loc[j, "ma20"]
            if pd.isna(ma20):
                continue
            if float(df.loc[j, "close"]) >= prev_c and float(df.loc[j, "close"]) > float(ma20):
                rows.append(
                    {
                        "date": df.loc[j, "date"],
                        "close": df.loc[j, "close"],
                        "note": "跳空低开后收复缺口",
                    }
                )
                break
    return pd.DataFrame(rows)


def _roe_ok(series: pd.Series, roe_min: float) -> pd.Series:
    return (series >= roe_min) | (series >= roe_min * 100)


def _g_ok(series: pd.Series, gmin: float) -> pd.Series:
    return (series >= gmin) | (series >= gmin * 100)


def _margin_ok(series: pd.Series, mmin: float) -> pd.Series:
    return (series >= mmin) | (series >= mmin * 100)


def signal_graham_deep_value(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """格雷厄姆深价值：PB/PE 历史分位极低，且盈利为正，站上 MA20。"""
    if "pb_pct" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pb_max = float(params.get("pb_pct_max") or 0.15)
    pe_max = float(params.get("pe_pct_max") or 0.25)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    earn_ok = True
    if "netProfit" in px.columns:
        earn_ok = px["netProfit"].isna() | (px["netProfit"] > 0)
    m = (
        px["pb_pct"].notna()
        & px["pe_pct"].notna()
        & (px["pb_pct"] <= pb_max)
        & (px["pe_pct"] <= pe_max)
        & earn_ok
        & cross
    )
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "格雷厄姆深价值站上MA20"
    return out


def signal_buffett_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """巴菲特质量：高ROE+高净利率+估值不过贵，回踩站上MA60。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.15))
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.12))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = roe_ok & mgn_ok & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.65)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "巴菲特质量回踩MA60"
    return out


def signal_lynch_garp(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """林奇GARP：高增长 + 估值合理（PE分位中低），突破站上MA20。"""
    gcol = None
    for c in ("YOYNI", "YOYEPSBasic", "YOYEquity"):
        if c in px.columns:
            gcol = c
            break
    if gcol is None or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.20))
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.55))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    mom = px["ret_60"].isna() | (px["ret_60"] > float(params.get("mom_min") or -0.05))
    m = g_ok & pe_ok & cross & mom
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"林奇GARP({gcol})"
    return out


def signal_fisher_growth_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """费雪成长质量：高增+高净利，突破60日高。"""
    gcol = None
    for c in ("YOYNI", "YOYEPSBasic"):
        if c in px.columns:
            gcol = c
            break
    if gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.25))
    mgn = px["npMargin"] if "npMargin" in px.columns else None
    mgn_ok = _margin_ok(mgn, float(params.get("margin_min") or 0.10)) if mgn is not None else True
    brk = px["close"] >= px["high_60"].shift(1)
    m = g_ok & mgn_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "费雪成长质量突破"
    return out


def signal_templeton_panic(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """邓普顿恐慌买点：估值极低 + 急跌后站上MA20。"""
    if "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pe_max = float(params.get("pe_pct_max") or 0.20)
    dd_need = -abs(float(params.get("dd_need") or 0.15))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = px["pe_pct"].notna() & (px["pe_pct"] <= pe_max) & (px["dd_20"] <= dd_need) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "邓普顿恐慌估值买点"
    return out


def signal_dreman_low_pe(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """德里曼逆向低PE：PE分位底部 + 盈利为正 + 站上MA60。"""
    if "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pe_max = float(params.get("pe_pct_max") or 0.20)
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    earn_ok = True
    if "epsTTM" in px.columns:
        earn_ok = px["epsTTM"].isna() | (px["epsTTM"] > 0)
    m = px["pe_pct"].notna() & (px["pe_pct"] <= pe_max) & earn_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "德里曼低PE逆向"
    return out


def signal_greenblatt_magic(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """格林布拉特魔法公式近似：高ROE + 低PE分位，站上MA20。"""
    if "roeAvg" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.18))
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.35))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & pe_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "魔法公式高ROE低PE"
    return out


def signal_oshaughnessy_value_mom(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """奥肖内西价值动量：低估值 + 中期动量为正 + 站上MA20。"""
    if "pe_pct" not in px.columns or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = (
        (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.40))
        & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.40))
    )
    mom = px["ret_60"] > float(params.get("mom_min") or 0.0)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = cheap & mom & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "价值+动量组合"
    return out


def signal_roe_improve_pb_cheap(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """自研：ROE环比改善 + PB低估 + 站上MA20。"""
    if "roeAvg" not in px.columns or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = pd.to_numeric(px["roeAvg"], errors="coerce")
    improve = roe.diff() > abs(float(params.get("roe_improve") or 0.005))
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.35))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = improve.fillna(False) & cheap & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE改善+低PB"
    return out


def signal_quality_on_sale(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """自研：优质公司打折——高ROE高净利，深回撤后站上MA20。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.10))
    dd_need = -abs(float(params.get("dd_need") or 0.12))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & mgn_ok & (px["dd_20"] <= dd_need) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "优质股打折买回"
    return out


def signal_dual_growth_value(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """自研：成长+价值双闸——同比高增且PB分位偏低，站上MA60。"""
    gcol = None
    for c in ("YOYNI", "YOYEPSBasic"):
        if c in px.columns:
            gcol = c
            break
    if gcol is None or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.15))
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.40))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = g_ok & cheap & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "成长价值双闸"
    return out


def signal_profit_margin_expand(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """自研：净利率扩张 + 估值不贵 + 金叉。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    expand = px["npMargin"].diff() > abs(float(params.get("margin_improve") or 0.005))
    cross = (px["ma20"] > px["ma60"]) & (px["ma20"].shift(1) <= px["ma60"].shift(1))
    m = expand & cross & (px["close"] > px["ma20"])
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.70)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利率扩张金叉"
    return out


def _pick_growth_col(px: pd.DataFrame) -> str | None:
    for c in ("YOYNI", "YOYEPSBasic", "YOYEquity"):
        if c in px.columns:
            return c
    return None


def signal_peg_garp(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """林奇PEG近似：高增长且 PE分位/增长 偏低，站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.20)
    g = px[gcol].astype(float)
    # 统一成小数增长率
    g_dec = g.where(g.abs() <= 5.0, g / 100.0)
    g_ok = _g_ok(g, gmin)
    peg = px["pe_pct"] / g_dec.replace(0, pd.NA)
    peg_max = float(params.get("peg_max") or 1.2)
    peg_ok = peg.notna() & (peg > 0) & (peg <= peg_max)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = g_ok & peg_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"PEG-GARP({gcol})"
    return out


def signal_lynch_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """林奇GARP突破版：高增长+合理PE，突破60日高。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.20))
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.55))
    brk = px["close"] >= px["high_60"].shift(1)
    m = g_ok & pe_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"林奇GARP突破({gcol})"
    return out


def signal_high_roe_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高ROE质量回踩：ROE高 + 估值不过贵，站上MA60。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.15))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = roe_ok & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高ROE回踩MA60"
    return out


def signal_gp_margin_expand(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张：gpMargin环比改善 + 站上MA20。"""
    if "gpMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    expand = px["gpMargin"].diff() > abs(float(params.get("margin_improve") or 0.005))
    level_ok = _margin_ok(px["gpMargin"], float(params.get("margin_min") or 0.20))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = expand & level_ok & cross
    if "pb_pct" in px.columns:
        m = m & (px["pb_pct"].isna() | (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.70)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张站上MA20"
    return out


def signal_twin_yoy_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双同比高增突破：YOYNI与YOYEPS同时强，突破60日高。"""
    if "YOYNI" not in px.columns or "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.15)
    g_ok = _g_ok(px["YOYNI"], gmin) & _g_ok(px["YOYEPSBasic"], gmin)
    lag = int(params.get("funda_lag") or 0)
    if lag > 0:
        hot = _funda_hot_window(_funda_event(px["YOYNI"]) & g_ok, lag)
    else:
        hot = g_ok
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双同比高增突破"
    return out


def signal_earnings_accel_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """盈利加速：YOY环比改善且水平不低，站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = px[gcol].astype(float)
    accel = g.diff() > abs(float(params.get("accel_min") or 0.02))
    level = _g_ok(g, float(params.get("growth_min") or 0.10))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = accel & level & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.65)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = f"盈利加速({gcol})"
    return out


def signal_quality_mom_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """质量动量突破：高ROE + 60日动量为正 + 突破60日高。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    mom = px["ret_60"] > float(params.get("mom_min") or 0.0)
    brk = px["close"] >= px["high_60"].shift(1)
    m = roe_ok & mom & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "质量动量突破"
    return out


def signal_pb_cheap_growth_mom(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低PB成长动量：PB低估 + 增长不差 + 动量为正，站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.35))
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.10))
    mom = px["ret_60"] > float(params.get("mom_min") or 0.0)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = cheap & g_ok & mom & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低PB成长动量"
    return out


def signal_margin_roe_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双质量回踩：高ROE+高净利率，站上MA20（更灵敏的巴菲特变体）。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.10))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & mgn_ok & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.70)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双质量回踩MA20"
    return out


def signal_dreman_growth_filter(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """德里曼+成长过滤：低PE + 增长为正，站上MA60。"""
    gcol = _pick_growth_col(px)
    if "pe_pct" not in px.columns or gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.25))
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.05))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = pe_ok & g_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低PE+正增长"
    return out


def signal_neff_growth_value(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Neff风格：增长/估值比高（YOY相对PE分位），站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = px[gcol].astype(float)
    g_dec = g.where(g.abs() <= 5.0, g / 100.0)
    pe = px["pe_pct"].clip(lower=0.05)
    score = g_dec / pe
    score_ok = score >= float(params.get("score_min") or 0.40)
    g_ok = _g_ok(g, float(params.get("growth_min") or 0.12))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = score_ok & g_ok & cross & pe.notna()
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "Neff增长价值比"
    return out


def signal_high_margin_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高净利率突破：高净利率 + 突破60日高（高净利率回踩的突破兄弟）。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.12))
    mom = px["ret_60"].isna() | (px["ret_60"] > float(params.get("mom_min") or -0.02))
    brk = px["close"] >= px["high_60"].shift(1)
    m = mgn_ok & mom & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高净利率突破60日高"
    return out


def signal_garp_ma60(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """GARP慢确认：高增长+合理PE，站上MA60（比MA20更稳）。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.18))
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.50))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = g_ok & pe_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "GARP站上MA60"
    return out


def signal_roe_expand_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE扩张突破：ROE环比改善且水平不低，突破60日高。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    level = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    lag = int(params.get("funda_lag") or 0)
    if lag > 0:
        improve = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= abs(float(params.get("roe_improve") or 0.003)))
        hot = _funda_hot_window(improve & level, lag)
    else:
        improve = px["roeAvg"].diff() > abs(float(params.get("roe_improve") or 0.003))
        hot = improve & level
    np_ok = True
    if "npMargin" in px.columns and params.get("np_min") is not None:
        np_ok = _to_dec(px["npMargin"]) >= float(params.get("np_min") or 0.0)
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & np_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE扩张突破"
    return out


def signal_pb_below_growth(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """破净成长：PB分位极低 + 增长为正，站上MA20。"""
    gcol = _pick_growth_col(px)
    if "pb_pct" not in px.columns or gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.20))
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.05))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = cheap & g_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "破净成长回踩"
    return out


def signal_quality_low_vol(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """优质低波：高ROE + 波动偏低分位近似（vol_60低），站上MA20。"""
    if "roeAvg" not in px.columns or "vol_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    vol = px["vol_60"]
    vol_ok = vol.notna() & (vol <= vol.rolling(252, min_periods=60).quantile(float(params.get("vol_q") or 0.40)))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & vol_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "优质低波回踩"
    return out


def signal_eps_yoy_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS高增回踩：YOYEPS高增 + 站上MA60。"""
    if "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px["YOYEPSBasic"], float(params.get("growth_min") or 0.20))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = g_ok & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPS高增站上MA60"
    return out


def signal_triple_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """三质量：高ROE+高净利+高增，站上MA20。"""
    gcol = _pick_growth_col(px)
    if "roeAvg" not in px.columns or "npMargin" not in px.columns or gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.08))
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.12))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = roe_ok & mgn_ok & g_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "三质量回踩"
    return out


def signal_value_quality_mom(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """价值质量动量：低PB + 高ROE + 正动量，站上MA20。"""
    if "pb_pct" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.40))
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    mom = px["ret_60"] > float(params.get("mom_min") or 0.0)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = cheap & roe_ok & mom & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "价值质量动量"
    return out


def signal_growth_pullback_ma20(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高增回踩：高增长 + 近端有回撤 + 站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.20))
    dd_need = -abs(float(params.get("dd_need") or 0.04))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = g_ok & (px["dd_20"] <= dd_need) & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高增回踩MA20"
    return out


def signal_cashcow_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """现金牛近似：高净利率 + 低波动动量不差，站上MA60。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.15))
    mom = px["ret_60"].isna() | (px["ret_60"] > float(params.get("mom_min") or -0.08))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = mgn_ok & mom & cross
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.55)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "现金牛回踩MA60"
    return out


def signal_pe_pb_growth_triple(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """三低估+成长：PE/PB双低估 + 正增长，站上MA20。"""
    gcol = _pick_growth_col(px)
    if gcol is None or "pe_pct" not in px.columns or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = (
        (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.35))
        & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.35))
    )
    g_ok = _g_ok(px[gcol], float(params.get("growth_min") or 0.08))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = cheap & g_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双低估+成长"
    return out


# ----- 另类 / 非常规思路 -----


def signal_neglect_reawakening(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """冷门唤醒：换手长期偏低后突然放大，叠加质量闸门，站上MA20。"""
    if "turn" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = px["turn"]
    turn_ma = turn.rolling(60, min_periods=30).mean()
    neglected = turn.rolling(10, min_periods=5).mean() <= turn_ma * float(params.get("neglect_ratio") or 0.55)
    awake = turn >= turn_ma * float(params.get("awake_ratio") or 1.4)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = neglected.shift(1).fillna(False) & awake & cross
    if "roeAvg" in px.columns:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "冷门唤醒放量站上MA20"
    return out


def signal_vol_crush_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """波动压缩反弹：60日波动从高位回落，价格站上MA20。"""
    if "vol_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    vol = px["vol_60"]
    vol_hi = vol.rolling(120, min_periods=40).quantile(float(params.get("vol_hi_q") or 0.70))
    vol_lo = vol.rolling(120, min_periods=40).quantile(float(params.get("vol_lo_q") or 0.45))
    was_high = vol.shift(5) >= vol_hi.shift(5)
    now_cool = vol <= vol_lo
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = was_high.fillna(False) & now_cool.fillna(False) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "波动压缩后站上MA20"
    return out


def signal_capital_light_growth(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """轻资产高增：净利同比高、股东权益同比明显更低（少稀释），突破60日高。"""
    if "YOYNI" not in px.columns or "YOYEquity" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.15))
    # equity 增速显著低于利润增速 → 资本效率更好
    ni = px["YOYNI"].astype(float)
    eq = px["YOYEquity"].astype(float)
    ni_dec = ni.where(ni.abs() <= 5.0, ni / 100.0)
    eq_dec = eq.where(eq.abs() <= 5.0, eq / 100.0)
    gap = float(params.get("equity_gap") or 0.10)
    light = (ni_dec - eq_dec) >= gap
    brk = px["close"] >= px["high_60"].shift(1)
    m = ni_ok & light & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "轻资产高增突破"
    return out


def signal_pricing_power_gap(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """定价权错杀：毛利率高但估值分位不高，站上MA20。"""
    if "gpMargin" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    mgn_ok = _margin_ok(px["gpMargin"], float(params.get("margin_min") or 0.25))
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = mgn_ok & pe_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高毛利低估值回踩"
    return out


def signal_illiquid_quality_bounce(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低流动性质量溢价：换手处在偏低分位 + 高ROE，站上MA60。"""
    if "turn" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = px["turn"]
    tq = turn.rolling(252, min_periods=60).quantile(float(params.get("turn_q") or 0.30))
    thin = turn.notna() & (turn <= tq)
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = thin & roe_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低换手高质量站上MA60"
    return out


def signal_crash_close_strength(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """急跌日内强收：20日大跌后当日收阳且站上MA20（短线另类反转）。"""
    if "open" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    dd_need = -abs(float(params.get("dd_need") or 0.12))
    bullish = px["close"] > px["open"]
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = (px["dd_20"] <= dd_need) & bullish & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "急跌后强势收阳站上MA20"
    return out


def signal_roe_turnaround(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE反转：此前低于阈值，今日上穿阈值，站上MA20。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    thr = float(params.get("roe_min") or 0.08)
    roe = px["roeAvg"].astype(float)
    # 兼容百分数
    roe_dec = roe.where(roe.abs() <= 2.0, roe / 100.0)
    prev = roe_dec.shift(1)
    crossed = (prev < thr) & (roe_dec >= thr)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = crossed.fillna(False) & cross
    if "pb_pct" in px.columns:
        m = m & (px["pb_pct"].isna() | (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.60)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE底部翻越回踩"
    return out


def signal_compounder_quiet_dip(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """安静复利回踩：高净利率 + 低波动 + 温和回撤后站上MA20（防御另类）。"""
    if "npMargin" not in px.columns or "vol_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    mgn_ok = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.12))
    vol = px["vol_60"]
    vol_ok = vol.notna() & (vol <= vol.rolling(252, min_periods=60).quantile(float(params.get("vol_q") or 0.35)))
    dd_ok = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03))
    dd_not_crash = px["dd_20"] >= -abs(float(params.get("dd_max") or 0.15))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = mgn_ok & vol_ok & dd_ok & dd_not_crash & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "安静复利股回踩"
    return out


def signal_decrowd_trend_hold(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """拥挤退潮仍持趋势：换手曾极端偏高，现回落但仍站上MA60。"""
    if "turn" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = px["turn"]
    turn_ma = turn.rolling(20, min_periods=10).mean()
    crowded = turn.shift(3) >= turn_ma.shift(3) * float(params.get("crowd_ratio") or 2.5)
    cooled = turn <= turn_ma * float(params.get("cool_ratio") or 1.2)
    above = px["close"] > px["ma60"]
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    mom = px["ret_60"].isna() | (px["ret_60"] > float(params.get("mom_min") or 0.0))
    m = crowded.fillna(False) & cooled.fillna(False) & above & cross & mom
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "拥挤退潮后趋势回踩"
    return out


def signal_month_end_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """月末效应×质量：临近换月的交易日 + 高ROE，站上MA20（另类日历）。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    dt = pd.to_datetime(px["date"])
    n = int(params.get("month_end_days") or 4)
    next_month = dt.shift(-1).dt.month
    last_day = dt.dt.month != next_month
    near_end = last_day.copy()
    for k in range(1, n):
        near_end = near_end | last_day.shift(-k).fillna(False)
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = near_end.fillna(False) & roe_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "月末质量回踩"
    return out


def signal_gap_down_intraday_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """跳空低开当日收复：低开后收盘回到昨收之上，且质量不差。"""
    if "open" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    prev = px["close"].shift(1)
    gap = (px["open"] / prev - 1.0) <= -abs(float(params.get("gap_min") or 0.02))
    reclaim = px["close"] >= prev
    m = gap.fillna(False) & reclaim.fillna(False) & px["ma20"].notna() & (px["close"] > px["ma20"])
    if "roeAvg" in px.columns:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "跳空低开当日收复"
    return out


def signal_rs_momentum_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """相对强势回踩（个股动量另类）：60日收益处在自身高分位后回踩MA20。"""
    if "ret_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    # 复用 industry 信号逻辑并加强「自身分位」
    r = px["ret_60"]
    rq = r.rolling(252, min_periods=60).quantile(float(params.get("rs_q") or 0.70))
    strong = r.notna() & (r >= rq) & (r > float(params.get("mom_min") or 0.05))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    dd = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03))
    m = strong & cross & dd
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "自身强势分位回踩"
    return out


# ----- 第五波：另类 / 微观结构 / 日历 / 体制 -----


def signal_nr7_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """NR7突破：近7日最窄振幅日后向上突破昨高。"""
    if "high" not in px.columns or "low" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rng = (px["high"] - px["low"]).astype(float)
    n = int(params.get("nr_window") or 7)
    nr = rng <= rng.rolling(n, min_periods=n).min()
    brk = px["close"] > px["high"].shift(1)
    m = nr.shift(1).fillna(False) & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "NR7后向上突破"
    return out


def signal_two_bar_reversal_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """两日反转质量：昨日阴线、今日收复昨高，叠加ROE闸门。"""
    if "open" not in px.columns or "high" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    prev_down = px["close"].shift(1) < px["open"].shift(1)
    today_up = px["close"] > px["open"]
    reclaim = px["close"] > px["high"].shift(1)
    m = prev_down.fillna(False) & today_up & reclaim
    if "roeAvg" in px.columns:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "质量两日反转收复昨高"
    return out


def signal_ma60_slope_turn(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """慢均线拐头：MA60斜率由负转正，价格站上MA60。"""
    if "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    lag = int(params.get("slope_lag") or 5)
    slope = px["ma60"] - px["ma60"].shift(lag)
    turn = (slope > 0) & (slope.shift(1) <= 0)
    m = turn.fillna(False) & (px["close"] > px["ma60"]) & (px["close"] > px["ma20"])
    if "roeAvg" in px.columns:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.06)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "MA60拐头向上"
    return out


def signal_amount_dryup_thrust(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """缩量后放量推力：成交额先干涸再突然放大并突破60日高。"""
    if "amount" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    amt = px["amount"].astype(float)
    ma = amt.rolling(20, min_periods=10).mean()
    dry = amt.rolling(5, min_periods=3).mean() <= ma * float(params.get("dry_ratio") or 0.65)
    thrust = amt >= ma * float(params.get("thrust_ratio") or 1.6)
    brk = px["close"] >= px["high_60"].shift(1)
    m = dry.shift(1).fillna(False) & thrust & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "缩量后放量突破"
    return out


def signal_friday_quality_dip(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """周五质量错杀：周五收阴且轻度回撤，高质量标的（周末效应）。"""
    if "open" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    dt = pd.to_datetime(px["date"])
    is_fri = dt.dt.weekday == 4
    weak = px["close"] < px["open"]
    dd = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.02))
    dd_cap = px["dd_20"] >= -abs(float(params.get("dd_max") or 0.12))
    m = is_fri & weak & dd & dd_cap
    if "roeAvg" in px.columns:
        m = m & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "周五质量错杀"
    return out


def signal_intraday_recovery(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """日内强修复：低开或近端弱势后收在振幅上沿，站上MA20。"""
    if "open" not in px.columns or "low" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rng = (px["high"] - px["low"]).replace(0, pd.NA)
    upper = (px["close"] - px["low"]) / rng >= float(params.get("upper_ratio") or 0.75)
    gap_or_weak = (px["open"] < px["close"].shift(1)) | (px["dd_20"] <= -abs(float(params.get("dd_need") or 0.04)))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = upper.fillna(False) & gap_or_weak.fillna(False) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "日内强修复站上MA20"
    return out


def signal_vol_expansion_trend(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """波动扩张趋势：低波体制后波动抬升，价格突破并站上MA60。"""
    if "vol_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    vol = px["vol_60"]
    vol_lo = vol.rolling(120, min_periods=40).quantile(float(params.get("vol_lo_q") or 0.35))
    vol_hi = vol.rolling(120, min_periods=40).quantile(float(params.get("vol_hi_q") or 0.55))
    was_quiet = vol.shift(5) <= vol_lo.shift(5)
    now_expand = vol >= vol_hi
    brk = px["close"] >= px["high_60"].shift(1)
    m = was_quiet.fillna(False) & now_expand.fillna(False) & brk & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低波转扩张突破"
    return out


def signal_turn_climax_cool(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """换手高潮冷却：数日前换手极端放大后回落，价格站上MA20。"""
    if "turn" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = px["turn"].astype(float)
    ma = turn.rolling(20, min_periods=10).mean()
    lag = int(params.get("climax_lag") or 3)
    climax = turn.shift(lag) >= ma.shift(lag) * float(params.get("climax_ratio") or 2.2)
    cool = turn <= ma * float(params.get("cool_ratio") or 1.1)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = climax.fillna(False) & cool.fillna(False) & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "换手高潮冷却回踩"
    return out


def signal_quiet_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """安静新高：突破60日高但20日涨幅不极端、换手不拥挤。"""
    if "turn" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    brk = px["close"] >= px["high_60"].shift(1)
    ret_ok = px["ret_20"].notna() & (px["ret_20"] >= 0) & (
        px["ret_20"] <= float(params.get("ret20_max") or 0.10)
    )
    turn = px["turn"].astype(float)
    tq = turn.rolling(60, min_periods=20).quantile(float(params.get("turn_q") or 0.60))
    quiet = turn.notna() & (turn <= tq)
    m = brk & ret_ok & quiet & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "安静新高突破"
    return out


def signal_gap_down_fill(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低开回补：明显低开后收盘回补缺口（收≥昨收）。"""
    if "open" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gap = float(params.get("gap_min") or 0.02)
    gap_down = px["open"] <= px["close"].shift(1) * (1.0 - gap)
    fill = px["close"] >= px["close"].shift(1)
    bullish = px["close"] > px["open"]
    m = gap_down.fillna(False) & fill & bullish
    if "roeAvg" in px.columns:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低开回补昨收"
    return out


def signal_stable_growth_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """稳健高增回踩：净利同比高且自身波动低，站上MA20。"""
    if "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = px["YOYNI"].astype(float)
    g_dec = g.where(g.abs() <= 5.0, g / 100.0)
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.12))
    stab = g_dec.rolling(8, min_periods=4).std() <= float(params.get("growth_std_max") or 0.25)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    pe_ok = True
    if "pe_pct" in px.columns:
        pe_ok = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.65))
    m = g_ok & stab.fillna(False) & cross & pe_ok
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "稳健高增回踩"
    return out


def signal_inside_day_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """内包日突破：昨日K线被内包后，今日收盘突破昨高。"""
    if "high" not in px.columns or "low" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    inside = (px["high"].shift(1) < px["high"].shift(2)) & (px["low"].shift(1) > px["low"].shift(2))
    brk = px["close"] > px["high"].shift(1)
    m = inside.fillna(False) & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "内包日后向上突破"
    return out


def _to_dec(s: pd.Series) -> pd.Series:
    x = s.astype(float)
    return x.where(x.abs() <= 5.0, x / 100.0)


def _funda_confirm(px: pd.DataFrame) -> pd.Series:
    """基本面因子只用轻量确认：站上 MA20（避免纯下跌中接刀）。"""
    return px["ma20"].notna() & (px["close"] > px["ma20"])


def _funda_event(series: pd.Series) -> pd.Series:
    """财报字段变更日（merge_asof 后值跳变）。"""
    return series.notna() & series.ne(series.shift(1))


def _mkv_yuan(px: pd.DataFrame) -> pd.Series:
    """总市值（元）≈ close × totalShare；缺股本则全 NaN。"""
    if "totalShare" not in px.columns or "close" not in px.columns:
        return pd.Series(float("nan"), index=px.index, dtype=float)
    sh = pd.to_numeric(px["totalShare"], errors="coerce")
    cl = pd.to_numeric(px["close"], errors="coerce")
    return cl * sh


def _tier_by_mkv(mkv: pd.Series, spec: Dict[str, Any], default: float) -> pd.Series:
    """按市值分档赋值。

    spec 例::
        {"edges": [5e10, 2e11], "values": [80, 60, 40]}
        # mkv < 5e10 → 80；[5e10, 2e11) → 60；≥ 2e11 → 40
    edges 升序，len(values) == len(edges) + 1。
    mkv 缺失时用 default。
    """
    edges = [float(x) for x in (spec.get("edges") or [])]
    values = [float(x) for x in (spec.get("values") or [])]
    if not edges or len(values) != len(edges) + 1:
        return pd.Series(float(default), index=mkv.index, dtype=float)
    out = pd.Series(float(values[-1]), index=mkv.index, dtype=float)
    # 从低到高覆盖
    out[:] = float(values[0])
    for i, e in enumerate(edges):
        out = out.where(~(mkv >= e), float(values[i + 1]))
    out = out.where(mkv.notna(), float(default))
    return out


def _param_scalar_or_mkv(
    px: pd.DataFrame,
    params: Dict[str, Any],
    key: str,
    default: float,
) -> tuple[float | None, pd.Series | None]:
    """常数参数 或 `{key}_by_mkv` 分档序列。

    返回 (scalar_or_None, series_or_None)；二者恰一非空。
    """
    by = params.get(f"{key}_by_mkv")
    if isinstance(by, dict) and by.get("edges") is not None and by.get("values") is not None:
        mkv = _mkv_yuan(px)
        return None, _tier_by_mkv(mkv, by, float(default))
    raw = params.get(key)
    if raw is None:
        return float(default), None
    return float(raw), None


# ----- 第六波：财务基本面为主（非纯量价） -----


def signal_dual_margin_expand(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双利率扩张：毛利率与净利率同时环比改善。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    improve = float(params.get("margin_improve") or 0.005)
    gp_up = (gp - gp.shift(1)) > improve
    np_up = (np_ - np_.shift(1)) > improve
    level = _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.08))
    evt = _funda_event(px["npMargin"]) | _funda_event(px["gpMargin"])
    m = evt & gp_up.fillna(False) & np_up.fillna(False) & level & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利净利双扩张"
    return out


def signal_roe_pb_misprice(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高ROE低估值错配：ROE高且PB分位低。"""
    if "roeAvg" not in px.columns or "pb_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.30))
    evt = _funda_event(px["roeAvg"]) | _funda_event(px["pbMRQ"] if "pbMRQ" in px.columns else px["roeAvg"])
    m = roe_ok & cheap & evt & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高ROE低PB错配"
    return out


def signal_parent_profit_lead(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """归母领先：归属母公司净利同比显著高于整体净利同比（主业更强）。"""
    if "YOYPNI" not in px.columns or "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pni = _to_dec(px["YOYPNI"])
    ni = _to_dec(px["YOYNI"])
    gap = float(params.get("parent_gap") or 0.03)
    lead = (pni - ni) >= gap
    g_ok = _g_ok(px["YOYPNI"], float(params.get("growth_min") or 0.10))
    evt = _funda_event(px["YOYPNI"])
    funda = evt & lead.fillna(False) & g_ok
    lag = int(params.get("funda_lag") or 0)
    hot = _funda_hot_window(funda, lag) if lag > 0 else funda
    pe_ok = True
    if "pe_pct" in px.columns:
        pe_ok = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.70))
    use_brk = params.get("break_days") is not None or params.get("use_break")
    if use_brk:
        brk_win = int(params.get("break_days") or 60)
        if brk_win == 60 and "high_60" in px.columns:
            brk = px["close"] >= px["high_60"].shift(1)
        else:
            hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
            brk = px["close"] >= hi.shift(1)
        m = hot & pe_ok & brk & (px["close"] > px["ma20"])
    else:
        m = hot & pe_ok & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "归母净利同比领先"
    return out


def signal_eps_ni_sync_growth(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """利润EPS共振：YOYNI 与 YOYEPS 同时高增。"""
    if "YOYNI" not in px.columns or "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.15)
    m = (
        _funda_event(px["YOYNI"])
        & _g_ok(px["YOYNI"], gmin)
        & _g_ok(px["YOYEPSBasic"], gmin)
        & _funda_confirm(px)
    )
    if "pe_pct" in px.columns:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.65)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利与EPS同比共振"
    return out


def signal_asset_light_efficiency(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """资产扩张克制：净利高增但总资产同比显著更低。"""
    if "YOYNI" not in px.columns or "YOYAsset" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni = _to_dec(px["YOYNI"])
    asset = _to_dec(px["YOYAsset"])
    gap = float(params.get("asset_gap") or 0.12)
    light = (ni - asset) >= gap
    funda = (
        _funda_event(px["YOYNI"])
        & _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.12))
        & light.fillna(False)
    )
    lag = int(params.get("funda_lag") or 0)
    hot = _funda_hot_window(funda, lag) if lag > 0 else funda
    use_brk = params.get("break_days") is not None or params.get("use_break")
    if use_brk:
        brk_win = int(params.get("break_days") or 60)
        if brk_win == 60 and "high_60" in px.columns:
            brk = px["close"] >= px["high_60"].shift(1)
        else:
            hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
            brk = px["close"] >= hi.shift(1)
        m = hot & brk & (px["close"] > px["ma20"])
    else:
        m = hot & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "资产克制下的净利高增"
    return out


def signal_share_shrink_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """股本收缩质量：总股本环比下降（回购/缩股）且 ROE 不差。"""
    if "totalShare" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    sh = px["totalShare"].astype(float)
    shrink = (sh < sh.shift(1) * (1.0 - float(params.get("shrink_min") or 0.002))) & sh.shift(1).notna()
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    evt = _funda_event(px["totalShare"])
    funda = evt & shrink.fillna(False) & roe_ok
    lag = int(params.get("funda_lag") or 0)
    hot = _funda_hot_window(funda, lag) if lag > 0 else funda
    use_brk = params.get("break_days") is not None or params.get("use_break")
    if use_brk:
        brk_win = int(params.get("break_days") or 60)
        if brk_win == 60 and "high_60" in px.columns:
            brk = px["close"] >= px["high_60"].shift(1)
        else:
            hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
            brk = px["close"] >= hi.shift(1)
        m = hot & brk & (px["close"] > px["ma20"])
    else:
        m = hot & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "股本收缩+质量"
    return out


def signal_revenue_up_roe(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收上台阶：主营收入环比明显上升，且 ROE 达标。"""
    if "MBRevenue" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rev = px["MBRevenue"].astype(float)
    grow = (rev / rev.shift(1) - 1.0) >= float(params.get("rev_qoq_min") or 0.08)
    # 避开基数过小/季节噪声：要求收入为正
    pos = rev > 0
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    evt = _funda_event(px["MBRevenue"])
    m = evt & grow.fillna(False) & pos & roe_ok & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "营收上台阶+ROE"
    return out


def signal_np_margin_regime(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利率体制切换：净利率上穿近8期中位数，且水平不低。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    np_ = _to_dec(px["npMargin"])
    med = np_.rolling(8, min_periods=4).median()
    cross = (np_ > med) & (np_.shift(1) <= med.shift(1))
    level = np_ >= float(params.get("margin_min") or 0.08)
    evt = _funda_event(px["npMargin"])
    funda = evt & cross.fillna(False) & level.fillna(False)
    lag = int(params.get("funda_lag") or 0)
    hot = _funda_hot_window(funda, lag) if lag > 0 else funda
    use_brk = params.get("break_days") is not None or params.get("use_break")
    if use_brk:
        brk_win = int(params.get("break_days") or 60)
        if brk_win == 60 and "high_60" in px.columns:
            brk = px["close"] >= px["high_60"].shift(1)
        else:
            hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
            brk = px["close"] >= hi.shift(1)
        m = hot & brk & (px["close"] > px["ma20"])
    else:
        m = hot & _funda_confirm(px)
    if "pe_pct" in px.columns and params.get("pe_pct_max") is not None:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 1.0)))
    elif "pe_pct" in px.columns and not use_brk:
        m = m & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.70)))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利率上穿历史中枢"
    return out


def signal_roe_persist_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE持续高位：近几期 ROE 持续达标（用向前填充后的滚动最低值近似）。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    thr = float(params.get("roe_min") or 0.10)
    # 公告日稀疏：在变更日检查「当前值高，且上一披露值也高」
    prev = roe.shift(1)
    persist = (roe >= thr) & (prev >= thr)
    evt = _funda_event(px["roeAvg"])
    cheap = True
    if "pe_pct" in px.columns:
        cheap = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60))
    m = evt & persist.fillna(False) & cheap & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE持续高位"
    return out


def signal_growth_not_expensive(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """成长不贵：高增 + PE分位受限 + 权益增速不过热。"""
    if "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.18))
    if "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    eq_ok = True
    if "YOYEquity" in px.columns:
        eq = _to_dec(px["YOYEquity"])
        eq_ok = eq.isna() | (eq <= float(params.get("equity_max") or 0.25))
    evt = _funda_event(px["YOYNI"])
    m = evt & g_ok & pe_ok & eq_ok & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高增且估值克制"
    return out


def signal_eps_reaccel(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS增速再加速：YOYEPS 从低位回升并转正改善。"""
    if "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = _to_dec(px["YOYEPSBasic"])
    improve = (g - g.shift(1)) >= float(params.get("accel_min") or 0.05)
    was_soft = g.shift(1) <= float(params.get("soft_max") or 0.05)
    now_ok = g >= float(params.get("growth_min") or 0.08)
    evt = _funda_event(px["YOYEPSBasic"])
    m = evt & improve.fillna(False) & was_soft.fillna(False) & now_ok.fillna(False) & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPS增速再加速"
    return out


def signal_gross_net_catchup(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛净利差收敛：高毛利下净利率环比上升（费用/经营杠杆改善）。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    high_gp = gp >= float(params.get("gp_min") or 0.25)
    np_up = (np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.008)
    gap = (gp - np_) >= float(params.get("gap_min") or 0.05)
    evt = _funda_event(px["npMargin"])
    m = evt & high_gp.fillna(False) & np_up.fillna(False) & gap.fillna(False) & _funda_confirm(px)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高毛利下净利率追赶"
    return out


def signal_contract_liab_expand(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债扩张：合同负债/预收款同比或环比明显上升（需求领先指标）。"""
    if "contract_liab" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    # 环比：相对上一披露值
    qoq_min = float(params.get("qoq_min") or 0.08)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + qoq_min))

    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        # 东财 YOY 多为百分数（如 44.6=44.6%）
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.15)

    m = evt & (qoq.fillna(False) | yoy_ok.fillna(False)) & cl.notna() & (cl > 0) & _funda_confirm(px)
    if "roeAvg" in px.columns and params.get("roe_min") is not None:
        m = m & (_roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)) | px["roeAvg"].isna())
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债/预收款扩张"
    return out


def signal_base_funda_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """长期横盘 + 财务好转后向上突破。

    技术面：近 N 日振幅收窄（箱体/横盘）；
    基本面：ROE / 净利率 / 净利同比 出现改善，并在随后若干日内仍有效；
    触发：收盘突破横盘上沿。
    """
    if "high" not in px.columns or "low" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    win = int(params.get("base_window") or 60)
    amp_max = float(params.get("amp_max") or 0.22)
    funda_lag = int(params.get("funda_lag") or 20)

    hi = px["high"].rolling(win, min_periods=max(20, win // 2)).max()
    lo = px["low"].rolling(win, min_periods=max(20, win // 2)).min()
    mid = (hi + lo) / 2.0
    amp = (hi - lo) / mid.replace(0, pd.NA)
    # 价格仍在箱体内（未深跌破下沿）
    in_box = px["close"] >= (lo * float(params.get("box_floor") or 0.97))
    base = amp.notna() & (amp <= amp_max) & in_box

    improve = pd.Series(False, index=px.index)
    if "roeAvg" in px.columns:
        roe = _to_dec(px["roeAvg"])
        improve = improve | (
            _funda_event(px["roeAvg"])
            & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.003))
        )
    if "npMargin" in px.columns:
        np_ = _to_dec(px["npMargin"])
        improve = improve | (
            _funda_event(px["npMargin"])
            & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
        )
    if "YOYNI" in px.columns:
        g = _to_dec(px["YOYNI"])
        improve = improve | (
            _funda_event(px["YOYNI"])
            & ((g - g.shift(1)) >= float(params.get("growth_accel") or 0.05))
            & (g >= float(params.get("growth_min") or 0.05))
        )

    funda_hot = improve.fillna(False)
    for i in range(1, funda_lag + 1):
        funda_hot = funda_hot | improve.shift(i).fillna(False)

    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & funda_hot & brk.fillna(False)
    if "ma20" in px.columns:
        m = m & px["ma20"].notna() & (px["close"] > px["ma20"])

    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "长期横盘+财务好转突破"
    return out


def signal_base_funda_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """长期横盘中财务好转后的回踩确认（更早介入，不等突破）。"""
    if "high" not in px.columns or "low" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    win = int(params.get("base_window") or 60)
    amp_max = float(params.get("amp_max") or 0.22)
    funda_lag = int(params.get("funda_lag") or 25)

    hi = px["high"].rolling(win, min_periods=max(20, win // 2)).max()
    lo = px["low"].rolling(win, min_periods=max(20, win // 2)).min()
    mid = (hi + lo) / 2.0
    amp = (hi - lo) / mid.replace(0, pd.NA)
    base = amp.notna() & (amp <= amp_max) & (px["close"] >= lo * 0.97) & (px["close"] <= hi * 1.01)

    improve = pd.Series(False, index=px.index)
    if "roeAvg" in px.columns:
        roe = _to_dec(px["roeAvg"])
        improve = improve | (
            _funda_event(px["roeAvg"])
            & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.003))
        )
    if "npMargin" in px.columns:
        np_ = _to_dec(px["npMargin"])
        improve = improve | (
            _funda_event(px["npMargin"])
            & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
        )
    if "YOYNI" in px.columns:
        g = _to_dec(px["YOYNI"])
        improve = improve | (
            _funda_event(px["YOYNI"])
            & ((g - g.shift(1)) >= float(params.get("growth_accel") or 0.05))
            & (g >= float(params.get("growth_min") or 0.05))
        )

    funda_hot = improve.fillna(False)
    for i in range(1, funda_lag + 1):
        funda_hot = funda_hot | improve.shift(i).fillna(False)

    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = base.fillna(False) & funda_hot & cross.fillna(False)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "横盘中财务好转回踩确认"
    return out


def _amp_base(px: pd.DataFrame, win: int, amp_max: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    hi = px["high"].rolling(win, min_periods=max(20, win // 2)).max()
    lo = px["low"].rolling(win, min_periods=max(20, win // 2)).min()
    mid = (hi + lo) / 2.0
    amp = (hi - lo) / mid.replace(0, pd.NA)
    base = amp.notna() & (amp <= amp_max)
    return hi, lo, base


def _funda_hot_window(improve: pd.Series, lag: int) -> pd.Series:
    hot = improve.fillna(False)
    for i in range(1, int(lag) + 1):
        hot = hot | improve.shift(i).fillna(False)
    return hot


def _any_funda_improve(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    improve = pd.Series(False, index=px.index)
    if "roeAvg" in px.columns:
        roe = _to_dec(px["roeAvg"])
        improve = improve | (
            _funda_event(px["roeAvg"])
            & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.003))
        )
    if "npMargin" in px.columns:
        np_ = _to_dec(px["npMargin"])
        improve = improve | (
            _funda_event(px["npMargin"])
            & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
        )
    if "YOYNI" in px.columns:
        g = _to_dec(px["YOYNI"])
        improve = improve | (
            _funda_event(px["YOYNI"])
            & ((g - g.shift(1)) >= float(params.get("growth_accel") or 0.05))
            & (g >= float(params.get("growth_min") or 0.05))
        )
    if "gpMargin" in px.columns:
        gp = _to_dec(px["gpMargin"])
        improve = improve | (
            _funda_event(px["gpMargin"])
            & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or 0.005))
        )
    if "contract_liab" in px.columns:
        cl = pd.to_numeric(px["contract_liab"], errors="coerce")
        evt = _funda_event(cl)
        qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
        yoy_ok = pd.Series(False, index=px.index)
        if "contract_liab_yoy" in px.columns:
            yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
            yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
            yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.15)
        improve = improve | (qoq.fillna(False) | yoy_ok.fillna(False))
    return improve


# ----- 通宵波次：基本面 × 技术面结合 -----


def signal_long_base_roe_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """更长横盘(120) + ROE改善后突破。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    win = int(params.get("base_window") or 120)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.28))
    roe = _to_dec(px["roeAvg"])
    improve = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.004))
    hot = _funda_hot_window(improve, int(params.get("funda_lag") or 25))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"]) & (px["close"] >= lo * 0.97)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "长横盘ROE改善突破"
    return out


def signal_cheap_quality_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低估高质量横盘突破：低PB分位 + 高ROE + 横盘后突破。"""
    if "pb_pct" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.22))
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.35))
    quality = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & cheap & quality & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低估高质量横盘突破"
    return out


def signal_growth_trend_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高增趋势回踩：净利高增 + MA60向上 + 回踩站上MA20。"""
    if "YOYNI" not in px.columns or "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.15))
    slope = px["ma60"] - px["ma60"].shift(int(params.get("slope_lag") or 5))
    up = slope > 0
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    dd = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03))
    pe_ok = True
    if "pe_pct" in px.columns:
        pe_ok = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60))
    m = g_ok & up.fillna(False) & cross & dd & pe_ok
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "高增趋势回踩"
    return out


def signal_margin_expand_ma60(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """利润率扩张慢确认：净利率改善后站上MA60。"""
    if "npMargin" not in px.columns or "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    np_ = _to_dec(px["npMargin"])
    improve = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
    hot = _funda_hot_window(improve, int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = hot & cross & _margin_ok(px["npMargin"], float(params.get("margin_min") or 0.06))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利率扩张站上MA60"
    return out


def signal_eps_accel_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS加速突破：EPS同比再加速后突破60日高。"""
    if "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = _to_dec(px["YOYEPSBasic"])
    improve = _funda_event(px["YOYEPSBasic"]) & ((g - g.shift(1)) >= float(params.get("accel_min") or 0.05))
    now_ok = g >= float(params.get("growth_min") or 0.08)
    hot = _funda_hot_window(improve & now_ok, int(params.get("funda_lag") or 20))
    brk = px["close"] >= px["high_60"].shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPS加速后突破"
    return out


def signal_pead_base_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """财报改善后的横盘回踩：财务事件后仍在箱体内，站上MA20。"""
    win = int(params.get("base_window") or 40)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.25))
    improve = _any_funda_improve(px, params)
    # 事件后延后几天再买，避免公告脉冲
    delay = int(params.get("pead_delay") or 3)
    delayed = improve.shift(delay).fillna(False)
    hot = _funda_hot_window(delayed, int(params.get("funda_lag") or 20))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = base.fillna(False) & hot & cross & (px["close"] >= lo * 0.97)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "财报改善后横盘回踩"
    return out


def signal_asset_light_trend(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """轻资产高增趋势：净利高增且资产增速低，MA20上穿MA60。"""
    if "YOYNI" not in px.columns or "YOYAsset" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni = _to_dec(px["YOYNI"])
    asset = _to_dec(px["YOYAsset"])
    light = (ni - asset) >= float(params.get("asset_gap") or 0.10)
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.12))
    cross = (px["ma20"] > px["ma60"]) & (px["ma20"].shift(1) <= px["ma60"].shift(1))
    m = g_ok & light.fillna(False) & cross & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "轻资产高增均线金叉"
    return out


def signal_contract_liab_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债扩张 + 横盘突破。"""
    if "contract_liab" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.12)
    hot = _funda_hot_window(qoq.fillna(False) | yoy_ok.fillna(False), int(params.get("funda_lag") or 25))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债扩张横盘突破"
    return out


def signal_dual_improve_breakout(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善突破：ROE与净利率同时环比改善后突破60日高。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    lag = int(params.get("funda_lag") or 5)
    hot = _funda_hot_window(roe_up, lag) & _funda_hot_window(np_up, lag)
    np_ok = np_ >= float(params.get("np_min") or 0.0)
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)) if params.get("roe_min") is not None else True
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & np_ok & roe_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE净利率双改善突破"
    return out


def signal_dual_improve_meanrev(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善均值回归：财务闸门同 breakout，技术面取相反方向。

    财务（不变）：ROE/净利率环比改善热窗 + 可选门槛。
    技术（反向突破）：
      - 明确非 N 日新高，且相对 N 日高回撤 ≥ pullback_min；
      - 近 20 日回撤足够（dd_20 ≤ -dd_need）或近期曾低于慢均线（弱势）；
      - 上穿 MA20 企稳反转（不做突破确认）。
    """
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    lag = int(params.get("funda_lag") or 5)
    hot = _funda_hot_window(roe_up, lag) & _funda_hot_window(np_up, lag)
    np_ok = np_ >= float(params.get("np_min") or 0.0)
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)) if params.get("roe_min") is not None else True

    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        hi_ref = px["high_60"].shift(1)
    else:
        hi_ref = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max().shift(1)
    pullback_min = float(params.get("pullback_min") or 0.06)
    deep_pull = hi_ref.notna() & (px["close"] <= hi_ref * (1.0 - pullback_min))
    not_brk = hi_ref.notna() & (px["close"] < hi_ref)

    dd_need = -abs(float(params.get("dd_need") or 0.04))
    dd_ok = px["dd_20"] <= dd_need if "dd_20" in px.columns else pd.Series(True, index=px.index)

    ma_weak = px["ma60"] if "ma60" in px.columns else px["ma20"]
    was_weak = (
        (px["close"] < ma_weak)
        | (px["close"].shift(1) < ma_weak.shift(1))
        | (px["close"].shift(2) < ma_weak.shift(2))
        | (px["close"].shift(3) < ma_weak.shift(3))
    )
    weak_ok = dd_ok.fillna(False) | was_weak.fillna(False)

    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & np_ok & roe_ok & not_brk & deep_pull & weak_ok & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善弱势回撤企稳"
    return out


def signal_value_repair_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """价值修复：低估 + 盈利转正/改善 + 站上MA60。"""
    if "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.30))
    improve = _any_funda_improve(px, params)
    hot = _funda_hot_window(improve, int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = cheap & hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低估价值修复站上MA60"
    return out


def signal_quality_coil_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """优质收缩突破：高ROE + 波动偏低 + 突破60日高。"""
    if "roeAvg" not in px.columns or "vol_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    vol = px["vol_60"]
    vol_ok = vol.notna() & (vol <= vol.rolling(120, min_periods=40).quantile(float(params.get("vol_q") or 0.40)))
    brk = px["close"] >= px["high_60"].shift(1)
    m = roe_ok & vol_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "优质低波收缩突破"
    return out


def signal_parent_lead_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """归母领先回踩：YOYPNI领先YOYNI，站上MA20。"""
    if "YOYPNI" not in px.columns or "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pni = _to_dec(px["YOYPNI"])
    ni = _to_dec(px["YOYNI"])
    lead = (pni - ni) >= float(params.get("parent_gap") or 0.03)
    g_ok = _g_ok(px["YOYPNI"], float(params.get("growth_min") or 0.10))
    evt = _funda_event(px["YOYPNI"])
    hot = _funda_hot_window(evt & lead & g_ok, int(params.get("funda_lag") or 20))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "归母领先后回踩"
    return out


def signal_gross_expand_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张突破：毛利率环比改善后突破 N 日高。

    支持按市值分档参数（函数型/分档型）：
    - ``margin_min_by_mkv`` / ``break_days_by_mkv``:
      ``{"edges": [5e10, 2e11], "values": [v_lo, v_mid, v_hi]}``
    - 市值 mkv = close × totalShare（元）；未给 ``*_by_mkv`` 时退化为常数 params。
    """
    if "gpMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    imp = float(params.get("margin_improve") or 0.005)
    improve = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= imp)
    if params.get("gp_consec"):
        prev_up = ((gp.shift(1) - gp.shift(2)) >= imp).fillna(False)
        improve = improve & prev_up
    mmin_s, mmin_ser = _param_scalar_or_mkv(px, params, "margin_min", 0.20)
    if mmin_ser is not None:
        level = gp >= mmin_ser
    else:
        level = gp >= float(mmin_s if mmin_s is not None else 0.20)
    hot = _funda_hot_window(improve & level, int(params.get("funda_lag") or 25))
    np_ok = True
    if "npMargin" in px.columns and params.get("np_min") is not None:
        np_ok = _to_dec(px["npMargin"]) >= float(params.get("np_min") or 0.0)
    if "npMargin" in px.columns and params.get("np_improve") is not None:
        np_ = _to_dec(px["npMargin"])
        np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.0))
        hot = hot & _funda_hot_window(np_up, int(params.get("funda_lag") or 25))
    soft = float(params.get("brk_soft") or 1.0)
    brk_s, brk_ser = _param_scalar_or_mkv(px, params, "break_days", 60.0)
    if brk_ser is not None:
        days_i = brk_ser.round().astype(int)
        brk = pd.Series(False, index=px.index)
        for d in sorted(set(int(x) for x in days_i.unique())):
            if d <= 0:
                continue
            if d == 60 and "high_60" in px.columns:
                hi_ref = px["high_60"].shift(1)
            else:
                hi_ref = px["high"].rolling(d, min_periods=max(5, d // 2)).max().shift(1)
            brk = brk | ((days_i == d) & (px["close"] >= hi_ref * soft))
    else:
        brk_win = int(brk_s if brk_s is not None else 60)
        if brk_win == 60 and "high_60" in px.columns:
            hi_ref = px["high_60"].shift(1)
        else:
            hi_ref = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max().shift(1)
        brk = px["close"] >= hi_ref * soft
    m = hot & np_ok & brk
    ma_col = "ma60" if int(params.get("ma_days") or 20) >= 60 else "ma20"
    if ma_col not in px.columns:
        ma_col = "ma20"
    m = m & (px["close"] > px[ma_col])
    if "roeAvg" in px.columns and params.get("roe_min") is not None:
        m = m & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if "pe_pct" in px.columns and params.get("pe_pct_max") is not None:
        m = m & px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 1.0))
    if "pb_pct" in px.columns and params.get("pb_pct_max") is not None:
        m = m & px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 1.0))
    if params.get("yoy_min") is not None and "YOYNI" in px.columns:
        m = m & _g_ok(px["YOYNI"], float(params.get("yoy_min") or 0.0))
    if params.get("ret20_max") is not None and "ret_20" in px.columns:
        m = m & (px["ret_20"].isna() | (px["ret_20"] <= float(params.get("ret20_max") or 1.0)))
    if params.get("amt_dry_ratio") is not None and "amount" in px.columns:
        amt_ma = px["amount"].rolling(20, min_periods=10).mean()
        dry = px["amount"].shift(1) <= amt_ma.shift(1) * float(params.get("amt_dry_ratio") or 0.6)
        m = m & dry.fillna(False)
    if params.get("dd_need") is not None and "dd_20" in px.columns:
        m = m & (px["dd_20"] <= -abs(float(params.get("dd_need") or 0.0)))
    # 绝对净利门槛（元，累计报告期口径）
    if params.get("net_profit_min") is not None and "netProfit" in px.columns:
        m = m & (pd.to_numeric(px["netProfit"], errors="coerce") >= float(params.get("net_profit_min") or 0.0))
    # 总市值门槛（元）≈ close × totalShare
    if params.get("mktcap_min") is not None and "totalShare" in px.columns:
        mkt = _mkv_yuan(px)
        m = m & mkt.notna() & (mkt >= float(params.get("mktcap_min") or 0.0))
    out = px.loc[m, ["date", "close"]].copy()
    note = "毛利率扩张突破"
    if params.get("margin_min_by_mkv") or params.get("break_days_by_mkv"):
        note = "毛利率扩张突破(mkv分档)"
    out["note"] = note
    return out


def signal_rev_accel_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收加速横盘突破：YOYEquity/营收代理用 YOYEPS 不可用时用 YOYNI；优先 YOYAsset 外的营收字段若有。"""
    col = "YOYNI"
    if "MBRevenue" in px.columns:
        # 无直接营收YOY时，用利润表营收环比代理：披露事件 + 营收绝对值上升
        pass
    if col not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = _to_dec(px[col])
    accel = _funda_event(px[col]) & ((g - g.shift(1)) >= float(params.get("accel_min") or 0.06))
    now_ok = g >= float(params.get("growth_min") or 0.10)
    hot = _funda_hot_window(accel & now_ok, int(params.get("funda_lag") or 25))
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "盈利加速横盘突破"
    return out


def signal_roe_dip_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE浅回调后修复：前期高ROE，短期下滑后再改善，站上MA20。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    was_high = (roe.shift(2) >= float(params.get("roe_high") or 0.12)).fillna(False)
    dipped = (roe.shift(1) < roe.shift(2) - float(params.get("dip") or 0.005)).fillna(False)
    repair = _funda_event(px["roeAvg"]) & (roe > roe.shift(1)) & was_high & dipped
    hot = _funda_hot_window(repair, int(params.get("funda_lag") or 20))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE浅回调修复"
    return out


def signal_consec_improve_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """连续两期改善突破：ROE连续两期上行后突破。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    evt = _funda_event(px["roeAvg"])
    up1 = (roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002)
    up2 = (roe.shift(1) - roe.shift(2)) >= float(params.get("roe_improve") or 0.002)
    hot = _funda_hot_window(evt & up1 & up2, int(params.get("funda_lag") or 25))
    brk = px["close"] >= px["high_60"].shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE连续改善突破"
    return out


def signal_pb_floor_quality_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """PB历史低位 + 质量底线 + 突破。"""
    if "pb_pct" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.20))
    quality = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    brk = px["close"] >= px["high_60"].shift(1)
    m = cheap & quality & brk & (px["close"] > px["ma20"]) & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "PB低位质量突破"
    return out


def signal_growth_not_expensive_pullback(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """成长不贵回踩：高增 + PE分位不高 + 回踩站上MA20。"""
    if "YOYNI" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.20))
    cheap = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    dd = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.04))
    m = g_ok & cheap & cross & dd & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "成长不贵回踩"
    return out


def signal_gross_expand_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张 + 横盘突破（强化版）。"""
    if "gpMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    improve = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.004))
    level = gp >= float(params.get("margin_min") or 0.18)
    hot = _funda_hot_window(improve & level, int(params.get("funda_lag") or 30))
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张横盘突破"
    return out


def signal_dual_improve_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善后回踩：ROE+净利率改善热窗口内站上MA20。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 8) & _funda_hot_window(np_up, 8)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善回踩确认"
    return out


def signal_eps_accel_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS加速 + 横盘突破。"""
    if "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = _to_dec(px["YOYEPSBasic"])
    improve = _funda_event(px["YOYEPSBasic"]) & ((g - g.shift(1)) >= float(params.get("accel_min") or 0.05))
    now_ok = g >= float(params.get("growth_min") or 0.08)
    hot = _funda_hot_window(improve & now_ok, int(params.get("funda_lag") or 25))
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPS加速横盘突破"
    return out


def signal_cheap_quality_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """低估高质量回踩：低PB + 高ROE，站上MA20。"""
    if "pb_pct" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.35))
    quality = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    dd = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03))
    m = cheap & quality & cross & dd & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "低估高质量回踩"
    return out


def signal_gp_np_expand_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率与净利率双扩张后突破。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or params.get("margin_improve") or 0.003))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.003))
    gp_ok = gp >= float(params.get("margin_min") or 0.0) if params.get("margin_min") is not None else True
    np_ok = np_ >= float(params.get("np_min") or 0.0) if params.get("np_min") is not None else True
    lag = int(params.get("funda_lag") or 6)
    hot = _funda_hot_window(gp_up & gp_ok, lag) & _funda_hot_window(np_up & np_ok, lag)
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛净利率双扩张突破"
    return out


def signal_contract_liab_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债扩张后回踩站上MA20。"""
    if "contract_liab" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.12)
    hot = _funda_hot_window(qoq.fillna(False) | yoy_ok.fillna(False), int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债扩张回踩"
    return out


def signal_gp_np_expand_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛净利率双扩张后回踩。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or 0.003))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.003))
    hot = _funda_hot_window(gp_up, 8) & _funda_hot_window(np_up, 8)
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛净利率双扩张回踩"
    return out


def signal_contract_liab_ma60(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债扩张后站上MA60。"""
    if "contract_liab" not in px.columns or "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.12)
    hot = _funda_hot_window(qoq.fillna(False) | yoy_ok.fillna(False), int(params.get("funda_lag") or 35))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债扩张站上MA60"
    return out


def signal_gross_expand_ma60(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张后站上MA60。"""
    if "gpMargin" not in px.columns or "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    improve = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.005))
    level = gp >= float(params.get("margin_min") or 0.18)
    hot = _funda_hot_window(improve & level, int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张站上MA60"
    return out


def signal_dual_improve_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善 + 横盘突破。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 6) & _funda_hot_window(np_up, 6)
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善横盘突破"
    return out


def signal_gp_np_tight_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛净利率双扩张（更严阈值）后突破。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or 0.006))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.005))
    level = (gp >= float(params.get("gp_min") or 0.20)) & (np_ >= float(params.get("np_min") or 0.06))
    hot = _funda_hot_window(gp_up & np_up & level, int(params.get("funda_lag") or 20))
    brk = px["close"] >= px["high_60"].shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛净利率严标准双扩张突破"
    return out


def signal_contract_liab_yoy_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债同比高增后突破60日高。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
    yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
    strong = yoy_dec >= float(params.get("yoy_min") or 0.20)
    evt = _funda_event(yoy)
    hot = _funda_hot_window(evt & strong, int(params.get("funda_lag") or 25))
    np_ok = True
    if "npMargin" in px.columns and params.get("np_min") is not None:
        np_ok = _to_dec(px["npMargin"]) >= float(params.get("np_min") or 0.0)
    brk = px["close"] >= px["high_60"].shift(1)
    m = hot & np_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债高同比突破"
    return out


def signal_dual_improve_base_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善横盘回踩。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 8) & _funda_hot_window(np_up, 8)
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = base.fillna(False) & hot & cross & (px["close"] >= lo * 0.97)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善横盘回踩"
    return out


def signal_gp_np_tight_base(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """严标准毛净利率双扩张 + 横盘突破。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or 0.006))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.005))
    level = (gp >= float(params.get("gp_min") or 0.20)) & (np_ >= float(params.get("np_min") or 0.06))
    hot = _funda_hot_window(gp_up & np_up & level, int(params.get("funda_lag") or 25))
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "严标准毛净利率横盘突破"
    return out


def signal_contract_yoy_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债高同比 + 横盘突破。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
    yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
    strong = yoy_dec >= float(params.get("yoy_min") or 0.20)
    evt = _funda_event(yoy)
    hot = _funda_hot_window(evt & strong, int(params.get("funda_lag") or 25))
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债高同比横盘突破"
    return out


def signal_dual_improve_ma60(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善后站上MA60。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns or "ma60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 10) & _funda_hot_window(np_up, 10)
    cross = (px["close"] > px["ma60"]) & (px["close"].shift(1) <= px["ma60"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善站上MA60"
    return out


def signal_gp_np_tight_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """严标准毛净利率双扩张回踩。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("gp_improve") or 0.006))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.005))
    level = (gp >= float(params.get("gp_min") or 0.20)) & (np_ >= float(params.get("np_min") or 0.06))
    hot = _funda_hot_window(gp_up & np_up & level, int(params.get("funda_lag") or 25))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross & (px["close"] > px["ma60"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "严标准毛净利率回踩"
    return out


def signal_contract_yoy_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债高同比后回踩。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
    yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
    strong = yoy_dec >= float(params.get("yoy_min") or 0.20)
    evt = _funda_event(yoy)
    hot = _funda_hot_window(evt & strong, int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债高同比回踩"
    return out


def signal_gross_dual_stack_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张 + ROE改善后突破。"""
    if "gpMargin" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    roe = _to_dec(px["roeAvg"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.004))
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    hot = _funda_hot_window(gp_up, 8) & _funda_hot_window(roe_up, 8)
    brk = px["close"] >= px["high_60"].shift(1)
    m = hot & brk & (px["close"] > px["ma20"]) & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率ROE双改善突破"
    return out


def signal_gross_dual_base_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率+ROE双改善后横盘突破。"""
    if "gpMargin" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    roe = _to_dec(px["roeAvg"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.005))
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    hot = _funda_hot_window(gp_up, 8) & _funda_hot_window(roe_up, 8)
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.22))
    brk = px["close"] >= hi.shift(1)
    m = (
        base.shift(1).fillna(False)
        & hot
        & brk
        & (px["close"] > px["ma20"])
        & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    )
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率ROE双改善横盘突破"
    return out


def signal_dual_improve_long_base(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双改善 + 更长横盘突破。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 6) & _funda_hot_window(np_up, 6)
    win = int(params.get("base_window") or 120)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.28))
    brk = px["close"] >= hi.shift(1)
    m = base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双改善长横盘突破"
    return out


def signal_contract_reclaim_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债扩张回踩 + ROE底线。"""
    if "contract_liab" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.12)
    hot = _funda_hot_window(qoq.fillna(False) | yoy_ok.fillna(False), int(params.get("funda_lag") or 30))
    cross = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
    m = hot & cross & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债扩张质量回踩"
    return out


def signal_gp_expand_cheap_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张 + 低估突破。"""
    if "gpMargin" not in px.columns or "pe_pct" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    improve = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.005))
    level = gp >= float(params.get("margin_min") or 0.18)
    hot = _funda_hot_window(improve & level, int(params.get("funda_lag") or 25))
    cheap = px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    np_ok = True
    if "npMargin" in px.columns and params.get("np_min") is not None:
        np_ok = _to_dec(px["npMargin"]) >= float(params.get("np_min") or 0.0)
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & cheap & np_ok & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张低估突破"
    return out


def signal_eps_dual_confirm_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS加速 + 净利率改善后突破。"""
    if "YOYEPSBasic" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g = _to_dec(px["YOYEPSBasic"])
    np_ = _to_dec(px["npMargin"])
    eps_up = _funda_event(px["YOYEPSBasic"]) & ((g - g.shift(1)) >= float(params.get("accel_min") or 0.05))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    lag = int(params.get("funda_lag") or 6)
    np_ok = True
    if params.get("np_min") is not None:
        np_ok = np_ >= float(params.get("np_min") or 0.0)
    hot = _funda_hot_window(eps_up & (g >= float(params.get("growth_min") or 0.08)) & np_ok, lag) & _funda_hot_window(np_up, lag)
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPS加速净利率确认突破"
    return out


def signal_gross_high_np_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张 + 高净利率水平后突破60日高（冠军毛利率线 × 高净利率过滤）。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    improve = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.005))
    level = gp >= float(params.get("margin_min") or 0.20)
    np_ok = np_ >= float(params.get("np_min") or 0.08)
    funda = improve & level & np_ok
    if params.get("np_improve") is not None:
        np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.0))
        funda = funda & np_up
    hot = _funda_hot_window(funda, int(params.get("funda_lag") or 28))
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    ma_col = "ma60" if int(params.get("ma_days") or 20) >= 60 else "ma20"
    if ma_col not in px.columns:
        ma_col = "ma20"
    trend = px["close"] > px[ma_col]
    if params.get("ma_cross"):
        trend = (px["close"] > px[ma_col]) & (px["close"].shift(1) <= px[ma_col].shift(1))
    roe_ok = True
    if "roeAvg" in px.columns and params.get("roe_min") is not None:
        roe_ok = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    cheap = True
    if "pb_pct" in px.columns and params.get("pb_pct_max") is not None:
        cheap = px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 1.0))
    if "pe_pct" in px.columns and params.get("pe_pct_max") is not None:
        pe_ok = px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 1.0))
        cheap = cheap & pe_ok if cheap is not True else pe_ok
    growth_ok = True
    gcol = _pick_growth_col(px)
    if gcol is not None and (
        params.get("growth_min") is not None or params.get("growth_accel") is not None
    ):
        g = px[gcol].astype(float)
        parts = []
        if params.get("growth_min") is not None:
            parts.append(_g_ok(g, float(params.get("growth_min") or 0.0)))
        if params.get("growth_accel") is not None:
            parts.append((g - g.shift(1)) >= float(params.get("growth_accel") or 0.0))
        growth_ok = parts[0]
        for p in parts[1:]:
            growth_ok = growth_ok & p
    entry = str(params.get("entry") or "break")
    if entry == "reclaim":
        tech = (px["close"] > px[ma_col]) & (px["close"].shift(1) <= px[ma_col].shift(1))
    elif entry == "either":
        tech = brk | ((px["close"] > px[ma_col]) & (px["close"].shift(1) <= px[ma_col].shift(1)))
    else:
        tech = brk & trend
    if params.get("amp_max") is not None:
        _hi, _lo, base = _amp_base(px, int(params.get("base_window") or 60), float(params.get("amp_max") or 0.22))
        tech = tech & base.shift(1).fillna(False)
    m = hot & tech & roe_ok & cheap & growth_ok
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张高净利率突破"
    return out


def signal_gross_np_up_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张 + 净利率环比改善后突破（相对高净利率水平过滤的互补主线）。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.006))
    gp_lvl = gp >= float(params.get("margin_min") or 0.20)
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("np_improve") or 0.003))
    np_ok = np_ >= float(params.get("np_min") or 0.0)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gp_up & gp_lvl, lag) & _funda_hot_window(np_up & np_ok, lag)
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率扩张净利率改善突破"
    return out


def signal_gross_net_catchup_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高毛利下净利率追赶后突破60日高。"""
    if "gpMargin" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    np_ = _to_dec(px["npMargin"])
    high_gp = gp >= float(params.get("gp_min") or 0.25)
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
    gap = (gp - np_) >= float(params.get("gap_min") or 0.05)
    hot = _funda_hot_window(high_gp & np_up & gap, int(params.get("funda_lag") or 28))
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        brk = px["close"] >= px["high_60"].shift(1)
    else:
        hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
        brk = px["close"] >= hi.shift(1)
    m = hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛净利差收敛突破"
    return out


def signal_quality_base_dual(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """高ROE横盘 + 双改善热窗口突破。"""
    if "roeAvg" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    quality = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.12))
    roe = _to_dec(px["roeAvg"])
    np_ = _to_dec(px["npMargin"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.002))
    np_up = _funda_event(px["npMargin"]) & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.003))
    hot = _funda_hot_window(roe_up, 6) & _funda_hot_window(np_up, 6)
    win = int(params.get("base_window") or 60)
    hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.22))
    brk = px["close"] >= hi.shift(1)
    m = quality & base.shift(1).fillna(False) & hot & brk & (px["close"] > px["ma20"])
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "优质横盘双改善突破"
    return out


# ----- 新结构波次：非高原参数微调 -----


def _break_high(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    brk_win = int(params.get("break_days") or 60)
    if brk_win == 60 and "high_60" in px.columns:
        return px["close"] >= px["high_60"].shift(1)
    hi = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max()
    return px["close"] >= hi.shift(1)


def _entry_tech(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    """技术图形入场：突破 / 回踩 / 横盘突破 / 趋势回踩。

    entry:
      - break: 突破 N 日高 + 站上均线
      - reclaim: 上穿均线
      - either: 突破或回踩
      - base_break: 先横盘收窄再突破上沿（箱体突破）
      - pullback: MA60 上行趋势中回踩站上 MA20
    """
    entry = str(params.get("entry") or "break")
    ma_col = "ma60" if int(params.get("ma_days") or 20) >= 60 and "ma60" in px.columns else "ma20"
    if ma_col not in px.columns:
        ma_col = "ma20"
    trend = px[ma_col].notna() & (px["close"] > px[ma_col])
    brk = _break_high(px, params)
    reclaim = (px["close"] > px[ma_col]) & (px["close"].shift(1) <= px[ma_col].shift(1))

    if entry == "reclaim":
        tech = reclaim
    elif entry == "either":
        tech = brk | reclaim
    elif entry == "base_break":
        win = int(params.get("base_window") or 60)
        hi, lo, base = _amp_base(px, win, float(params.get("amp_max") or 0.24))
        in_box = px["close"] >= (lo * float(params.get("box_floor") or 0.97))
        box_brk = px["close"] >= hi.shift(1)
        tech = base.shift(1).fillna(False) & in_box.shift(1).fillna(False) & box_brk.fillna(False) & trend
    elif entry == "pullback":
        if "ma60" not in px.columns or "ma20" not in px.columns:
            return pd.Series(False, index=px.index)
        slope = px["ma60"] - px["ma60"].shift(int(params.get("slope_lag") or 5))
        up = slope > 0
        cross20 = (px["close"] > px["ma20"]) & (px["close"].shift(1) <= px["ma20"].shift(1))
        dd_ok = True
        if "dd_20" in px.columns:
            dd_ok = px["dd_20"] <= -abs(float(params.get("dd_need") or 0.03))
        tech = up.fillna(False) & cross20 & dd_ok & (px["close"] > px["ma60"])
    else:
        tech = brk & trend

    # 可选：任意 entry 叠加横盘约束（更严的图形过滤）
    if params.get("amp_max") is not None and entry not in ("base_break",):
        _hi, _lo, base = _amp_base(px, int(params.get("base_window") or 60), float(params.get("amp_max") or 0.24))
        tech = tech & base.shift(1).fillna(False)
    return tech


def _contract_expand_raw(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    if "contract_liab" not in px.columns:
        return pd.Series(False, index=px.index)
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    evt = _funda_event(cl)
    qoq = evt & cl.notna() & cl.shift(1).notna() & (cl >= cl.shift(1) * (1.0 + float(params.get("qoq_min") or 0.08)))
    yoy_ok = pd.Series(False, index=px.index)
    if "contract_liab_yoy" in px.columns:
        yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce")
        yoy_dec = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
        yoy_ok = yoy_dec >= float(params.get("yoy_min") or 0.15)
    return (qoq.fillna(False) | yoy_ok.fillna(False)) & cl.notna() & (cl > 0)


def signal_cl_intensity_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债强度突破：预收/合同负债占营收有实质占比且强度上升后突破。

    用「强度」近似预收型业务（航司预售票、设备订金、软件预收等），
    过滤金融/贸易等合同负债噪声票。
    """
    if "contract_liab" not in px.columns or "MBRevenue" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    intensity = cl / rev.replace(0, pd.NA)
    evt = _funda_event(cl) | _funda_event(rev)
    material = intensity >= float(params.get("cl_rev_min") or 0.05)
    up = intensity.notna() & intensity.shift(1).notna() & (
        intensity >= intensity.shift(1) * (1.0 + float(params.get("intensity_improve") or 0.08))
    )
    hot = _funda_hot_window(evt & material & up, int(params.get("funda_lag") or 28))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "合同负债强度突破"
    return out


def signal_demand_pricing_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """需求×定价：合同负债扩张 AND 毛利率扩张后突破。"""
    if "gpMargin" not in px.columns or "contract_liab" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= float(params.get("margin_improve") or 0.005))
    gp_ok = gp >= float(params.get("margin_min") or 0.15)
    cl_up = _contract_expand_raw(px, params)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gp_up & gp_ok, lag) & _funda_hot_window(cl_up, lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "需求定价双确认突破"
    return out


def signal_rev_qoq_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收环比扩张突破：主营业务收入披露上升后突破（非净利代理）。"""
    if "MBRevenue" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    evt = _funda_event(rev)
    qoq_min = float(params.get("qoq_min") or 0.08)
    up = evt & rev.notna() & rev.shift(1).notna() & (rev >= rev.shift(1) * (1.0 + qoq_min))
    hot = _funda_hot_window(up, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "营收环比扩张突破"
    return out


def signal_parent_lead_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """归属净利领先突破：YOYPNI 高于 YOYNI（占比/质量改善）后突破。"""
    if "YOYPNI" not in px.columns or "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pni = _to_dec(px["YOYPNI"])
    ni = _to_dec(px["YOYNI"])
    lead = _funda_event(px["YOYPNI"]) & pni.notna() & ni.notna() & (
        (pni - ni) >= float(params.get("lead_min") or 0.03)
    )
    level = pni >= float(params.get("growth_min") or 0.10)
    hot = _funda_hot_window(lead & level, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "归属净利领先突破"
    return out


def signal_asset_light_cl_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """轻资产+预收：资产同比不高 + 合同负债扩张后突破。"""
    if "contract_liab" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl_up = _contract_expand_raw(px, params)
    light = pd.Series(True, index=px.index)
    if "YOYAsset" in px.columns:
        asset_g = _to_dec(px["YOYAsset"])
        light = asset_g.isna() | (asset_g <= float(params.get("asset_yoy_max") or 0.15))
    hot = _funda_hot_window(cl_up & light, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "轻资产合同负债突破"
    return out


def signal_gp_consec_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率连续两期扩张后突破（持续定价能力，非单季脉冲）。"""
    if "gpMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    step = float(params.get("margin_improve") or 0.003)
    evt = _funda_event(px["gpMargin"])
    up1 = (gp - gp.shift(1)) >= step
    up2 = (gp.shift(1) - gp.shift(2)) >= step
    level = gp >= float(params.get("margin_min") or 0.15)
    hot = _funda_hot_window(evt & up1 & up2 & level, int(params.get("funda_lag") or 28))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "毛利率连续扩张突破"
    return out


# ---------------------------------------------------------------------------
# 非毛利率主线：净利率 / 营收×ROE / 归属×EPS / 回购 / 轻资产净利 / 预收×ROE / 双同比加速
# ---------------------------------------------------------------------------


def signal_np_regime_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利率体制突破：净利率连续两期扩张且达水平后入场（毛利率主线的净利对照）。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    np_ = _to_dec(px["npMargin"])
    step = float(params.get("margin_improve") or 0.003)
    evt = _funda_event(px["npMargin"])
    up1 = (np_ - np_.shift(1)) >= step
    up2 = (np_.shift(1) - np_.shift(2)) >= step
    level = np_ >= float(params.get("np_min") or 0.08)
    hot = _funda_hot_window(evt & up1 & up2 & level, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利率连续扩张突破"
    return out


def signal_np_expand_cheap_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利率扩张×低估：净利率改善热窗口内，PE/PB 历史分位偏低后入场。"""
    if "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    np_ = _to_dec(px["npMargin"])
    evt = _funda_event(px["npMargin"])
    up = evt & ((np_ - np_.shift(1)) >= float(params.get("margin_improve") or 0.005))
    level = np_ >= float(params.get("np_min") or 0.06)
    hot = _funda_hot_window(up & level, int(params.get("funda_lag") or 28))
    cheap = pd.Series(True, index=px.index)
    if "pe_pct" in px.columns:
        cheap = cheap & px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    if "pb_pct" in px.columns and params.get("pb_pct_max") is not None:
        cheap = cheap & px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.45))
    m = hot & cheap & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利率扩张低估突破"
    return out


def signal_rev_roe_sync_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收×ROE 同步：营收环比上台阶且 ROE 同期改善后入场。"""
    if "MBRevenue" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    roe = _to_dec(px["roeAvg"])
    qoq_min = float(params.get("qoq_min") or 0.08)
    rev_up = (
        _funda_event(rev)
        & rev.notna()
        & rev.shift(1).notna()
        & (rev >= rev.shift(1) * (1.0 + qoq_min))
    )
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.003))
    roe_lvl = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(rev_up, lag) & _funda_hot_window(roe_up & roe_lvl, lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "营收ROE同步突破"
    return out


def signal_parent_eps_twin_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """归属净利×EPS 双高增：YOYPNI 与 YOYEPS 同时达标后入场。"""
    if "YOYPNI" not in px.columns or "YOYEPSBasic" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.15)
    twin = (
        (_funda_event(px["YOYPNI"]) | _funda_event(px["YOYEPSBasic"]))
        & _g_ok(px["YOYPNI"], gmin)
        & _g_ok(px["YOYEPSBasic"], gmin)
    )
    hot = _funda_hot_window(twin, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        hot = hot & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.65)))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "归属净利EPS双高增"
    return out


def signal_share_buyback_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """回购低估收复：总股本收缩 + PE/PB 偏低后上穿均线。"""
    if "totalShare" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    sh = pd.to_numeric(px["totalShare"], errors="coerce")
    shrink = sh.notna() & sh.shift(1).notna() & (
        sh < sh.shift(1) * (1.0 - float(params.get("shrink_min") or 0.002))
    )
    funda = _funda_event(px["totalShare"]) & shrink.fillna(False)
    if "roeAvg" in px.columns and params.get("roe_min") is not None:
        funda = funda & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    hot = _funda_hot_window(funda, int(params.get("funda_lag") or 40))
    cheap = pd.Series(True, index=px.index)
    if "pe_pct" in px.columns:
        cheap = cheap & px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.40))
    if "pb_pct" in px.columns:
        cheap = cheap & px["pb_pct"].notna() & (px["pb_pct"] <= float(params.get("pb_pct_max") or 0.40))
    p = {**params, "entry": str(params.get("entry") or "reclaim")}
    m = hot & cheap & _entry_tech(px, p)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "回购低估收复"
    return out


def signal_asset_light_ni_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """轻资产净利：净利高增且资产同比显著更低后入场（效率型扩张）。"""
    if "YOYNI" not in px.columns or "YOYAsset" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni = _to_dec(px["YOYNI"])
    asset = _to_dec(px["YOYAsset"])
    gap = float(params.get("asset_gap") or 0.12)
    light = (ni - asset) >= gap
    funda = (
        _funda_event(px["YOYNI"])
        & _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.12))
        & light.fillna(False)
    )
    hot = _funda_hot_window(funda, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "轻资产净利高增突破"
    return out


def signal_cl_intensity_roe_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """预收强度×ROE：合同负债/营收强度上升且 ROE 改善后入场（不用毛利率）。"""
    if "contract_liab" not in px.columns or "MBRevenue" not in px.columns or "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab"], errors="coerce")
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    intensity = cl / rev.replace(0, pd.NA)
    evt = _funda_event(cl) | _funda_event(rev)
    material = intensity >= float(params.get("cl_rev_min") or 0.05)
    up = intensity.notna() & intensity.shift(1).notna() & (
        intensity >= intensity.shift(1) * (1.0 + float(params.get("intensity_improve") or 0.08))
    )
    roe = _to_dec(px["roeAvg"])
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= float(params.get("roe_improve") or 0.003))
    roe_lvl = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(evt & material & up, lag) & _funda_hot_window(roe_up & roe_lvl, lag)
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "预收强度ROE突破"
    return out


def signal_dual_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """双同比再加速：YOYNI 与 YOYPNI 同时加速且达水平后入场。"""
    if "YOYNI" not in px.columns or "YOYPNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni = _to_dec(px["YOYNI"])
    pni = _to_dec(px["YOYPNI"])
    accel = float(params.get("growth_accel") or 0.05)
    gmin = float(params.get("growth_min") or 0.10)
    evt = _funda_event(px["YOYNI"]) | _funda_event(px["YOYPNI"])
    both = (
        evt
        & ni.notna()
        & pni.notna()
        & ((ni - ni.shift(1)) >= accel)
        & ((pni - pni.shift(1)) >= accel)
        & (ni >= gmin)
        & (pni >= gmin)
    )
    hot = _funda_hot_window(both, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "双同比再加速突破"
    return out


def signal_roe_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE 连续加速：ROE 连续两期改善且达水平后入场。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    step = float(params.get("roe_improve") or 0.003)
    evt = _funda_event(px["roeAvg"])
    up1 = (roe - roe.shift(1)) >= step
    up2 = (roe.shift(1) - roe.shift(2)) >= step
    level = _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.10))
    hot = _funda_hot_window(evt & up1 & up2 & level, int(params.get("funda_lag") or 28))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "ROE连续加速突破"
    return out


def signal_ni_quality_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利质量：YOYNI 高增 + 净利率底线后入场（质量增长，非毛利率）。"""
    if "YOYNI" not in px.columns or "npMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.15))
    np_ok = _margin_ok(px["npMargin"], float(params.get("np_min") or 0.08))
    funda = _funda_event(px["YOYNI"]) & g_ok & np_ok
    hot = _funda_hot_window(funda, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        hot = hot & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.55)))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "净利质量高增突破"
    return out


# ---------------------------------------------------------------------------
# 更大结构差异：每股营收 / 流通盘 / 绝对净利 / EPS TTM / 股权利差 / 预收领先 / 量能×基本面
# （不用 gpMargin，也不做净利率/毛利率扩张细网格）
# ---------------------------------------------------------------------------


def signal_rev_per_share_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """每股营收再加速：MBRevenue/totalShare 连续两期环比上升后入场。"""
    if "MBRevenue" not in px.columns or "totalShare" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    sh = pd.to_numeric(px["totalShare"], errors="coerce").replace(0, pd.NA)
    rps = rev / sh
    qoq_min = float(params.get("qoq_min") or 0.06)
    evt = _funda_event(rev) | _funda_event(sh)
    up1 = rps.notna() & rps.shift(1).notna() & (rps >= rps.shift(1) * (1.0 + qoq_min))
    up2 = rps.shift(1).notna() & rps.shift(2).notna() & (
        rps.shift(1) >= rps.shift(2) * (1.0 + qoq_min)
    )
    hot = _funda_hot_window(evt & up1 & up2, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "每股营收再加速"
    return out


def signal_float_concentration_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """流通盘收紧：流通股本占比下降（筹码集中）后入场。"""
    if "totalShare" not in px.columns or "liqaShare" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    tot = pd.to_numeric(px["totalShare"], errors="coerce")
    liq = pd.to_numeric(px["liqaShare"], errors="coerce")
    ratio = liq / tot.replace(0, pd.NA)
    step = float(params.get("float_shrink") or 0.01)
    evt = _funda_event(liq) | _funda_event(tot)
    tighten = ratio.notna() & ratio.shift(1).notna() & ((ratio.shift(1) - ratio) >= step)
    # 可选：流通股本绝对下降
    if params.get("require_liqa_down"):
        tighten = tighten & liq.notna() & liq.shift(1).notna() & (liq < liq.shift(1))
    hot = _funda_hot_window(evt & tighten, int(params.get("funda_lag") or 40))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("growth_min") is not None and "YOYNI" in px.columns:
        hot = hot & _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "流通盘收紧突破"
    return out


def signal_netprofit_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """绝对净利二阶加速：netProfit 环比连续两期改善（非利润率、非同比）。"""
    if "netProfit" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    npv = pd.to_numeric(px["netProfit"], errors="coerce")
    qoq_min = float(params.get("qoq_min") or 0.08)
    evt = _funda_event(npv)
    pos = npv > 0
    up1 = npv.notna() & npv.shift(1).notna() & (npv >= npv.shift(1) * (1.0 + qoq_min))
    up2 = npv.shift(1).notna() & npv.shift(2).notna() & (
        npv.shift(1) >= npv.shift(2) * (1.0 + qoq_min)
    )
    hot = _funda_hot_window(evt & pos & up1 & up2, int(params.get("funda_lag") or 28))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        hot = hot & px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.50))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "绝对净利二阶加速"
    return out


def signal_eps_ttm_mom_cheap_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """EPS TTM 动量×低估：epsTTM 连续两期上升且 PE 分位偏低后入场。"""
    if "epsTTM" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    eps = pd.to_numeric(px["epsTTM"], errors="coerce")
    step = float(params.get("eps_improve") or 0.0)
    # 相对改善：至少非降，或绝对改善幅度
    rel = float(params.get("eps_qoq_min") or 0.03)
    evt = _funda_event(eps)
    up1 = eps.notna() & eps.shift(1).notna() & (eps > 0) & (
        (eps - eps.shift(1) >= step) & (eps >= eps.shift(1) * (1.0 + rel))
    )
    up2 = eps.shift(1).notna() & eps.shift(2).notna() & (
        eps.shift(1) >= eps.shift(2) * (1.0 + rel)
    )
    hot = _funda_hot_window(evt & up1 & up2, int(params.get("funda_lag") or 28))
    if "pe_pct" in px.columns:
        hot = hot & px["pe_pct"].notna() & (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.45))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "EPSTTM动量低估"
    return out


def signal_equity_outrun_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """股权利差：归属净利增速显著跑赢净资产增速（稀释克制下的利润扩张）。"""
    if "YOYPNI" not in px.columns or "YOYEquity" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pni = _to_dec(px["YOYPNI"])
    eq = _to_dec(px["YOYEquity"])
    gap = float(params.get("equity_gap") or 0.10)
    gmin = float(params.get("growth_min") or 0.12)
    evt = _funda_event(px["YOYPNI"]) | _funda_event(px["YOYEquity"])
    outrun = pni.notna() & eq.notna() & ((pni - eq) >= gap) & (pni >= gmin)
    hot = _funda_hot_window(evt & outrun, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        hot = hot & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.60)))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "归属增速跑赢净资产"
    return out


def signal_advance_recv_lead_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """预收领先需求：advance_recv 环比扩张，而营收尚未同幅跟上（需求领先指标）。"""
    ar_col = "advance_recv" if "advance_recv" in px.columns else None
    if ar_col is None and "contract_liab_raw" in px.columns:
        ar_col = "contract_liab_raw"
    if ar_col is None or "MBRevenue" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ar = pd.to_numeric(px[ar_col], errors="coerce")
    rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
    ar_qoq = float(params.get("ar_qoq_min") or 0.10)
    rev_cap = float(params.get("rev_qoq_max") or 0.08)
    evt = _funda_event(ar)
    ar_up = ar.notna() & ar.shift(1).notna() & (ar > 0) & (ar >= ar.shift(1) * (1.0 + ar_qoq))
    # 营收未同步爆发：环比低于阈值或缺失
    rev_lag = rev.isna() | rev.shift(1).isna() | (rev < rev.shift(1) * (1.0 + rev_cap))
    hot = _funda_hot_window(evt & ar_up & rev_lag, int(params.get("funda_lag") or 28))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    m = hot & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "预收领先营收突破"
    return out


def signal_turn_dry_growth_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """缩量蓄势×成长：换手低于均线后放量，且同比成长达标。"""
    if "turn" not in px.columns or "YOYNI" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    turn = pd.to_numeric(px["turn"], errors="coerce")
    tma = turn.rolling(int(params.get("turn_ma") or 20), min_periods=10).mean()
    dry = turn.shift(1).notna() & tma.shift(1).notna() & (
        turn.shift(1) <= tma.shift(1) * float(params.get("dry_ratio") or 0.60)
    )
    surge = turn.notna() & tma.notna() & (turn >= tma * float(params.get("surge_ratio") or 1.15))
    g_ok = _g_ok(px["YOYNI"], float(params.get("growth_min") or 0.15))
    # 成长热窗：披露后若干日仍有效
    g_hot = _funda_hot_window(_funda_event(px["YOYNI"]) & g_ok, int(params.get("funda_lag") or 40))
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        g_hot = g_hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    tech = _entry_tech(px, params)
    m = dry.fillna(False) & surge.fillna(False) & g_hot & tech
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "缩量蓄势成长突破"
    return out


def signal_amount_coil_outrun_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """成交额收缩×股权利差：近窗成交额萎缩后放量，叠加归属跑赢净资产。"""
    if "amount" not in px.columns or "YOYPNI" not in px.columns or "YOYEquity" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    amt = pd.to_numeric(px["amount"], errors="coerce")
    win = int(params.get("amt_window") or 20)
    ama = amt.rolling(win, min_periods=max(8, win // 2)).mean()
    coil = ama.shift(1).notna() & amt.shift(1).notna() & (
        amt.shift(1) <= ama.shift(1) * float(params.get("coil_ratio") or 0.70)
    )
    wake = amt.notna() & ama.notna() & (amt >= ama * float(params.get("wake_ratio") or 1.20))
    pni = _to_dec(px["YOYPNI"])
    eq = _to_dec(px["YOYEquity"])
    gap = float(params.get("equity_gap") or 0.08)
    gmin = float(params.get("growth_min") or 0.10)
    funda = _funda_hot_window(
        (_funda_event(px["YOYPNI"]) | _funda_event(px["YOYEquity"]))
        & pni.notna()
        & eq.notna()
        & ((pni - eq) >= gap)
        & (pni >= gmin),
        int(params.get("funda_lag") or 35),
    )
    m = coil.fillna(False) & wake.fillna(False) & funda & _entry_tech(px, params)
    out = px.loc[m, ["date", "close"]].copy()
    out["note"] = "成交收缩股权利差突破"
    return out


# Wind 业绩预告类型码（S_PROFITNOTICE_STYLE）
_FCST_STYLE_PRE_INCREASE = 454010000.0  # 预增
_FCST_STYLE_SLIGHT_UP = 454008000.0  # 略增
_FCST_STYLE_CONT_PROFIT = 454003000.0  # 续盈
_FCST_STYLE_TURNAROUND = 454004000.0  # 扭亏
_FCST_STYLE_SKIP = {
    454001000.0,  # 不确定
    454002000.0,  # 略减
    454004000.0,  # 扭亏（伪翻倍主来源）
    454006000.0,  # 首亏
    454007000.0,  # 续亏
    454009000.0,  # 预减
}
_FCST_STYLE_POSITIVE = {
    _FCST_STYLE_PRE_INCREASE,
    _FCST_STYLE_SLIGHT_UP,
    _FCST_STYLE_CONT_PROFIT,
}


def signal_fcst_profit_gap(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """业绩预告爆发利润断层：增速下限≥explosive 的正向预告，公告日事件买入。

    纯预告/基本面事件（非 earnings_forecast 的追高三维）。排除扭亏伪翻倍：
    类型为扭亏/亏损类，或可由预告净利反推基期≤0 时跳过。
    """
    if "fcst_change_min" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    chg = pd.to_numeric(px["fcst_change_min"], errors="coerce")
    # 库内为百分数（100=100%）；偶发小数则放大到百分数口径
    chg_pct = chg.where(chg.abs() > 5.0, chg * 100.0)
    explosive = float(params.get("explosive_chg") or params.get("explosive_chg_pct_dwn") or 100.0)
    explosive_ok = chg_pct.notna() & (chg_pct >= explosive)

    style = pd.to_numeric(px["fcst_style"], errors="coerce") if "fcst_style" in px.columns else pd.Series(pd.NA, index=px.index)
    style_skip = style.isin(list(_FCST_STYLE_SKIP))
    style_pos = style.isna() | style.isin(list(_FCST_STYLE_POSITIVE))

    np_min = (
        pd.to_numeric(px["fcst_np_min"], errors="coerce")
        if "fcst_np_min" in px.columns
        else pd.Series(pd.NA, index=px.index)
    )
    # 反推上年同季基期：np_min / (1 + chg%)；基期亏损则视为伪翻倍
    prior = np_min / (1.0 + chg_pct / 100.0)
    base_loss = np_min.notna() & chg_pct.notna() & (prior <= 0)
    np_pos = np_min.isna() | (np_min > 0)

    abstract_turn = pd.Series(False, index=px.index)
    if "fcst_abstract" in px.columns:
        abstract_turn = px["fcst_abstract"].astype(str).str.contains("扭亏", na=False)

    gate = explosive_ok & style_pos & (~style_skip) & np_pos & (~base_loss) & (~abstract_turn)
    evt = _funda_event(px["fcst_change_min"]) & gate.fillna(False)

    lag = int(params.get("funda_lag") or 0)
    hot = _funda_hot_window(evt, lag) if lag > 0 else evt

    require_ma = params.get("require_ma20", True)
    if require_ma:
        m = hot & _funda_confirm(px)
    else:
        m = hot

    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "预告爆发利润断层"
    return out


def signal_q_np_gap(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """正式季报单季净利润断层式跨越增长（非预告）。

    依赖 ashare_fin_db 派生列：累计净利差分→q_np，再算 q_np_yoy / q_np_qoq / q_np_prior_yoy。
    信号：单季 YoY≥θ，且「断层」（上年同季增速不高 或 单季环比跨越）；
    排除单季亏损与基期亏损伪翻倍；按公告日 asof 事件对齐。
    """
    if "q_np_yoy" not in px.columns or "q_np" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    yoy = pd.to_numeric(px["q_np_yoy"], errors="coerce").astype(float)
    q_np = pd.to_numeric(px["q_np"], errors="coerce").astype(float)
    qoq = (
        pd.to_numeric(px["q_np_qoq"], errors="coerce").astype(float)
        if "q_np_qoq" in px.columns
        else pd.Series(float("nan"), index=px.index, dtype=float)
    )
    prior_yoy = (
        pd.to_numeric(px["q_np_prior_yoy"], errors="coerce").astype(float)
        if "q_np_prior_yoy" in px.columns
        else pd.Series(float("nan"), index=px.index, dtype=float)
    )

    # explosive_chg：兼容百分数（100=100%）与小数（1.0=100%）
    explosive_raw = float(params.get("explosive_chg") or 100.0)
    explosive = explosive_raw / 100.0 if abs(explosive_raw) > 5.0 else explosive_raw
    prior_max_raw = float(params.get("prior_yoy_max") or 30.0)
    prior_max = prior_max_raw / 100.0 if abs(prior_max_raw) > 5.0 else prior_max_raw
    qoq_gap_raw = float(params.get("qoq_gap_min") or 50.0)
    qoq_gap = qoq_gap_raw / 100.0 if abs(qoq_gap_raw) > 5.0 else qoq_gap_raw

    explosive_ok = yoy.notna() & (yoy >= explosive)
    np_pos = q_np.notna() & (q_np > 0)
    # 断层：上年同季增速不高，或本期单季环比跨越（缺上年同比时不默认放行）
    soft_prior = prior_yoy.notna() & (prior_yoy < prior_max)
    qoq_jump = qoq.notna() & (qoq >= qoq_gap)
    gap_ok = soft_prior | qoq_jump

    gate = (explosive_ok & np_pos & gap_ok).fillna(False)
    evt = (_funda_event(yoy) & gate).fillna(False)

    lag = int(params.get("funda_lag") or 0)
    hot = (_funda_hot_window(evt, lag) if lag > 0 else evt).fillna(False)

    require_ma = bool(params.get("require_ma20", True))
    if require_ma:
        m = (hot & _funda_confirm(px)).fillna(False)
    else:
        m = hot

    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "正式季报单季净利断层"
    return out


def _tech_break_confirm(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    """通用技术确认：N 日高突破 + 站上 MA20（与 dual_improve / gross_expand 同构）。"""
    brk_win = int(params.get("break_days") or 60)
    soft = float(params.get("brk_soft") or 1.0)
    if brk_win == 60 and "high_60" in px.columns:
        hi_ref = px["high_60"].shift(1)
    else:
        hi_ref = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max().shift(1)
    brk = hi_ref.notna() & (px["close"] >= hi_ref * soft)
    ma_ok = _funda_confirm(px) if bool(params.get("require_ma20", True)) else pd.Series(True, index=px.index)
    return (brk & ma_ok).fillna(False)


def signal_expr_ros_improve_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """快报 ROS（净利/营收）同比改善 + 技术突破确认。

    PIT：快报实际/公告日 merge_asof。ΔROS 优先用同行上年字段（expr_dros）；
    缺列时退化为 expr_ros 环比跳变代理（弱）。
    """
    dros_col = "expr_dros" if "expr_dros" in px.columns else None
    ros_col = "expr_ros" if "expr_ros" in px.columns else None
    if dros_col is None and ros_col is None:
        # 运行时粗算：若面板仅有净利/营收
        if "expr_net_profit" in px.columns and "expr_oper_rev" in px.columns:
            rev = pd.to_numeric(px["expr_oper_rev"], errors="coerce")
            np_ = pd.to_numeric(px["expr_net_profit"], errors="coerce")
            ros = np_ / rev.replace(0, pd.NA)
            px = px.copy()
            px["expr_ros"] = ros
            ros_col = "expr_ros"
        else:
            return pd.DataFrame(columns=["date", "close", "note"])

    improve = float(params.get("ros_improve") or params.get("margin_improve") or 0.005)
    if dros_col is not None:
        dros = pd.to_numeric(px[dros_col], errors="coerce")
        evt = _funda_event(px[dros_col])
        gate = evt & dros.notna() & (dros >= improve)
    else:
        ros = pd.to_numeric(px[ros_col], errors="coerce")
        dros = ros - ros.shift(1)
        evt = _funda_event(px[ros_col])
        gate = evt & dros.notna() & (dros >= improve)

    if "expr_net_profit" in px.columns:
        np_pos = pd.to_numeric(px["expr_net_profit"], errors="coerce") > 0
        gate = gate & np_pos.fillna(False)
    if "expr_oper_rev" in px.columns:
        rev_pos = pd.to_numeric(px["expr_oper_rev"], errors="coerce") > 0
        gate = gate & rev_pos.fillna(False)
    if params.get("ros_min") is not None and ros_col is not None:
        ros_now = pd.to_numeric(px[ros_col], errors="coerce")
        gate = gate & (ros_now >= float(params.get("ros_min") or 0.0))

    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate.fillna(False)
    tech = _tech_break_confirm(px, params)
    m = (hot & tech).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "快报ROS改善突破"
    return out


def signal_fcst_np_proxy_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """弱 ROS 代理：仅业绩预告净利增速达标 + 同技术突破。

    预告无营收，无法算真 ROS；用 fcst_change_min（同比增速下限，百分数）作代理。
    PIT：首次公告日（S_PROFITNOTICE_FIRSTANNDATE）asof。
    """
    if "fcst_change_min" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    chg = pd.to_numeric(px["fcst_change_min"], errors="coerce")
    chg_pct = chg.where(chg.abs() > 5.0, chg * 100.0)
    thr = float(params.get("fcst_chg_min") or params.get("explosive_chg") or 20.0)
    # thr 兼容小数（0.2=20%）
    if abs(thr) <= 5.0:
        thr = thr * 100.0
    chg_ok = chg_pct.notna() & (chg_pct >= thr)

    style = (
        pd.to_numeric(px["fcst_style"], errors="coerce")
        if "fcst_style" in px.columns
        else pd.Series(pd.NA, index=px.index)
    )
    style_skip = style.isin(list(_FCST_STYLE_SKIP))
    style_pos = style.isna() | style.isin(list(_FCST_STYLE_POSITIVE))

    np_min = (
        pd.to_numeric(px["fcst_np_min"], errors="coerce")
        if "fcst_np_min" in px.columns
        else pd.Series(pd.NA, index=px.index)
    )
    prior = np_min / (1.0 + chg_pct / 100.0)
    base_loss = np_min.notna() & chg_pct.notna() & (prior <= 0)
    np_pos = np_min.isna() | (np_min > 0)

    abstract_turn = pd.Series(False, index=px.index)
    if "fcst_abstract" in px.columns:
        abstract_turn = px["fcst_abstract"].astype(str).str.contains("扭亏", na=False)

    gate = chg_ok & style_pos & (~style_skip) & np_pos & (~base_loss) & (~abstract_turn)
    evt = _funda_event(px["fcst_change_min"]) & gate.fillna(False)

    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(evt.fillna(False), lag) if lag > 0 else evt.fillna(False)
    tech = _tech_break_confirm(px, params)
    m = (hot & tech).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "预告净利代理突破(弱ROS)"
    return out


@lru_cache(maxsize=1)
def _ipo_list_date_map() -> Dict[str, pd.Timestamp]:
    """上市日：本地财务库 S_INFO_LISTDATE。"""
    try:
        from app.services.factors import ashare_fin_db as fin_db

        basic = fin_db.fetch_basic()
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, pd.Timestamp] = {}
    if basic is None or basic.empty:
        return out
    for _, r in basic.iterrows():
        code = r.get("code")
        raw = r.get("S_INFO_LISTDATE")
        if not code or raw is None:
            continue
        s = str(raw).strip()
        try:
            if len(s) == 8 and s.isdigit():
                out[str(code)] = pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
            else:
                out[str(code)] = pd.Timestamp(s)
        except Exception:  # noqa: BLE001
            continue
    return out


def _ipo_crash_ok(px: pd.DataFrame, age_days: pd.Series, params: Dict[str, Any]) -> pd.Series:
    """上市后 0–N 月内是否出现过大跌（相对上市后峰值最大回撤）。

    参数：
    - ``ipo_crash_months``：观察窗（默认 18 月，日历近似 30.44 天/月）
    - ``ipo_crash_dd``：阈值，如 -0.40 / -0.45 / -0.50（最大回撤 ≤ 该值即算大跌）

    一旦在观察窗内触及阈值，之后全程保持 True（供 2.5 年窗入场使用）。
    若行情覆盖不足（观察窗内有效 bar < 20），则回退为上市后至年龄 2.0 年内的最大回撤。
    """
    if not params.get("require_ipo_crash", False):
        return pd.Series(True, index=px.index)
    months = float(params.get("ipo_crash_months") or 18.0)
    thr = float(params.get("ipo_crash_dd") or -0.45)
    if thr > 0:
        thr = -abs(thr)
    crash_end = months * 30.44
    post = age_days.notna() & (age_days >= 0)
    in_win = post & (age_days <= crash_end)
    close = pd.to_numeric(px["close"], errors="coerce")
    peak = close.where(post).cummax()
    dd = close / peak.replace(0, pd.NA) - 1.0

    # 覆盖不足时回退：用上市后至 2.0 年的早期回撤近似「上市后大跌」
    if int(in_win.fillna(False).sum()) < 20:
        in_win = post & (age_days <= 2.0 * 365.25)

    min_dd = dd.where(in_win).cummin()
    hit_in_win = in_win.fillna(False) & (min_dd <= thr).fillna(False)
    # sticky：窗内一旦触发，年龄窗内仍有效
    return hit_in_win.cummax().fillna(False)


def _ipo_consol_ok(px: pd.DataFrame, age_days: pd.Series, params: Dict[str, Any]) -> pd.Series:
    """大跌后、进入 IPO 年龄窗前/内：长期横盘（箱体窄 或 贴近均线）。

    参数：
    - ``consol_window``：横盘观察窗（交易日，默认 120）
    - ``consol_amp_max``：箱体振幅上限 (high-low)/mid（默认 0.32，不过严）
    - ``consol_ma_band``：相对 ma60 偏离上限（默认 0.08）；无 ma60 则用 ma20
    - ``consol_min_age_years``：至少过完大跌窗才认横盘（默认 = ipo_crash_months/12）
    """
    if not params.get("require_consol", False):
        return pd.Series(True, index=px.index)
    win = int(params.get("consol_window") or 120)
    amp_max = float(params.get("consol_amp_max") or 0.32)
    band = float(params.get("consol_ma_band") or 0.08)
    crash_m = float(params.get("ipo_crash_months") or 18.0)
    min_age = float(params.get("consol_min_age_years") if params.get("consol_min_age_years") is not None else (crash_m / 12.0))
    after_crash = age_days.notna() & (age_days / 365.25 >= min_age)

    hi, lo, base = _amp_base(px, win, amp_max)
    ma_col = "ma60" if "ma60" in px.columns else ("ma20" if "ma20" in px.columns else None)
    near_ma = pd.Series(False, index=px.index)
    if ma_col is not None:
        ma = pd.to_numeric(px[ma_col], errors="coerce")
        near_ma = ma.notna() & (px["close"] > 0) & ((px["close"] / ma - 1.0).abs() <= band)
    # 入场日看「此前已横盘」：shift(1)
    consol = (base.fillna(False) | near_ma.fillna(False)).shift(1).fillna(False)
    return after_crash & consol


def _ipo_soft_entry(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    """横盘后软入场：突破（可 soft）或企稳（站上 ma20），不过严。

    ``entry_mode``:
      - soft（默认）：N 日高 soft突破 或 收盘站上 ma20
      - break：仅突破
      - stabilize：仅站上 ma20
      - none / use_break=False：不过滤
    """
    use_brk = params.get("use_break", True)
    brk_raw = params.get("break_days")
    mode = str(params.get("entry_mode") or "soft").lower()
    if use_brk is False or mode in ("none", "off") or (brk_raw is not None and int(brk_raw) <= 0 and mode == "break"):
        if mode in ("none", "off") or use_brk is False:
            return pd.Series(True, index=px.index)

    brk_win = int(brk_raw or 40)
    soft = float(params.get("brk_soft") or 0.985)
    if brk_win == 60 and "high_60" in px.columns:
        hi_ref = px["high_60"].shift(1)
    else:
        hi_ref = px["high"].rolling(brk_win, min_periods=max(5, brk_win // 2)).max().shift(1)
    brk = px["close"] >= hi_ref * soft

    stab = pd.Series(False, index=px.index)
    if "ma20" in px.columns:
        stab = px["ma20"].notna() & (px["close"] > px["ma20"])
        # 企稳：站上 ma20，且不低于近窗中轴过多
        win = int(params.get("consol_window") or 120)
        mid = (
            px["high"].rolling(win, min_periods=max(20, win // 2)).max()
            + px["low"].rolling(win, min_periods=max(20, win // 2)).min()
        ) / 2.0
        stab = stab & mid.notna() & (px["close"] >= mid * float(params.get("stab_mid_floor") or 0.96))

    if mode == "break":
        tech = brk
        if params.get("require_ma20", True) and "ma20" in px.columns:
            tech = tech & px["ma20"].notna() & (px["close"] > px["ma20"])
    elif mode == "stabilize":
        tech = stab
    else:  # soft
        tech = brk.fillna(False) | stab.fillna(False)
        if params.get("require_ma20", False) and "ma20" in px.columns:
            # soft 默认不强制 ma20；显式 require_ma20=True 时叠加
            tech = tech & px["ma20"].notna() & (px["close"] > px["ma20"])
    return tech.fillna(False)


def signal_ipo_age_earn_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """IPO 形态：上市后大跌 → 长期横盘 → 年龄≈2.5 年窗 + 业绩改善 + 软入场。

    上市日优先用列 ``list_date``；否则按 ``code`` 查财务库 S_INFO_LISTDATE。

    形态阈值（可配）：
    - 大跌：``require_ipo_crash`` + ``ipo_crash_months``(12/18) + ``ipo_crash_dd``(-0.40/-0.45/-0.50)
    - 横盘：``require_consol`` + ``consol_window`` + ``consol_amp_max`` / ``consol_ma_band``
    - 年龄：``ipo_age_lo``/``ipo_age_hi``（建议 [2.4, 3.0)）
    - 业绩：毛利/净利率/净利改善（既有）+ 可选 ``require_rev``/``np_min``
    - 入场：``entry_mode=soft|break|stabilize``（横盘后突破或企稳，默认 soft 不过严）
    """
    if "close" not in px.columns or "date" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    if "list_date" in px.columns and pd.to_datetime(px["list_date"], errors="coerce").notna().any():
        ld = pd.to_datetime(px["list_date"], errors="coerce")
    else:
        code = None
        if "code" in px.columns and len(px):
            code = str(px["code"].iloc[0])
        ld_one = _ipo_list_date_map().get(code) if code else None
        if ld_one is None:
            return pd.DataFrame(columns=["date", "close", "note"])
        ld = pd.Series(ld_one, index=px.index)

    dt = pd.to_datetime(px["date"], errors="coerce")
    age_days = (dt - ld).dt.days
    age = age_days / 365.25
    lo = float(params.get("ipo_age_lo") or 2.4)
    hi = float(params.get("ipo_age_hi") or 3.0)
    in_win = age.notna() & (age >= lo) & (age < hi)

    improve = pd.Series(False, index=px.index)
    if "gpMargin" in px.columns:
        gp = _to_dec(px["gpMargin"])
        imp = float(params.get("margin_improve") or 0.003)
        improve = improve | (_funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= imp))
    if "npMargin" in px.columns:
        npm = _to_dec(px["npMargin"])
        imp = float(params.get("np_improve") or params.get("margin_improve") or 0.003)
        improve = improve | (_funda_event(px["npMargin"]) & ((npm - npm.shift(1)) >= imp))
    if "netProfit" in px.columns:
        np_ = pd.to_numeric(px["netProfit"], errors="coerce")
        improve = improve | (_funda_event(px["netProfit"]) & (np_ > np_.shift(1)))

    if params.get("require_rev") and "MBRevenue" in px.columns:
        rev = pd.to_numeric(px["MBRevenue"], errors="coerce")
        rev_ok = _funda_event(px["MBRevenue"]) & (rev > rev.shift(1))
        improve = improve & rev_ok.fillna(False)

    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(improve.fillna(False), lag) if lag > 0 else improve.fillna(False)

    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & (_to_dec(px["npMargin"]) >= float(params.get("np_min") or 0.0))
    if params.get("net_profit_min") is not None and "netProfit" in px.columns:
        hot = hot & (
            pd.to_numeric(px["netProfit"], errors="coerce")
            >= float(params.get("net_profit_min") or 0.0)
        )

    crash_ok = _ipo_crash_ok(px, age_days, params)
    consol_ok = _ipo_consol_ok(px, age_days, params)
    tech = _ipo_soft_entry(px, params)

    m = in_win & hot & crash_ok & consol_ok & tech.fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = f"IPO大跌横盘[{lo},{hi})+业绩改善软入场"
    return out


# ---------------------------------------------------------------------------
# 营收/净利 YoY 增速及其变化趋势（二阶导、由负转正、连续两季改善）
# 口径写清：growth.YOYNI=净利润同比；fin_rev_yoy/fin_np_yoy=累计同报告期 YoY；
# q_np_yoy=正式季报单季净利 YoY（非预告）。
# ---------------------------------------------------------------------------


def _yoy_series(px: pd.DataFrame, col: str) -> Optional[pd.Series]:
    if col not in px.columns:
        return None
    return _to_dec(px[col])


def _yoy_event_delta(raw: pd.Series, yoy: pd.Series) -> tuple[pd.Series, pd.Series]:
    """财报跳变日的 ΔYoY（相对上一披露值）。"""
    evt = _funda_event(raw)
    delta = yoy - yoy.shift(1)
    return evt.fillna(False), delta


def _yoy_consec2_improve(raw: pd.Series, yoy: pd.Series, step: float) -> pd.Series:
    """连续两季 YoY 改善：本季 ΔYoY≥step 且上季 ΔYoY≥step（按披露事件对齐）。"""
    evt, delta = _yoy_event_delta(raw, yoy)
    delta_at = delta.where(evt)
    prev_delta = delta_at.ffill().shift(1)
    return (evt & (delta >= step) & (prev_delta >= step)).fillna(False)


def _yoy_gate_hot(px: pd.DataFrame, gate: pd.Series, params: Dict[str, Any]) -> pd.Series:
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate.fillna(False)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        hot = hot & (px["pe_pct"].isna() | (px["pe_pct"] <= float(params.get("pe_pct_max") or 0.55)))
    return hot.fillna(False)


def signal_ni_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利同比再加速：YOYNI（净利润同比）ΔYoY≥阈值且水平达标后技术入场。

    口径：baostock/growth 缓存 YOYNI（同比小数）；二阶=本期YoY−上期YoY。
    与 dual_yoy_accel 差异：仅需 YOYNI，不强制 YOYPNI。
    """
    col = str(params.get("yoy_col") or "YOYNI")
    yoy = _yoy_series(px, col)
    if yoy is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    evt, delta = _yoy_event_delta(px[col], yoy)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.05)
    gmin = float(params.get("growth_min") or params.get("yoy_min") or 0.08)
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= gmin)
    hot = _yoy_gate_hot(px, gate, params)
    m = hot & _entry_tech(px, params)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "净利同比再加速"
    return out


def signal_ni_yoy_turn_pos_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利同比由负转正：上期 YoY<0（或≤turn_from）、本期 YoY≥turn_to 后入场。"""
    col = str(params.get("yoy_col") or "YOYNI")
    yoy = _yoy_series(px, col)
    if yoy is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    evt = _funda_event(px[col])
    prev = yoy.shift(1)
    turn_from = float(params.get("turn_from") or 0.0)
    turn_to = float(params.get("turn_to") or params.get("growth_min") or 0.0)
    gate = (
        evt
        & prev.notna()
        & yoy.notna()
        & (prev <= turn_from)
        & (yoy >= turn_to)
    )
    # 可选：要求 ΔYoY 足够大，避免贴零噪声
    min_jump = params.get("growth_accel") or params.get("accel_min")
    if min_jump is not None:
        gate = gate & ((yoy - prev) >= float(min_jump))
    hot = _yoy_gate_hot(px, gate.fillna(False), params)
    m = hot & _entry_tech(px, params)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "净利同比由负转正"
    return out


def signal_ni_yoy_consec2_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利同比连续两季改善：连续两期 ΔYoY≥阈值，且本期水平≥growth_min。"""
    col = str(params.get("yoy_col") or "YOYNI")
    yoy = _yoy_series(px, col)
    if yoy is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    step = float(params.get("growth_accel") or params.get("accel_min") or 0.03)
    gmin = float(params.get("growth_min") or params.get("yoy_min") or 0.05)
    consec = _yoy_consec2_improve(px[col], yoy, step)
    gate = consec & yoy.notna() & (yoy >= gmin)
    hot = _yoy_gate_hot(px, gate, params)
    m = hot & _entry_tech(px, params)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "净利同比连续两季改善"
    return out


def signal_q_np_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """单季净利 YoY 再加速（非断层）：q_np_yoy 二阶改善 + 水平门槛 + 技术确认。

    口径：ashare_fin_db 正式季报单季净利 YoY；与 signal_q_np_gap（爆炸式断层）不同。
    """
    if "q_np_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["q_np_yoy"], errors="coerce").astype(float)
    raw = px["q_np_yoy"]
    evt, delta = _yoy_event_delta(raw, yoy)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.10)
    gmin = float(params.get("growth_min") or params.get("yoy_min") or 0.15)
    pos = pd.Series(True, index=px.index)
    if "q_np" in px.columns:
        pos = pd.to_numeric(px["q_np"], errors="coerce") > 0
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= gmin) & pos.fillna(False)
    hot = _yoy_gate_hot(px, gate, params)
    # 默认突破确认（可用 entry=pullback）
    p2 = dict(params)
    if "entry" not in p2:
        p2["entry"] = "break"
    if "break_days" not in p2:
        p2["break_days"] = 60
    m = hot & _entry_tech(px, p2)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "单季净利YoY再加速"
    return out


def signal_rev_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收同比再加速：fin_rev_yoy（累计同报告期营收 YoY）ΔYoY≥阈值后入场。"""
    col = str(params.get("yoy_col") or "fin_rev_yoy")
    if col not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px[col], errors="coerce").astype(float)
    evt, delta = _yoy_event_delta(px[col], yoy)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.05)
    gmin = float(params.get("growth_min") or params.get("yoy_min") or 0.08)
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= gmin)
    hot = _yoy_gate_hot(px, gate, params)
    m = hot & _entry_tech(px, params)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "营收同比再加速"
    return out


def signal_dual_rev_np_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """营收+净利同比双加速：fin_rev_yoy 与 YOYNI/fin_np_yoy 同时再加速。"""
    rev_col = "fin_rev_yoy"
    np_col = "YOYNI" if "YOYNI" in px.columns else ("fin_np_yoy" if "fin_np_yoy" in px.columns else None)
    if rev_col not in px.columns or np_col is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    rev = pd.to_numeric(px[rev_col], errors="coerce").astype(float)
    ni = _to_dec(px[np_col]) if np_col == "YOYNI" else pd.to_numeric(px[np_col], errors="coerce").astype(float)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.04)
    gmin = float(params.get("growth_min") or params.get("yoy_min") or 0.06)
    evt = _funda_event(px[rev_col]) | _funda_event(px[np_col])
    both = (
        evt
        & rev.notna()
        & ni.notna()
        & ((rev - rev.shift(1)) >= accel)
        & ((ni - ni.shift(1)) >= accel)
        & (rev >= gmin)
        & (ni >= gmin)
    )
    hot = _yoy_gate_hot(px, both.fillna(False), params)
    m = hot & _entry_tech(px, params)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "营收净利同比双加速"
    return out


# ----- 利润因果链 Round1：L2 驱动变量（正交于纯 YoY #198–#200） -----


def signal_cl_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债 YoY 再加速：需求领先指标的二阶（ΔYoY），非单纯高同比水平。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce").astype(float)
    yoy = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
    evt, delta = _yoy_event_delta(px["contract_liab_yoy"], yoy)
    accel = float(params.get("cl_accel") or params.get("growth_accel") or params.get("accel_min") or 0.08)
    ymin = float(params.get("yoy_min") or 0.10)
    cl_pos = pd.Series(True, index=px.index)
    if "contract_liab" in px.columns:
        cl_pos = pd.to_numeric(px["contract_liab"], errors="coerce") > 0
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= ymin) & cl_pos.fillna(False)
    hot = _yoy_gate_hot(px, gate.fillna(False), params)
    m = hot & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "合同负债YoY再加速"
    return out


def signal_gp_rev_dual_hit_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利+营收双击：毛利率环比改善 × 营收同比达标/再加速（利润≈收入×利润率）。"""
    if "gpMargin" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    gp_imp = float(params.get("gp_improve") or params.get("margin_improve") or 0.005)
    gmin = float(params.get("rev_yoy_min") or params.get("growth_min") or params.get("yoy_min") or 0.08)
    racc = float(params.get("growth_accel") or params.get("accel_min") or 0.0)
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= gp_imp)
    rev_evt = _funda_event(px["fin_rev_yoy"])
    rev_ok = rev.notna() & (rev >= gmin)
    if racc > 0:
        rev_ok = rev_ok & rev_evt & ((rev - rev.shift(1)) >= racc)
    gp_min = params.get("margin_min") or params.get("gp_min")
    gp_level = gp >= float(gp_min) if gp_min is not None else pd.Series(True, index=px.index)
    # 要求两闸同窗：毛利改善热窗 ∩ 营收条件热窗
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gp_up.fillna(False), lag) & _funda_hot_window(
        (rev_evt & rev_ok).fillna(False) if racc > 0 else rev_ok.fillna(False), lag
    )
    if gp_min is not None:
        hot = hot & gp_level.fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "毛利营收双击"
    return out


def signal_opex_down_rev_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """费用率下行 + 营收加速：销售+管理费用/营收下降，同时营收 YoY 再加速。"""
    if "fin_opex_ratio" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    opex = pd.to_numeric(px["fin_opex_ratio"], errors="coerce").astype(float)
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    opex_imp = float(params.get("opex_improve") or 0.005)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.05)
    gmin = float(params.get("growth_min") or params.get("rev_yoy_min") or 0.06)
    opex_evt = _funda_event(px["fin_opex_ratio"])
    opex_down = opex_evt & opex.notna() & ((opex.shift(1) - opex) >= opex_imp)
    if params.get("opex_max") is not None:
        opex_down = opex_down & (opex <= float(params.get("opex_max") or 0.35))
    rev_evt, rev_delta = _yoy_event_delta(px["fin_rev_yoy"], rev)
    rev_acc = rev_evt & rev_delta.notna() & (rev_delta >= accel) & rev.notna() & (rev >= gmin)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(opex_down.fillna(False), lag) & _funda_hot_window(rev_acc.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "费用率下行+营收加速"
    return out


def signal_inv_delever_rev_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """存货/营收下行 + 营收同比：去库存/周转改善伴随需求（营收）不塌。"""
    if "fin_inv_to_rev" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    invr = pd.to_numeric(px["fin_inv_to_rev"], errors="coerce").astype(float)
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    inv_imp = float(params.get("inv_improve") or 0.02)
    gmin = float(params.get("growth_min") or params.get("rev_yoy_min") or 0.05)
    evt = _funda_event(px["fin_inv_to_rev"])
    inv_down = evt & invr.notna() & ((invr.shift(1) - invr) >= inv_imp)
    if params.get("inv_max") is not None:
        inv_down = inv_down & (invr <= float(params.get("inv_max") or 0.8))
    rev_ok = rev.notna() & (rev >= gmin)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(inv_down.fillna(False), lag) & rev_ok.fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "存货强度下行+营收"
    return out


def signal_ar_tighten_rev_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """应收/营收下行 + 营收同比：回款质量改善，收入增长更可信。"""
    if "fin_ar_to_rev" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    arr = pd.to_numeric(px["fin_ar_to_rev"], errors="coerce").astype(float)
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    ar_imp = float(params.get("ar_improve") or 0.015)
    gmin = float(params.get("growth_min") or params.get("rev_yoy_min") or 0.05)
    evt = _funda_event(px["fin_ar_to_rev"])
    ar_down = evt & arr.notna() & ((arr.shift(1) - arr) >= ar_imp)
    if params.get("ar_max") is not None:
        ar_down = ar_down & (arr <= float(params.get("ar_max") or 0.6))
    rev_ok = rev.notna() & (rev >= gmin)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(ar_down.fillna(False), lag) & rev_ok.fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "应收强度下行+营收"
    return out


# ----- 结构大批量 Round1：ROE/ROA/杠杆/现金流质量/双击组合 -----


def signal_roe_struct_improve_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE 结构改善：roeAvg 环比升 + 可选毛利/净利地板，技术确认。"""
    if "roeAvg" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    roe_imp = float(params.get("roe_improve") or 0.004)
    evt = _funda_event(px["roeAvg"])
    roe_up = evt & ((roe - roe.shift(1)) >= roe_imp)
    if params.get("roe_min") is not None:
        roe_up = roe_up & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(roe_up.fillna(False), lag)
    if params.get("margin_min") is not None and "gpMargin" in px.columns:
        hot = hot & _margin_ok(px["gpMargin"], float(params.get("margin_min") or 0.0)).fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "ROE结构改善"
    return out


def signal_roa_improve_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROA 改善：归母净利/总资产环比升（资产盈利能力结构）。"""
    if "fin_roa" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roa = pd.to_numeric(px["fin_roa"], errors="coerce").astype(float)
    roa_imp = float(params.get("roa_improve") or 0.002)
    evt = _funda_event(px["fin_roa"])
    roa_up = evt & roa.notna() & ((roa - roa.shift(1)) >= roa_imp)
    if params.get("roa_min") is not None:
        roa_up = roa_up & (roa >= float(params.get("roa_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(roa_up.fillna(False), lag)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)).fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "ROA改善"
    return out


def signal_roe_roa_sync_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """ROE×ROA 双击：权益与资产盈利能力同步改善。"""
    if "roeAvg" not in px.columns or "fin_roa" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    roe = _to_dec(px["roeAvg"])
    roa = pd.to_numeric(px["fin_roa"], errors="coerce").astype(float)
    roe_imp = float(params.get("roe_improve") or 0.003)
    roa_imp = float(params.get("roa_improve") or 0.0015)
    roe_up = _funda_event(px["roeAvg"]) & ((roe - roe.shift(1)) >= roe_imp)
    roa_up = _funda_event(px["fin_roa"]) & roa.notna() & ((roa - roa.shift(1)) >= roa_imp)
    if params.get("roe_min") is not None:
        roe_up = roe_up & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0))
    if params.get("roa_min") is not None:
        roa_up = roa_up & (roa >= float(params.get("roa_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(roe_up.fillna(False), lag) & _funda_hot_window(roa_up.fillna(False), lag)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "ROE×ROA双击"
    return out


def signal_lev_delever_quality_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """杠杆下行 + 质量地板：资产负债率下降且 ROE/净利不过差。"""
    if "fin_lev" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    lev = pd.to_numeric(px["fin_lev"], errors="coerce").astype(float)
    lev_imp = float(params.get("lev_improve") or 0.02)
    evt = _funda_event(px["fin_lev"])
    lev_down = evt & lev.notna() & ((lev.shift(1) - lev) >= lev_imp)
    if params.get("lev_max") is not None:
        lev_down = lev_down & (lev <= float(params.get("lev_max") or 0.7))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(lev_down.fillna(False), lag)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)).fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "杠杆下行+质量"
    return out


def signal_cfo_quality_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """经营现金流质量：cfo/归母净利水平或改善 + 可选利润率地板。"""
    if "cfo_to_np" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cfoq = pd.to_numeric(px["cfo_to_np"], errors="coerce").astype(float)
    cfo_min = float(params.get("cfo_min") or 0.8)
    cfo_imp = float(params.get("cfo_improve") or 0.0)
    evt = _funda_event(px["cfo_to_np"])
    gate = evt & cfoq.notna() & (cfoq >= cfo_min)
    if cfo_imp > 0:
        gate = gate & ((cfoq - cfoq.shift(1)) >= cfo_imp)
    # 排除极端负利润导致的比值爆炸
    gate = gate & (cfoq.abs() <= 8.0)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "现金流质量"
    return out


def signal_gp_opex_dual_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利↑ × 费用率↓ 双击：定价/成本结构同步改善。"""
    if "gpMargin" not in px.columns or "fin_opex_ratio" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    opex = pd.to_numeric(px["fin_opex_ratio"], errors="coerce").astype(float)
    gp_imp = float(params.get("gp_improve") or params.get("margin_improve") or 0.004)
    opex_imp = float(params.get("opex_improve") or 0.004)
    gp_up = _funda_event(px["gpMargin"]) & ((gp - gp.shift(1)) >= gp_imp)
    opex_down = _funda_event(px["fin_opex_ratio"]) & opex.notna() & ((opex.shift(1) - opex) >= opex_imp)
    if params.get("margin_min") is not None:
        gp_up = gp_up & (gp >= float(params.get("margin_min") or 0.0))
    if params.get("opex_max") is not None:
        opex_down = opex_down & (opex <= float(params.get("opex_max") or 0.4))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gp_up.fillna(False), lag) & _funda_hot_window(opex_down.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "毛利费用双击"
    return out


def signal_ar_inv_dual_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """应收+存货强度双下行：营运资本结构改善。"""
    if "fin_ar_to_rev" not in px.columns or "fin_inv_to_rev" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    arr = pd.to_numeric(px["fin_ar_to_rev"], errors="coerce").astype(float)
    invr = pd.to_numeric(px["fin_inv_to_rev"], errors="coerce").astype(float)
    ar_imp = float(params.get("ar_improve") or 0.01)
    inv_imp = float(params.get("inv_improve") or 0.015)
    ar_down = _funda_event(px["fin_ar_to_rev"]) & arr.notna() & ((arr.shift(1) - arr) >= ar_imp)
    inv_down = _funda_event(px["fin_inv_to_rev"]) & invr.notna() & ((invr.shift(1) - invr) >= inv_imp)
    if params.get("ar_max") is not None:
        ar_down = ar_down & (arr <= float(params.get("ar_max") or 0.55))
    if params.get("inv_max") is not None:
        inv_down = inv_down & (invr <= float(params.get("inv_max") or 0.85))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(ar_down.fillna(False), lag) & _funda_hot_window(inv_down.fillna(False), lag)
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        hot = hot & (rev.notna() & (rev >= float(params.get("growth_min") or 0.0))).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "应收存货双改善"
    return out


def signal_asset_turn_up_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """资产周转提升：营收/总资产环比升（效率结构）。"""
    if "fin_asset_turn" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    at = pd.to_numeric(px["fin_asset_turn"], errors="coerce").astype(float)
    at_imp = float(params.get("asset_turn_improve") or 0.01)
    evt = _funda_event(px["fin_asset_turn"])
    at_up = evt & at.notna() & ((at - at.shift(1)) >= at_imp)
    if params.get("asset_turn_min") is not None:
        at_up = at_up & (at >= float(params.get("asset_turn_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(at_up.fillna(False), lag)
    if params.get("roe_min") is not None and "roeAvg" in px.columns:
        hot = hot & _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "资产周转提升"
    return out


# ----- 物理世界结构 Round1：收现 / 转固 / 应付授信 / 资本开支 / CFO 二阶 -----


def signal_cash_collect_up_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """销售收现比上行：销售商品收到的现金/营收环比改善，收入含金量上升。"""
    if "fin_cash_collect" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cc = pd.to_numeric(px["fin_cash_collect"], errors="coerce").astype(float)
    cc_imp = float(params.get("collect_improve") or 0.03)
    evt = _funda_event(px["fin_cash_collect"])
    gate = evt & cc.notna() & ((cc - cc.shift(1)) >= cc_imp)
    if params.get("collect_min") is not None:
        gate = gate & (cc >= float(params.get("collect_min") or 0.85))
    gate = gate & (cc > 0.2) & (cc < 2.5)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        hot = hot & (rev.notna() & (rev >= float(params.get("growth_min") or 0.0))).fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "销售收现比上行"
    return out


def signal_cip_convert_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """在建工程转固：CIP 下降且固定资产上升 —— 产能落地的物理时钟。"""
    need = ("fin_cip_delta", "fin_fa_delta")
    if any(c not in px.columns for c in need):
        return pd.DataFrame(columns=["date", "close", "note"])
    cip_d = pd.to_numeric(px["fin_cip_delta"], errors="coerce")
    fa_d = pd.to_numeric(px["fin_fa_delta"], errors="coerce")
    cip_drop = float(params.get("cip_drop") or 0.0)
    fa_rise = float(params.get("fa_rise") or 0.0)
    evt_col = "fin_cip" if "fin_cip" in px.columns else "fin_cip_delta"
    evt = _funda_event(px[evt_col])
    gate = evt & cip_d.notna() & fa_d.notna() & (cip_d < -abs(cip_drop)) & (fa_d > abs(fa_rise))
    if "fin_cip_share" in px.columns and params.get("cip_share_max") is not None:
        share = pd.to_numeric(px["fin_cip_share"], errors="coerce")
        gate = gate & share.notna() & (share <= float(params.get("cip_share_max") or 0.5))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        hot = hot & (rev.notna() & (rev >= float(params.get("growth_min") or 0.0))).fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "在建工程转固"
    return out


def signal_ap_credit_rev_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """应付/营收上行 + 营收增长：扩张期占用供应商信用。"""
    if "fin_ap_to_rev" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    apr = pd.to_numeric(px["fin_ap_to_rev"], errors="coerce").astype(float)
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    ap_imp = float(params.get("ap_improve") or 0.015)
    gmin = float(params.get("growth_min") or params.get("rev_yoy_min") or 0.06)
    evt = _funda_event(px["fin_ap_to_rev"])
    ap_up = evt & apr.notna() & ((apr - apr.shift(1)) >= ap_imp)
    if params.get("ap_max") is not None:
        ap_up = ap_up & (apr <= float(params.get("ap_max") or 0.8))
    rev_ok = rev.notna() & (rev >= gmin)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(ap_up.fillna(False), lag) & rev_ok.fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "应付授信扩张"
    return out


def signal_capex_cycle_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """资本开支强度上行 + 营收加速：扩张周期。"""
    if "fin_capex_to_rev" not in px.columns or "fin_rev_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cx = pd.to_numeric(px["fin_capex_to_rev"], errors="coerce").astype(float)
    rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce").astype(float)
    cx_imp = float(params.get("capex_improve") or 0.02)
    gmin = float(params.get("growth_min") or 0.05)
    accel = float(params.get("growth_accel") or params.get("accel_min") or 0.0)
    evt = _funda_event(px["fin_capex_to_rev"])
    cx_up = evt & cx.notna() & ((cx - cx.shift(1)) >= cx_imp) & (cx > 0)
    if params.get("capex_min") is not None:
        cx_up = cx_up & (cx >= float(params.get("capex_min") or 0.0))
    rev_ok = rev.notna() & (rev >= gmin)
    if accel > 0:
        rev_evt, rev_delta = _yoy_event_delta(px["fin_rev_yoy"], rev)
        rev_ok = rev_ok & rev_evt & rev_delta.notna() & (rev_delta >= accel)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(cx_up.fillna(False), lag) & _funda_hot_window(rev_ok.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "资本开支扩张周期"
    return out


def signal_cfo_yoy_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """经营现金流 YoY 再加速：现金利润二阶。"""
    if "fin_cfo_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["fin_cfo_yoy"], errors="coerce").astype(float)
    accel = float(params.get("cfo_accel") or params.get("accel_min") or 0.08)
    ymin = float(params.get("cfo_yoy_min") or params.get("yoy_min") or 0.05)
    evt, delta = _yoy_event_delta(px["fin_cfo_yoy"], yoy)
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= ymin)
    if "cfo" in px.columns and params.get("require_cfo_pos", True):
        cfo = pd.to_numeric(px["cfo"], errors="coerce")
        gate = gate & cfo.notna() & (cfo > 0)
    hot = _yoy_gate_hot(px, gate.fillna(False), params)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "经营现金流YoY再加速"
    return out


# ----- 银行业特色：净息差代理 / 中收 / 信用减值 / 贷款拨备 -----


def _bank_soft_value_gate(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    """可选软估值闸（非主逻辑）：缺列或未设阈值时恒真。"""
    ok = pd.Series(True, index=px.index)
    if params.get("pb_pct_max") is not None and "pb_pct" in px.columns:
        thr = float(params["pb_pct_max"])
        ok = ok & (px["pb_pct"].isna() | (px["pb_pct"] <= thr))
    if params.get("pe_pct_max") is not None and "pe_pct" in px.columns:
        thr = float(params["pe_pct_max"])
        ok = ok & (px["pe_pct"].isna() | (px["pe_pct"] <= thr))
    if params.get("pb_max") is not None and "pbMRQ" in px.columns:
        thr = float(params["pb_max"])
        ok = ok & px["pbMRQ"].notna() & (px["pbMRQ"] > 0) & (px["pbMRQ"] <= thr)
    return ok


def _bank_roe_soft(px: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
    if params.get("roe_min") is None or "roeAvg" not in px.columns:
        return pd.Series(True, index=px.index)
    return _roe_ok(px["roeAvg"], float(params.get("roe_min") or 0.08)) | px["roeAvg"].isna()


def signal_bank_nim_improve_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """息差代理改善：fin_nim_proxy 环比上行 + 技术确认。"""
    if "fin_nim_proxy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    nim = pd.to_numeric(px["fin_nim_proxy"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_nim_proxy_delta"], errors="coerce")
        if "fin_nim_proxy_delta" in px.columns
        else nim - nim.shift(1)
    )
    improve = float(params.get("nim_improve") or 1e-4)
    evt = _funda_event(px["fin_nim_proxy"])
    gate = evt & dlt.notna() & (dlt >= improve) & nim.notna() & (nim > 0)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _bank_roe_soft(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行息差代理改善"
    return out


def signal_bank_net_int_yoy_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净息收入同比改善/再加速。"""
    if "fin_net_int_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["fin_net_int_yoy"], errors="coerce")
    ymin = float(params.get("net_int_yoy_min") or params.get("yoy_min") or 0.0)
    evt, delta = _yoy_event_delta(px["fin_net_int_yoy"], yoy)
    accel = params.get("net_int_accel")
    gate = evt & yoy.notna() & (yoy >= ymin)
    if accel is not None:
        gate = gate & delta.notna() & (delta >= float(accel))
    else:
        # 默认要求同比环比抬升
        gate = gate & delta.notna() & (delta >= float(params.get("yoy_improve") or 0.01))
    hot = _yoy_gate_hot(px, gate.fillna(False), params)
    m = hot & _bank_soft_value_gate(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "净息收入YoY改善"
    return out


def signal_bank_fee_mix_improve(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """中收占比抬升：收入结构多元化。"""
    if "fin_fee_share" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    share = pd.to_numeric(px["fin_fee_share"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_fee_share_delta"], errors="coerce")
        if "fin_fee_share_delta" in px.columns
        else share - share.shift(1)
    )
    improve = float(params.get("fee_share_improve") or 0.005)
    level = float(params.get("fee_share_min") or 0.05)
    evt = _funda_event(px["fin_fee_share"])
    gate = evt & dlt.notna() & (dlt >= improve) & share.notna() & (share >= level)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _bank_roe_soft(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行中收占比抬升"
    return out


def signal_bank_fee_yoy_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """中收同比高增突破/回踩。"""
    if "fin_fee_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["fin_fee_yoy"], errors="coerce")
    ymin = float(params.get("fee_yoy_min") or 0.08)
    evt, delta = _yoy_event_delta(px["fin_fee_yoy"], yoy)
    gate = evt & yoy.notna() & (yoy >= ymin)
    if params.get("fee_yoy_accel") is not None:
        gate = gate & delta.notna() & (delta >= float(params["fee_yoy_accel"]))
    hot = _yoy_gate_hot(px, gate.fillna(False), params)
    m = hot & _bank_soft_value_gate(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行中收YoY高增"
    return out


def signal_bank_impair_ease_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """信用减值压力缓解：impair/营业利润 下行。"""
    if "fin_impair_to_op" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ratio = pd.to_numeric(px["fin_impair_to_op"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_impair_to_op_delta"], errors="coerce")
        if "fin_impair_to_op_delta" in px.columns
        else ratio - ratio.shift(1)
    )
    ease = -abs(float(params.get("impair_ease") or 0.02))
    cap = float(params.get("impair_max") or 0.80)
    evt = _funda_event(px["fin_impair_to_op"])
    gate = evt & dlt.notna() & (dlt <= ease) & ratio.notna() & (ratio <= cap) & (ratio > 0)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _bank_roe_soft(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行减值压力缓解"
    return out


def signal_bank_loan_growth_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """贷款扩张 + 减值不恶化（质量扩表）。"""
    if "fin_loan_growth" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    lg = pd.to_numeric(px["fin_loan_growth"], errors="coerce")
    gmin = float(params.get("loan_growth_min") or 0.05)
    evt = _funda_event(px["fin_loan_growth"])
    gate = evt & lg.notna() & (lg >= gmin)
    if "fin_impair_to_op_delta" in px.columns:
        idlt = pd.to_numeric(px["fin_impair_to_op_delta"], errors="coerce")
        # 允许轻微上行，但不能明显恶化
        gate = gate & (idlt.isna() | (idlt <= float(params.get("impair_worsen_max") or 0.03)))
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _bank_roe_soft(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行质量扩表"
    return out


def signal_bank_prov_thicken(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """拨备厚度抬升：prov/loans 上行（主动夯实）。"""
    if "fin_prov_loan" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    pl = pd.to_numeric(px["fin_prov_loan"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_prov_loan_delta"], errors="coerce")
        if "fin_prov_loan_delta" in px.columns
        else pl - pl.shift(1)
    )
    improve = float(params.get("prov_improve") or 0.001)
    level = float(params.get("prov_loan_min") or 0.015)
    evt = _funda_event(px["fin_prov_loan"])
    gate = evt & dlt.notna() & (dlt >= improve) & pl.notna() & (pl >= level)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行拨备夯实"
    return out


def signal_bank_int_spread_improve(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """利息收支差改善：(利息收入-利息支出)/利息收入 上行。"""
    if "fin_int_spread" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    sp = pd.to_numeric(px["fin_int_spread"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_int_spread_delta"], errors="coerce")
        if "fin_int_spread_delta" in px.columns
        else sp - sp.shift(1)
    )
    improve = float(params.get("spread_improve") or 0.005)
    level = float(params.get("spread_min") or 0.35)
    evt = _funda_event(px["fin_int_spread"])
    gate = evt & dlt.notna() & (dlt >= improve) & sp.notna() & (sp >= level)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行利息收支差改善"
    return out


def signal_bank_dual_int_fee(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净息+中收双增：息差业务与非息同步改善。"""
    if "fin_net_int_yoy" not in px.columns or "fin_fee_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni = pd.to_numeric(px["fin_net_int_yoy"], errors="coerce")
    fee = pd.to_numeric(px["fin_fee_yoy"], errors="coerce")
    ni_min = float(params.get("net_int_yoy_min") or 0.0)
    fee_min = float(params.get("fee_yoy_min") or 0.05)
    evt = _funda_event(px["fin_net_int_yoy"]) | _funda_event(px["fin_fee_yoy"])
    gate = evt & ni.notna() & fee.notna() & (ni >= ni_min) & (fee >= fee_min)
    lag = int(params.get("funda_lag") or 20)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _bank_roe_soft(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行净息+中收双增"
    return out


def signal_bank_impair_turn_prov(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """减值见顶回落 + 拨备厚度尚可：资产质量拐点。"""
    need = ("fin_impair_to_op", "fin_prov_loan")
    if any(c not in px.columns for c in need):
        return pd.DataFrame(columns=["date", "close", "note"])
    ratio = pd.to_numeric(px["fin_impair_to_op"], errors="coerce")
    dlt = (
        pd.to_numeric(px["fin_impair_to_op_delta"], errors="coerce")
        if "fin_impair_to_op_delta" in px.columns
        else ratio - ratio.shift(1)
    )
    pl = pd.to_numeric(px["fin_prov_loan"], errors="coerce")
    ease = -abs(float(params.get("impair_ease") or 0.015))
    # 前期减值偏高（有压力）再缓解，避免一直低减值噪声
    prior_high = ratio.shift(1) >= float(params.get("impair_prior_min") or 0.25)
    prov_ok = pl.notna() & (pl >= float(params.get("prov_loan_min") or 0.015))
    evt = _funda_event(px["fin_impair_to_op"])
    gate = evt & prior_high.fillna(False) & dlt.notna() & (dlt <= ease) & prov_ok
    lag = int(params.get("funda_lag") or 24)
    hot = _funda_hot_window(gate.fillna(False), lag) if lag > 0 else gate
    m = hot & _bank_soft_value_gate(px, params) & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行资产质量拐点"
    return out


# ----- 银行业截面分化：相对同行强弱 / 质量 / 错杀反转 -----


def _cs_ok(px: pd.DataFrame, col: str, lo: float | None = None, hi: float | None = None) -> pd.Series:
    if col not in px.columns:
        return pd.Series(False, index=px.index)
    s = pd.to_numeric(px[col], errors="coerce")
    m = s.notna()
    if lo is not None:
        m = m & (s >= float(lo))
    if hi is not None:
        m = m & (s <= float(hi))
    return m


def signal_bank_cs_mom_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """同行强势 + 质量不差：60日收益排名靠前，减值排名不过差。"""
    mom_min = float(params.get("cs_mom_min") or 0.70)
    aq_max = float(params.get("cs_impair_max") or 0.60)
    q_min = float(params.get("cs_quality_min") or 0.40)
    gate = _cs_ok(px, "cs_ret_60", lo=mom_min)
    if "cs_fin_impair_to_op" in px.columns:
        gate = gate & _cs_ok(px, "cs_fin_impair_to_op", hi=aq_max)
    if "cs_quality" in px.columns:
        gate = gate & _cs_ok(px, "cs_quality", lo=q_min)
    # 相对超额为正，避免全行业普涨噪声
    if "x_ret_60" in px.columns:
        x = pd.to_numeric(px["x_ret_60"], errors="coerce")
        gate = gate & x.notna() & (x >= float(params.get("x_ret60_min") or 0.0))
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行同行强势质量"
    return out


def signal_bank_cs_cheap_quality(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """同行相对便宜 + 相对高 ROE（银行内 GARP）。"""
    pb_max = float(params.get("cs_pb_max") or 0.35)
    roe_min = float(params.get("cs_roe_min") or 0.60)
    gate = _cs_ok(px, "cs_pb_pct", hi=pb_max) & _cs_ok(px, "cs_roeAvg", lo=roe_min)
    if "cs_quality" in px.columns:
        gate = gate & _cs_ok(px, "cs_quality", lo=float(params.get("cs_quality_min") or 0.45))
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行相对低估高质量"
    return out


def signal_bank_cs_fee_leader(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """中收结构领先：fee_share 同行排名高。"""
    fee_min = float(params.get("cs_fee_min") or 0.70)
    gate = _cs_ok(px, "cs_fin_fee_share", lo=fee_min)
    if "cs_fin_fee_yoy" in px.columns:
        gate = gate & (
            px["cs_fin_fee_yoy"].isna()
            | (pd.to_numeric(px["cs_fin_fee_yoy"], errors="coerce") >= float(params.get("cs_fee_yoy_min") or 0.40))
        )
    # 可选：要求绝对 fee_share 也在改善
    if "fin_fee_share_delta" in px.columns and params.get("require_fee_improve", True):
        dlt = pd.to_numeric(px["fin_fee_share_delta"], errors="coerce")
        evt = _funda_event(px["fin_fee_share"]) if "fin_fee_share" in px.columns else dlt.notna()
        lag = int(params.get("funda_lag") or 20)
        improve = evt & dlt.notna() & (dlt >= float(params.get("fee_share_improve") or 0.0))
        hot = _funda_hot_window(improve.fillna(False), lag) if lag > 0 else improve
        gate = gate & hot
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行中收同行领先"
    return out


def signal_bank_cs_aq_leader(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """资产质量相对最优：减值压力同行低分位 + 拨备厚度不差。"""
    aq_max = float(params.get("cs_impair_max") or 0.30)
    prov_min = float(params.get("cs_prov_min") or 0.45)
    gate = _cs_ok(px, "cs_fin_impair_to_op", hi=aq_max)
    if "cs_fin_prov_loan" in px.columns:
        gate = gate & _cs_ok(px, "cs_fin_prov_loan", lo=prov_min)
    if "cs_roeAvg" in px.columns:
        gate = gate & _cs_ok(px, "cs_roeAvg", lo=float(params.get("cs_roe_min") or 0.40))
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行资产质量同行领先"
    return out


def signal_bank_cs_loan_leader(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """扩表领先且质量可控：贷款增速同行高、减值不过差。"""
    lg_min = float(params.get("cs_loan_min") or 0.70)
    aq_max = float(params.get("cs_impair_max") or 0.65)
    gate = _cs_ok(px, "cs_fin_loan_growth", lo=lg_min)
    if "cs_fin_impair_to_op" in px.columns:
        gate = gate & _cs_ok(px, "cs_fin_impair_to_op", hi=aq_max)
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行质量扩表同行领先"
    return out


def signal_bank_cs_nim_leader(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """息差代理同行领先。"""
    nim_min = float(params.get("cs_nim_min") or 0.65)
    gate = _cs_ok(px, "cs_fin_nim_proxy", lo=nim_min)
    if "fin_nim_proxy_delta" in px.columns and params.get("require_nim_improve", False):
        dlt = pd.to_numeric(px["fin_nim_proxy_delta"], errors="coerce")
        evt = _funda_event(px["fin_nim_proxy"]) if "fin_nim_proxy" in px.columns else dlt.notna()
        lag = int(params.get("funda_lag") or 20)
        hot = _funda_hot_window(
            (evt & dlt.notna() & (dlt >= float(params.get("nim_improve") or 0.0))).fillna(False),
            lag,
        )
        gate = gate & hot
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行息差同行领先"
    return out


def signal_bank_cs_catchup(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """错杀反转：前期相对弱势、质量尚可，短期动量回升。"""
    lag = int(params.get("weak_lag") or 20)
    weak_max = float(params.get("cs_weak_max") or 0.35)
    now_min = float(params.get("cs_now_min") or 0.50)
    q_min = float(params.get("cs_quality_min") or 0.50)
    if "cs_ret_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cs60 = pd.to_numeric(px["cs_ret_60"], errors="coerce")
    was_weak = cs60.shift(lag) <= weak_max
    now_ok = False
    if "cs_ret_20" in px.columns:
        now_ok = pd.to_numeric(px["cs_ret_20"], errors="coerce") >= now_min
    else:
        now_ok = cs60 >= now_min
    q_ok = True
    if "cs_quality" in px.columns:
        q_ok = _cs_ok(px, "cs_quality", lo=q_min)
    elif "cs_roeAvg" in px.columns:
        q_ok = _cs_ok(px, "cs_roeAvg", lo=q_min)
    gate = was_weak.fillna(False) & now_ok.fillna(False) & q_ok
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行高质量错杀反转"
    return out


def signal_bank_cs_tier_mom(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """分层内相对强势：大行/股份/城商各自内部选强。"""
    if "cs_tier_ret_60" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    tmin = float(params.get("cs_tier_mom_min") or 0.75)
    gate = _cs_ok(px, "cs_tier_ret_60", lo=tmin)
    if "cs_tier_roe" in px.columns:
        gate = gate & (
            px["cs_tier_roe"].isna()
            | (pd.to_numeric(px["cs_tier_roe"], errors="coerce") >= float(params.get("cs_tier_roe_min") or 0.40))
        )
    # 可选只做某一层
    tier = params.get("tier_only")
    if tier and "tier" in px.columns:
        gate = gate & (px["tier"].astype(str) == str(tier))
    m = gate & _entry_tech(px, params)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行分层内相对强势"
    return out


def signal_bank_cs_quality_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """综合质量分领先 + 突破（挑银行里的「好银行」趋势）。"""
    q_min = float(params.get("cs_quality_min") or 0.70)
    if "cs_quality" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gate = _cs_ok(px, "cs_quality", lo=q_min)
    if "cs_ret_20" in px.columns:
        gate = gate & _cs_ok(px, "cs_ret_20", lo=float(params.get("cs_mom20_min") or 0.45))
    # 默认突破入场
    p = dict(params)
    p.setdefault("entry", "break")
    m = gate & _entry_tech(px, p)
    out = px.loc[m.fillna(False), ["date", "close"]].copy()
    out["note"] = "银行综合质量突破"
    return out


# ---------------------------------------------------------------------------
# 二阶挖掘 Round2：减速/领先滞后/营运资本二阶导/现金质量交叉（未入库专用）
# ---------------------------------------------------------------------------


def signal_ni_yoy_soft_decel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """净利 YoY 软着陆：水平仍 ≥ gmin，但 ΔYoY ∈ [decel_lo, 0)（增速放缓未转负）。"""
    col = str(params.get("yoy_col") or "YOYNI")
    yoy = _yoy_series(px, col)
    if yoy is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    gmin = float(params.get("growth_min") or 0.08)
    decel_lo = float(params.get("decel_lo") or -0.15)
    decel_hi = float(params.get("decel_hi") or -0.01)
    evt, delta = _yoy_event_delta(px[col], yoy)
    soft = (
        evt
        & yoy.notna()
        & (yoy >= gmin)
        & delta.notna()
        & (delta <= decel_hi)
        & (delta >= decel_lo)
    )
    hot = _yoy_gate_hot(px, soft.fillna(False), params)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "净利YoY软着陆减速"
    return out


def signal_cl_yoy_decel_reclaim(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债 YoY 高位回落：上期 YoY 仍高，本期 ΔYoY 为负（领先指标见顶减速）后回踩。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce").astype(float)
    prev_min = float(params.get("prev_yoy_min") or 0.20)
    decel_max = float(params.get("decel_max") or -0.05)
    yoy_floor = float(params.get("yoy_min") or 0.0)
    evt, delta = _yoy_event_delta(px["contract_liab_yoy"], yoy)
    prev = yoy.shift(1)
    gate = (
        evt
        & prev.notna()
        & (prev >= prev_min)
        & delta.notna()
        & (delta <= decel_max)
        & yoy.notna()
        & (yoy >= yoy_floor)
    )
    if "contract_liab" in px.columns and params.get("require_cl_pos", True):
        cl = pd.to_numeric(px["contract_liab"], errors="coerce")
        gate = gate & cl.notna() & (cl > 0)
    p = dict(params)
    p.setdefault("entry", "pullback")
    hot = _yoy_gate_hot(px, gate.fillna(False), p)
    m = hot.fillna(False) & _entry_tech(px, p).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "合同负债YoY高位减速回踩"
    return out


def signal_cl_lead_ni_lag_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """合同负债加速领先、净利尚未加速：需求领先、利润滞后的时间差窗口。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    ni_col = str(params.get("yoy_col") or "YOYNI")
    ni = _yoy_series(px, ni_col)
    if ni is None:
        return pd.DataFrame(columns=["date", "close", "note"])
    cl = pd.to_numeric(px["contract_liab_yoy"], errors="coerce").astype(float)
    cl_acc = float(params.get("cl_accel") or 0.08)
    cl_ymin = float(params.get("yoy_min") or 0.10)
    ni_acc_max = float(params.get("ni_accel_max") or 0.02)
    ni_gmin = float(params.get("growth_min") or -0.05)
    cl_evt, cl_delta = _yoy_event_delta(px["contract_liab_yoy"], cl)
    ni_evt, ni_delta = _yoy_event_delta(px[ni_col], ni)
    cl_ok = cl_evt & cl_delta.notna() & (cl_delta >= cl_acc) & cl.notna() & (cl >= cl_ymin)
    ni_lag = ni.notna() & (ni >= ni_gmin) & (
        ni_delta.isna() | (ni_delta <= ni_acc_max)
    )
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(cl_ok.fillna(False), lag) & ni_lag.fillna(False)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "合同负债领先净利滞后"
    return out


def signal_inv_improve_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """存货强度改善的二阶：本季去库存幅度大于上季（周转加速改善）。"""
    if "fin_inv_to_rev" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    invr = pd.to_numeric(px["fin_inv_to_rev"], errors="coerce").astype(float)
    step = float(params.get("inv_accel") or params.get("inv_improve") or 0.015)
    evt = _funda_event(px["fin_inv_to_rev"])
    improve = invr.shift(1) - invr  # 正=强度下降=改善
    prev_imp = invr.shift(2) - invr.shift(1)
    gate = evt & improve.notna() & (improve >= step) & prev_imp.notna() & (improve > prev_imp)
    if params.get("inv_max") is not None:
        gate = gate & invr.notna() & (invr <= float(params.get("inv_max") or 0.8))
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        gate = gate & rev.notna() & (rev >= float(params.get("growth_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "存货强度改善二阶"
    return out


def signal_ar_improve_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """应收强度改善的二阶：本季回款改善幅度大于上季。"""
    if "fin_ar_to_rev" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    arr = pd.to_numeric(px["fin_ar_to_rev"], errors="coerce").astype(float)
    step = float(params.get("ar_accel") or params.get("ar_improve") or 0.012)
    evt = _funda_event(px["fin_ar_to_rev"])
    improve = arr.shift(1) - arr
    prev_imp = arr.shift(2) - arr.shift(1)
    gate = evt & improve.notna() & (improve >= step) & prev_imp.notna() & (improve > prev_imp)
    if params.get("ar_max") is not None:
        gate = gate & arr.notna() & (arr <= float(params.get("ar_max") or 0.6))
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        gate = gate & rev.notna() & (rev >= float(params.get("growth_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "应收强度改善二阶"
    return out


def signal_cfo_np_quality_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """现金流质量二阶：cfo/净利 环比再改善，且净利 YoY 不太差。"""
    if "cfo_to_np" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cfoq = pd.to_numeric(px["cfo_to_np"], errors="coerce").astype(float)
    cfo_min = float(params.get("cfo_min") or 0.6)
    cfo_imp = float(params.get("cfo_improve") or 0.08)
    evt = _funda_event(px["cfo_to_np"])
    delta = cfoq - cfoq.shift(1)
    gate = (
        evt
        & cfoq.notna()
        & (cfoq >= cfo_min)
        & (cfoq.abs() <= 8.0)
        & delta.notna()
        & (delta >= cfo_imp)
    )
    ni_col = str(params.get("yoy_col") or "YOYNI")
    if ni_col in px.columns and params.get("growth_min") is not None:
        ni = _yoy_series(px, ni_col)
        if ni is not None:
            gate = gate & ni.notna() & (ni >= float(params.get("growth_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "现金流质量二阶改善"
    return out


def signal_cash_collect_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """销售收现比改善二阶：本季改善幅度大于上季。"""
    if "fin_cash_collect" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cc = pd.to_numeric(px["fin_cash_collect"], errors="coerce").astype(float)
    step = float(params.get("collect_accel") or params.get("collect_improve") or 0.02)
    evt = _funda_event(px["fin_cash_collect"])
    improve = cc - cc.shift(1)
    prev_imp = cc.shift(1) - cc.shift(2)
    gate = (
        evt
        & improve.notna()
        & (improve >= step)
        & prev_imp.notna()
        & (improve > prev_imp)
        & cc.notna()
        & (cc > 0.2)
        & (cc < 2.5)
    )
    if params.get("collect_min") is not None:
        gate = gate & (cc >= float(params.get("collect_min") or 0.85))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        hot = hot & rev.notna() & (rev >= float(params.get("growth_min") or 0.0))
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "销售收现比改善二阶"
    return out


def signal_ar_cl_dual_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """应收收紧 × 合同负债加速：需求真 + 回款好的交叉验证。"""
    need = ("fin_ar_to_rev", "contract_liab_yoy")
    if any(c not in px.columns for c in need):
        return pd.DataFrame(columns=["date", "close", "note"])
    arr = pd.to_numeric(px["fin_ar_to_rev"], errors="coerce").astype(float)
    cl = pd.to_numeric(px["contract_liab_yoy"], errors="coerce").astype(float)
    ar_imp = float(params.get("ar_improve") or 0.012)
    cl_acc = float(params.get("cl_accel") or 0.08)
    cl_ymin = float(params.get("yoy_min") or 0.08)
    ar_evt = _funda_event(px["fin_ar_to_rev"])
    ar_ok = ar_evt & arr.notna() & ((arr.shift(1) - arr) >= ar_imp)
    cl_evt, cl_delta = _yoy_event_delta(px["contract_liab_yoy"], cl)
    cl_ok = cl_evt & cl_delta.notna() & (cl_delta >= cl_acc) & cl.notna() & (cl >= cl_ymin)
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(ar_ok.fillna(False), lag) & _funda_hot_window(cl_ok.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "应收收紧×合同负债加速"
    return out


def signal_gp_margin_accel_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """毛利率扩张二阶：本季毛利提升幅度大于上季（定价/成本改善加速）。"""
    if "gpMargin" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    gp = _to_dec(px["gpMargin"])
    step = float(params.get("gp_accel") or params.get("gp_improve") or 0.004)
    evt = _funda_event(px["gpMargin"])
    d1 = gp - gp.shift(1)
    d0 = gp.shift(1) - gp.shift(2)
    gate = evt & d1.notna() & (d1 >= step) & d0.notna() & (d1 > d0)
    if params.get("margin_min") is not None:
        gate = gate & gp.notna() & (gp >= float(params.get("margin_min") or 0.0))
    if params.get("growth_min") is not None and "fin_rev_yoy" in px.columns:
        rev = pd.to_numeric(px["fin_rev_yoy"], errors="coerce")
        gate = gate & rev.notna() & (rev >= float(params.get("growth_min") or 0.0))
    lag = int(params.get("funda_lag") or 28)
    hot = _funda_hot_window(gate.fillna(False), lag)
    if params.get("np_min") is not None and "npMargin" in px.columns:
        hot = hot & _margin_ok(px["npMargin"], float(params.get("np_min") or 0.0)).fillna(False)
    m = hot.fillna(False) & _entry_tech(px, params).fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "毛利率扩张二阶"
    return out


def signal_new_low_first_buy(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """N 日新低后的反弹买入（研究：新低后 20 日胜率偏高；加 MA20 确认抑止熊市扎堆）。

    默认：近 lookback 日内出现过 N 日新低，今日收盘上穿 MA20。
    若 confirm=False，则退化为「新低波段首日」直接买（研究原始口径）。
    """
    if "close" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    w = int(params.get("low_window") or 120)
    close = pd.to_numeric(px["close"], errors="coerce").astype(float)
    prior_lo = close.shift(1).rolling(w, min_periods=w).min()
    is_nl = close.notna() & prior_lo.notna() & (close < prior_lo)
    first = is_nl & ~is_nl.shift(1).fillna(False)

    confirm = params.get("confirm")
    if confirm is None:
        confirm = True
    if not confirm:
        m = first.fillna(False)
        out = px.loc[m.astype(bool), ["date", "close"]].copy()
        out["note"] = f"{w}日新低首日"
        return out

    lookback = int(params.get("lookback") or 10)
    was_low = first.rolling(lookback, min_periods=1).max().astype(bool)
    if "ma20" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    cross = (close > px["ma20"]) & (close.shift(1) <= px["ma20"].shift(1))
    m = was_low.fillna(False) & cross.fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = f"{w}日新低后站上MA20"
    return out
