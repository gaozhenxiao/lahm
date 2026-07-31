"""各因子入场信号（基本面闸门 + K 线确认）。"""
from __future__ import annotations

from typing import Any, Dict

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


def signal_bottom_earn_vol_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """长期底部 + 业绩扭亏转好 + 地量后放量突破。

    对齐仕佳光子路径：磨底 → 业绩由亏转盈/同比显著改善 → 缩量蓄势后放量突破。
    """
    df = px.copy()
    if "amount" not in df.columns or "high_60" not in df.columns:
        return pd.DataFrame(columns=["date", "close", "note"])

    near_pct = float(params.get("near_low_pct") or 0.12)
    dd_need = -abs(float(params.get("dd_252_need") or 0.28))
    bottom_lookback = int(params.get("bottom_lookback") or 252)
    max_lift = float(params.get("max_lift_from_low") or 0.55)
    if "low_252" in df.columns:
        low252 = df["low_252"]
    else:
        low252 = df["low"].rolling(252).min()
    if "dd_252" in df.columns:
        dd252 = df["dd_252"]
    else:
        hi252 = df["high"].rolling(252).max()
        dd252 = df["close"] / hi252 - 1.0

    # 底部：一年内触底，且当前仍深度回撤或仍在底部区；离一年低点不能太远
    touched_bottom = (df["low"] <= low252 * (1.0 + near_pct)).rolling(
        bottom_lookback, min_periods=20
    ).max().astype(bool)
    still_depressed = dd252 <= dd_need
    near_zone = df["close"] <= low252 * (1.0 + float(params.get("near_zone_pct") or 0.45))
    lift_from_low = df["close"] / low252 - 1.0
    not_too_far = lift_from_low.isna() | (lift_from_low <= max_lift)
    bottom = touched_bottom & (still_depressed | near_zone) & not_too_far

    # 估值：近端曾便宜即可（突破日估值常被一日抬高）
    val_ok = pd.Series(True, index=df.index)
    pb_max = float(params.get("pb_pct_max") or 0.50)
    pe_max = float(params.get("pe_pct_max") or 0.55)
    val_look = int(params.get("val_lookback") or 60)
    if "pb_pct" in df.columns:
        pb_recent = df["pb_pct"].rolling(val_look, min_periods=1).min()
        val_ok = val_ok & (df["pb_pct"].isna() | (pb_recent <= pb_max))
    if "pe_pct" in df.columns:
        pe_recent = df["pe_pct"].rolling(val_look, min_periods=1).min()
        val_ok = val_ok & (df["pe_pct"].isna() | (pe_recent <= pe_max))

    # 业绩：必须「曾经差过」+「现在转好」，且近端有转好事件
    funda_hist = int(params.get("funda_hist") or 400)
    earn_event = pd.Series(False, index=df.index)
    turnaround_state = pd.Series(False, index=df.index)

    if "roeAvg" in df.columns and df["roeAvg"].notna().any():
        roe = pd.to_numeric(df["roeAvg"], errors="coerce")
        roe_past_min = roe.rolling(funda_hist, min_periods=40).min().shift(1)
        roe_had_weak = roe_past_min < float(params.get("roe_weak_max") or 0.02)
        roe_now_ok = roe >= float(params.get("roe_min") or 0.0)
        roe_turn = (roe.shift(1) < 0) & (roe >= 0)
        improve = float(params.get("roe_improve") or 0.003)
        roe_up = (roe.diff() > improve) | (roe.diff() > improve * 100)
        turnaround_state = turnaround_state | (roe_had_weak & roe_now_ok)
        earn_event = earn_event | roe_turn | roe_up

    gcol = None
    for c in ("YOYNI", "YOYEPSBasic", "NIYOY"):
        if c in df.columns and df[c].notna().any():
            gcol = c
            break
    if gcol is not None:
        g = pd.to_numeric(df[gcol], errors="coerce")
        g_past_min = g.rolling(funda_hist, min_periods=40).min().shift(1)
        had_neg = g_past_min < 0
        now_pos = (g >= float(params.get("growth_min") or 0.10)) | (
            g >= float(params.get("growth_min") or 0.10) * 100
        )
        turn = (g.shift(1) < 0) & (g >= 0)
        lift_thr = float(params.get("growth_lift") or 0.20)
        lift = (g.diff() > lift_thr) | (g.diff() > lift_thr * 100)
        newly_pos = now_pos & (~now_pos.shift(1).fillna(False))
        turnaround_state = turnaround_state | (had_neg & now_pos)
        earn_event = earn_event | turn | lift | newly_pos

    if not bool(turnaround_state.any()) and not bool(earn_event.any()):
        return pd.DataFrame(columns=["date", "close", "note"])

    win = int(params.get("earn_window") or 180)
    recent_earn = earn_event.rolling(win, min_periods=1).max().astype(bool)
    # 必须处于扭亏/转好状态，且近端确有转好事件（避免常年高增误伤）
    earn_ok = turnaround_state & recent_earn

    # 地量蓄势后放量；允许「先放量、后几日突破」（仕佳：9/24放量、9/27突破）
    amt_ma20 = df["amount"].rolling(20).mean()
    amt_ma60 = df["amount"].rolling(60).mean()
    quiet = amt_ma20.shift(1) <= amt_ma60.shift(1) * float(params.get("quiet_ratio") or 0.95)
    surge = df["amount"] >= amt_ma20 * float(params.get("vol_mult") or 1.7)
    vol_day = quiet & surge
    vol_lag = int(params.get("vol_lag") or 5)
    vol_ok = vol_day.rolling(vol_lag, min_periods=1).max().astype(bool)

    hi20 = df["high"].rolling(20).max().shift(1)
    brk60 = df["close"] >= df["high_60"].shift(1)
    brk20 = df["close"] >= hi20
    # 仍在底部区：20 日突破即可；略远则要求 60 日突破
    brk = (near_zone & brk20) | brk60

    not_chased = df["ret_20"].isna() | (df["ret_20"] <= float(params.get("ret20_max") or 0.25))
    not_runaway = df["ret_60"].isna() | (df["ret_60"] <= float(params.get("ret60_max") or 0.60))

    m = (
        bottom
        & val_ok
        & earn_ok
        & vol_ok
        & brk
        & df["ma20"].notna()
        & (df["close"] > df["ma20"])
        & not_chased
        & not_runaway
    )

    # 同股去抖：一次启动只保留首个信号
    cool = int(params.get("cooldown_days") or 20)
    keep = []
    last_pos = -10**9
    pos_map = {idx: pos for pos, idx in enumerate(df.index)}
    for idx in df.index[m.fillna(False)]:
        pos = pos_map[idx]
        if pos - last_pos >= cool:
            keep.append(idx)
            last_pos = pos
    if not keep:
        return pd.DataFrame(columns=["date", "close", "note"])
    out = df.loc[keep, ["date", "close"]].copy()
    out["note"] = "长期底部+业绩扭亏+放量突破"
    return out
