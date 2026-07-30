"""业绩预告双路径因子（earnings_forecast）。

是否公告直买（追高）综合三维：
1. 超预期幅度：爆发（≥100%）与一般强增（≥30%）分档；轻度增长不追
2. 中长期股价位置：约两年涨幅已高则不追
3. 短期涨幅：公告前已炒过则不追

否则走公告后回调买入。对齐发布日；收盘成交；计佣金+印花税。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("webapi.factors.earnings_forecast")

POSITIVE_TYPES = {
    "预增",
    "略增",
    "扭亏",
    "续盈",
    "减亏",
    "大幅上升",
    "增长",
}

DEFAULT_PARAMS: Dict[str, Any] = {
    "universe": "hs300",  # hs300 | zz500 | custom
    "forecast_start": "2018-01-01",
    "min_chg_pct_dwn": 10.0,  # 基础正面：增长下限 ≥10%（扭亏等豁免）
    "strong_chg_pct_dwn": 30.0,  # 较强：≥30%
    "explosive_chg_pct_dwn": 100.0,  # 突然爆发：≥100%（与+30%档位区分）
    # 短期：公告前涨幅
    "pre_run_lookback": 20,
    "pre_run_max": 0.05,  # 较强档：短期 ≤5% 才可考虑直买
    "pre_run_max_explosive": 0.10,  # 爆发档：短期可放到 ≤10%
    # 中长期位置：约 2 年
    "lt_lookback": 504,
    "lt_quiet_max": 0.40,  # 两年涨幅 ≤40% 视为位置不高
    "lt_hot_min": 1.00,  # 两年涨幅 ≥100% 视为已涨很久
    # 直买路径：公告日收盘
    "announce_buy_delay": 0,
    # 回调路径
    "min_days_after_announce": 3,
    "max_days_wait": 45,
    "pullback_pct": 0.08,
    "hold_days": 20,
    "stop_loss": 0.15,
    "max_positions": 8,
    "cash_annual": 0.0,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.4,
    "bench_code": "sh.000300",
}


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "factors" / "earnings_forecast"


def _clear_proxy() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


class _RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = max(float(interval), 0.05)
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = self.interval - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


def _bs_login():
    import baostock as bs  # noqa: WPS433

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return bs


def _rs_to_df(rs) -> pd.DataFrame:
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=list(rs.fields or []))
    return pd.DataFrame(rows, columns=rs.fields)


def fetch_universe_codes(universe: str, limiter: _RateLimiter) -> List[str]:
    """返回 baostock 风格代码列表，如 sh.600000。"""
    cache = _data_dir() / f"universe_{universe}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        return [str(x) for x in df["code"].tolist()]

    _clear_proxy()
    bs = _bs_login()
    try:
        limiter.wait()
        if universe == "zz500":
            rs = bs.query_zz500_stocks()
        else:
            rs = bs.query_hs300_stocks()
        df = _rs_to_df(rs)
        if df.empty:
            return []
        # fields typically: updateDate, code, code_name
        out = df[["code"]].drop_duplicates()
        _data_dir().mkdir(parents=True, exist_ok=True)
        out.to_parquet(cache, index=False)
        return out["code"].astype(str).tolist()
    finally:
        bs.logout()


def fetch_forecast_report(
    code: str,
    start_date: str,
    end_date: str,
    limiter: _RateLimiter,
    *,
    force: bool = False,
    bs=None,
) -> pd.DataFrame:
    cache = _data_dir() / "forecast" / f"{code.replace('.', '_')}.parquet"
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["profitForcastExpPubDate"] = pd.to_datetime(df["profitForcastExpPubDate"], errors="coerce")
        return df

    own_session = bs is None
    if own_session:
        _clear_proxy()
        bs = _bs_login()
    try:
        limiter.wait()
        rs = bs.query_forecast_report(code, start_date=start_date, end_date=end_date)
        df = _rs_to_df(rs)
        cache.parent.mkdir(parents=True, exist_ok=True)
        if df.empty:
            empty = pd.DataFrame(
                columns=[
                    "code",
                    "profitForcastExpPubDate",
                    "profitForcastExpStatDate",
                    "profitForcastType",
                    "profitForcastAbstract",
                    "profitForcastChgPctUp",
                    "profitForcastChgPctDwn",
                ]
            )
            empty.to_parquet(cache, index=False)
            return empty
        df.to_parquet(cache, index=False)
        df["profitForcastExpPubDate"] = pd.to_datetime(df["profitForcastExpPubDate"], errors="coerce")
        return df
    finally:
        if own_session:
            bs.logout()


def fetch_daily_bars(
    code: str,
    start_date: str,
    end_date: str,
    limiter: _RateLimiter,
    *,
    force: bool = False,
    bs=None,
) -> pd.DataFrame:
    cache = _data_dir() / "daily" / f"{code.replace('.', '_')}.parquet"
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        last = df["date"].max()
        first = df["date"].min()
        end_ok = pd.notna(last) and last >= pd.Timestamp(end_date) - pd.Timedelta(days=5)
        start_ok = pd.notna(first) and first <= pd.Timestamp(start_date) + pd.Timedelta(days=10)
        if end_ok and start_ok:
            return df.sort_values("date").reset_index(drop=True)

    own_session = bs is None
    if own_session:
        _clear_proxy()
        bs = _bs_login()
    try:
        limiter.wait()
        rs = bs.query_history_k_data_plus(
            code,
            "date,code,open,high,low,close,volume,amount,turn,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
        df = _rs_to_df(rs)
        if df.empty:
            empty = pd.DataFrame(
                columns=["date", "code", "open", "high", "low", "close", "volume", "amount", "turn", "pctChg"]
            )
            cache.parent.mkdir(parents=True, exist_ok=True)
            empty.to_parquet(cache, index=False)
            return empty
        for c in ("open", "high", "low", "close", "volume", "amount", "turn", "pctChg"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            old = pd.read_parquet(cache)
            old["date"] = pd.to_datetime(old["date"], errors="coerce")
            df = (
                pd.concat([old, df], ignore_index=True)
                .dropna(subset=["date", "close"])
                .drop_duplicates("date", keep="last")
                .sort_values("date")
            )
        df.to_parquet(cache, index=False)
        return df.reset_index(drop=True)
    finally:
        if own_session:
            bs.logout()


def _forecast_chg_floor(row: pd.Series) -> Optional[float]:
    dwn = pd.to_numeric(row.get("profitForcastChgPctDwn"), errors="coerce")
    up = pd.to_numeric(row.get("profitForcastChgPctUp"), errors="coerce")
    if pd.notna(dwn):
        return float(dwn)
    if pd.notna(up):
        return float(up)
    return None


def _is_positive_forecast(row: pd.Series, params: Dict[str, Any]) -> bool:
    typ = str(row.get("profitForcastType") or "").strip()
    if typ not in POSITIVE_TYPES and typ not in {"预盈"}:
        if not any(t in typ for t in POSITIVE_TYPES):
            return False
    if typ in {"扭亏", "减亏", "续盈", "预盈"}:
        return True
    floor = float(params.get("min_chg_pct_dwn") or 10.0)
    base = _forecast_chg_floor(row)
    if base is None:
        return typ in POSITIVE_TYPES
    return float(base) >= floor


def _surprise_tier(row: pd.Series, params: Dict[str, Any]) -> str:
    """超预期分档：explosive / strong / mild / none。

    突然爆发（如翻倍以上）与一般增长 30% 不是同一档。
    """
    typ = str(row.get("profitForcastType") or "").strip()
    explosive = float(params.get("explosive_chg_pct_dwn") or 100.0)
    strong = float(params.get("strong_chg_pct_dwn") or 30.0)
    base = _forecast_chg_floor(row)
    if base is not None:
        if float(base) >= explosive:
            return "explosive"
        if float(base) >= strong:
            return "strong"
        if float(base) >= float(params.get("min_chg_pct_dwn") or 10.0):
            return "mild"
    if typ in {"扭亏"}:
        # 扭亏接近质变，按较强（未到爆发）
        return "strong"
    if typ in {"预增", "大幅上升"}:
        return "strong" if base is None else "mild"
    if typ in POSITIVE_TYPES or typ in {"预盈"}:
        return "mild"
    return "none"


def _is_strong_forecast(row: pd.Series, params: Dict[str, Any]) -> bool:
    return _surprise_tier(row, params) in {"strong", "explosive"}


def _price_run(bars: pd.DataFrame, ann_i: int, lookback: int) -> Optional[float]:
    """公告日前 lookback 个交易日收盘相对涨幅。"""
    if ann_i <= 0:
        return None
    lb = max(int(lookback), 1)
    start_i = ann_i - lb
    if start_i < 0:
        return None
    c0 = bars.loc[start_i, "close"]
    c1 = bars.loc[ann_i - 1, "close"]
    if pd.isna(c0) or pd.isna(c1) or float(c0) <= 0:
        return None
    return float(c1) / float(c0) - 1.0


def _should_chase(
    surprise: str,
    pre_run: float,
    lt_run: float,
    params: Dict[str, Any],
) -> Tuple[bool, str]:
    """三维综合：是否公告直买（追预期）。

    1) 超预期幅度：mild 不追；strong/explosive 才可能追
    2) 中长期位置：两年已大涨则不追
    3) 短期涨幅：已炒过则不追（爆发档阈值略宽）
    """
    lt_quiet_max = float(params.get("lt_quiet_max") or 0.40)
    lt_hot_min = float(params.get("lt_hot_min") or 1.0)
    pre_max = float(params.get("pre_run_max") or 0.05)
    pre_max_exp = float(params.get("pre_run_max_explosive") or 0.10)

    if surprise not in {"strong", "explosive"}:
        return False, "超预期不足（非强/爆发），等回调"
    if lt_run >= lt_hot_min:
        return False, f"中长期已大涨({lt_run*100:.0f}%)，不追高"
    if lt_run > lt_quiet_max:
        return False, f"中长期位置偏高({lt_run*100:.0f}%)，等回调"

    if surprise == "explosive":
        if pre_run > pre_max_exp:
            return False, f"爆发但短期已涨{pre_run*100:.0f}%>{pre_max_exp*100:.0f}%，等回调"
        return True, f"爆发超预期+中长期不高+短期可控({pre_run*100:.0f}%)，公告直买"

    # strong
    if pre_run > pre_max:
        return False, f"较强但短期已涨{pre_run*100:.0f}%>{pre_max*100:.0f}%，等回调"
    return True, f"较强超预期+中长期不高+短期未涨，公告直买"


def collect_positive_events(
    codes: Sequence[str],
    params: Optional[Dict[str, Any]] = None,
    *,
    end_date: Optional[str] = None,
    force: bool = False,
    progress_every: int = 20,
) -> pd.DataFrame:
    params = {**DEFAULT_PARAMS, **(params or {})}
    limiter = _RateLimiter(float(params.get("request_interval_sec") or 0.4))
    start = str(params.get("forecast_start") or "2018-01-01")
    end = end_date or datetime.now().strftime("%Y-%m-%d")
    frames: List[pd.DataFrame] = []
    _clear_proxy()
    bs = _bs_login()
    try:
        for i, code in enumerate(codes, 1):
            try:
                raw = fetch_forecast_report(code, start, end, limiter, force=force, bs=bs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("forecast fetch fail %s: %s", code, exc)
                continue
            if raw.empty:
                continue
            keep_rows = []
            for _, row in raw.iterrows():
                if _is_positive_forecast(row, params):
                    keep_rows.append(row)
            if keep_rows:
                frames.append(pd.DataFrame(keep_rows))
            if progress_every and i % progress_every == 0:
                print(f"[forecast] {i}/{len(codes)}")
    finally:
        bs.logout()
    if not frames:
        return pd.DataFrame()
    ev = pd.concat(frames, ignore_index=True)
    ev["profitForcastExpPubDate"] = pd.to_datetime(ev["profitForcastExpPubDate"], errors="coerce")
    ev = ev.dropna(subset=["profitForcastExpPubDate", "code"])
    ev = ev.sort_values(["code", "profitForcastExpPubDate"]).drop_duplicates(
        ["code", "profitForcastExpPubDate", "profitForcastExpStatDate"], keep="last"
    )
    path = _data_dir() / "positive_events.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(path, index=False)
    return ev.reset_index(drop=True)


@dataclass
class TradeLeg:
    code: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    event_pub: pd.Timestamp
    pullback: float
    days_after: int
    reason: str
    entry_mode: str = "pullback"  # announce_buy | pullback
    pre_run: float = 0.0
    lt_run: float = 0.0
    surprise_tier: str = "mild"
    strong: bool = False
    chase_reason: str = ""


def _find_entry_announce_buy(
    bars: pd.DataFrame,
    ann_i: int,
    params: Dict[str, Any],
) -> Optional[Tuple[pd.Timestamp, float, float, int]]:
    delay = int(params.get("announce_buy_delay") or 0)
    i = ann_i + max(delay, 0)
    if i >= len(bars):
        return None
    cl = bars.loc[i, "close"]
    if pd.isna(cl):
        return None
    return pd.Timestamp(bars.loc[i, "date"]), float(cl), 0.0, int(i - ann_i)


def _find_entry_after_pullback(
    bars: pd.DataFrame,
    ann_i: int,
    params: Dict[str, Any],
) -> Optional[Tuple[pd.Timestamp, float, float, int]]:
    """返回 (entry_date, entry_price, pullback, days_after) 或 None。"""
    min_d = int(params.get("min_days_after_announce") or 3)
    max_d = int(params.get("max_days_wait") or 45)
    pullback_need = -abs(float(params.get("pullback_pct") or 0.08))

    peak = float(bars.loc[ann_i, "high"] if pd.notna(bars.loc[ann_i, "high"]) else bars.loc[ann_i, "close"])
    start_i = ann_i + min_d
    end_i = min(ann_i + max_d, len(bars) - 1)
    if start_i > end_i:
        return None

    for i in range(ann_i, start_i):
        hi = bars.loc[i, "high"]
        if pd.notna(hi):
            peak = max(peak, float(hi))

    for i in range(start_i, end_i + 1):
        hi = bars.loc[i, "high"]
        cl = bars.loc[i, "close"]
        if pd.notna(hi):
            peak = max(peak, float(hi))
        if pd.isna(cl) or peak <= 0:
            continue
        pb = float(cl) / peak - 1.0
        if pb <= pullback_need:
            return pd.Timestamp(bars.loc[i, "date"]), float(cl), pb, int(i - ann_i)
    return None


def _find_entry(
    bars: pd.DataFrame,
    pub_date: pd.Timestamp,
    event_row: pd.Series,
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """综合超预期/中长期位置/短期涨幅，决定直买或回调。"""
    if bars.empty:
        return None
    b = bars.sort_values("date").reset_index(drop=True)
    idx = b.index[b["date"] >= pd.Timestamp(pub_date.date())]
    if len(idx) == 0:
        return None
    ann_i = int(idx[0])
    pre_lb = int(params.get("pre_run_lookback") or 20)
    lt_lb = int(params.get("lt_lookback") or 504)
    pre_run = _price_run(b, ann_i, pre_lb)
    lt_run = _price_run(b, ann_i, lt_lb)
    if pre_run is None:
        pre_run = 0.0
    if lt_run is None:
        lt_run = float(params.get("lt_quiet_max") or 0.40) + 0.01

    surprise = _surprise_tier(event_row, params)
    chase, chase_reason = _should_chase(surprise, float(pre_run), float(lt_run), params)
    strong = surprise in {"strong", "explosive"}

    if chase:
        hit = _find_entry_announce_buy(b, ann_i, params)
        mode = "announce_buy"
    else:
        hit = _find_entry_after_pullback(b, ann_i, params)
        mode = "pullback"
    if hit is None:
        return None
    dt, px, pb, days = hit
    return {
        "entry_date": dt,
        "entry_price": px,
        "pullback": pb,
        "days_after": days,
        "entry_mode": mode,
        "pre_run": float(pre_run),
        "lt_run": float(lt_run),
        "surprise_tier": surprise,
        "strong": strong,
        "chase_reason": chase_reason,
    }


def build_trade_legs(
    events: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
    *,
    price_start: str = "2016-01-01",
    price_end: Optional[str] = None,
    force_price: bool = False,
) -> pd.DataFrame:
    params = {**DEFAULT_PARAMS, **(params or {})}
    limiter = _RateLimiter(float(params.get("request_interval_sec") or 0.4))
    end = price_end or datetime.now().strftime("%Y-%m-%d")
    hold_days = int(params.get("hold_days") or 20)
    stop_loss = float(params.get("stop_loss") or 0.15)
    legs: List[TradeLeg] = []

    if events.empty:
        return pd.DataFrame()

    codes = sorted(events["code"].astype(str).unique().tolist())
    price_map: Dict[str, pd.DataFrame] = {}
    need_fetch: List[str] = []
    for code in codes:
        cache = _data_dir() / "daily" / f"{str(code).replace('.', '_')}.parquet"
        if cache.exists() and not force_price:
            df = pd.read_parquet(cache)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date", "close"]).sort_values("date")
            first = df["date"].min() if not df.empty else None
            last = df["date"].max() if not df.empty else None
            end_ok = pd.notna(last) and last >= pd.Timestamp(end) - pd.Timedelta(days=10)
            start_ok = pd.notna(first) and first <= pd.Timestamp(price_start) + pd.Timedelta(days=30)
            if end_ok and start_ok and not df.empty:
                price_map[code] = df.reset_index(drop=True)
                continue
            if not df.empty:
                # 先用现有缓存，缺段稍后再补
                price_map[code] = df.reset_index(drop=True)
        need_fetch.append(code)

    if need_fetch:
        _clear_proxy()
        bs = None
        for attempt in range(3):
            try:
                bs = _bs_login()
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("baostock login retry %s: %s", attempt + 1, exc)
                time.sleep(2 * (attempt + 1))
        if bs is None:
            print(f"[warn] baostock unavailable; using cache only, skip fetch n={len(need_fetch)}")
        else:
            try:
                for i, code in enumerate(need_fetch, 1):
                    try:
                        price_map[code] = fetch_daily_bars(
                            code, price_start, end, limiter, force=force_price, bs=bs
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("daily fetch fail %s: %s", code, exc)
                        if code not in price_map:
                            price_map[code] = pd.DataFrame()
                    if i % 20 == 0:
                        print(f"[daily] {i}/{len(need_fetch)}")
            finally:
                bs.logout()

    for _, ev in events.iterrows():
        code = str(ev["code"])
        pub = pd.Timestamp(ev["profitForcastExpPubDate"])
        bars = price_map.get(code)
        if bars is None or bars.empty:
            continue
        hit = _find_entry(bars, pub, ev, params)
        if hit is None:
            continue
        entry_dt = hit["entry_date"]
        entry_px = float(hit["entry_price"])
        b = bars.sort_values("date").reset_index(drop=True)
        e_idx_list = b.index[b["date"] == entry_dt]
        if len(e_idx_list) == 0:
            continue
        e_i = int(e_idx_list[0])
        exit_i = min(e_i + hold_days, len(b) - 1)
        reason = "hold_end"
        exit_px = float(b.loc[exit_i, "close"])
        exit_dt = pd.Timestamp(b.loc[exit_i, "date"])
        for j in range(e_i + 1, exit_i + 1):
            cl = b.loc[j, "close"]
            if pd.isna(cl):
                continue
            if float(cl) <= entry_px * (1.0 - stop_loss):
                exit_i = j
                exit_px = float(cl)
                exit_dt = pd.Timestamp(b.loc[j, "date"])
                reason = "stop_loss"
                break
        legs.append(
            TradeLeg(
                code=code,
                entry_date=entry_dt,
                entry_price=entry_px,
                exit_date=exit_dt,
                exit_price=exit_px,
                event_pub=pub,
                pullback=float(hit["pullback"]),
                days_after=int(hit["days_after"]),
                reason=reason,
                entry_mode=str(hit["entry_mode"]),
                pre_run=float(hit["pre_run"]),
                lt_run=float(hit["lt_run"]),
                surprise_tier=str(hit["surprise_tier"]),
                strong=bool(hit["strong"]),
                chase_reason=str(hit["chase_reason"]),
            )
        )

    if not legs:
        return pd.DataFrame()
    df = pd.DataFrame([leg.__dict__ for leg in legs])
    path = _data_dir() / "trade_legs.parquet"
    df.to_parquet(path, index=False)
    return df


def run_portfolio_backtest(
    legs: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """等权、有限名额组合；收盘调仓；扣佣金+卖出印花税。"""
    params = {**DEFAULT_PARAMS, **(params or {})}
    if legs is None or legs.empty:
        return pd.DataFrame(), {"error": "no_legs"}

    legs = legs.copy()
    legs["entry_date"] = pd.to_datetime(legs["entry_date"])
    legs["exit_date"] = pd.to_datetime(legs["exit_date"])
    commission = float(params.get("commission_rate") or 0.0001)
    stamp = float(params.get("stamp_tax_sell") or 0.001)
    max_pos = int(params.get("max_positions") or 8)
    cash_daily = float(params.get("cash_annual") or 0.0) / 365.0

    # 交易日日历取自基准指数
    day_set = sorted(set(legs["entry_date"].tolist()) | set(legs["exit_date"].tolist()))
    # 扩展为连续交易日序列：读基准指数
    limiter = _RateLimiter(float(params.get("request_interval_sec") or 0.4))
    bench_code = str(params.get("bench_code") or "sh.000300")
    bench = fetch_daily_bars(
        bench_code,
        (start or str(legs["entry_date"].min().date())),
        (end or datetime.now().strftime("%Y-%m-%d")),
        limiter,
    )
    if bench.empty:
        calendar = pd.DatetimeIndex(sorted(day_set))
        bench_ret = pd.Series(0.0, index=calendar)
    else:
        calendar = pd.DatetimeIndex(bench["date"].sort_values().unique())
        if start:
            calendar = calendar[calendar >= pd.Timestamp(start)]
        if end:
            calendar = calendar[calendar <= pd.Timestamp(end)]
        b = bench.set_index("date").sort_index()
        bench_ret = b["close"].pct_change().reindex(calendar).fillna(0.0)

    # 预装个股收益
    code_ret: Dict[str, pd.Series] = {}
    for code in legs["code"].unique():
        path = _data_dir() / "daily" / f"{str(code).replace('.', '_')}.parquet"
        if not path.exists():
            continue
        px = pd.read_parquet(path)
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = px.dropna(subset=["date", "close"]).set_index("date").sort_index()
        code_ret[str(code)] = px["close"].pct_change()

    # 事件驱动占用名额：按 entry 排序，满仓则跳过
    accepted = []
    active: List[dict] = []
    for _, row in legs.sort_values("entry_date").iterrows():
        # 清掉已结束
        active = [a for a in active if a["exit_date"] > row["entry_date"]]
        if len(active) >= max_pos:
            continue
        accepted.append(row)
        active.append(row.to_dict())
    if not accepted:
        return pd.DataFrame(), {"error": "no_accepted_legs"}
    acc = pd.DataFrame(accepted)

    rows = []
    open_pos: Dict[str, dict] = {}
    equity = 1.0
    for dt in calendar:
        cost_today = 0.0
        # 收盘买入：当日收益只算隔夜仓，不含今日新开
        overnight = list(open_pos.keys())
        asset_ret = 0.0
        if overnight:
            w = 1.0 / len(overnight)
            for code in overnight:
                r = code_ret.get(code)
                if r is None or dt not in r.index or pd.isna(r.loc[dt]):
                    continue
                asset_ret += w * float(r.loc[dt])

        # 收盘平仓（持有日含 exit_date 当日收益）
        to_close = [c for c, info in open_pos.items() if pd.Timestamp(info["exit_date"]) == dt]
        for code in to_close:
            cost_today += (commission + stamp) * (1.0 / max_pos)
            open_pos.pop(code, None)

        # 收盘开仓
        to_open = acc[acc["entry_date"] == dt]
        for _, row in to_open.iterrows():
            if len(open_pos) >= max_pos:
                break
            code = str(row["code"])
            if code in open_pos:
                continue
            open_pos[code] = row.to_dict()
            cost_today += commission * (1.0 / max_pos)

        n_mark = len(overnight)  # 当日暴露按隔夜仓计
        if overnight:
            gross = asset_ret
        else:
            gross = cash_daily
        net = gross - cost_today
        equity *= 1.0 + net
        rows.append(
            {
                "date": dt,
                "n_pos": n_mark,
                "asset_ret": asset_ret,
                "cost_ret": cost_today,
                "strategy_ret": net,
                "equity": equity,
                "bench_ret": float(bench_ret.loc[dt]) if dt in bench_ret.index else 0.0,
                "position": (n_mark / max_pos) if max_pos else 0.0,
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, {"error": "empty_daily"}

    eq = daily["equity"]
    n = len(daily)
    years = max(n / 252.0, 1e-9)
    total = float(eq.iloc[-1] - 1)
    ann = float(eq.iloc[-1] ** (1 / years) - 1)
    vol = float(daily["strategy_ret"].std() * (252 ** 0.5))
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    bh = (1 + daily["bench_ret"].fillna(0)).cumprod()
    mode_counts = acc["entry_mode"].value_counts().to_dict() if "entry_mode" in acc.columns else {}
    summary = {
        "bars": n,
        "start": str(pd.Timestamp(daily["date"].iloc[0]).date()),
        "end": str(pd.Timestamp(daily["date"].iloc[-1]).date()),
        "total_return": round(total, 4),
        "annual_return": round(ann, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "buy_hold_return": round(float(bh.iloc[-1] - 1), 4),
        "n_events": int(len(legs)),
        "n_legs_raw": int(len(legs)),
        "n_legs_accepted": int(len(acc)),
        "n_announce_buy": int(mode_counts.get("announce_buy", 0)),
        "n_pullback": int(mode_counts.get("pullback", 0)),
        "avg_position": round(float(daily["position"].mean()), 4),
        "total_cost_drag": round(float(daily["cost_ret"].sum()), 4),
        "commission_rate": commission,
        "stamp_tax_sell": stamp,
        "pullback_pct": params.get("pullback_pct"),
        "pre_run_max": params.get("pre_run_max"),
        "pre_run_max_explosive": params.get("pre_run_max_explosive"),
        "lt_quiet_max": params.get("lt_quiet_max"),
        "lt_hot_min": params.get("lt_hot_min"),
        "strong_chg_pct_dwn": params.get("strong_chg_pct_dwn"),
        "explosive_chg_pct_dwn": params.get("explosive_chg_pct_dwn"),
        "min_days_after_announce": params.get("min_days_after_announce"),
        "hold_days": params.get("hold_days"),
        "stop_loss": params.get("stop_loss"),
        "position_logic": "dual_path_3factor_chase",
        "accounting": "eod_rebalance_hold_earns_day",
        "note": "追高综合：超预期幅度+中长期位置+短期涨幅；否则等回调",
    }
    return daily, summary


def compute_earnings_forecast_signal(
    params: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    """最新信号：双路径下今日可买的标的。"""
    params = {**DEFAULT_PARAMS, **(params or {})}
    asof_dt = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now().date())
    asof_dt = asof_dt.normalize()
    ev_path = _data_dir() / "positive_events.parquet"
    if not ev_path.exists():
        return {
            "factor_id": "earnings_forecast",
            "asof": asof_dt.to_pydatetime(),
            "signal": "neutral",
            "value": 0.0,
            "note": "无缓存事件，请先运行 refresh_earnings_forecast_data.py",
        }
    events = pd.read_parquet(ev_path)
    events["profitForcastExpPubDate"] = pd.to_datetime(events["profitForcastExpPubDate"], errors="coerce")
    max_d = int(params.get("max_days_wait") or 45)
    recent = events[events["profitForcastExpPubDate"] >= asof_dt - pd.Timedelta(days=max_d + 10)]
    limiter = _RateLimiter(float(params.get("request_interval_sec") or 0.4))
    candidates = []
    for _, ev in recent.iterrows():
        code = str(ev["code"])
        bars = fetch_daily_bars(
            code,
            (asof_dt - pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
            asof_dt.strftime("%Y-%m-%d"),
            limiter,
        )
        hit = _find_entry(bars, pd.Timestamp(ev["profitForcastExpPubDate"]), ev, params)
        if hit is None:
            continue
        entry_dt = hit["entry_date"]
        if entry_dt == asof_dt or abs((entry_dt - asof_dt).days) <= 1:
            candidates.append(
                {
                    "code": code,
                    "pub": str(pd.Timestamp(ev["profitForcastExpPubDate"]).date()),
                    "entry": str(pd.Timestamp(entry_dt).date()),
                    "entry_mode": hit["entry_mode"],
                    "surprise_tier": hit["surprise_tier"],
                    "pre_run": round(float(hit["pre_run"]), 4),
                    "lt_run": round(float(hit["lt_run"]), 4),
                    "pullback": round(float(hit["pullback"]), 4),
                    "days_after": hit["days_after"],
                    "chase_reason": hit["chase_reason"],
                    "type": ev.get("profitForcastType"),
                }
            )
    signal = "buy" if candidates else "neutral"
    return {
        "factor_id": "earnings_forecast",
        "asof": asof_dt.to_pydatetime(),
        "signal": signal,
        "value": float(len(candidates)),
        "components": {
            "candidates": candidates[:20],
            "params": {
                "explosive_chg_pct_dwn": params.get("explosive_chg_pct_dwn"),
                "strong_chg_pct_dwn": params.get("strong_chg_pct_dwn"),
                "pre_run_max": params.get("pre_run_max"),
                "lt_quiet_max": params.get("lt_quiet_max"),
                "pullback_pct": params.get("pullback_pct"),
            },
        },
        "note": "追高综合超预期/中长期位置/短期涨幅；否则等回调",
    }
