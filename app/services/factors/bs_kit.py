"""baostock 公共工具：限速、宇宙、日线（含估值）、季度财务、组合回测骨架。"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("webapi.factors.bs_kit")

ROOT = Path(__file__).resolve().parents[3]
FACTORS_DATA = ROOT / "data" / "factors"


def clear_proxy() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


class RateLimiter:
    def __init__(self, interval: float = 0.35) -> None:
        self.interval = max(float(interval), 0.05)
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = self.interval - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


def bs_login():
    import baostock as bs  # noqa: WPS433

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return bs


def rs_to_df(rs) -> pd.DataFrame:
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=list(rs.fields or []))
    return pd.DataFrame(rows, columns=rs.fields)


def factor_cache_dir(factor_id: str) -> Path:
    p = FACTORS_DATA / factor_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def shared_cache_dir() -> Path:
    """日线/财务/宇宙跨因子复用，避免每个因子重复拉取。"""
    p = FACTORS_DATA / "_shared"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fetch_universe_codes(
    universe: str,
    limiter: RateLimiter,
    cache_dir: Path,
) -> List[str]:
    cache = cache_dir / f"universe_{universe}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)["code"].astype(str).tolist()
    clear_proxy()
    bs = bs_login()
    try:
        limiter.wait()
        u = (universe or "hs300").lower().strip()
        if u in ("all", "all_a", "ashare"):
            # 全 A：股票基础信息；过滤退市/非股票
            rs = bs.query_stock_basic()
            df = rs_to_df(rs)
            if df.empty:
                return []
            code_col = "code" if "code" in df.columns else df.columns[0]
            out = df.copy()
            out["code"] = out[code_col].astype(str)
            if "type" in out.columns:
                # type=1 股票（baostock 约定）
                out = out[out["type"].astype(str).isin(["1", "1.0"])]
            if "status" in out.columns:
                out = out[out["status"].astype(str).isin(["1", "1.0", ""])]
            # 只要沪深 A 股代码
            out = out[out["code"].str.match(r"^(sh|sz)\.\d{6}$", na=False)]
            out = out[["code"]].drop_duplicates()
        elif u == "zz500":
            rs = bs.query_zz500_stocks()
            df = rs_to_df(rs)
            if df.empty:
                return []
            out = df[["code"]].drop_duplicates()
        else:
            rs = bs.query_hs300_stocks()
            df = rs_to_df(rs)
            if df.empty:
                return []
            out = df[["code"]].drop_duplicates()
        out.to_parquet(cache, index=False)
        return out["code"].astype(str).tolist()
    finally:
        bs.logout()


def fetch_daily_valuation(
    code: str,
    start: str,
    end: str,
    limiter: RateLimiter,
    cache_dir: Path,
    *,
    force: bool = False,
    bs=None,
) -> pd.DataFrame:
    """日线 + peTTM/pbMRQ（后复权）。"""
    cache = cache_dir / "daily" / f"{code.replace('.', '_')}.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        last = df["date"].max()
        first = df["date"].min()
        end_ok = pd.notna(last) and last >= pd.Timestamp(end) - pd.Timedelta(days=10)
        start_ok = pd.notna(first) and first <= pd.Timestamp(start) + pd.Timedelta(days=40)
        if end_ok and start_ok and not df.empty:
            return df.sort_values("date").reset_index(drop=True)

    own = bs is None
    if own:
        clear_proxy()
        bs = bs_login()
    try:
        limiter.wait()
        rs = bs.query_history_k_data_plus(
            code,
            "date,code,open,high,low,close,volume,amount,turn,pctChg,peTTM,pbMRQ",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
        df = rs_to_df(rs)
        if df.empty:
            empty = pd.DataFrame(
                columns=[
                    "date",
                    "code",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "turn",
                    "pctChg",
                    "peTTM",
                    "pbMRQ",
                ]
            )
            empty.to_parquet(cache, index=False)
            return empty
        for c in ("open", "high", "low", "close", "volume", "amount", "turn", "pctChg", "peTTM", "pbMRQ"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
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
        if own:
            bs.logout()


def fetch_profit_quarters(
    code: str,
    years: Sequence[int],
    limiter: RateLimiter,
    cache_dir: Path,
    *,
    force: bool = False,
    bs=None,
) -> pd.DataFrame:
    cache = cache_dir / "profit" / f"{code.replace('.', '_')}.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        if not df.empty:
            df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")
            return df

    own = bs is None
    if own:
        clear_proxy()
        bs = bs_login()
    frames = []
    try:
        for year in years:
            for q in (1, 2, 3, 4):
                try:
                    limiter.wait()
                    rs = bs.query_profit_data(code=code, year=year, quarter=q)
                    part = rs_to_df(rs)
                    if not part.empty:
                        frames.append(part)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("profit %s %sQ%s: %s", code, year, q, exc)
    finally:
        if own:
            bs.logout()
    if not frames:
        empty = pd.DataFrame()
        empty.to_parquet(cache, index=False)
        return empty
    df = pd.concat(frames, ignore_index=True)
    for c in ("roeAvg", "npMargin", "gpMargin", "netProfit", "epsTTM", "MBRevenue"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["pubDate"] = pd.to_datetime(df.get("pubDate"), errors="coerce")
    df["statDate"] = pd.to_datetime(df.get("statDate"), errors="coerce")
    df = df.dropna(subset=["pubDate"]).sort_values("pubDate").drop_duplicates(
        ["statDate"], keep="last"
    )
    df.to_parquet(cache, index=False)
    return df.reset_index(drop=True)


def fetch_growth_quarters(
    code: str,
    years: Sequence[int],
    limiter: RateLimiter,
    cache_dir: Path,
    *,
    force: bool = False,
    bs=None,
) -> pd.DataFrame:
    cache = cache_dir / "growth" / f"{code.replace('.', '_')}.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        if not df.empty:
            df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")
            return df
    own = bs is None
    if own:
        clear_proxy()
        bs = bs_login()
    frames = []
    try:
        for year in years:
            for q in (1, 2, 3, 4):
                try:
                    limiter.wait()
                    rs = bs.query_growth_data(code=code, year=year, quarter=q)
                    part = rs_to_df(rs)
                    if not part.empty:
                        frames.append(part)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("growth %s %sQ%s: %s", code, year, q, exc)
    finally:
        if own:
            bs.logout()
    if not frames:
        empty = pd.DataFrame()
        empty.to_parquet(cache, index=False)
        return empty
    df = pd.concat(frames, ignore_index=True)
    for c in df.columns:
        if c not in ("code", "pubDate", "statDate"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["pubDate"] = pd.to_datetime(df.get("pubDate"), errors="coerce")
    df = df.dropna(subset=["pubDate"]).sort_values("pubDate").drop_duplicates(
        ["statDate"], keep="last"
    )
    df.to_parquet(cache, index=False)
    return df.reset_index(drop=True)


def code_to_em_symbol(code: str) -> str:
    """sh.600519 / sh_600519 -> SH600519"""
    s = str(code).strip().replace("_", ".")
    if "." in s:
        mkt, num = s.split(".", 1)
        return f"{mkt.upper()}{num}"
    if s.isdigit() and len(s) == 6:
        prefix = "SH" if s.startswith(("5", "6", "9")) else "SZ"
        return f"{prefix}{s}"
    return s.upper()


def fetch_contract_liab(
    code: str,
    cache_dir: Path,
    *,
    force: bool = False,
    limiter: Optional[RateLimiter] = None,
) -> pd.DataFrame:
    """东财资产负债表：合同负债 + 预收账款（新准则前后兼容）。

    返回列：pubDate, statDate, contract_liab, advance_recv, contract_liab_yoy
    contract_liab 为「合同负债与预收款」合并值（通常不同期只填其一）。
    """
    cache = cache_dir / "balance" / f"{code.replace('.', '_')}.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not force:
        try:
            df = pd.read_parquet(cache)
            if not df.empty and "contract_liab" in df.columns:
                df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")
                return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("balance cache read %s: %s", cache, exc)

    clear_proxy()
    if limiter is not None:
        limiter.wait()
    try:
        import akshare as ak

        raw = ak.stock_balance_sheet_by_report_em(symbol=code_to_em_symbol(code))
    except Exception as exc:  # noqa: BLE001
        logger.warning("contract_liab fetch %s failed: %s", code, exc)
        empty = pd.DataFrame(
            columns=["pubDate", "statDate", "contract_liab", "advance_recv", "contract_liab_yoy"]
        )
        empty.to_parquet(cache, index=False)
        return empty

    if raw is None or raw.empty:
        empty = pd.DataFrame(
            columns=["pubDate", "statDate", "contract_liab", "advance_recv", "contract_liab_yoy"]
        )
        empty.to_parquet(cache, index=False)
        return empty

    df = raw.copy()
    notice = pd.to_datetime(df["NOTICE_DATE"], errors="coerce") if "NOTICE_DATE" in df.columns else pd.Series(pd.NaT, index=df.index)
    report = pd.to_datetime(df["REPORT_DATE"], errors="coerce") if "REPORT_DATE" in df.columns else pd.Series(pd.NaT, index=df.index)
    cl = (
        pd.to_numeric(df["CONTRACT_LIAB"], errors="coerce")
        if "CONTRACT_LIAB" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    ar = (
        pd.to_numeric(df["ADVANCE_RECEIVABLES"], errors="coerce")
        if "ADVANCE_RECEIVABLES" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    yoy = (
        pd.to_numeric(df["CONTRACT_LIAB_YOY"], errors="coerce")
        if "CONTRACT_LIAB_YOY" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    # 合并：新准则后多在合同负债，旧准则在预收；同时有值则相加（极少）
    combined = cl.fillna(0.0) + ar.fillna(0.0)
    combined = combined.where(cl.notna() | ar.notna(), np.nan)

    out = pd.DataFrame(
        {
            "code": code,
            "pubDate": notice.fillna(report),
            "statDate": report,
            "contract_liab": combined,
            "advance_recv": ar,
            "contract_liab_raw": cl,
            "contract_liab_yoy": yoy,
        }
    )
    out = out.dropna(subset=["pubDate"]).sort_values("pubDate")
    out = out.drop_duplicates(["statDate"], keep="last").reset_index(drop=True)
    out.to_parquet(cache, index=False)
    return out


def fetch_industry_map(limiter: RateLimiter, cache_dir: Path, *, force: bool = False) -> pd.DataFrame:
    cache = cache_dir / "industry_map.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)
    clear_proxy()
    bs = bs_login()
    try:
        limiter.wait()
        rs = bs.query_stock_industry()
        df = rs_to_df(rs)
        if df.empty:
            return df
        # typically code, code_name, industry, industryClassification
        keep = [c for c in ("code", "code_name", "industry", "industryClassification") if c in df.columns]
        out = df[keep].drop_duplicates("code")
        out.to_parquet(cache, index=False)
        return out
    finally:
        bs.logout()


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """历史分位（含当日），window 不足则 NaN。"""

    def _pct(x: np.ndarray) -> float:
        if len(x) < max(60, window // 5):
            return np.nan
        v = x[-1]
        if np.isnan(v):
            return np.nan
        return float((np.sum(x <= v) - 1) / max(len(x) - 1, 1))

    return series.rolling(window, min_periods=max(60, window // 5)).apply(_pct, raw=True)


def attach_ma(df: pd.DataFrame, windows: Sequence[int] = (20, 60, 120)) -> pd.DataFrame:
    out = df.copy()
    for w in windows:
        out[f"ma{w}"] = out["close"].rolling(w).mean()
    return out


def run_equal_weight_backtest(
    legs: pd.DataFrame,
    *,
    params: Dict[str, Any],
    bench_daily: Optional[pd.DataFrame] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    """收盘调仓等权组合；买入当日不计收益。

    start/end = 交易区间：仅该区间内开仓的腿参与名额占用与净值；
    不结转区间前持仓。返回 (daily, summary, accepted_legs)。
    """
    empty_legs = pd.DataFrame()
    if legs is None or legs.empty:
        return pd.DataFrame(), {"error": "no_legs"}, empty_legs
    legs = legs.copy()
    legs["entry_date"] = pd.to_datetime(legs["entry_date"])
    legs["exit_date"] = pd.to_datetime(legs["exit_date"])
    # start = 交易起点：只保留该日及之后开仓的腿（不结转起点前持仓）
    if start:
        legs = legs[legs["entry_date"] >= pd.Timestamp(start)].copy()
    if end:
        legs = legs[legs["entry_date"] <= pd.Timestamp(end)].copy()
    if legs.empty:
        return pd.DataFrame(), {"error": "no_legs_after_start"}, empty_legs
    commission = float(params.get("commission_rate") or 0.0001)
    stamp = float(params.get("stamp_tax_sell") or 0.001)
    max_pos = int(params.get("max_positions") or 8)

    if bench_daily is None or bench_daily.empty:
        return pd.DataFrame(), {"error": "no_bench"}, empty_legs
    b = bench_daily.copy()
    b["date"] = pd.to_datetime(b["date"])
    b = b.dropna(subset=["date", "close"]).sort_values("date")
    calendar = pd.DatetimeIndex(b["date"].unique())
    if start:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    bench_ret = b.set_index("date")["close"].pct_change().reindex(calendar).fillna(0.0)

    code_ret: Dict[str, pd.Series] = {}
    for code in legs["code"].astype(str).unique():
        # expect caller to pass path via legs attrs or we skip - use close path in params cache
        pass

    # Prefer precomputed ret columns from legs expansion — rebuild from cache_dir
    cache_dir = Path(params.get("_cache_dir") or FACTORS_DATA)
    for code in legs["code"].astype(str).unique():
        path = cache_dir / "daily" / f"{str(code).replace('.', '_')}.parquet"
        if not path.exists():
            continue
        px = pd.read_parquet(path)
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = px.dropna(subset=["date", "close"]).set_index("date").sort_index()
        code_ret[str(code)] = px["close"].pct_change()

    accepted = []
    active: List[dict] = []
    for _, row in legs.sort_values("entry_date").iterrows():
        active = [a for a in active if pd.Timestamp(a["exit_date"]) > row["entry_date"]]
        if len(active) >= max_pos:
            continue
        accepted.append(row)
        active.append(row.to_dict())
    if not accepted:
        return pd.DataFrame(), {"error": "no_accepted_legs"}, empty_legs
    acc = pd.DataFrame(accepted)

    rows = []
    open_pos: Dict[str, dict] = {}
    equity = 1.0
    for dt in calendar:
        cost_today = 0.0
        overnight = list(open_pos.keys())
        asset_ret = 0.0
        if overnight:
            w = 1.0 / len(overnight)
            for code in overnight:
                r = code_ret.get(code)
                if r is None or dt not in r.index or pd.isna(r.loc[dt]):
                    continue
                asset_ret += w * float(r.loc[dt])

        to_close = [c for c, info in open_pos.items() if pd.Timestamp(info["exit_date"]) == dt]
        for code in to_close:
            cost_today += (commission + stamp) * (1.0 / max_pos)
            open_pos.pop(code, None)

        to_open = acc[acc["entry_date"] == dt]
        for _, row in to_open.iterrows():
            if len(open_pos) >= max_pos:
                break
            code = str(row["code"])
            if code in open_pos:
                continue
            open_pos[code] = row.to_dict()
            cost_today += commission * (1.0 / max_pos)

        n_mark = len(overnight)
        gross = asset_ret if overnight else 0.0
        net = gross - cost_today
        equity *= 1.0 + net
        rows.append(
            {
                "date": dt,
                "n_pos": n_mark,
                "strategy_ret": net,
                "equity": equity,
                "bench_ret": float(bench_ret.loc[dt]) if dt in bench_ret.index else 0.0,
                "position": (n_mark / max_pos) if max_pos else 0.0,
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, {"error": "empty_daily"}, empty_legs
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
        "n_legs_raw": int(len(legs)),
        "n_legs_accepted": int(len(acc)),
        "avg_position": round(float(daily["position"].mean()), 4),
        "position_logic": str(params.get("position_logic") or "equal_weight"),
        "accounting": "eod_rebalance_hold_earns_day",
        "trade_start": start,
        "trade_end": end,
    }
    return daily, summary, acc


_STOCK_NAME_MAP: Optional[Dict[str, str]] = None


def code_to_symbol6(code: Any) -> str:
    """sh.600000 / 600000.SH / 600000 → 600000。"""
    s = str(code or "").strip()
    if not s:
        return ""
    if "." in s:
        left, right = s.split(".", 1)
        s = right if right.isdigit() else left
    if s.isdigit():
        return s.zfill(6)
    return s


def load_stock_name_map(*, force: bool = False) -> Dict[str, str]:
    """代码→名称；优先本地缓存，其次 Mongo stock_basic_info，再次 akshare。"""
    global _STOCK_NAME_MAP
    if _STOCK_NAME_MAP is not None and not force:
        return _STOCK_NAME_MAP
    cache = shared_cache_dir() / "stock_names.parquet"
    mapping: Dict[str, str] = {}
    if cache.exists() and not force:
        try:
            df = pd.read_parquet(cache)
            if "code" in df.columns and "name" in df.columns:
                for code, name in zip(df["code"].astype(str), df["name"].astype(str)):
                    if code and name:
                        mapping[code_to_symbol6(code)] = name
        except Exception as exc:  # noqa: BLE001
            logger.warning("read stock_names cache fail: %s", exc)
    if len(mapping) < 100:
        try:
            from pymongo import MongoClient

            from app.core.config import settings

            client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=4000)
            db = client[settings.MONGO_DB]
            for doc in db.stock_basic_info.find({}, {"code": 1, "symbol": 1, "name": 1, "_id": 0}):
                name = str(doc.get("name") or "").strip()
                if not name:
                    continue
                for key in (doc.get("code"), doc.get("symbol")):
                    sym = code_to_symbol6(key)
                    if sym:
                        mapping[sym] = name
            client.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo stock names fail: %s", exc)
    if len(mapping) < 100:
        try:
            import akshare as ak

            df = ak.stock_info_a_code_name()
            if df is not None and not df.empty:
                cols = {str(c).lower(): c for c in df.columns}
                code_col = cols.get("code") or cols.get("代码") or df.columns[0]
                name_col = cols.get("name") or cols.get("名称") or df.columns[1]
                for code, name in zip(df[code_col].astype(str), df[name_col].astype(str)):
                    sym = code_to_symbol6(code)
                    if sym and name:
                        mapping[sym] = name
        except Exception as exc:  # noqa: BLE001
            logger.warning("akshare stock names fail: %s", exc)
    if mapping:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [{"code": k, "name": v} for k, v in sorted(mapping.items())]
            ).to_parquet(cache, index=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("write stock_names cache fail: %s", exc)
    _STOCK_NAME_MAP = mapping
    return mapping


def attach_stock_name_column(trades: pd.DataFrame) -> pd.DataFrame:
    """在 code 旁插入 name（股票名称）列。"""
    if trades is None or trades.empty or "code" not in trades.columns:
        return trades if trades is not None else pd.DataFrame()
    out = trades.copy()
    for col in ("name", "code_name"):
        if col in out.columns:
            out = out.drop(columns=[col])
    nm = load_stock_name_map()
    names = [nm.get(code_to_symbol6(c), "") for c in out["code"]]
    cols = list(out.columns)
    idx = cols.index("code") + 1 if "code" in cols else 0
    out.insert(idx, "name", names)
    return out


def attach_equity_column(trades: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """把回测日净值贴到交易明细最后一列（按成交日对齐；区间外留空）。"""
    if trades is None or trades.empty:
        return trades if trades is not None else pd.DataFrame()
    out = trades.copy()
    # 先去掉旧列，保证 equity 始终在最后
    if "equity" in out.columns:
        out = out.drop(columns=["equity"])
    if daily is None or daily.empty or "date" not in daily.columns or "equity" not in daily.columns:
        out["equity"] = ""
        return out
    eq = daily[["date", "equity"]].copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
    eq = eq.dropna(subset=["date"]).drop_duplicates("date", keep="last")
    eq_map = dict(zip(eq["date"], eq["equity"]))
    dates = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    vals = []
    for d in dates:
        v = eq_map.get(d)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            vals.append("")
        else:
            vals.append(round(float(v), 6))
    out["equity"] = vals
    return out


def write_factor_artifacts(
    factor_id: str,
    daily: pd.DataFrame,
    summary: Dict[str, Any],
    trades: pd.DataFrame,
    *,
    params: Dict[str, Any],
    title: str,
    plot: bool = True,
) -> None:
    FACTORS_DATA.mkdir(parents=True, exist_ok=True)
    daily_path = FACTORS_DATA / f"{factor_id}_backtest.csv"
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    trades = attach_stock_name_column(trades)
    trades = attach_equity_column(trades, daily)
    trades_path = FACTORS_DATA / f"{factor_id}_trade_history.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    # summary 里勿写入 DataFrame
    clean_summary = {k: v for k, v in summary.items() if not str(k).startswith("_")}
    payload = {
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "results": {clean_summary.get("position_logic") or "main": clean_summary},
        "notes": [clean_summary.get("note") or title],
    }
    json_path = FACTORS_DATA / f"{factor_id}_backtest.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if plot:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
            axes[0].plot(daily["date"], daily["equity"], label=factor_id, color="#1f4e79")
            bh = (1 + daily["bench_ret"].fillna(0)).cumprod()
            axes[0].plot(daily["date"], bh, label="CSI300", color="#999999", alpha=0.85)
            axes[0].legend(loc="upper left")
            axes[0].set_title(title)
            axes[0].grid(True, alpha=0.25)
            axes[1].fill_between(daily["date"], 0, daily["position"].fillna(0), color="#2a9d8f", alpha=0.55)
            axes[1].set_ylabel("exposure")
            axes[1].set_ylim(0, 1.05)
            axes[1].grid(True, alpha=0.25)
            fig.tight_layout()
            fig.savefig(FACTORS_DATA / f"{factor_id}_equity_curve.png", dpi=120)
            plt.close(fig)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plot skip %s: %s", factor_id, exc)
    print(f"[ok] artifacts {factor_id}: return={summary.get('total_return')} sharpe={summary.get('sharpe')}")


def years_range(start_year: int = 2016, end_year: Optional[int] = None) -> List[int]:
    end_year = end_year or datetime.now().year
    return list(range(start_year, end_year + 1))
