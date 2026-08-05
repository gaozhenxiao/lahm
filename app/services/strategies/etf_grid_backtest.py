# -*- coding: utf-8 -*-
"""ETF 网格回测（默认聚焦红利 ETF）。

规则（收盘成交、等比网格）：
- 资金均分 n_grids 档；初始建仓 floor(n_grids/2) 档
- 相对上次成交价跌超 step → 加一档；涨超 step → 减一档
- 佣金万一双边；ETF 免印花税
- 对照：同标的买入持有
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services.factors.dividend_etf_swing import load_or_fetch_etf

logger = logging.getLogger("webapi.strategies.etf_grid_backtest")

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "data" / "strategies"

# 红利优先；回测可再加宽基作对照
DIVIDEND_ETFS: List[Tuple[str, str, float]] = [
    ("515080", "中证红利ETF", 0.010),
    ("512890", "红利低波ETF", 0.010),
    ("510880", "红利ETF", 0.010),
    ("515180", "红利质量ETF", 0.010),
]

COMPARE_ETFS: List[Tuple[str, str, float]] = [
    ("510300", "沪深300ETF", 0.012),
    ("510500", "中证500ETF", 0.015),
]

DEFAULT_PARAMS: Dict[str, Any] = {
    "n_grids": 6,
    "step_pct": 0.010,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.0,
    "initial_layers": None,  # None → n_grids // 2
    "start": "2018-01-01",
    "cash_annual": 0.014,
}

# v2：MA60 开关 + 密网格叠加
DEFAULT_PARAMS_V2: Dict[str, Any] = {
    "n_grids": 8,
    "step_pct": 0.005,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.0,
    "base_frac": 0.70,  # 站上 MA60 时底仓；剩余做密网格
    "ma_fast": 20,
    "ma_slow": 60,
    "start": "2018-01-01",
    "cash_annual": 0.014,
}

# v3：向上倾斜网格（中枢只上不下 + 底仓不卖光）
# 默认取红利池扫描较优组：step0.8% / min2 / grids10 / MA90
DEFAULT_PARAMS_V3: Dict[str, Any] = {
    "n_grids": 10,
    "step_pct": 0.008,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.0,
    "min_layers": 2,
    "ma_center": 90,
    "drift_daily": 0.0,
    "start": "2018-01-01",
    "cash_annual": 0.014,
}


def _metrics(equity: pd.Series, *, ann_cash: float = 0.0) -> Dict[str, Any]:
    eq = equity.dropna().astype(float)
    if len(eq) < 5:
        return {"error": "too_short"}
    ret = eq.pct_change().fillna(0.0)
    n = len(eq)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-6) if hasattr(eq.index[0], "year") else n / 252.0
    # if RangeIndex, use business-day approx
    if not isinstance(eq.index, pd.DatetimeIndex):
        years = n / 252.0
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0) if eq.iloc[0] > 0 else 0.0
    vol = float(ret.std() * np.sqrt(252))
    sharpe = float((ret.mean() * 252 - ann_cash) / vol) if vol > 1e-12 else 0.0
    peak = eq.cummax()
    dd = eq / peak - 1.0
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < -1e-12 else 0.0
    return {
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "vol": round(vol, 4),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 4),
        "calmar": round(calmar, 3),
        "n_days": int(n),
        "years": round(years, 2),
    }


def run_grid_backtest(
    df: pd.DataFrame,
    *,
    step_pct: float = 0.01,
    n_grids: int = 6,
    commission_rate: float = 0.0001,
    stamp_tax_sell: float = 0.0,
    initial_layers: Optional[int] = None,
    cash_annual: float = 0.014,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """对单标的 OHLC 做网格回测。df 需含 date, close。"""
    px = df.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    if len(px) < 60:
        return px, pd.DataFrame(), {"error": "insufficient_bars", "n": len(px)}

    n_grids = max(int(n_grids), 2)
    step = abs(float(step_pct))
    unit = 1.0 / n_grids
    init_n = int(initial_layers) if initial_layers is not None else n_grids // 2
    init_n = max(0, min(init_n, n_grids))

    cash = 1.0
    lots: List[float] = []  # share counts per buy lot
    costs: List[float] = []  # entry price per lot
    ref: Optional[float] = None
    trades: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    def _buy(price: float, d) -> None:
        nonlocal cash, ref
        if len(lots) >= n_grids or cash < unit * 0.5:
            return
        spend = min(cash, unit)
        fee = spend * commission_rate
        if spend <= fee:
            return
        shares = (spend - fee) / price
        cash -= spend
        lots.append(shares)
        costs.append(price)
        ref = price
        trades.append({"date": d, "side": "buy", "price": price, "shares": shares, "layers": len(lots)})

    def _sell(price: float, d) -> None:
        nonlocal cash, ref
        if not lots:
            return
        shares = lots.pop(0)  # FIFO
        costs.pop(0)
        gross = shares * price
        fee = gross * (commission_rate + stamp_tax_sell)
        cash += gross - fee
        ref = price
        trades.append({"date": d, "side": "sell", "price": price, "shares": shares, "layers": len(lots)})

    for i, r in px.iterrows():
        d = r["date"]
        price = float(r["close"])
        if price <= 0 or np.isnan(price):
            continue

        if ref is None:
            # 首日按 init_n 建仓
            for _ in range(init_n):
                _buy(price, d)
            if ref is None:
                ref = price
        else:
            # 可连触发多档（极端日）
            guard = 0
            while len(lots) < n_grids and price <= ref * (1.0 - step) and guard < n_grids:
                _buy(price, d)
                guard += 1
            guard = 0
            while lots and price >= ref * (1.0 + step) and guard < n_grids:
                _sell(price, d)
                guard += 1

        pos_val = sum(s * price for s in lots)
        equity = cash + pos_val
        rows.append(
            {
                "date": d,
                "close": price,
                "cash": cash,
                "position_value": pos_val,
                "equity": equity,
                "layers": len(lots),
                "exposure": pos_val / equity if equity > 1e-12 else 0.0,
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame(), {"error": "empty_daily"}

    # buy & hold（同日首笔全仓）
    bh0 = float(px.iloc[0]["close"])
    bh_shares = (1.0 * (1.0 - commission_rate)) / bh0
    daily["bh_equity"] = bh_shares * daily["close"]
    # 期末卖出扣费近似体现在最后一日
    daily.loc[daily.index[-1], "bh_equity"] *= 1.0 - commission_rate

    daily = daily.set_index("date", drop=False)
    grid_m = _metrics(daily["equity"], ann_cash=cash_annual)
    bh_m = _metrics(daily["bh_equity"], ann_cash=cash_annual)
    trade_df = pd.DataFrame(trades)
    summary = {
        "step_pct": step,
        "n_grids": n_grids,
        "initial_layers": init_n,
        "n_trades": int(len(trade_df)),
        "n_buys": int((trade_df["side"] == "buy").sum()) if not trade_df.empty else 0,
        "n_sells": int((trade_df["side"] == "sell").sum()) if not trade_df.empty else 0,
        "final_layers": int(daily["layers"].iloc[-1]),
        "grid": grid_m,
        "buy_hold": bh_m,
        "excess_cagr": round(grid_m.get("cagr", 0) - bh_m.get("cagr", 0), 4),
        "excess_sharpe": round(grid_m.get("sharpe", 0) - bh_m.get("sharpe", 0), 3),
    }
    return daily.reset_index(drop=True), trade_df, summary


def _regime_series(px: pd.DataFrame, *, ma_fast: int = 20, ma_slow: int = 60) -> pd.Series:
    """trend_up / trend_down / range（用前一日均线，避免当日偷看）。"""
    close = px["close"].astype(float)
    ma_f = close.rolling(ma_fast).mean()
    ma_s = close.rolling(ma_slow).mean()
    # shift(1)：当日决策只用到昨收均线状态
    c1, f1, s1 = close.shift(1), ma_f.shift(1), ma_s.shift(1)
    up = (c1 > s1) & (f1 > s1)
    down = (c1 < s1) & (f1 < s1)
    regime = pd.Series("range", index=px.index, dtype=object)
    regime = regime.mask(up.fillna(False), "trend_up")
    regime = regime.mask(down.fillna(False), "trend_down")
    # 均线未就绪
    regime = regime.mask(s1.isna() | f1.isna(), "range")
    return regime


def run_grid_backtest_v2(
    df: pd.DataFrame,
    *,
    step_pct: float = 0.005,
    n_grids: int = 8,
    commission_rate: float = 0.0001,
    stamp_tax_sell: float = 0.0,
    base_frac: float = 0.70,
    ma_fast: int = 20,
    ma_slow: int = 60,
    cash_annual: float = 0.014,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """密网格 + MA60 趋势开关（红利友好）。

    - 收盘站上 MA60（昨值）：目标底仓 base_frac，剩余资金做密网格（双边）
    - 跌破 MA60：底仓与网格都降到 0（趋势过滤离场）
    - 不再用 MA20 细切 trend_down（避免红利慢牛被反复洗出）
    """
    px = df.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    if len(px) < max(ma_slow + 5, 80):
        return px, pd.DataFrame(), {"error": "insufficient_bars", "n": len(px)}

    n_grids = max(int(n_grids), 2)
    step = abs(float(step_pct))
    base_frac = float(np.clip(base_frac, 0.0, 0.95))
    grid_unit = (1.0 - base_frac) / n_grids
    close = px["close"].astype(float)
    ma_s = close.rolling(ma_slow).mean()
    # 用昨收相对昨 MA60，避免偷看
    invested = (close.shift(1) > ma_s.shift(1)).fillna(False)

    cash = 1.0
    base_shares = 0.0
    lots: List[float] = []
    ref: Optional[float] = None
    trades: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    regime_counts = {"invested_grid": 0, "cash": 0}

    def _fee_buy(notional: float) -> float:
        return notional * commission_rate

    def _fee_sell(notional: float) -> float:
        return notional * (commission_rate + stamp_tax_sell)

    def _buy_base(price: float, d, target_value: float) -> None:
        nonlocal cash, base_shares
        cur = base_shares * price
        need = target_value - cur
        if need <= price * 1e-8:
            return
        spend = min(cash, need)
        if spend <= 0:
            return
        fee = _fee_buy(spend)
        if spend <= fee:
            return
        got = (spend - fee) / price
        cash -= spend
        base_shares += got
        trades.append({"date": d, "side": "buy_base", "price": price, "shares": got, "layers": len(lots)})

    def _sell_base(price: float, d, target_value: float) -> None:
        nonlocal cash, base_shares
        cur = base_shares * price
        excess = cur - target_value
        if excess <= price * 1e-8 or base_shares <= 0:
            return
        sell_sh = min(base_shares, excess / price)
        gross = sell_sh * price
        fee = _fee_sell(gross)
        cash += gross - fee
        base_shares -= sell_sh
        trades.append({"date": d, "side": "sell_base", "price": price, "shares": sell_sh, "layers": len(lots)})

    def _grid_buy(price: float, d) -> None:
        nonlocal cash, ref
        if grid_unit <= 0 or len(lots) >= n_grids or cash < grid_unit * 0.5:
            return
        spend = min(cash, grid_unit)
        fee = _fee_buy(spend)
        if spend <= fee:
            return
        shares = (spend - fee) / price
        cash -= spend
        lots.append(shares)
        ref = price
        trades.append({"date": d, "side": "buy", "price": price, "shares": shares, "layers": len(lots)})

    def _grid_sell(price: float, d) -> None:
        nonlocal cash, ref
        if not lots:
            return
        shares = lots.pop(0)
        gross = shares * price
        fee = _fee_sell(gross)
        cash += gross - fee
        ref = price
        trades.append({"date": d, "side": "sell", "price": price, "shares": shares, "layers": len(lots)})

    def _flatten_all(price: float, d) -> None:
        while lots:
            _grid_sell(price, d)
        _sell_base(price, d, target_value=0.0)

    for i in range(len(px)):
        d = px.at[i, "date"]
        price = float(px.at[i, "close"])
        if price <= 0 or np.isnan(price):
            continue
        on = bool(invested.at[i])
        if on:
            regime_counts["invested_grid"] += 1
            equity_mark = cash + base_shares * price + sum(s * price for s in lots)
            target_base = base_frac * equity_mark
            cur_base = base_shares * price
            if cur_base < target_base * 0.98:
                _buy_base(price, d, target_value=target_base)
            elif cur_base > target_base * 1.02:
                _sell_base(price, d, target_value=target_base)

            if ref is None:
                init_n = max(1, n_grids // 2)
                for _ in range(init_n):
                    _grid_buy(price, d)
                if ref is None:
                    ref = price
            else:
                guard = 0
                while len(lots) < n_grids and price <= ref * (1.0 - step) and guard < n_grids:
                    _grid_buy(price, d)
                    guard += 1
                guard = 0
                while lots and price >= ref * (1.0 + step) and guard < n_grids:
                    _grid_sell(price, d)
                    guard += 1
            regime = "invested_grid"
        else:
            regime_counts["cash"] += 1
            _flatten_all(price, d)
            ref = None
            regime = "cash"

        pos_val = base_shares * price + sum(s * price for s in lots)
        equity = cash + pos_val
        rows.append(
            {
                "date": d,
                "close": price,
                "cash": cash,
                "base_value": base_shares * price,
                "grid_value": sum(s * price for s in lots),
                "position_value": pos_val,
                "equity": equity,
                "layers": len(lots),
                "exposure": pos_val / equity if equity > 1e-12 else 0.0,
                "regime": regime,
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame(), {"error": "empty_daily"}

    bh0 = float(px.iloc[0]["close"])
    bh_shares = (1.0 * (1.0 - commission_rate)) / bh0
    daily["bh_equity"] = bh_shares * daily["close"]
    daily.loc[daily.index[-1], "bh_equity"] *= 1.0 - commission_rate

    daily = daily.set_index("date", drop=False)
    grid_m = _metrics(daily["equity"], ann_cash=cash_annual)
    bh_m = _metrics(daily["bh_equity"], ann_cash=cash_annual)
    trade_df = pd.DataFrame(trades)
    n_days = max(len(daily), 1)
    summary = {
        "version": "v2_ma60_dense_overlay",
        "step_pct": step,
        "n_grids": n_grids,
        "base_frac": base_frac,
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "n_trades": int(len(trade_df)),
        "n_buys": int(trade_df["side"].isin(["buy", "buy_base"]).sum()) if not trade_df.empty else 0,
        "n_sells": int(trade_df["side"].isin(["sell", "sell_base"]).sum()) if not trade_df.empty else 0,
        "final_layers": int(daily["layers"].iloc[-1]),
        "regime_frac": {k: round(v / n_days, 3) for k, v in regime_counts.items()},
        "grid": grid_m,
        "buy_hold": bh_m,
        "excess_cagr": round(grid_m.get("cagr", 0) - bh_m.get("cagr", 0), 4),
        "excess_sharpe": round(grid_m.get("sharpe", 0) - bh_m.get("sharpe", 0), 3),
    }
    return daily.reset_index(drop=True), trade_df, summary




def run_grid_backtest_slope_up(
    df: pd.DataFrame,
    *,
    step_pct: float = 0.006,
    n_grids: int = 8,
    min_layers: int = 3,
    ma_center: int = 60,
    drift_daily: float = 0.0,
    commission_rate: float = 0.0001,
    stamp_tax_sell: float = 0.0,
    cash_annual: float = 0.014,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """向上倾斜网格。

    - 中枢 center 每日取 max(旧中枢, MA60, 可选固定上漂)，只升不降
    - 相对中枢跌超 step → 加仓一档；涨超 step → 减仓一档
    - 减仓时不少于 min_layers（保留向上底座，避免卖成空仓错过慢牛）
    - 初始建仓 max(min_layers, n_grids//2) 档
    """
    px = df.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    if len(px) < max(int(ma_center) + 5, 80):
        return px, pd.DataFrame(), {"error": "insufficient_bars", "n": len(px)}

    n_grids = max(int(n_grids), 2)
    min_layers = int(np.clip(min_layers, 0, n_grids))
    step = abs(float(step_pct))
    unit = 1.0 / n_grids
    ma = px["close"].astype(float).rolling(int(ma_center)).mean()

    cash = 1.0
    lots: List[float] = []
    center: Optional[float] = None
    trades: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    def _buy(price: float, d) -> None:
        nonlocal cash
        if len(lots) >= n_grids or cash < unit * 0.5:
            return
        spend = min(cash, unit)
        fee = spend * commission_rate
        if spend <= fee:
            return
        shares = (spend - fee) / price
        cash -= spend
        lots.append(shares)
        trades.append({"date": d, "side": "buy", "price": price, "shares": shares, "layers": len(lots), "center": center})

    def _sell(price: float, d) -> None:
        nonlocal cash
        if len(lots) <= min_layers:
            return
        shares = lots.pop(0)
        gross = shares * price
        fee = gross * (commission_rate + stamp_tax_sell)
        cash += gross - fee
        trades.append({"date": d, "side": "sell", "price": price, "shares": shares, "layers": len(lots), "center": center})

    for i in range(len(px)):
        d = px.at[i, "date"]
        price = float(px.at[i, "close"])
        if price <= 0 or np.isnan(price):
            continue
        ma_i = float(ma.at[i]) if pd.notna(ma.at[i]) else price

        if center is None:
            center = price
            init_n = max(min_layers, n_grids // 2)
            for _ in range(init_n):
                _buy(price, d)
        else:
            # 中枢只上不下：主要跟 MA（勿日日贴着现价抬，否则永远触不到步长）
            lifted = max(center, ma_i)
            if drift_daily > 0:
                lifted = max(lifted, center * (1.0 + drift_daily))
            center = lifted

            guard = 0
            while len(lots) < n_grids and price <= center * (1.0 - step) and guard < n_grids:
                _buy(price, d)
                guard += 1
            guard = 0
            while len(lots) > min_layers and price >= center * (1.0 + step) and guard < n_grids:
                _sell(price, d)
                guard += 1

        pos_val = sum(s * price for s in lots)
        equity = cash + pos_val
        rows.append(
            {
                "date": d,
                "close": price,
                "center": center,
                "cash": cash,
                "position_value": pos_val,
                "equity": equity,
                "layers": len(lots),
                "exposure": pos_val / equity if equity > 1e-12 else 0.0,
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame(), {"error": "empty_daily"}

    bh0 = float(px.iloc[0]["close"])
    bh_shares = (1.0 * (1.0 - commission_rate)) / bh0
    daily["bh_equity"] = bh_shares * daily["close"]
    daily.loc[daily.index[-1], "bh_equity"] *= 1.0 - commission_rate

    daily = daily.set_index("date", drop=False)
    grid_m = _metrics(daily["equity"], ann_cash=cash_annual)
    bh_m = _metrics(daily["bh_equity"], ann_cash=cash_annual)
    trade_df = pd.DataFrame(trades)
    summary = {
        "version": "v3_slope_up",
        "step_pct": step,
        "n_grids": n_grids,
        "min_layers": min_layers,
        "ma_center": int(ma_center),
        "drift_daily": float(drift_daily),
        "n_trades": int(len(trade_df)),
        "n_buys": int((trade_df["side"] == "buy").sum()) if not trade_df.empty else 0,
        "n_sells": int((trade_df["side"] == "sell").sum()) if not trade_df.empty else 0,
        "final_layers": int(daily["layers"].iloc[-1]),
        "final_center": float(daily["center"].iloc[-1]),
        "grid": grid_m,
        "buy_hold": bh_m,
        "excess_cagr": round(grid_m.get("cagr", 0) - bh_m.get("cagr", 0), 4),
        "excess_sharpe": round(grid_m.get("sharpe", 0) - bh_m.get("sharpe", 0), 3),
    }
    return daily.reset_index(drop=True), trade_df, summary



def backtest_symbol(
    code: str,
    *,
    name: str = "",
    step_pct: Optional[float] = None,
    start: str = "2018-01-01",
    end: Optional[str] = None,
    force_fetch: bool = False,
    params: Optional[Dict[str, Any]] = None,
    version: str = "v1",
) -> Dict[str, Any]:
    if version == "v3":
        base = DEFAULT_PARAMS_V3
    elif version == "v2":
        base = DEFAULT_PARAMS_V2
    else:
        base = DEFAULT_PARAMS
    p = {**base, **(params or {})}
    step = float(step_pct if step_pct is not None else p["step_pct"])
    df = load_or_fetch_etf(
        code,
        start=start.replace("-", ""),
        end=(end or datetime.now().strftime("%Y%m%d")).replace("-", ""),
        force=force_fetch,
    )
    if df is None or df.empty:
        return {"code": code, "name": name, "error": "no_data"}
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]

    if version == "v3":
        daily, trades, summary = run_grid_backtest_slope_up(
            df,
            step_pct=step,
            n_grids=int(p["n_grids"]),
            min_layers=int(p.get("min_layers") if p.get("min_layers") is not None else 2),
            ma_center=int(p.get("ma_center") or 90),
            drift_daily=float(p.get("drift_daily") or 0.0),
            commission_rate=float(p["commission_rate"]),
            stamp_tax_sell=float(p["stamp_tax_sell"]),
            cash_annual=float(p.get("cash_annual") or 0.014),
        )
    elif version == "v2":
        daily, trades, summary = run_grid_backtest_v2(
            df,
            step_pct=step,
            n_grids=int(p["n_grids"]),
            commission_rate=float(p["commission_rate"]),
            stamp_tax_sell=float(p["stamp_tax_sell"]),
            base_frac=float(p.get("base_frac") or 0.7),
            ma_fast=int(p.get("ma_fast") or 20),
            ma_slow=int(p.get("ma_slow") or 60),
            cash_annual=float(p.get("cash_annual") or 0.014),
        )
    else:
        daily, trades, summary = run_grid_backtest(
            df,
            step_pct=step,
            n_grids=int(p["n_grids"]),
            commission_rate=float(p["commission_rate"]),
            stamp_tax_sell=float(p["stamp_tax_sell"]),
            initial_layers=p.get("initial_layers"),
            cash_annual=float(p.get("cash_annual") or 0.014),
        )
    if summary.get("error"):
        return {"code": code, "name": name, "error": summary["error"], **summary}
    out = {
        "code": code,
        "name": name or code,
        "start": str(daily["date"].iloc[0].date()),
        "end": str(daily["date"].iloc[-1].date()),
        **summary,
    }
    return {"result": out, "daily": daily, "trades": trades}


def run_dividend_grid_batch(
    *,
    include_compare: bool = True,
    start: str = "2018-01-01",
    force_fetch: bool = False,
    params: Optional[Dict[str, Any]] = None,
    version: str = "v1",
) -> Dict[str, Any]:
    universe = list(DIVIDEND_ETFS)
    if include_compare:
        universe = universe + list(COMPARE_ETFS)

    v2_step = {
        "515080": 0.005,
        "512890": 0.005,
        "510880": 0.006,
        "515180": 0.005,
        "510300": 0.008,
        "510500": 0.008,
    }

    rows: List[Dict[str, Any]] = []
    details: Dict[str, Any] = {}
    for code, name, step in universe:
        if version == "v3":
            # 默认跟 DEFAULT_PARAMS_V3；个股不再压小步长
            use_step = float((params or {}).get("step_pct") or DEFAULT_PARAMS_V3["step_pct"])
        elif version == "v2":
            use_step = v2_step.get(code, step)
        else:
            use_step = step
        hit = backtest_symbol(
            code,
            name=name,
            step_pct=use_step,
            start=start,
            force_fetch=force_fetch,
            params=params,
            version=version,
        )
        if hit.get("error"):
            rows.append({"code": code, "name": name, "error": hit.get("error"), "version": version})
            continue
        r = hit["result"]
        g, b = r.get("grid") or {}, r.get("buy_hold") or {}
        row = {
            "code": code,
            "name": name,
            "version": version,
            "group": "dividend" if code in {x[0] for x in DIVIDEND_ETFS} else "compare",
            "step_pct": r.get("step_pct"),
            "n_trades": r.get("n_trades"),
            "grid_cagr": g.get("cagr"),
            "grid_sharpe": g.get("sharpe"),
            "grid_max_dd": g.get("max_dd"),
            "bh_cagr": b.get("cagr"),
            "bh_sharpe": b.get("sharpe"),
            "bh_max_dd": b.get("max_dd"),
            "excess_cagr": r.get("excess_cagr"),
            "excess_sharpe": r.get("excess_sharpe"),
            "start": r.get("start"),
            "end": r.get("end"),
        }
        if r.get("regime_frac"):
            rf = r["regime_frac"]
            row["regime_invested"] = rf.get("invested_grid", rf.get("trend_up"))
            row["regime_cash"] = rf.get("cash", rf.get("trend_down"))
            row["regime_range"] = rf.get("range")
        rows.append(row)
        details[code] = {"summary": r, "_daily": hit["daily"], "_trades": hit["trades"]}

    table = pd.DataFrame(rows)
    if not table.empty and "grid_sharpe" in table.columns:
        table = table.sort_values(["group", "grid_sharpe"], ascending=[True, False])

    if version == "v3":
        rule = "v3 向上倾斜网格：中枢=max(旧, MA90) 只升不降；默认 10 档/步长0.8%/底仓≥2"
        notes = [
            "扫描后默认：step=0.8%、min_layers=2、n_grids=10、ma_center=90。",
            "中枢只跟均线上移（不贴日线），回踩加仓、冲高减仓但不卖光底座。",
            "非对称买卖步长提升有限；优先调步长/档数/均线窗口。",
        ]
        base_params = DEFAULT_PARAMS_V3
    elif version == "v2":
        rule = "v2：站上MA60持仓（70%底仓+30%密网格），跌破MA60空仓"
        notes = [
            "v2：MA60 做进出；持仓期内密网格叠加。",
            "对照看 excess_cagr / max_dd / Sharpe。",
        ]
        base_params = DEFAULT_PARAMS_V2
    else:
        rule = "等比网格：跌一步加仓、涨一步减仓；初始半仓档；佣金万一"
        notes = [
            "红利 ETF 波动通常小于宽基成长，纯网格趋势市易掉队。",
            "趋势单边时网格会滞后于买入持有；看 excess_cagr / max_dd 综合判断。",
        ]
        base_params = DEFAULT_PARAMS
    payload = {
        "asof": datetime.now().isoformat(timespec="seconds"),
        "version": version,
        "params": {**base_params, **(params or {}), "start": start},
        "rule": rule,
        "summary_table": rows,
        "notes": notes,
    }
    return {"payload": payload, "table": table, "details": details}


def save_batch_outputs(
    batch: Dict[str, Any],
    out_dir: Optional[Path] = None,
    *,
    tag: str = "",
) -> Path:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(batch["payload"])
    ver = str(payload.get("version") or tag or "v1")
    stem = "etf_grid_dividend_backtest" if ver == "v1" else f"etf_grid_dividend_backtest_{ver}"
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    table: pd.DataFrame = batch["table"]
    if not table.empty:
        table.to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8-sig")

    details = batch.get("details") or {}
    suffix = "" if ver == "v1" else f"_{ver}"
    for code, blob in details.items():
        daily = blob.get("_daily")
        trades = blob.get("_trades")
        if isinstance(daily, pd.DataFrame) and not daily.empty:
            daily.to_csv(out_dir / f"etf_grid_{code}{suffix}_daily.csv", index=False, encoding="utf-8-sig")
        if isinstance(trades, pd.DataFrame) and not trades.empty:
            trades.to_csv(out_dir / f"etf_grid_{code}{suffix}_trades.csv", index=False, encoding="utf-8-sig")
    return path
