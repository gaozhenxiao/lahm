"""国家队因子：510300 份额变化 + 新闻情绪 + 可选国诚标注。"""
from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("webapi")

NEWS_BUY_KEYWORDS = [
    "国家队",
    "中央汇金",
    "汇金增持",
    "汇金买入",
    "稳市",
    "护盘",
    "救市",
    "增持ETF",
    "买入ETF",
    "平准",
]
NEWS_SELL_KEYWORDS = [
    "减持",
    "撤离",
    "减仓ETF",
    "赎回ETF",
    "国家队离场",
    "汇金减持",
]


def _safe_import_ak():
    try:
        # Eastmoney endpoints often break behind corporate proxies
        import os

        for k in list(os.environ.keys()):
            if "proxy" in k.lower():
                os.environ.pop(k, None)
        import akshare as ak

        return ak
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare unavailable: %s", exc)
        return None


def _etf_hist_via_eastmoney(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Direct eastmoney kline fetch; bypass system proxy (trust_env=False)."""
    try:
        import requests
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    market = "1" if str(symbol).startswith(("5", "6")) else "0"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": 101,
        "fqt": 0,
        "beg": start,
        "end": end,
        "secid": f"{market}.{symbol}",
    }
    try:
        sess = requests.Session()
        sess.trust_env = False
        last_exc: Optional[Exception] = None
        resp = None
        for _ in range(3):
            try:
                resp = sess.get(url, params=params, timeout=60)
                resp.raise_for_status()
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                resp = None
        if resp is None:
            raise last_exc or RuntimeError("eastmoney kline failed")
        klines = ((resp.json() or {}).get("data") or {}).get("klines") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("eastmoney kline failed: %s", exc)
        return pd.DataFrame()
    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5],
                "amount": parts[6],
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in ("open", "close", "high", "low", "volume", "amount"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _filter_hist_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    s = pd.to_datetime(start, format="%Y%m%d", errors="coerce")
    e = pd.to_datetime(end, format="%Y%m%d", errors="coerce")
    if pd.notna(s):
        out = out[out["date"] >= s]
    if pd.notna(e):
        out = out[out["date"] <= e]
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def fetch_etf_hist(symbol: str = "510300", start: str = "20200101", end: Optional[str] = None) -> pd.DataFrame:
    end = end or datetime.now().strftime("%Y%m%d")
    start = str(start).replace("-", "")
    end = str(end).replace("-", "")
    # Prefer direct HTTP (avoids corporate proxy that breaks akshare)
    out = _etf_hist_via_eastmoney(symbol, start, end)
    if not out.empty:
        return out
    ak = _safe_import_ak()
    if ak is not None:
        try:
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="")
        except Exception as exc:  # noqa: BLE001
            logger.warning("fund_etf_hist_em failed: %s", exc)
            df = None
        if df is not None and not df.empty:
            cols = list(df.columns)
            rename = {}
            # typical order: 日期 开盘 收盘 最高 最低 成交量 成交额 振幅 涨跌幅 涨跌额 换手率
            if len(cols) >= 7:
                rename[cols[0]] = "date"
                rename[cols[1]] = "open"
                rename[cols[2]] = "close"
                rename[cols[3]] = "high"
                rename[cols[4]] = "low"
                rename[cols[5]] = "volume"
                rename[cols[6]] = "amount"
            out = df.rename(columns=rename)
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
            for c in ("open", "close", "high", "low", "volume", "amount"):
                if c in out.columns:
                    out[c] = pd.to_numeric(out[c], errors="coerce")
            out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
            if not out.empty:
                return out
    # Local cache fallback (e.g. corporate proxy flaps)
    cache = Path(__file__).resolve().parents[3] / "data" / "factors" / f"{symbol}_daily.parquet"
    if cache.exists():
        try:
            cached = pd.read_parquet(cache)
            out = _filter_hist_range(cached, start, end)
            if not out.empty:
                logger.info("using cached ETF hist %s (%s rows)", cache, len(out))
                return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read failed: %s", exc)
    return pd.DataFrame()


def load_cached_etf_share(symbol: str = "510300") -> pd.DataFrame:
    """Load weekly/daily share cache written by share backfill."""
    cache = Path(__file__).resolve().parents[3] / "data" / "factors" / f"{symbol}_share.parquet"
    if not cache.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(cache)
    except Exception as exc:  # noqa: BLE001
        logger.warning("share cache read failed: %s", exc)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["share"] = pd.to_numeric(out["share"], errors="coerce")
    out = out.dropna(subset=["date", "share"]).drop_duplicates("date").sort_values("date")
    out["share_chg"] = out["share"].pct_change()
    return out.reset_index(drop=True)


def fetch_etf_share_series(symbol: str = "510300", lookback_calendar_days: int = 40) -> pd.DataFrame:
    """Prefer local share cache; optionally patch recent days from SSE."""
    cached = load_cached_etf_share(symbol)
    if not bool(int(os.environ.get("NT_FORCE_SHARE_LIVE", "0"))) and len(cached) >= 20:
        return cached

    ak = _safe_import_ak()
    if ak is None:
        return cached
    rows = cached.to_dict("records") if not cached.empty else []
    have = {pd.Timestamp(r["date"]).strftime("%Y-%m-%d") for r in rows}
    today = datetime.now().date()
    for i in range(lookback_calendar_days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        key = d.strftime("%Y-%m-%d")
        if key in have:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            sdf = ak.fund_etf_scale_sse(date=ds)
        except Exception:  # noqa: BLE001
            continue
        if sdf is None or sdf.empty:
            continue
        code_col = None
        share_col = None
        for c in sdf.columns:
            cs = str(c)
            if code_col is None and ("代码" in cs or "code" in cs.lower()):
                code_col = c
            if share_col is None and ("份额" in cs or "share" in cs.lower() or "规模" in cs):
                share_col = c
        if code_col is None:
            code_col = sdf.columns[0]
        if share_col is None and len(sdf.columns) > 1:
            share_col = sdf.columns[-1]
        hit = sdf[sdf[code_col].astype(str).str.contains(symbol[:6], na=False)]
        if hit.empty:
            continue
        share = pd.to_numeric(hit.iloc[0][share_col], errors="coerce")
        if pd.isna(share):
            continue
        rows.append({"date": pd.Timestamp(d), "share": float(share)})
        have.add(key)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
    out["share_chg"] = out["share"].pct_change()
    return out.reset_index(drop=True)


def score_news_texts(texts: List[str]) -> Tuple[float, Dict[str, int]]:
    buy_hits = 0
    sell_hits = 0
    joined = "\n".join(texts or [])
    for kw in NEWS_BUY_KEYWORDS:
        buy_hits += len(re.findall(re.escape(kw), joined))
    for kw in NEWS_SELL_KEYWORDS:
        sell_hits += len(re.findall(re.escape(kw), joined))
    raw = buy_hits - sell_hits
    # squash to [-1,1]
    value = math.tanh(raw / 3.0)
    return value, {"buy_hits": buy_hits, "sell_hits": sell_hits}


def fetch_national_team_news(limit: int = 30) -> List[str]:
    """Best-effort news pull; returns empty list on failure."""
    ak = _safe_import_ak()
    texts: List[str] = []
    if ak is None:
        return texts
    # try stock news for 510300 / 汇金 related
    for symbol in ("510300", "000001"):
        try:
            if hasattr(ak, "stock_news_em"):
                df = ak.stock_news_em(symbol=symbol)
                if df is not None and not df.empty:
                    for col in df.columns:
                        if "标题" in str(col) or "title" in str(col).lower() or "内容" in str(col):
                            texts.extend(df[col].astype(str).head(limit).tolist())
                            break
        except Exception as exc:  # noqa: BLE001
            logger.debug("news fetch %s failed: %s", symbol, exc)
    # filter to relevant
    filtered = [t for t in texts if any(k in t for k in ("国家队", "汇金", "ETF", "稳市", "护盘", "减持"))]
    return filtered[:limit] if filtered else texts[:limit]


def load_guocheng_csv(path: Optional[str] = None) -> pd.DataFrame:
    """Optional manual labels from 国诚: columns date,direction(buy/sell/neutral)."""
    candidates = []
    if path:
        candidates.append(Path(path))
    root = Path(__file__).resolve().parents[3]
    candidates.extend(
        [
            root / "data" / "factors" / "guocheng_signals.csv",
            root / "data" / "guocheng_signals.csv",
        ]
    )
    for p in candidates:
        if p.exists():
            df = pd.read_csv(p)
            cols = {c.lower(): c for c in df.columns}
            date_col = cols.get("date") or cols.get("日期")
            dir_col = cols.get("direction") or cols.get("方向") or cols.get("signal")
            if not date_col or not dir_col:
                continue
            out = pd.DataFrame(
                {
                    "date": pd.to_datetime(df[date_col], errors="coerce"),
                    "direction": df[dir_col].astype(str).str.lower().str.strip(),
                }
            ).dropna()
            return out
    return pd.DataFrame()


def _direction_to_value(direction: str) -> float:
    d = (direction or "").lower()
    if d in ("buy", "long", "买入", "增持", "护盘"):
        return 1.0
    if d in ("sell", "short", "卖出", "减持", "撤离"):
        return -1.0
    return 0.0


def compute_national_team_signal(
    params: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    params = params or {}
    etf = str(params.get("etf_code") or "510300")
    lookback = int(params.get("share_lookback_days") or 5)
    buy_th = float(params.get("share_buy_threshold") or 0.005)
    sell_th = float(params.get("share_sell_threshold") or -0.005)

    asof_dt = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now().date())

    hist = fetch_etf_hist(etf, start="20180101", end=asof_dt.strftime("%Y%m%d"))
    shares = fetch_etf_share_series(etf, lookback_calendar_days=max(lookback * 4, 30))

    components: Dict[str, Any] = {
        "etf": etf,
        "asof": str(asof_dt.date()),
        "share_source": "sse_scale" if not shares.empty else "volume_proxy",
    }

    share_score = 0.0
    if not shares.empty:
        sub = shares[shares["date"] <= asof_dt].tail(lookback + 1)
        if len(sub) >= 2 and sub["share"].iloc[0] > 0:
            chg = float(sub["share"].iloc[-1] / sub["share"].iloc[0] - 1.0)
            components["share_chg"] = chg
            if chg >= buy_th:
                share_score = min(1.0, chg / max(buy_th * 3, 1e-6))
            elif chg <= sell_th:
                share_score = max(-1.0, chg / max(abs(sell_th) * 3, 1e-6))
            else:
                share_score = chg / max(abs(buy_th), 1e-6) * 0.3
    elif not hist.empty:
        # 双向代理：放量上涨→增仓(+), 放量下跌→减仓(-)
        h = hist[hist["date"] <= asof_dt].tail(80)
        if len(h) >= 30 and "amount" in h.columns:
            ret_1 = h["close"].pct_change()
            signed_flow = np.sign(ret_1.fillna(0.0)) * h["amount"]
            flow_sum = signed_flow.rolling(lookback).sum()
            mu = flow_sum.tail(60).mean()
            sd = flow_sum.tail(60).std()
            if sd and sd > 0:
                share_score = float(np.clip((flow_sum.iloc[-1] - mu) / sd / 3.0, -1, 1))
            components["flow_z"] = share_score
            components["etf_ret"] = float(h["close"].iloc[-1] / h["close"].iloc[-lookback] - 1.0) if lookback < len(h) else 0.0

    news_texts = fetch_national_team_news()
    news_score, news_hits = score_news_texts(news_texts)
    components["news"] = news_hits
    components["news_samples"] = news_texts[:5]

    gc = load_guocheng_csv()
    guocheng_score = 0.0
    if not gc.empty:
        g = gc[gc["date"] <= asof_dt].tail(1)
        if not g.empty:
            guocheng_score = _direction_to_value(str(g.iloc[0]["direction"]))
            components["guocheng"] = str(g.iloc[0]["direction"])
    else:
        components["guocheng"] = "missing_csv"

    # weights: share 0.5, news 0.3, guocheng 0.2 (if missing, reweight)
    if components.get("guocheng") == "missing_csv":
        value = 0.65 * share_score + 0.35 * news_score
    else:
        value = 0.5 * share_score + 0.3 * news_score + 0.2 * guocheng_score

    if value >= 0.25:
        signal = "buy"
    elif value <= -0.25:
        signal = "sell"
    else:
        signal = "neutral"

    note_parts = [
        f"share_score={share_score:.3f}",
        f"news_score={news_score:.3f}",
        f"guocheng_score={guocheng_score:.3f}",
        f"source={components['share_source']}",
    ]
    return {
        "factor_id": "national_team",
        "asof": asof_dt.to_pydatetime(),
        "signal": signal,
        "value": float(value),
        "components": components,
        "note": "; ".join(note_parts),
    }


def _zscore(s: pd.Series, window: int = 60) -> pd.Series:
    mu = s.rolling(window, min_periods=max(10, window // 3)).mean()
    sd = s.rolling(window, min_periods=max(10, window // 3)).std()
    return (s - mu) / sd.replace(0, pd.NA)


def _positions_from_factor(
    factor: pd.Series,
    *,
    mode: str = "long_flat",
    enter: float = 0.35,
    exit: float = 0.15,
) -> list[float]:
    """旧版日频滞回映射（易假信号，保留作对比）。

    mode:
      - long_short: +1 / 0 / -1
      - long_flat:  +1 / 0
    """
    pos: list[float] = []
    cur = 0.0
    for v in factor.fillna(0.0).tolist():
        if cur <= 0 and v >= enter:
            cur = 1.0
        elif cur >= 0 and v <= -enter:
            cur = -1.0 if mode == "long_short" else 0.0
        elif cur > 0 and v <= exit:
            cur = 0.0
        elif cur < 0 and v >= -exit:
            cur = 0.0
        pos.append(cur)
    return pos


def load_news_events_csv(path: Optional[str] = None) -> pd.DataFrame:
    """新闻/事件火花：列 date,direction(buy/sell/neutral)。"""
    p = Path(path) if path else (_factors_data_dir() / "national_team_news_events.csv")
    if not p.exists():
        return pd.DataFrame(columns=["date", "direction"])
    try:
        df = pd.read_csv(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("news events csv read failed: %s", exc)
        return pd.DataFrame(columns=["date", "direction"])
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("日期")
    dir_col = cols.get("direction") or cols.get("方向") or cols.get("signal")
    if not date_col or not dir_col:
        return pd.DataFrame(columns=["date", "direction"])
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "direction": df[dir_col].astype(str).str.lower().str.strip(),
        }
    ).dropna(subset=["date"])
    return out.sort_values("date").reset_index(drop=True)


# 汇金持股观测池（银行股为主；季报十大股东可追踪增减）
HUIJIN_HOLDINGS_UNIVERSE: Dict[str, str] = {
    "601398": "工商银行",
    "601939": "建设银行",
    "601288": "农业银行",
    "601988": "中国银行",
    "601818": "光大银行",
}

_HUIJIN_HOLDER_KEYS = ("中央汇金投资有限责任公司", "中央汇金")


def fetch_huijin_bank_holdings_raw(
    symbols: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """拉取银行十大股东原始表（含截止日期、公告日期）。"""
    ak = _safe_import_ak()
    if ak is None:
        return pd.DataFrame()
    symbols = symbols or HUIJIN_HOLDINGS_UNIVERSE
    rows: List[pd.DataFrame] = []
    for code, name in symbols.items():
        try:
            df = ak.stock_main_stock_holder(stock=code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock_main_stock_holder %s failed: %s", code, exc)
            continue
        if df is None or df.empty:
            continue
        df = df.copy()
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols
        # akshare 列名稳定顺序：序号,股东名称,持股数量,持股比例,股本类型,截止日期,公告日期,...
        rename = {}
        if len(cols) >= 7:
            rename = {
                cols[0]: "rank",
                cols[1]: "holder",
                cols[2]: "shares",
                cols[3]: "pct",
                cols[4]: "share_type",
                cols[5]: "period_end",
                cols[6]: "announce_date",
            }
        df = df.rename(columns=rename)
        need = {"holder", "shares", "pct", "period_end", "announce_date"}
        if not need.issubset(set(df.columns)):
            logger.warning("unexpected holder columns for %s: %s", code, list(df.columns))
            continue
        df["symbol"] = code
        df["stock_name"] = name
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["period_end"] = pd.to_datetime(out["period_end"], errors="coerce")
    out["announce_date"] = pd.to_datetime(out["announce_date"], errors="coerce")
    out["shares"] = pd.to_numeric(out["shares"], errors="coerce")
    out["pct"] = pd.to_numeric(out["pct"], errors="coerce")
    return out.dropna(subset=["holder", "period_end", "announce_date"])


def build_huijin_quarterly_calendar(
    raw: Optional[pd.DataFrame] = None,
    *,
    min_d_pct: float = 0.05,
    min_d_share_ratio: float = 0.001,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """由原始持股表生成「公告日」对齐的增减日历。

    返回 (calendar, detail)：
    - calendar: announce_date, period_end, direction, n_increase, n_decrease, score, note
    - detail: 单票变动明细
    """
    if raw is None:
        path = _factors_data_dir() / "huijin_holdings_raw.csv"
        if not path.exists():
            return pd.DataFrame(), pd.DataFrame()
        raw = pd.read_csv(path)
    if raw is None or raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = raw.copy()
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    df["pct"] = pd.to_numeric(df["pct"], errors="coerce")
    mask = df["holder"].astype(str).apply(lambda x: any(k in x for k in _HUIJIN_HOLDER_KEYS))
    # 排除「汇金资产」以免与中央汇金划转重复计数；只要名称含中央汇金
    mask = mask & df["holder"].astype(str).str.contains("中央汇金", na=False)
    mask = mask & ~df["holder"].astype(str).str.contains("汇金资产", na=False)
    hj = df.loc[mask].copy()
    if hj.empty:
        return pd.DataFrame(), pd.DataFrame()

    hj = (
        hj.sort_values(["symbol", "period_end", "announce_date"])
        .groupby(["symbol", "period_end"], as_index=False)
        .agg(
            {
                "announce_date": "max",
                "shares": "last",
                "pct": "last",
                "stock_name": "last",
                "holder": "last",
            }
        )
    )

    details: List[Dict[str, Any]] = []
    for sym, g in hj.groupby("symbol"):
        g = g.sort_values("period_end").copy()
        g["shares_prev"] = g["shares"].shift(1)
        g["pct_prev"] = g["pct"].shift(1)
        g["d_shares"] = g["shares"] - g["shares_prev"]
        g["d_pct"] = g["pct"] - g["pct_prev"]
        for _, r in g.iterrows():
            if pd.isna(r["d_shares"]) or pd.isna(r["announce_date"]):
                continue
            prev = float(r["shares_prev"]) if pd.notna(r["shares_prev"]) else 0.0
            ratio = float(r["d_shares"]) / prev if prev > 0 else 0.0
            d_pct = float(r["d_pct"]) if pd.notna(r["d_pct"]) else 0.0
            material = abs(d_pct) >= min_d_pct or abs(ratio) >= min_d_share_ratio
            if not material:
                direction = "flat"
            elif float(r["d_shares"]) > 0:
                direction = "increase"
            else:
                direction = "decrease"
            details.append(
                {
                    "symbol": sym,
                    "stock_name": r.get("stock_name"),
                    "period_end": pd.Timestamp(r["period_end"]).normalize(),
                    "announce_date": pd.Timestamp(r["announce_date"]).normalize(),
                    "shares": float(r["shares"]) if pd.notna(r["shares"]) else None,
                    "d_shares": float(r["d_shares"]),
                    "pct": float(r["pct"]) if pd.notna(r["pct"]) else None,
                    "d_pct": d_pct,
                    "direction": direction,
                    "lag_days": int(
                        (pd.Timestamp(r["announce_date"]) - pd.Timestamp(r["period_end"])).days
                    ),
                }
            )
    detail = pd.DataFrame(details)
    if detail.empty:
        return pd.DataFrame(), detail

    # 按公告日聚合（同日多票增减 → 一条日历事件）
    cal_rows: List[Dict[str, Any]] = []
    for ad, g in detail.groupby("announce_date"):
        n_inc = int((g["direction"] == "increase").sum())
        n_dec = int((g["direction"] == "decrease").sum())
        if n_inc == 0 and n_dec == 0:
            continue
        period = pd.to_datetime(g["period_end"]).max()
        lag = int((pd.Timestamp(ad) - pd.Timestamp(period)).days)
        # 极短滞后 + 多票同降：多为划转/特殊过户（如划入汇金资产），不当真减持
        transfer_like = n_dec >= 3 and lag <= 5 and n_inc == 0
        if transfer_like:
            direction = "neutral"
            score = 0.0
            note_extra = "; skip_transfer_like"
        elif n_inc > n_dec:
            direction = "buy"
            score = float(n_inc - n_dec)
            note_extra = ""
        elif n_dec > n_inc:
            direction = "sell"
            score = float(n_inc - n_dec)
            note_extra = ""
        else:
            direction = "neutral"
            score = 0.0
            note_extra = ""
        if direction == "neutral" and not transfer_like:
            continue
        if transfer_like:
            continue  # 不写入日历，避免假卖出
        names = ",".join(sorted({str(x) for x in g["symbol"].tolist()}))
        cal_rows.append(
            {
                "announce_date": pd.Timestamp(ad).normalize(),
                "period_end": pd.Timestamp(period).normalize(),
                "direction": direction,
                "n_increase": n_inc,
                "n_decrease": n_dec,
                "score": score,
                "symbols": names,
                "note": f"银行季报持股变动(公告日); lag~{lag}d{note_extra}",
            }
        )
    calendar = pd.DataFrame(cal_rows).sort_values("announce_date").reset_index(drop=True)
    return calendar, detail


def load_huijin_quarterly_calendar(path: Optional[str] = None) -> pd.DataFrame:
    """读取已构建的汇金季报日历；缺失则尝试从 raw 重建。"""
    p = Path(path) if path else (_factors_data_dir() / "huijin_quarterly_calendar.csv")
    if p.exists():
        try:
            df = pd.read_csv(p)
            df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
            if "period_end" in df.columns:
                df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
            return df.dropna(subset=["announce_date"]).sort_values("announce_date").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("huijin calendar read failed: %s", exc)
    raw_path = _factors_data_dir() / "huijin_holdings_raw.csv"
    if raw_path.exists():
        cal, _ = build_huijin_quarterly_calendar(pd.read_csv(raw_path))
        if not cal.empty:
            try:
                cal.to_csv(p, index=False, encoding="utf-8-sig")
            except Exception:  # noqa: BLE001
                pass
            return cal
    return pd.DataFrame()


def build_huijin_confirm_series(
    dates: pd.Series,
    *,
    mode: str = "buy_only",
) -> pd.Series:
    """公告日确认序列。

    mode:
      - buy_only: 只把增持公告当作确认（默认；减持仍交给份额信号）
      - both: 增持>0，减持<0
    """
    idx = dates.index if hasattr(dates, "index") else pd.RangeIndex(len(dates))
    out = pd.Series(0.0, index=idx, dtype=float)
    cal = load_huijin_quarterly_calendar()
    if cal.empty:
        return out
    buy_map: Dict[pd.Timestamp, float] = {}
    for _, r in cal.iterrows():
        ad = pd.Timestamp(r["announce_date"]).normalize()
        direction = str(r.get("direction") or "").lower()
        score = float(r["score"]) if pd.notna(r.get("score")) else 0.0
        if direction in ("buy", "increase", "增持"):
            buy_map[ad] = max(buy_map.get(ad, 0.0), max(1.0, score))
        elif mode == "both" and direction in ("sell", "decrease", "减持"):
            buy_map[ad] = min(buy_map.get(ad, 0.0), min(-1.0, score if score < 0 else -1.0))
    dts = pd.to_datetime(pd.Series(dates).to_numpy())
    vals = []
    for d in dts:
        key = pd.Timestamp(d).normalize()
        vals.append(float(buy_map.get(key, 0.0)))
    return pd.Series(vals, index=idx, dtype=float)


def load_policy_events_csv(path: Optional[str] = None) -> pd.DataFrame:
    """政策事件日历：列 date,direction(buy/sell),strength,note。

    与国家队新闻并列：buy=维稳/托底；sell=收紧/减持/清配资等风险。
    """
    p = Path(path) if path else (_factors_data_dir() / "policy_events.csv")
    if not p.exists():
        return pd.DataFrame(columns=["date", "direction", "strength", "note"])
    try:
        df = pd.read_csv(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("policy events csv read failed: %s", exc)
        return pd.DataFrame(columns=["date", "direction", "strength", "note"])
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("日期")
    dir_col = cols.get("direction") or cols.get("方向") or cols.get("signal")
    if not date_col or not dir_col:
        return pd.DataFrame(columns=["date", "direction", "strength", "note"])
    strength_col = cols.get("strength") or cols.get("权重") or cols.get("强度")
    note_col = cols.get("note") or cols.get("备注")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "direction": df[dir_col].astype(str).str.lower().str.strip(),
            "strength": pd.to_numeric(df[strength_col], errors="coerce") if strength_col else 1.0,
            "note": df[note_col].astype(str) if note_col else "",
        }
    ).dropna(subset=["date"])
    out["strength"] = out["strength"].fillna(1.0)
    return out.sort_values("date").reset_index(drop=True)


def build_policy_series(dates: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """返回 (policy_buy, policy_risk)，均按交易日对齐。

    policy_buy>0 可作开仓/确认火花；policy_risk>0 强制减仓/清仓（可突破 min_hold）。
    """
    idx = dates.index if hasattr(dates, "index") else pd.RangeIndex(len(dates))
    buy = pd.Series(0.0, index=idx, dtype=float)
    risk = pd.Series(0.0, index=idx, dtype=float)
    ev = load_policy_events_csv()
    if ev.empty:
        return buy, risk
    buy_map: Dict[pd.Timestamp, float] = {}
    risk_map: Dict[pd.Timestamp, float] = {}
    for _, r in ev.iterrows():
        d = pd.Timestamp(r["date"]).normalize()
        direction = str(r["direction"])
        strength = float(r["strength"] or 1.0)
        if direction in ("buy", "long", "买入", "维稳", "托底", "护盘", "宽松"):
            buy_map[d] = max(buy_map.get(d, 0.0), strength)
        elif direction in ("sell", "short", "卖出", "减持", "收紧", "风险", "清配资"):
            risk_map[d] = max(risk_map.get(d, 0.0), strength)
    dts = pd.to_datetime(pd.Series(dates).to_numpy())
    buy_vals = []
    risk_vals = []
    for d in dts:
        key = pd.Timestamp(d).normalize()
        buy_vals.append(float(buy_map.get(key, 0.0)))
        risk_vals.append(float(risk_map.get(key, 0.0)))
    return pd.Series(buy_vals, index=idx, dtype=float), pd.Series(risk_vals, index=idx, dtype=float)


def build_news_spark_series(
    dates: pd.Series,
    close: pd.Series,
    ret_1: pd.Series,
    gc_spark: Optional[pd.Series] = None,
    *,
    panic_ret: float = -0.02,
    panic_dd: float = -0.08,
    stress_lookback: int = 60,
    panic_spark_strength: float = 0.5,
    include_policy: bool = True,
) -> pd.Series:
    """新闻先导火花：精选事件/国诚/政策买入=1.0；急跌恐慌代理=较弱强度（默认0.5）。

    强度编码便于仓位逻辑区分「真新闻」与「市场恐慌近似」。
    """
    idx = close.index
    curated = pd.Series(0.0, index=idx, dtype=float)
    if gc_spark is not None:
        curated = pd.concat([curated, gc_spark.reindex(idx).fillna(0.0)], axis=1).max(axis=1)

    ev = load_news_events_csv()
    if not ev.empty:
        buy_days = set(
            pd.to_datetime(
                ev.loc[ev["direction"].isin(["buy", "long", "买入", "增持", "护盘"]), "date"]
            ).dt.normalize()
        )
        dts = pd.to_datetime(pd.Series(dates).to_numpy())
        event_s = pd.Series(
            [1.0 if pd.Timestamp(d).normalize() in buy_days else 0.0 for d in dts],
            index=idx,
        )
        curated = pd.concat([curated, event_s], axis=1).max(axis=1)

    if include_policy:
        policy_buy, _policy_risk = build_policy_series(dates)
        pol = policy_buy.reindex(idx).fillna(0.0)
        # 仅强度>=1.0 的强政策可作开仓火花；弱政策另作延长（见 policy_support）
        strong = pol.where(pol >= 1.0, 0.0).clip(lower=0.0)
        strong = strong.where(strong <= 0, 1.0)
        curated = pd.concat([curated, strong], axis=1).max(axis=1)

    roll_max = close.rolling(stress_lookback, min_periods=max(10, stress_lookback // 3)).max()
    dd = close / roll_max - 1.0
    panic = (
        (ret_1.reindex(idx).fillna(0.0) <= panic_ret) & (dd.fillna(0.0) <= panic_dd)
    ).astype(float) * float(panic_spark_strength)

    # 精选新闻优先；同日恐慌不会压过 curated=1.0
    spark = pd.concat([curated.fillna(0.0), panic.fillna(0.0)], axis=1).max(axis=1)
    return spark.fillna(0.0)



def _positions_episode(
    factor: pd.Series,
    close: pd.Series,
    *,
    enter: float = 0.45,
    exit_th: float = 0.0,
    confirm_enter: int = 5,
    confirm_exit: int = 15,
    min_hold: int = 45,
    cooldown: int = 40,
    stress_lookback: int = 60,
    stress_dd: float = -0.12,
    spark: Optional[pd.Series] = None,
) -> Tuple[list[float], list[str]]:
    """旧战役状态机（保留对比）：OFF → SUPPORT → COOLDOWN。"""
    n = len(factor)
    if n == 0:
        return [], []

    roll_enter = factor.rolling(confirm_enter, min_periods=confirm_enter).mean()
    roll_exit = factor.rolling(confirm_exit, min_periods=confirm_exit).mean()
    roll_max = close.rolling(stress_lookback, min_periods=max(10, stress_lookback // 3)).max()
    dd = close / roll_max - 1.0
    spark_s = spark.reindex(factor.index).fillna(0.0) if spark is not None else pd.Series(0.0, index=factor.index)
    closes = close.tolist()

    state = "OFF"
    hold_bars = 0
    cool_left = 0
    ep_low = math.inf
    pos: list[float] = []
    states: list[str] = []

    for i in range(n):
        re = roll_enter.iloc[i]
        rx = roll_exit.iloc[i]
        ddi = dd.iloc[i]
        px = float(closes[i]) if pd.notna(closes[i]) else float("nan")
        sp = float(spark_s.iloc[i]) > 0

        if state == "COOLDOWN":
            cool_left -= 1
            pos.append(0.0)
            states.append("COOLDOWN")
            if cool_left <= 0:
                state = "OFF"
            continue

        if state == "OFF":
            strong = pd.notna(re) and float(re) >= enter
            stressed = pd.notna(ddi) and float(ddi) <= stress_dd
            if sp or (strong and stressed):
                state = "SUPPORT"
                hold_bars = 1
                ep_low = px if pd.notna(px) else math.inf
                pos.append(1.0)
                states.append("SUPPORT")
            else:
                pos.append(0.0)
                states.append("OFF")
            continue

        hold_bars += 1
        if pd.notna(px):
            ep_low = min(ep_low, px)
        weak = pd.notna(rx) and float(rx) <= exit_th
        if hold_bars >= min_hold and weak:
            state = "COOLDOWN"
            cool_left = cooldown
            ep_low = math.inf
            pos.append(0.0)
            states.append("COOLDOWN")
        else:
            pos.append(1.0)
            states.append("SUPPORT")

    return pos, states


def _positions_continuous(
    news_spark: pd.Series,
    share_z: pd.Series,
    close: pd.Series,
    *,
    z_lo: float = -0.15,
    z_hi: float = 0.20,
    smooth: int = 2,
    exit_z: float = -0.30,
    exit_confirm_days: int = 8,
    curated_spark_min: float = 0.99,
    allow_panic_entry: bool = False,
    panic_entry_share_z: float = 0.05,
    allow_signal_reentry: bool = True,
    reentry_z: float = 0.03,
    cooldown: int = 2,
    policy_risk: Optional[pd.Series] = None,
    policy_support: Optional[pd.Series] = None,
    huijin_confirm: Optional[pd.Series] = None,
    policy_hard_exit: float = 1.2,
    policy_soft_exit: float = 1.0,
    policy_risk_cooldown: int = 15,
    episode_dd_exit: float = -0.18,
    episode_dd_exit_series: Optional[pd.Series] = None,
    extend_min_support: float = 1.2,
    max_pos: float = 1.0,
    campaign_floor: float = 0.10,
) -> Tuple[list[float], list[str]]:
    """连续仓位（灵活版）：底仓低、响应快，允许份额信号反复进出。

    - share_z 线性映射到仓位；中性以上保留 campaign_floor 底仓
    - share_z 掉到 z_lo 以下则底仓也跟着降，可软退出
    - 开仓：强政策/精选新闻，或份额信号上穿 reentry_z（可开关）
    """
    n = len(close)
    if n == 0:
        return [], []

    news = news_spark.fillna(0.0).tolist()
    closes = close.tolist()
    share = share_z.reindex(close.index).tolist()
    share_s = pd.Series(share_z.reindex(close.index).astype(float))
    roll_exit = share_s.rolling(exit_confirm_days, min_periods=max(3, exit_confirm_days // 2)).mean()

    if huijin_confirm is None:
        hj_list = [0.0] * n
    else:
        hj_list = huijin_confirm.reindex(close.index).fillna(0.0).astype(float).tolist()
    if policy_risk is None:
        risk_list = [0.0] * n
    else:
        risk_list = policy_risk.reindex(close.index).fillna(0.0).astype(float).tolist()
    if policy_support is None:
        support_list = [0.0] * n
    else:
        support_list = policy_support.reindex(close.index).fillna(0.0).astype(float).tolist()
    if episode_dd_exit_series is None:
        dd_exit_list = [float(episode_dd_exit)] * n
    else:
        dd_exit_list = (
            episode_dd_exit_series.reindex(close.index).fillna(float(episode_dd_exit)).astype(float).tolist()
        )

    span = max(1, int(smooth))
    alpha = 2.0 / (span + 1.0)
    z_span = max(float(z_hi) - float(z_lo), 1e-6)
    floor = float(max(0.0, min(float(max_pos), campaign_floor)))

    active = False
    cool_left = 0
    risk_block_left = 0
    ep_peak = math.nan
    smooth_pos = 0.0
    pos: list[float] = []
    states: list[str] = []

    def _px(i: int) -> float:
        v = closes[i]
        return float(v) if pd.notna(v) else float("nan")

    def _map_target(sz_v: float) -> float:
        """中性以上：映射并保底仓；偏弱：底仓随份额下滑直至 0。"""
        if sz_v >= float(z_lo):
            raw = (sz_v - float(z_lo)) / z_span
            mapped = float(max(0.0, min(float(max_pos), raw * float(max_pos))))
            return max(mapped, floor)
        # z_lo → exit_z：从 floor 降到 0
        lo, ez = float(z_lo), float(exit_z)
        if sz_v <= ez or lo <= ez:
            return 0.0
        return float(max(0.0, floor * (sz_v - ez) / (lo - ez)))

    for i in range(n):
        sp_v = float(news[i] or 0.0)
        curated = sp_v >= curated_spark_min
        weak_spark = (not curated) and sp_v > 0
        sz = share[i]
        sz_v = float(sz) if pd.notna(sz) else 0.0
        red = roll_exit.iloc[i]
        red_v = float(red) if pd.notna(red) else sz_v
        hj_v = float(hj_list[i] or 0.0)
        risk_v = float(risk_list[i] or 0.0)
        support_v = float(support_list[i] or 0.0)
        dd_th = float(dd_exit_list[i])

        px = _px(i)
        if active and pd.notna(px):
            ep_peak = px if not pd.notna(ep_peak) else max(ep_peak, px)
        dd = 0.0
        if active and pd.notna(px) and pd.notna(ep_peak) and ep_peak > 0:
            dd = px / ep_peak - 1.0
        in_dd = dd <= dd_th
        strong_support = hj_v > 0 or support_v >= float(extend_min_support) or (
            curated and support_v >= 1.0
        )

        if risk_v >= policy_soft_exit:
            risk_block_left = max(risk_block_left, int(policy_risk_cooldown))

        if cool_left > 0:
            cool_left -= 1
            if risk_block_left > 0:
                risk_block_left -= 1
            active = False
            smooth_pos = 0.0
            ep_peak = math.nan
            pos.append(0.0)
            states.append("COOLDOWN")
            continue

        # 政策硬/软退出
        if active and risk_v >= policy_soft_exit:
            active = False
            smooth_pos = 0.0
            ep_peak = math.nan
            cool_left = max(cooldown, int(policy_risk_cooldown) if risk_v >= policy_hard_exit else cooldown)
            pos.append(0.0)
            states.append("COOLDOWN")
            continue

        # 战役回撤止损
        if active and in_dd and not strong_support:
            active = False
            smooth_pos = 0.0
            ep_peak = math.nan
            cool_left = max(cooldown, 5)
            pos.append(0.0)
            states.append("COOLDOWN")
            continue

        # 深缩份额硬退出
        if active and (hj_v < 0 or red_v <= float(exit_z)):
            active = False
            smooth_pos = 0.0
            ep_peak = math.nan
            cool_left = cooldown
            pos.append(0.0)
            states.append("COOLDOWN")
            continue

        if not active:
            if risk_block_left > 0:
                risk_block_left -= 1
                pos.append(0.0)
                states.append("OFF")
                continue
            if risk_v >= policy_soft_exit:
                pos.append(0.0)
                states.append("OFF")
                continue
            signal_in = bool(allow_signal_reentry) and sz_v >= float(reentry_z)
            open_ok = curated or signal_in or (
                bool(allow_panic_entry) and weak_spark and sz_v >= float(panic_entry_share_z)
            )
            if open_ok:
                active = True
                ep_peak = px
                target = _map_target(sz_v)
                target = max(target, floor if curated or signal_in else 0.05)
                target = min(target, float(max_pos))
                smooth_pos = target
                pos.append(float(smooth_pos))
                states.append("ACTIVE")
            else:
                pos.append(0.0)
                states.append("OFF")
            continue

        # ACTIVE：快速跟踪份额
        target = _map_target(sz_v)
        if hj_v > 0 or support_v >= 1.0:
            target = max(target, min(float(max_pos), max(floor, 0.25)))
        smooth_pos = alpha * target + (1.0 - alpha) * smooth_pos
        # 软退出：目标已到 0 且平滑仓位很轻
        if target <= 1e-9 and smooth_pos < max(0.03, floor * 0.5):
            active = False
            smooth_pos = 0.0
            ep_peak = math.nan
            cool_left = max(1, cooldown // 2)
            pos.append(0.0)
            states.append("OFF")
        else:
            pos.append(float(max(0.0, min(float(max_pos), smooth_pos))))
            states.append("ACTIVE")

    return pos, states


def apply_position_logic(
    factor: pd.Series,
    close: pd.Series,
    *,
    params: Optional[Dict[str, Any]] = None,
    spark: Optional[pd.Series] = None,
    share_z: Optional[pd.Series] = None,
    ret_1: Optional[pd.Series] = None,
    huijin_confirm: Optional[pd.Series] = None,
    policy_risk: Optional[pd.Series] = None,
    policy_support: Optional[pd.Series] = None,
    dates: Optional[pd.Series] = None,
) -> Tuple[pd.Series, pd.Series]:
    """按 params 生成仓位与状态。返回 (position, state)。"""
    params = params or {}
    logic = str(params.get("position_logic") or "continuous")
    if logic == "long_hold":
        logic = "continuous"
    mode = str(params.get("position_mode") or "long_flat")
    enter = float(params.get("enter_threshold") or (0.45 if logic == "episode" else 0.35))
    exit_th = float(
        params.get("exit_threshold") if params.get("exit_threshold") is not None else (0.0 if logic == "episode" else 0.15)
    )

    if logic == "threshold":
        pos = _positions_from_factor(factor, mode=mode, enter=enter, exit=exit_th)
        state = ["LONG" if p > 0 else ("SHORT" if p < 0 else "FLAT") for p in pos]
        return pd.Series(pos, index=factor.index), pd.Series(state, index=factor.index)

    if logic == "episode":
        pos, state = _positions_episode(
            factor,
            close,
            enter=enter,
            exit_th=exit_th,
            confirm_enter=int(params.get("confirm_enter_days") or 5),
            confirm_exit=int(params.get("confirm_exit_days") or 15),
            min_hold=int(params.get("min_hold_bars") or 45),
            cooldown=int(params.get("cooldown_bars") or 40),
            stress_lookback=int(params.get("stress_lookback") or 60),
            stress_dd=float(params.get("stress_dd") or -0.12),
            spark=spark,
        )
        return pd.Series(pos, index=factor.index), pd.Series(state, index=factor.index)

    # shared inputs for continuous
    news = spark.reindex(factor.index).fillna(0.0) if spark is not None else pd.Series(0.0, index=factor.index)
    sz = share_z.reindex(factor.index) if share_z is not None else factor
    use_hj = bool(params.get("use_huijin_calendar", True))
    hj = (
        huijin_confirm.reindex(factor.index).fillna(0.0)
        if (use_hj and huijin_confirm is not None)
        else pd.Series(0.0, index=factor.index)
    )
    use_pol = bool(params.get("use_policy_events", True))
    risk = (
        policy_risk.reindex(factor.index).fillna(0.0)
        if (use_pol and policy_risk is not None)
        else pd.Series(0.0, index=factor.index)
    )
    support = (
        policy_support.reindex(factor.index).fillna(0.0)
        if (use_pol and policy_support is not None)
        else pd.Series(0.0, index=factor.index)
    )
    # 分时代/窗口回撤止损：
    # - 默认关闭(-0.99)
    # - 2018 年启用较严止损，砍掉救市后粘持穿过熊市
    # - 2023-10 后保持关闭，保住近年趋势
    pre_dd = float(params.get("episode_dd_exit_pre") if params.get("episode_dd_exit_pre") is not None else -0.99)
    post_dd = float(params.get("episode_dd_exit_post") if params.get("episode_dd_exit_post") is not None else -0.99)
    switch = pd.Timestamp(params.get("episode_dd_switch") or "2023-10-01")
    base_dd = float(params.get("episode_dd_exit") if params.get("episode_dd_exit") is not None else pre_dd)
    bear_dd = float(params.get("bear_window_dd_exit") if params.get("bear_window_dd_exit") is not None else -0.10)
    bear_start = pd.Timestamp(params.get("bear_window_start") or "2018-01-01")
    bear_end = pd.Timestamp(params.get("bear_window_end") or "2018-12-31")
    if dates is not None:
        raw = dates.reindex(factor.index) if hasattr(dates, "reindex") else dates
        dts = pd.to_datetime(pd.Series(raw).to_numpy())
        vals = []
        for d in dts:
            ts = pd.Timestamp(d)
            if bear_start <= ts <= bear_end:
                vals.append(bear_dd)
            elif ts >= switch:
                vals.append(post_dd)
            else:
                vals.append(pre_dd)
        dd_series = pd.Series(vals, index=factor.index, dtype=float)
    else:
        dd_series = pd.Series(base_dd, index=factor.index, dtype=float)

    if logic == "continuous":
        pos, state = _positions_continuous(
            news,
            sz,
            close,
            z_lo=float(params.get("cont_z_lo") if params.get("cont_z_lo") is not None else -0.15),
            z_hi=float(params.get("cont_z_hi") if params.get("cont_z_hi") is not None else 0.20),
            smooth=int(params.get("cont_smooth") or 2),
            exit_z=float(params.get("cont_exit_z") if params.get("cont_exit_z") is not None else -0.30),
            exit_confirm_days=int(params.get("cont_exit_confirm_days") or 8),
            curated_spark_min=float(params.get("curated_spark_min") or 0.99),
            allow_panic_entry=bool(params.get("allow_panic_entry", False)),
            panic_entry_share_z=float(
                params.get("panic_entry_share_z") if params.get("panic_entry_share_z") is not None else 0.05
            ),
            allow_signal_reentry=bool(params.get("cont_allow_signal_reentry", True)),
            reentry_z=float(params.get("cont_reentry_z") if params.get("cont_reentry_z") is not None else 0.03),
            cooldown=int(
                params.get("cont_cooldown_bars")
                if params.get("cont_cooldown_bars") is not None
                else (params.get("cooldown_bars") or 2)
            ),
            policy_risk=risk,
            policy_support=support,
            huijin_confirm=hj,
            policy_hard_exit=float(params.get("policy_hard_exit") or 1.2),
            policy_soft_exit=float(params.get("policy_soft_exit") or 1.0),
            policy_risk_cooldown=int(params.get("policy_risk_cooldown") or 10),
            episode_dd_exit=base_dd,
            episode_dd_exit_series=dd_series,
            extend_min_support=float(params.get("extend_min_support") or 1.5),
            max_pos=float(params.get("cont_max_pos") if params.get("cont_max_pos") is not None else 1.0),
            campaign_floor=float(
                params.get("cont_campaign_floor") if params.get("cont_campaign_floor") is not None else 0.10
            ),
        )
        return pd.Series(pos, index=factor.index), pd.Series(state, index=factor.index)

    raise ValueError(
        f"unsupported position_logic={logic!r}; use continuous/episode/threshold"
    )


def _factors_data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "factors"


# 汇金/国家队高占比宽基ETF —— 只作「是否增减仓」信号
HUIJIN_SIGNAL_ETFS: List[Tuple[str, float]] = [
    ("510300", 0.60),  # 华泰柏瑞沪深300（汇金系占比最高）
    ("510310", 0.22),  # 易方达沪深300
    ("510330", 0.18),  # 华夏沪深300
]


# 信号 vs 交易分离（回到较优交易结构，避免越改越差）：
# - signal：始终用汇金重仓300ETF份额
# - trade：早期宽基；近年银行+科创（2024后表现更好的那套）
ERA_BASKETS: List[Dict[str, Any]] = [
    {
        "name": "sse50",
        "start": "2012-01-01",
        "end": "2016-12-31",
        "note": "信号=汇金300ETF；交易=上证50",
        "trade": [("000016", 1.0)],
        "signal": list(HUIJIN_SIGNAL_ETFS),
    },
    {
        "name": "csi300",
        "start": "2017-01-01",
        "end": "2023-09-30",
        "note": "信号=汇金300ETF；交易=沪深300",
        "trade": [("000300", 1.0)],
        "signal": list(HUIJIN_SIGNAL_ETFS),
    },
    {
        "name": "bank_star",
        "start": "2023-10-01",
        "end": "2099-12-31",
        "note": "信号=汇金300ETF增减；交易=银行+科创50（跟近年实际风格）",
        "trade": [("BANK4", 0.55), ("000688", 0.45)],
        "signal": list(HUIJIN_SIGNAL_ETFS),
    },
]


def load_price_series(symbol: str) -> pd.DataFrame:
    """Load local parquet bars (index/ETF/synthetic)."""
    path = _factors_data_dir() / f"{symbol}_daily.parquet"
    if path.exists():
        try:
            df = pd.read_parquet(path)
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            if "amount" in df.columns:
                df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
            else:
                df["amount"] = pd.to_numeric(df.get("volume"), errors="coerce")
            return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load_price_series %s failed: %s", symbol, exc)
    if symbol.isdigit() and len(symbol) == 6 and symbol.startswith(("5", "1")):
        return fetch_etf_hist(symbol, start="20120101")
    return pd.DataFrame()


def _era_for_date(ts: pd.Timestamp, eras: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    eras = eras or ERA_BASKETS
    d = pd.Timestamp(ts).normalize()
    for era in eras:
        if pd.Timestamp(era["start"]) <= d <= pd.Timestamp(era["end"]):
            return era
    return eras[-1]


def _build_era_trade_panel(
    start: pd.Timestamp,
    end: pd.Timestamp,
    eras: List[Dict[str, Any]],
) -> pd.DataFrame:
    """按日切换时代权重，生成可交易组合收益与净值（不在时代边界重置）。"""
    symbols = []
    for era in eras:
        for sym, _w in era["trade"]:
            if sym not in symbols:
                symbols.append(sym)
    frames = []
    for sym in symbols:
        px = load_price_series(sym)
        if px.empty:
            continue
        s = px[(px["date"] >= start - pd.Timedelta(days=5)) & (px["date"] <= end)][["date", "close"]].copy()
        s[f"r_{sym}"] = s["close"].pct_change()
        s = s.rename(columns={"close": f"c_{sym}"})
        frames.append(s[["date", f"c_{sym}", f"r_{sym}"]])
    if not frames:
        return pd.DataFrame()
    panel = frames[0]
    for f in frames[1:]:
        panel = panel.merge(f, on="date", how="outer")
    panel = panel.sort_values("date")
    panel = panel[(panel["date"] >= start) & (panel["date"] <= end)].reset_index(drop=True)

    era_names = []
    port_rets = []
    for _, row in panel.iterrows():
        era = _era_for_date(row["date"], eras)
        era_names.append(era["name"])
        w_map = {sym: float(w) for sym, w in era["trade"]}
        num = 0.0
        den = 0.0
        for sym, w in w_map.items():
            r = row.get(f"r_{sym}")
            if pd.notna(r):
                num += w * float(r)
                den += w
        port_rets.append(num / den if den > 0 else np.nan)

    panel["era"] = era_names
    panel["bench_ret"] = port_rets
    panel["close"] = (1.0 + pd.Series(panel["bench_ret"]).fillna(0.0)).cumprod()
    # amount: average available close as weak proxy not needed; use mean abs ret proxy via first leg amount if any
    panel["amount"] = np.nan
    for sym in symbols:
        c = f"c_{sym}"
        if c in panel.columns:
            panel["amount"] = panel["amount"].fillna(panel[c])
    return panel[["date", "close", "amount", "bench_ret", "era"]].dropna(subset=["date"]).reset_index(drop=True)


def _signal_share_factor(signal_weights: List[Tuple[str, float]], dates: pd.Series) -> pd.Series:
    """Weighted share-expansion zscore across ETF share caches; missing legs skipped."""
    base = pd.DataFrame({"date": pd.to_datetime(dates)}).reset_index(drop=True)
    pieces = []
    weights = []
    for sym, w in signal_weights:
        sh = load_cached_etf_share(sym)
        if sh.empty:
            continue
        s = sh[["date", "share"]].copy()
        s["date"] = pd.to_datetime(s["date"])
        m = base.merge(s, on="date", how="left")
        m["share"] = m["share"].ffill()
        m["chg4"] = m["share"].pct_change(20)
        z = _zscore(m["chg4"], 120).clip(-3, 3) / 3.0
        pieces.append(z.reset_index(drop=True))
        weights.append(float(w))
    if not pieces:
        return pd.Series(np.nan, index=base.index)
    mat = pd.concat(pieces, axis=1)
    w = np.array(weights, dtype=float)
    w_row = np.tile(w, (len(mat), 1))
    valid = mat.notna().to_numpy()
    w_row = np.where(valid, w_row, 0.0)
    w_sum = w_row.sum(axis=1, keepdims=True)
    w_sum = np.where(w_sum > 0, w_sum, np.nan)
    w_row = w_row / w_sum
    weighted = pd.Series((mat.fillna(0.0).to_numpy() * w_row).sum(axis=1), index=base.index)
    pos_max = mat.max(axis=1)
    pos_max.index = base.index
    return (0.65 * weighted + 0.35 * pos_max.fillna(0.0)).clip(-1, 1)


def _signal_share_factor_by_era(panel: pd.DataFrame, eras: List[Dict[str, Any]]) -> pd.Series:
    """Each day uses that era's signal ETF basket."""
    out = pd.Series(np.nan, index=panel.index, dtype="float64")
    for era in eras:
        mask = panel["era"] == era["name"]
        if not mask.any():
            continue
        sub_dates = panel.loc[mask, "date"]
        sig = _signal_share_factor(list(era["signal"]), sub_dates)
        out.iloc[np.flatnonzero(mask.to_numpy())] = np.asarray(sig, dtype=float)
    return out


def build_national_team_daily_factor(
    start: str = "2018-01-01",
    end: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """日度国家队因子。默认按时代切换标的篮子（上证50→宽基→银行+科创）。"""
    params = params or {}
    if not bool(params.get("use_era_universe", True)):
        return _build_single_etf_factor(start=start, end=end, params=params)

    end_ts = pd.Timestamp(end) if end else pd.Timestamp(datetime.now().date())
    start_ts = pd.Timestamp(start)
    eras = params.get("era_baskets") or ERA_BASKETS

    h = _build_era_trade_panel(start_ts, end_ts, eras)
    if h.empty:
        return _build_single_etf_factor(start=start, end=end, params=params)

    h["share_z"] = _signal_share_factor_by_era(h, eras)

    lookback = int(params.get("share_lookback_days") or 5)
    h["ret_1"] = h["bench_ret"]
    h["amount_ma20"] = h["amount"].rolling(20).mean()
    h["signed_flow"] = np.sign(h["ret_1"].fillna(0.0)) * h["amount"].fillna(0.0)
    h["flow_sum"] = h["signed_flow"].rolling(lookback).sum()
    h["flow_z"] = _zscore(h["flow_sum"], 60).clip(-3, 3) / 3.0
    h["proxy"] = h["flow_z"].fillna(0.0)

    if h["share_z"].notna().any():
        h["factor_raw"] = (0.85 * h["share_z"].fillna(0.0) + 0.15 * h["proxy"]).where(
            h["share_z"].notna(), h["proxy"] * 0.5
        )
        share_source = "era_share_baskets"
    else:
        h["factor_raw"] = h["proxy"] * 0.5
        share_source = "volume_proxy_damped"

    h["gc_spark"] = 0.0
    h["gc_score"] = 0.0
    gc = load_guocheng_csv()
    if not gc.empty:
        gc = gc.copy()
        gc["gc_score"] = gc["direction"].map(_direction_to_value)
        score_map = gc[["date", "gc_score"]].drop_duplicates("date")
        h = h.drop(columns=["gc_score"], errors="ignore").merge(score_map, on="date", how="left")
        h["gc_score"] = h["gc_score"].fillna(0.0)
        h["gc_spark"] = (h["gc_score"] > 0).astype(float)

    h["factor"] = (h["factor_raw"].fillna(0) + 0.20 * h["gc_score"].fillna(0)).clip(-1, 1)
    confirm = int(params.get("confirm_enter_days") or 5)
    h["support_score"] = h["factor"].rolling(confirm, min_periods=1).mean()
    h["share_source"] = share_source

    if "share_z" not in h.columns:
        h["share_z"] = h["factor"]
    h["news_spark"] = build_news_spark_series(
        h["date"],
        h["close"],
        h["bench_ret"] if "bench_ret" in h.columns else h["close"].pct_change(),
        gc_spark=h["gc_spark"],
        panic_ret=float(params.get("panic_ret") or -0.02),
        panic_dd=float(params.get("panic_dd") or -0.08),
        stress_lookback=int(params.get("stress_lookback") or 60),
        panic_spark_strength=float(
            params.get("panic_spark_strength") if params.get("panic_spark_strength") is not None else 0.5
        ),
        include_policy=bool(params.get("use_policy_events", True)),
    )
    _pol_buy, pol_risk = build_policy_series(h["date"])
    h["policy_buy"] = _pol_buy
    h["policy_risk"] = pol_risk
    # 弱政策(<1.0)只作持仓延长；强政策已进入 news_spark
    h["policy_support"] = _pol_buy.where(_pol_buy > 0, 0.0)
    h["huijin_confirm"] = build_huijin_confirm_series(
        h["date"],
        mode=str(params.get("huijin_calendar_mode") or "buy_only"),
    )
    pos, state = apply_position_logic(
        h["factor"],
        h["close"],
        params=params,
        spark=h["news_spark"],
        share_z=h["share_z"],
        huijin_confirm=h["huijin_confirm"],
        policy_risk=h["policy_risk"],
        policy_support=h["policy_support"],
        dates=h["date"],
    )
    h["position"] = pos
    h["episode_state"] = state

    cols = [
        "date",
        "close",
        "amount",
        "factor",
        "support_score",
        "position",
        "episode_state",
        "proxy",
        "gc_spark",
        "news_spark",
        "policy_buy",
        "policy_risk",
        "policy_support",
        "huijin_confirm",
        "share_source",
        "era",
        "bench_ret",
        "share_z",
    ]
    return h[[c for c in cols if c in h.columns]].dropna(subset=["date", "close", "factor"]).reset_index(drop=True)


def _build_single_etf_factor(
    start: str = "2018-01-01",
    end: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """兼容旧逻辑：单一 ETF（默认 510300）。"""
    params = params or {}
    etf = str(params.get("etf_code") or "510300")
    lookback = int(params.get("share_lookback_days") or 5)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp(datetime.now().date())
    hist = fetch_etf_hist(etf, start=start.replace("-", ""), end=end_ts.strftime("%Y%m%d"))
    if hist.empty:
        return pd.DataFrame()

    h = hist.copy()
    h["ret_1"] = h["close"].pct_change()
    h["amount_ma20"] = h["amount"].rolling(20).mean()
    h["signed_flow"] = np.sign(h["ret_1"].fillna(0.0)) * h["amount"]
    h["flow_sum"] = h["signed_flow"].rolling(lookback).sum()
    h["flow_z"] = _zscore(h["flow_sum"], 60).clip(-3, 3) / 3.0
    h["proxy"] = h["flow_z"].fillna(0.0)

    shares = pd.DataFrame()
    if not bool(params.get("skip_share_fetch", False)):
        shares = fetch_etf_share_series(etf, lookback_calendar_days=int(params.get("share_fetch_days", 15)))
    share_source = "none"
    if not shares.empty:
        s = shares[["date", "share", "share_chg"]].copy()
        s["date"] = pd.to_datetime(s["date"])
        h = h.merge(s, on="date", how="left")
        h["share"] = h["share"].ffill()
        h["share_chg_1w"] = h["share"].pct_change(5)
        h["share_chg_4w"] = h["share"].pct_change(20)
        h["share_z"] = _zscore(h["share_chg_4w"].fillna(h["share_chg_1w"]), 120).clip(-3, 3) / 3.0
        h["factor_raw"] = (0.85 * h["share_z"].fillna(0.0) + 0.15 * h["proxy"]).where(
            h["share_z"].notna(), h["proxy"] * 0.5
        )
        share_source = "sse_share_cache"
    else:
        h["factor_raw"] = h["proxy"] * 0.5
        share_source = "volume_proxy_damped"

    h["gc_spark"] = 0.0
    h["gc_score"] = 0.0
    gc = load_guocheng_csv()
    if not gc.empty:
        gc = gc.copy()
        gc["gc_score"] = gc["direction"].map(_direction_to_value)
        score_map = gc[["date", "gc_score"]].drop_duplicates("date")
        h = h.drop(columns=["gc_score"], errors="ignore").merge(score_map, on="date", how="left")
        h["gc_score"] = h["gc_score"].fillna(0.0)
        h["gc_spark"] = (h["gc_score"] > 0).astype(float)

    h["factor"] = (h["factor_raw"].fillna(0) + 0.20 * h["gc_score"].fillna(0)).clip(-1, 1)
    confirm = int(params.get("confirm_enter_days") or 5)
    h["support_score"] = h["factor"].rolling(confirm, min_periods=1).mean()
    h["share_source"] = share_source
    h["era"] = "single_" + etf
    if "share_z" not in h.columns:
        h["share_z"] = np.nan
    h["bench_ret"] = h["close"].pct_change()
    h["news_spark"] = build_news_spark_series(
        h["date"],
        h["close"],
        h["bench_ret"],
        gc_spark=h["gc_spark"],
        panic_ret=float(params.get("panic_ret") or -0.02),
        panic_dd=float(params.get("panic_dd") or -0.08),
        stress_lookback=int(params.get("stress_lookback") or 60),
        panic_spark_strength=float(
            params.get("panic_spark_strength") if params.get("panic_spark_strength") is not None else 0.5
        ),
        include_policy=bool(params.get("use_policy_events", True)),
    )
    _pol_buy, pol_risk = build_policy_series(h["date"])
    h["policy_buy"] = _pol_buy
    h["policy_risk"] = pol_risk
    # 弱政策(<1.0)只作持仓延长；强政策已进入 news_spark
    h["policy_support"] = _pol_buy.where(_pol_buy > 0, 0.0)
    h["huijin_confirm"] = build_huijin_confirm_series(
        h["date"],
        mode=str(params.get("huijin_calendar_mode") or "buy_only"),
    )
    pos, state = apply_position_logic(
        h["factor"],
        h["close"],
        params=params,
        spark=h["news_spark"],
        share_z=h["share_z"],
        huijin_confirm=h["huijin_confirm"],
        policy_risk=h["policy_risk"],
        policy_support=h["policy_support"],
        dates=h["date"],
    )
    h["position"] = pos
    h["episode_state"] = state

    cols = [
        "date",
        "close",
        "amount",
        "factor",
        "support_score",
        "position",
        "episode_state",
        "proxy",
        "gc_spark",
        "news_spark",
        "policy_buy",
        "policy_risk",
        "policy_support",
        "huijin_confirm",
        "share_source",
        "era",
        "bench_ret",
        "share_z",
    ]
    if "share_chg_4w" in h.columns:
        cols.append("share_chg_4w")
    return h[[c for c in cols if c in h.columns]].dropna(subset=["date", "close", "factor"]).reset_index(drop=True)

