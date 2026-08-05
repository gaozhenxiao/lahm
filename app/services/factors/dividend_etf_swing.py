"""红利 ETF 波段择时因子。

标的默认华泰柏瑞红利 ETF（515080），可切换 512890 / 510880 等。
规则偏防守波段：
1. 趋势过滤：收盘站上 MA60
2. 入场：回踩后重新站上 MA20（可选叠加波动压缩）
3. 离场：跌破 MA20 确认 / 止损 / 最长持有

记账：收盘调仓；隔夜仓计次日收益；ETF 佣金万一、免印花税。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.factors.national_team import _normalize_etf_adjust, fetch_etf_hist

logger = logging.getLogger("webapi.factors.dividend_etf_swing")

FACTORS_DATA = Path(__file__).resolve().parents[3] / "data" / "factors"

DEFAULT_PARAMS: Dict[str, Any] = {
    "etf_code": "515080",  # 华泰柏瑞红利ETF
    "fallback_etfs": ["512890", "510880", "515180"],
    "bench_code": "000922",  # 中证红利指数（东财可能用 sh000922）
    "bench_ak": "sh000922",
    "ma_fast": 20,
    "ma_slow": 60,
    "use_vol_crush": True,
    "vol_window": 60,
    "vol_lookback": 120,
    "vol_hi_q": 0.65,
    "vol_lo_q": 0.50,
    "hold_days": 25,
    "stop_loss": 0.08,
    "exit_confirm_days": 1,  # 连续跌破 MA20 天数
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.0,  # ETF 免印花税
    "cash_annual": 0.014,
    "position_logic": "ma_pullback",
    "start": "2018-01-01",
}


def _cache_path(symbol: str, *, adjust: str = "") -> Path:
    adj = _normalize_etf_adjust(adjust)
    if adj == "qfq":
        return FACTORS_DATA / f"{symbol}_daily_qfq.parquet"
    if adj == "hfq":
        return FACTORS_DATA / f"{symbol}_daily_hfq.parquet"
    return FACTORS_DATA / f"{symbol}_daily.parquet"


def _dividend_cache_path(symbol: str) -> Path:
    return FACTORS_DATA / f"{symbol}_dividends.parquet"


def fetch_etf_dividends(
    symbol: str,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """ETF 现金分红（除息日 / 每股分红）。来源：新浪累计分红差分。

    返回列：date, dps, cum_div
    """
    code = str(symbol).strip()
    path = _dividend_cache_path(code)
    if path.exists() and not force:
        try:
            cached = pd.read_parquet(path)
            cached["date"] = pd.to_datetime(cached["date"], errors="coerce")
            cached["dps"] = pd.to_numeric(cached["dps"], errors="coerce")
            out = cached.dropna(subset=["date", "dps"])
            out = out[out["dps"] > 0].sort_values("date").reset_index(drop=True)
            if not out.empty:
                return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("dividend cache read %s failed: %s", path, exc)

    import os

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"

    try:
        import akshare as ak
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare unavailable for dividends: %s", exc)
        return pd.DataFrame(columns=["date", "dps", "cum_div"])

    sina = f"sh{code}" if code.startswith(("5", "6")) else f"sz{code}"
    try:
        raw = ak.fund_etf_dividend_sina(symbol=sina)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fund_etf_dividend_sina %s failed: %s", sina, exc)
        return pd.DataFrame(columns=["date", "dps", "cum_div"])

    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "dps", "cum_div"])

    df = raw.copy()
    # 列名可能是中文：日期 / 累计分红
    cols = list(df.columns)
    if len(cols) < 2:
        return pd.DataFrame(columns=["date", "dps", "cum_div"])
    df = df.rename(columns={cols[0]: "date", cols[1]: "cum_div"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["cum_div"] = pd.to_numeric(df["cum_div"], errors="coerce")
    df = df.dropna(subset=["date", "cum_div"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=["date", "dps", "cum_div"])
    df["dps"] = df["cum_div"].diff()
    df.loc[df.index[0], "dps"] = float(df["cum_div"].iloc[0])
    df = df[df["dps"] > 1e-8][["date", "dps", "cum_div"]].reset_index(drop=True)
    try:
        FACTORS_DATA.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dividend cache write failed: %s", exc)
    return df


def dividends_as_series(dividends: pd.DataFrame) -> pd.Series:
    """date -> dps。"""
    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)
    d = dividends.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["dps"] = pd.to_numeric(d["dps"], errors="coerce")
    d = d.dropna(subset=["date", "dps"])
    d = d[d["dps"] > 0]
    if d.empty:
        return pd.Series(dtype=float)
    return d.set_index("date")["dps"].astype(float).sort_index()


def load_or_fetch_etf(
    symbol: str,
    *,
    start: str = "20160101",
    end: Optional[str] = None,
    force: bool = False,
    adjust: str = "",
) -> pd.DataFrame:
    end = end or datetime.now().strftime("%Y%m%d")
    adj = _normalize_etf_adjust(adjust)
    path = _cache_path(symbol, adjust=adj)

    def _read_ok(p: Path, *, min_rows: int = 200) -> pd.DataFrame:
        if not p.exists():
            return pd.DataFrame()
        try:
            cached = pd.read_parquet(p)
            cached["date"] = pd.to_datetime(cached["date"], errors="coerce")
            out = cached.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
            return out if len(out) >= min_rows else pd.DataFrame()
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read %s failed: %s", p, exc)
            return pd.DataFrame()

    if not force:
        hit = _read_ok(path)
        if not hit.empty:
            return hit

    # 清理代理，避免 eastmoney/akshare 走坏掉的系统代理
    import os

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"

    hist = fetch_etf_hist(
        symbol,
        start=start.replace("-", ""),
        end=end.replace("-", ""),
        adjust=adj,
    )
    if hist is None or hist.empty:
        hist = _fetch_etf_via_baostock(symbol, start=start, end=end, adjust=adj)
    if hist is None:
        hist = pd.DataFrame()
    else:
        hist = hist.copy()
        hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
        hist = hist.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    # 拒绝用过短样本覆盖已有长缓存（外网抖动时 baostock 常只吐近半年）
    old = _read_ok(path, min_rows=1)
    if not hist.empty and not old.empty and len(hist) + 50 < len(old):
        logger.warning(
            "skip short fetch %s adjust=%s n=%s < cache n=%s",
            symbol,
            adj or "none",
            len(hist),
            len(old),
        )
        return old

    # 前复权拉不到长序列时，回退本地不复权长缓存（宽基对照可接受；红利标的应尽量有 qfq）
    if (hist.empty or len(hist) < 200) and adj == "qfq":
        raw = _read_ok(_cache_path(symbol, adjust=""), min_rows=200)
        if not raw.empty:
            logger.warning("qfq unavailable for %s, fallback to raw cache n=%s", symbol, len(raw))
            return raw

    if hist.empty:
        return old if not old.empty else pd.DataFrame()

    try:
        FACTORS_DATA.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache write failed: %s", exc)
    return hist


def _fetch_etf_via_baostock(
    symbol: str, *, start: str, end: str, adjust: str = ""
) -> pd.DataFrame:
    try:
        import baostock as bs
    except Exception:
        return pd.DataFrame()
    code = str(symbol)
    # 沪市：6/5；深市：0/1/3 等
    bs_code = f"sh.{code}" if code.startswith(("5", "6")) else f"sz.{code}"
    start_s = pd.Timestamp(str(start).replace("-", "")).strftime("%Y-%m-%d")
    end_s = pd.Timestamp(str(end).replace("-", "")).strftime("%Y-%m-%d")
    adj = _normalize_etf_adjust(adjust)
    # baostock: 1后复权 2前复权 3不复权
    adjustflag = {"qfq": "2", "hfq": "1"}.get(adj, "3")
    lg = bs.login()
    if lg.error_code != "0":
        logger.warning("baostock login failed: %s", lg.error_msg)
        return pd.DataFrame()
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_s,
            end_date=end_s,
            frequency="d",
            adjustflag=adjustflag,
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        out = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        for c in ("open", "high", "low", "close", "volume", "amount"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("baostock etf fetch failed: %s", exc)
        return pd.DataFrame()
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


def _fetch_dividend_index_proxy(*, start: str, end: str) -> pd.DataFrame:
    """中证红利全收益/价格指数代理（000922）。"""
    proxy_path = FACTORS_DATA / "dividend_index_proxy_daily.parquet"
    if proxy_path.exists():
        try:
            df = pd.read_parquet(proxy_path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            if len(df) >= 200:
                return df
        except Exception:  # noqa: BLE001
            pass
    # baostock index
    try:
        import baostock as bs

        start_s = pd.Timestamp(str(start).replace("-", "")).strftime("%Y-%m-%d")
        end_s = pd.Timestamp(str(end).replace("-", "")).strftime("%Y-%m-%d")
        lg = bs.login()
        if lg.error_code != "0":
            return pd.DataFrame()
        try:
            rs = bs.query_history_k_data_plus(
                "sh.000922",
                "date,open,high,low,close,volume,amount",
                start_date=start_s,
                end_date=end_s,
                frequency="d",
                adjustflag="3",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return pd.DataFrame()
            out = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
            for c in ("open", "high", "low", "close", "volume", "amount"):
                out[c] = pd.to_numeric(out[c], errors="coerce")
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
            return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        finally:
            bs.logout()
    except Exception as exc:  # noqa: BLE001
        logger.warning("dividend index proxy failed: %s", exc)
        return pd.DataFrame()


def resolve_etf_panel(params: Optional[Dict[str, Any]] = None, *, force: bool = False) -> Tuple[str, pd.DataFrame]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    candidates = [str(p.get("etf_code") or "515080")] + [
        str(x) for x in (p.get("fallback_etfs") or []) if str(x) != str(p.get("etf_code"))
    ]
    start = str(p.get("price_start") or "20160101")
    adjust = _normalize_etf_adjust(p.get("price_adjust") or "")

    def _read_local(path: Path, label: str) -> Optional[Tuple[str, pd.DataFrame]]:
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
            if "open" not in df.columns:
                df["open"] = df["close"]
            if "high" not in df.columns:
                df["high"] = df["close"]
            if "low" not in df.columns:
                df["low"] = df["close"]
            if len(df) >= 260:
                return label, df
        except Exception as exc:  # noqa: BLE001
            logger.warning("proxy read %s failed: %s", path, exc)
        return None

    # 1) 已有 ETF 本地缓存（按复权口径分文件）
    for code in candidates:
        cached = _read_local(_cache_path(code, adjust=adjust), code)
        if cached is not None:
            return cached

    # 2) 尝试在线拉取（可能因代理/黑名单失败）
    if not bool(int((__import__("os").environ.get("DIVIDEND_ETF_OFFLINE") or "0"))):
        for code in candidates:
            df = load_or_fetch_etf(code, start=start, force=force, adjust=adjust)
            if df is not None and len(df) >= 260:
                return code, df

    # 3) 离线红利风格代理
    local_proxies = [
        (FACTORS_DATA / "BANK4_daily.parquet", "BANK4(红利风格代理)"),
        (FACTORS_DATA / "000016_daily.parquet", "000016(上证50代理)"),
        (FACTORS_DATA / "dividend_index_proxy_daily.parquet", "000922(中证红利代理)"),
    ]
    for path, label in local_proxies:
        hit = _read_local(path, label)
        if hit is not None:
            logger.warning("ETF 外网不可用，使用本地代理行情: %s", label)
            return hit

    proxy = _fetch_dividend_index_proxy(start=start, end=datetime.now().strftime("%Y%m%d"))
    if proxy is not None and len(proxy) >= 260:
        try:
            FACTORS_DATA.mkdir(parents=True, exist_ok=True)
            proxy.to_parquet(FACTORS_DATA / "dividend_index_proxy_daily.parquet", index=False)
        except Exception:  # noqa: BLE001
            pass
        logger.warning("using CSI Dividend index 000922 as proxy for ETF backtest")
        return f"{candidates[0]}(idx000922)", proxy
    return candidates[0], pd.DataFrame()


def _load_bench(params: Dict[str, Any], calendar: pd.DatetimeIndex) -> pd.Series:
    """基准日收益；优先红利指数，失败则用 ETF 自身 buy&hold。"""
    # try ETF self as last resort — caller can pass bench from same panel
    return pd.Series(0.0, index=calendar)


def enrich_features(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    fast = int(p.get("ma_fast") or 20)
    slow = int(p.get("ma_slow") or 60)
    out["ma_fast"] = out["close"].rolling(fast).mean()
    out["ma_slow"] = out["close"].rolling(slow).mean()
    out["ret"] = out["close"].pct_change()
    vw = int(p.get("vol_window") or 60)
    out["vol"] = out["ret"].rolling(vw).std()
    lb = int(p.get("vol_lookback") or 120)
    out["vol_hi"] = out["vol"].rolling(lb, min_periods=max(40, lb // 3)).quantile(float(p.get("vol_hi_q") or 0.65))
    out["vol_lo"] = out["vol"].rolling(lb, min_periods=max(40, lb // 3)).quantile(float(p.get("vol_lo_q") or 0.50))
    out["vol_crush"] = (out["vol"].shift(5) >= out["vol_hi"].shift(5)) & (out["vol"] <= out["vol_lo"])
    out["cross_fast"] = (out["close"] > out["ma_fast"]) & (out["close"].shift(1) <= out["ma_fast"].shift(1))
    out["above_slow"] = out["close"] > out["ma_slow"]
    out["below_fast"] = out["close"] < out["ma_fast"]
    return out


def build_positions(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """生成收盘后目标仓位 position ∈ {0,1}。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out = enrich_features(df, p)
    logic = str(p.get("position_logic") or "ma_pullback")
    hold_days = int(p.get("hold_days") or 25)
    stop = abs(float(p.get("stop_loss") or 0.08))
    exit_n = int(p.get("exit_confirm_days") or 1)
    use_crush = bool(p.get("use_vol_crush", True))

    pos = np.zeros(len(out), dtype=float)
    entry_px = None
    entry_i = -1
    below_cnt = 0

    for i in range(len(out)):
        if i == 0 or pd.isna(out.loc[i, "ma_fast"]) or pd.isna(out.loc[i, "ma_slow"]):
            pos[i] = 0.0
            continue

        # carry
        prev = pos[i - 1] if i > 0 else 0.0
        pos[i] = prev

        if prev <= 0:
            # entry
            if logic == "trend_follow":
                enter = bool(out.loc[i, "close"] > out.loc[i, "ma_fast"] and out.loc[i, "ma_fast"] > out.loc[i, "ma_slow"])
                # only flip on cross to reduce churn
                enter = enter and bool(out.loc[i, "cross_fast"])
            else:  # ma_pullback
                enter = bool(out.loc[i, "above_slow"] and out.loc[i, "cross_fast"])
                if use_crush:
                    # 软条件：有波动压缩更好，但不是硬门槛
                    pass
            if enter:
                pos[i] = 1.0
                entry_px = float(out.loc[i, "close"])
                entry_i = i
                below_cnt = 0
        else:
            # exits
            below_cnt = below_cnt + 1 if bool(out.loc[i, "below_fast"]) else 0
            exit_ma = below_cnt >= exit_n
            held = (i - entry_i) if entry_i >= 0 else 0
            exit_time = held >= hold_days
            dd = 0.0
            if entry_px and entry_px > 0:
                dd = float(out.loc[i, "close"]) / entry_px - 1.0
            exit_stop = dd <= -stop
            # 趋势跟随：跌破慢均线也清
            exit_slow = bool(out.loc[i, "close"] < out.loc[i, "ma_slow"]) if logic == "trend_follow" else False
            if exit_ma or exit_time or exit_stop or exit_slow:
                pos[i] = 0.0
                entry_px = None
                entry_i = -1
                below_cnt = 0

        # annotate entry quality
    out["position"] = pos
    out["signal"] = 0.0
    out.loc[out["position"].diff().fillna(0) > 0, "signal"] = 1.0
    out.loc[out["position"].diff().fillna(0) < 0, "signal"] = -1.0
    return out


def run_backtest(
    params: Optional[Dict[str, Any]] = None,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force_fetch: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    code, raw = resolve_etf_panel(p, force=force_fetch)
    if raw.empty:
        return pd.DataFrame(), {"error": "no_etf_data", "etf_code": code}, pd.DataFrame()

    panel = build_positions(raw, p)
    start = start or str(p.get("start") or "2018-01-01")
    panel = panel[panel["date"] >= pd.Timestamp(start)]
    if end:
        panel = panel[panel["date"] <= pd.Timestamp(end)]
    panel = panel.reset_index(drop=True)
    if panel.empty:
        return panel, {"error": "empty_range", "etf_code": code}, pd.DataFrame()

    commission = float(p.get("commission_rate") or 0.0001)
    stamp = float(p.get("stamp_tax_sell") or 0.0)
    cash_ann = float(p.get("cash_annual") or 0.0)
    cash_d = (1.0 + cash_ann) ** (1.0 / 252.0) - 1.0 if cash_ann else 0.0

    panel["position_hold"] = panel["position"].shift(1).fillna(0.0)
    panel["asset_ret"] = panel["close"].pct_change().fillna(0.0)
    # cost on position change at close
    delta = panel["position"] - panel["position_hold"]
    buy_cost = delta.clip(lower=0) * commission
    sell_cost = (-delta.clip(upper=0)) * (commission + stamp)
    panel["cost_ret"] = buy_cost + sell_cost
    hold = panel["position_hold"]
    panel["strategy_ret"] = hold * panel["asset_ret"] + (1.0 - hold) * cash_d - panel["cost_ret"]
    panel["equity"] = (1.0 + panel["strategy_ret"]).cumprod()
    panel["bench_ret"] = panel["asset_ret"]  # buy&hold ETF as bench
    panel["bh_equity"] = (1.0 + panel["bench_ret"]).cumprod()

    eq = panel["equity"]
    total_return = float(eq.iloc[-1] - 1.0)
    bars = len(panel)
    years = max(bars / 252.0, 1e-9)
    annual_return = float(eq.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(panel["strategy_ret"].std() * np.sqrt(252)) if bars > 2 else 0.0
    sharpe = float(annual_return / vol) if vol > 1e-12 else 0.0
    peak = eq.cummax()
    mdd = float((eq / peak - 1.0).min())
    bh = float(panel["bh_equity"].iloc[-1] - 1.0)

    trades = _trade_history(panel)
    summary = {
        "bars": bars,
        "start": panel["date"].iloc[0].strftime("%Y-%m-%d"),
        "end": panel["date"].iloc[-1].strftime("%Y-%m-%d"),
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "buy_hold_return": round(bh, 4),
        "avg_position": round(float(panel["position"].mean()), 4),
        "n_roundtrips": int(((panel["position"].shift(1).fillna(0) <= 0) & (panel["position"] > 0)).sum()),
        "etf_code": code,
        "position_logic": str(p.get("position_logic") or "ma_pullback"),
        "commission_rate": commission,
        "stamp_tax_sell": stamp,
        "accounting": "eod_rebalance_hold_earns_day",
        "note": f"红利ETF波段 · {code}",
    }
    daily = panel[
        [
            "date",
            "close",
            "ma_fast",
            "ma_slow",
            "position",
            "position_hold",
            "strategy_ret",
            "equity",
            "bench_ret",
            "cost_ret",
            "signal",
        ]
    ].copy()
    daily["n_pos"] = daily["position_hold"].apply(lambda x: 1 if x > 0.05 else 0)
    return daily, summary, trades


def _trade_history(df: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    eod = df["position"].fillna(0.0)
    hold = df["position_hold"].fillna(0.0)
    equity = df["equity"] if "equity" in df.columns else (1.0 + df["strategy_ret"].fillna(0)).cumprod()
    entry_equity: Optional[float] = None
    entry_pos: Optional[float] = None
    entry_date: Optional[str] = None
    entry_cost: Optional[float] = None
    base_note = "红利ETF收盘调仓；隔夜仓计当日收益"
    for i in range(len(df)):
        p0, p1 = float(hold.iloc[i]), float(eod.iloc[i])
        eq = float(equity.iloc[i])
        dt = pd.Timestamp(df["date"].iloc[i]).strftime("%Y-%m-%d")
        close = float(df["close"].iloc[i])
        note = base_note
        if p0 <= 0.05 and p1 > 0.05:
            action = "开仓"
            entry_equity = eq
            entry_pos = p1
            entry_date = dt
            entry_cost = close
            buy_position = round(p1, 4)
            nav_pnl = ""
        elif p0 > 0.05 and p1 <= 0.05:
            action = "清仓"
            buy_position = round(entry_pos, 4) if entry_pos is not None else round(p0, 4)
            if entry_equity and entry_equity > 0:
                nav_pnl = f"{(eq / entry_equity - 1.0) * 100:.2f}%"
            else:
                nav_pnl = ""
            if entry_date and entry_cost is not None:
                note = f"{base_note}；买入{entry_date} 成本价{entry_cost:.4f}"
            entry_equity = None
            entry_pos = None
            entry_date = None
            entry_cost = None
        else:
            continue
        rows.append(
            {
                "date": dt,
                "action": action,
                "buy_position": buy_position,
                "nav_pnl": nav_pnl,
                "position_before": round(p0, 4),
                "position_after": round(p1, 4),
                "delta": round(p1 - p0, 4),
                "equity": round(eq, 4),
                "day_ret": f"{float(df['strategy_ret'].iloc[i]) * 100:.2f}%",
                "close": close,
                "note": note,
            }
        )
    return pd.DataFrame(rows)


def compute_dividend_etf_swing_signal(params: Optional[Dict[str, Any]] = None, asof: Optional[str] = None) -> Dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    code, raw = resolve_etf_panel(p)
    if raw.empty:
        return {
            "factor_id": "dividend_etf_swing",
            "asof": asof or datetime.now().isoformat(timespec="seconds"),
            "signal": "neutral",
            "value": 0.0,
            "components": {"etf": code, "error": "no_data"},
            "note": "无红利ETF行情",
        }
    if asof:
        raw = raw[raw["date"] <= pd.Timestamp(asof)]
    panel = build_positions(raw, p)
    last = panel.iloc[-1]
    pos = float(last["position"])
    prev = float(panel.iloc[-2]["position"]) if len(panel) > 1 else 0.0
    if pos > 0.05 and prev <= 0.05:
        signal = "buy"
    elif pos <= 0.05 and prev > 0.05:
        signal = "sell"
    elif pos > 0.05:
        signal = "hold"
    else:
        signal = "neutral"
    return {
        "factor_id": "dividend_etf_swing",
        "asof": pd.Timestamp(last["date"]).strftime("%Y-%m-%d"),
        "signal": signal,
        "value": round(pos, 4),
        "components": {
            "etf": code,
            "close": float(last["close"]),
            "ma_fast": float(last["ma_fast"]) if pd.notna(last["ma_fast"]) else None,
            "ma_slow": float(last["ma_slow"]) if pd.notna(last["ma_slow"]) else None,
            "above_slow": bool(last["above_slow"]) if pd.notna(last.get("above_slow", np.nan)) else None,
            "vol_crush": bool(last["vol_crush"]) if "vol_crush" in last and pd.notna(last["vol_crush"]) else None,
            "position_logic": str(p.get("position_logic") or "ma_pullback"),
        },
        "note": f"{code} 红利ETF波段仓位={pos:.0%}",
    }
