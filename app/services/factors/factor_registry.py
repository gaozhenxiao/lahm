"""因子实现注册表：id -> meta/params/signal/flags。

负收益冒烟因子已从注册表移除（见 factors_service.RETIRED_FACTOR_IDS）。
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.factors import signal_specs as sig

_COMMON = {
    "universe": "hs300",
    "price_start": "2016-01-01",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
}


def _p(**kwargs: Any) -> Dict[str, Any]:
    return {**_COMMON, **kwargs}


FACTOR_IMPL: Dict[str, Dict[str, Any]] = {
    "pb_low_ma_reclaim": {
        "name": "低PB回踩确认",
        "category": "fundamental",
        "description": "PB历史分位偏低时，等待收盘重新站上MA60，避免单纯抄底。",
        "tags": ["估值", "PB", "均线", "回踩"],
        "title": "Low PB + MA60 reclaim",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_pb_low_ma_reclaim,
        "params": _p(val_window=756, pb_pct_max=0.25, hold_days=20, stop_loss=0.12),
    },
    "double_cheap_reclaim": {
        "name": "双低估回踩",
        "category": "fundamental",
        "description": "PE与PB同时处在偏低分位，收盘站上MA20。",
        "tags": ["估值", "PE", "PB", "均线"],
        "title": "Double cheap PE/PB reclaim",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_double_cheap_reclaim,
        "params": _p(val_window=756, pe_pct_max=0.35, pb_pct_max=0.35, hold_days=20, stop_loss=0.12),
    },
    "growth_breakout": {
        "name": "高增突破",
        "category": "fundamental",
        "description": "业绩高增长闸门下，收盘突破60日高点且站上MA20。",
        "tags": ["成长", "突破", "均线"],
        "title": "Growth breakout",
        "need_profit": False,
        "need_growth": True,
        "signal": sig.signal_growth_breakout,
        "params": _p(growth_min=0.25, hold_days=20, stop_loss=0.15),
    },
    "oversold_roe_bounce": {
        "name": "急跌ROE反弹",
        "category": "fundamental",
        "description": "ROE质量闸门下，短期急跌后收盘站上MA20。",
        "tags": ["ROE", "超卖", "反弹"],
        "title": "Oversold ROE bounce",
        "need_profit": True,
        "need_growth": False,
        "signal": sig.signal_oversold_roe_bounce,
        "params": _p(roe_min=0.08, dd_need=0.12, hold_days=15, stop_loss=0.12),
    },
    "pead_roe_drift": {
        "name": "ROE改善漂移",
        "category": "fundamental",
        "description": "ROE改善披露后，数日内回踩MA20不破再买（简化PEAD）。",
        "tags": ["PEAD", "ROE", "财报后"],
        "title": "ROE improvement post-drift",
        "need_profit": True,
        "need_growth": False,
        "signal": sig.signal_pead_post_earn,
        "params": _p(roe_improve=0.005, pead_wait=5, hold_days=20, stop_loss=0.12),
    },
    "volume_breakout": {
        "name": "放量突破",
        "category": "technical",
        "description": "成交额明显放大且收盘突破60日高点。",
        "tags": ["放量", "突破"],
        "title": "Volume surge breakout",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_volume_breakout,
        "params": _p(vol_mult=1.8, ret20_max=0.25, hold_days=15, stop_loss=0.12),
    },
    "narrow_range_breakout": {
        "name": "窄幅突破",
        "category": "technical",
        "description": "近端振幅处在低分位后，收盘创20日新高。",
        "tags": ["波动收敛", "突破"],
        "title": "Narrow range breakout",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_narrow_range_breakout,
        "params": _p(amp_pct_max=0.25, hold_days=15, stop_loss=0.12),
    },
    "pb_below_one_reclaim": {
        "name": "破净回踩",
        "category": "fundamental",
        "description": "PB小于1时，收盘站上MA20再买。",
        "tags": ["破净", "PB", "均线"],
        "title": "PB below one reclaim",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_pb_below_one_reclaim,
        "params": _p(pb_max=1.0, hold_days=20, stop_loss=0.12),
    },
    "turn_surge_ma_reclaim": {
        "name": "换手放大上均线",
        "category": "technical",
        "description": "换手相对20日均值明显放大，同时收盘站上MA60。",
        "tags": ["换手", "资金", "均线"],
        "title": "Turnover surge MA60 reclaim",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_turn_surge_ma_reclaim,
        "params": _p(surge_ratio=2.0, hold_days=15, stop_loss=0.12),
    },
    "boll_lower_reclaim": {
        "name": "布林下轨反弹",
        "category": "technical",
        "description": "价格触及布林下轨附近后，收盘站上MA20。",
        "tags": ["布林", "超卖", "反弹"],
        "title": "Bollinger lower reclaim",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_boll_lower_reclaim,
        "params": _p(boll_window=20, boll_k=2.0, hold_days=12, stop_loss=0.10),
    },
    "new_high_pullback": {
        "name": "新高回踩",
        "category": "technical",
        "description": "创120日新高后出现回撤，再站上MA20。",
        "tags": ["新高", "回踩", "强势"],
        "title": "New high pullback",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_new_high_pullback,
        "params": _p(lookback=15, dd_need=0.04, hold_days=15, stop_loss=0.12),
    },
    "dual_ma_volume": {
        "name": "放量金叉",
        "category": "technical",
        "description": "MA20上穿MA60且成交额放大。",
        "tags": ["金叉", "放量", "趋势"],
        "title": "Dual MA cross with volume",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_dual_ma_volume,
        "params": _p(vol_mult=1.3, hold_days=20, stop_loss=0.12),
    },
    "pe_quality_cross": {
        "name": "低估值质量金叉",
        "category": "fundamental",
        "description": "PE分位偏低且ROE达标时，MA20上穿MA60。",
        "tags": ["估值", "ROE", "金叉"],
        "title": "Cheap PE quality golden cross",
        "need_profit": True,
        "need_growth": False,
        "signal": sig.signal_pe_quality_cross,
        "params": _p(val_window=756, pe_pct_max=0.50, roe_min=0.10, hold_days=25, stop_loss=0.12),
    },
    "ret20_extreme_bounce": {
        "name": "二十日急跌反弹",
        "category": "technical",
        "description": "20日跌幅过深后，收盘重新站上MA20。",
        "tags": ["超卖", "反弹", "均线"],
        "title": "20-day crash bounce",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_ret20_extreme_bounce,
        "params": _p(ret20_min=0.15, hold_days=10, stop_loss=0.10),
    },
    "amount_shrink_breakout": {
        "name": "缩量后放量突破",
        "category": "technical",
        "description": "成交额先萎缩再放量，同时收盘突破20日高点。",
        "tags": ["缩量", "放量", "突破"],
        "title": "Shrink-then-surge breakout",
        "need_profit": False,
        "need_growth": False,
        "signal": sig.signal_amount_shrink_breakout,
        "params": _p(shrink_ratio=0.6, surge_ratio=1.5, hold_days=12, stop_loss=0.12),
    },
}


def compute_factor_signal(factor_id: str, params: Dict[str, Any] | None = None, asof: str | None = None):
    from app.services.factors.runner import latest_candidates

    meta = FACTOR_IMPL[factor_id]
    p = {**meta["params"], **(params or {})}
    return latest_candidates(
        factor_id,
        meta["signal"],
        p,
        need_profit=meta["need_profit"],
        need_growth=meta["need_growth"],
        asof=asof,
    )
