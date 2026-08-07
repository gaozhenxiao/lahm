"""暴跌抄底择时因子（dip_buy）。

思路（与网上常见「逆向 + 估值锚」一致）：
1. 多指数监测急跌/回撤（沪深300、创业板指、中证500）
2. 用历史 PE/PB 分位做水位闸门：高估区间几乎不抄；低估区间允许更高仓位
3. 点信号 value ∈ [0,1]：crash_score × size_cap；≥阈值 → buy

估值源：乐咕乐股指数 PE/PB（akshare），分位由本地滚动历史计算。
创业板价格用 399006；PE 用创业板50 代理，PB 用创业板市场 PB。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("webapi.factors.dip_buy")

# 监测宇宙
UNIVERSES: Dict[str, Dict[str, Any]] = {
    "csi300": {
        "name": "沪深300",
        "price_symbol": "000300",
        "ak_price": "sh000300",
        "pe": ("index_pe", "沪深300"),
        "pb": ("index_pb", "沪深300"),
    },
    "cyb": {
        "name": "创业板指",
        "price_symbol": "399006",
        "ak_price": "sz399006",
        "pe": ("index_pe", "创业板50"),  # 代理
        "pb": ("market_pb", "创业板"),
    },
    "csi500": {
        "name": "中证500",
        "price_symbol": "000905",
        "ak_price": "sh000905",
        "pe": ("index_pe", "中证500"),
        "pb": ("index_pb", "中证500"),
    },
}

DEFAULT_PARAMS: Dict[str, Any] = {
    "universes": ["csi300", "cyb", "csi500"],
    "ret_short": 5,
    "ret_mid": 20,
    "dd_lookback": 60,
    # 稍敏感：更容易触发抄底
    "ret_short_soft": -0.03,
    "ret_short_hard": -0.07,
    "ret_mid_soft": -0.06,
    "ret_mid_hard": -0.13,
    "dd_soft": -0.06,
    "dd_hard": -0.15,
    "val_window": 1260,  # ~5y
    "val_min_periods": 252,
    "cheap_pct": 30.0,  # 低估区间放宽
    "expensive_pct": 75.0,  # 高估闸门略松
    "enter_threshold": 0.18,
    "buy_threshold": 0.18,
    "smooth": 2,
    # 更积极：仓位放大，弱信号也少归零
    "aggression": 1.35,
    "min_pos_keep": 0.08,
    # 回测：按最强宇宙对应 ETF 交易；空仓计货币利息
    "trade_mode": "best_etf",  # best_etf | csi300 | index
    "cash_annual": 0.014,
    # 交易成本（占调仓名义仓位比例；不计滑点）
    "commission_rate": 0.0001,  # 万分之一，买卖双向
    "stamp_tax_sell": 0.0,  # ETF 通常免印花税
    "etf_map": {
        "csi300": "510300",
        "cyb": "159915",
        "csi500": "510500",
    },
}


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "factors"


def _clear_proxy() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def _safe_import_ak():
    try:
        import akshare as ak  # noqa: WPS433

        return ak
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare import failed: %s", exc)
        return None


def _merge_by_date(path: Path, new: pd.DataFrame, value_cols: List[str]) -> pd.DataFrame:
    """增量合并；新数据非空覆盖旧值，但 NaN 不冲掉已有列（避免只刷到 PE 时清空 PB）。"""
    if new is None or new.empty:
        if path.exists():
            return pd.read_parquet(path)
        return pd.DataFrame()
    new = new.copy()
    new["date"] = pd.to_datetime(new["date"], errors="coerce")
    for c in value_cols:
        if c in new.columns:
            new[c] = pd.to_numeric(new[c], errors="coerce")
    keep = ["date"] + [c for c in value_cols if c in new.columns]
    new = new[keep].dropna(subset=["date"]).drop_duplicates("date", keep="last")
    if path.exists():
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"], errors="coerce")
        old = old.dropna(subset=["date"]).drop_duplicates("date", keep="last")
        base = old.set_index("date")
        add = new.set_index("date")
        for c in add.columns:
            if c not in base.columns:
                base[c] = add[c]
            else:
                # 优先新值；新值为 NaN 时保留旧值
                base[c] = add[c].combine_first(base[c])
        new_idx = add.index.difference(base.index)
        if len(new_idx):
            base = pd.concat([base, add.loc[new_idx]], axis=0)
        merged = base.sort_index().reset_index()
    else:
        merged = new.sort_values("date").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)
    return merged.reset_index(drop=True)


def load_price_series(symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    path = _data_dir() / f"{symbol}_daily.parquet"
    df = pd.DataFrame()
    if path.exists():
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("read price cache failed %s: %s", path, exc)
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).drop_duplicates("date").sort_values("date")
    if start:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end:
        out = out[out["date"] <= pd.Timestamp(end)]
    return out.reset_index(drop=True)


def fetch_and_cache_index_price(symbol: str, ak_symbol: str, start: str = "2010-01-01") -> pd.DataFrame:
    """Pull index daily and merge into data/factors/{symbol}_daily.parquet."""
    _clear_proxy()
    ak = _safe_import_ak()
    path = _data_dir() / f"{symbol}_daily.parquet"
    if ak is None:
        return load_price_series(symbol)
    try:
        raw = ak.stock_zh_index_daily(symbol=ak_symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("index price fetch failed %s: %s", ak_symbol, exc)
        return load_price_series(symbol)
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "amount" not in df.columns:
        df["amount"] = df["volume"] if "volume" in df.columns else np.nan
    df = df[df["date"] >= pd.Timestamp(start)]
    return _merge_by_date(path, df, ["open", "high", "low", "close", "volume", "amount"])


def _normalize_valuation_frame(df: pd.DataFrame, pe_col: Optional[str], pb_col: Optional[str]) -> pd.DataFrame:
    out = pd.DataFrame()
    if df is None or df.empty:
        return out
    d = df.copy()
    date_col = "日期" if "日期" in d.columns else ("date" if "date" in d.columns else None)
    if date_col is None:
        return out
    out["date"] = pd.to_datetime(d[date_col], errors="coerce")
    if pe_col and pe_col in d.columns:
        out["pe"] = pd.to_numeric(d[pe_col], errors="coerce")
    if pb_col and pb_col in d.columns:
        out["pb"] = pd.to_numeric(d[pb_col], errors="coerce")
    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_valuation_series(kind: str, symbol: str) -> pd.DataFrame:
    """kind: index_pe | index_pb | market_pb."""
    _clear_proxy()
    ak = _safe_import_ak()
    if ak is None:
        return pd.DataFrame()
    try:
        if kind == "index_pe":
            raw = ak.stock_index_pe_lg(symbol=symbol)
            return _normalize_valuation_frame(raw, pe_col="滚动市盈率", pb_col=None)
        if kind == "index_pb":
            raw = ak.stock_index_pb_lg(symbol=symbol)
            return _normalize_valuation_frame(raw, pe_col=None, pb_col="市净率")
        if kind == "market_pb":
            raw = ak.stock_market_pb_lg(symbol=symbol)
            return _normalize_valuation_frame(raw, pe_col=None, pb_col="市净率")
    except Exception as exc:  # noqa: BLE001
        logger.warning("valuation fetch failed %s/%s: %s", kind, symbol, exc)
    return pd.DataFrame()


def load_or_refresh_valuation(universe_id: str, force: bool = False) -> pd.DataFrame:
    """Return date, pe, pb, pe_pct, pb_pct, val_pct for a universe."""
    meta = UNIVERSES[universe_id]
    path = _data_dir() / f"{universe_id}_valuation.parquet"
    need_live = force or (not path.exists()) or bool(int(os.environ.get("DIP_FORCE_VAL_LIVE", "0")))
    pe_df = pb_df = pd.DataFrame()
    if need_live:
        pe_kind, pe_sym = meta["pe"]
        pb_kind, pb_sym = meta["pb"]
        pe_df = fetch_valuation_series(pe_kind, pe_sym)
        pb_df = fetch_valuation_series(pb_kind, pb_sym)
        frames = []
        if not pe_df.empty:
            frames.append(pe_df[["date", "pe"]] if "pe" in pe_df.columns else pe_df)
        if not pb_df.empty:
            frames.append(pb_df[["date", "pb"]] if "pb" in pb_df.columns else pb_df)
        if frames:
            out = frames[0]
            for f in frames[1:]:
                out = pd.merge(out, f, on="date", how="outer")
            out = out.sort_values("date").drop_duplicates("date", keep="last")
            _merge_by_date(path, out, [c for c in ("pe", "pb") if c in out.columns])

    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("pe", "pb"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Historical percentile of latest value vs trailing window (0-100)."""

    def _pct(arr: np.ndarray) -> float:
        if len(arr) < max(min_periods, 2):
            return float("nan")
        x = arr[-1]
        if np.isnan(x):
            return float("nan")
        hist = arr[:-1]
        hist = hist[~np.isnan(hist)]
        if len(hist) < max(min_periods - 1, 20):
            return float("nan")
        return float((hist < x).mean() * 100.0)

    return series.rolling(window=window, min_periods=min_periods).apply(_pct, raw=True)


def _piecewise_score(x: float, soft: float, hard: float) -> float:
    """Map more-negative x to [0,1]. soft/hard are negative thresholds."""
    if np.isnan(x):
        return 0.0
    if x >= soft:
        return 0.0
    if x <= hard:
        return 1.0
    return float((soft - x) / max(soft - hard, 1e-9))


def valuation_size_cap(val_pct: float, cheap_pct: float, expensive_pct: float) -> float:
    """高估值 → 0；低估值 → 1；中间线性。"""
    if np.isnan(val_pct):
        return 0.0
    if val_pct >= expensive_pct:
        return 0.0
    if val_pct <= cheap_pct:
        return 1.0
    return float((expensive_pct - val_pct) / max(expensive_pct - cheap_pct, 1e-9))


def crash_score_from_prices(
    close: pd.Series,
    *,
    ret_short: int,
    ret_mid: int,
    dd_lookback: int,
    ret_short_soft: float,
    ret_short_hard: float,
    ret_mid_soft: float,
    ret_mid_hard: float,
    dd_soft: float,
    dd_hard: float,
) -> Tuple[pd.Series, pd.DataFrame]:
    ret_s = close.pct_change(ret_short)
    ret_m = close.pct_change(ret_mid)
    dd = close / close.rolling(dd_lookback, min_periods=max(20, dd_lookback // 3)).max() - 1.0

    s_s = ret_s.map(lambda v: _piecewise_score(float(v) if pd.notna(v) else np.nan, ret_short_soft, ret_short_hard))
    s_m = ret_m.map(lambda v: _piecewise_score(float(v) if pd.notna(v) else np.nan, ret_mid_soft, ret_mid_hard))
    s_d = dd.map(lambda v: _piecewise_score(float(v) if pd.notna(v) else np.nan, dd_soft, dd_hard))
    crash = (0.4 * s_s + 0.3 * s_m + 0.3 * s_d).clip(0.0, 1.0)
    detail = pd.DataFrame(
        {
            "ret_short": ret_s,
            "ret_mid": ret_m,
            "drawdown": dd,
            "crash_short": s_s,
            "crash_mid": s_m,
            "crash_dd": s_d,
            "crash_score": crash,
        }
    )
    return crash, detail


def enrich_valuation(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    w = int(params.get("val_window") or 1260)
    mp = int(params.get("val_min_periods") or 252)
    if "pe" in out.columns:
        out["pe_pct"] = rolling_percentile(out["pe"], w, mp)
    if "pb" in out.columns:
        out["pb_pct"] = rolling_percentile(out["pb"], w, mp)
    cols = [c for c in ("pe_pct", "pb_pct") if c in out.columns]
    if cols:
        out["val_pct"] = out[cols].mean(axis=1)
    else:
        out["val_pct"] = np.nan
    return out


def build_universe_panel(
    universe_id: str,
    params: Optional[Dict[str, Any]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    refresh_valuation: bool = False,
) -> pd.DataFrame:
    params = {**DEFAULT_PARAMS, **(params or {})}
    meta = UNIVERSES[universe_id]
    price = load_price_series(meta["price_symbol"], start=start, end=end)
    if price.empty:
        # try live once
        price = fetch_and_cache_index_price(meta["price_symbol"], meta["ak_price"])
        if start or end:
            price = load_price_series(meta["price_symbol"], start=start, end=end)
    if price.empty:
        return pd.DataFrame()

    val = load_or_refresh_valuation(universe_id, force=refresh_valuation)
    if val.empty:
        return pd.DataFrame()
    val = enrich_valuation(val, params)

    df = price[["date", "close"]].copy()
    df = pd.merge(df, val, on="date", how="left")
    # valuation often lags a day; forward-fill modestly
    for c in ("pe", "pb", "pe_pct", "pb_pct", "val_pct"):
        if c in df.columns:
            df[c] = df[c].ffill(limit=5)

    crash, detail = crash_score_from_prices(
        df["close"],
        ret_short=int(params["ret_short"]),
        ret_mid=int(params["ret_mid"]),
        dd_lookback=int(params["dd_lookback"]),
        ret_short_soft=float(params["ret_short_soft"]),
        ret_short_hard=float(params["ret_short_hard"]),
        ret_mid_soft=float(params["ret_mid_soft"]),
        ret_mid_hard=float(params["ret_mid_hard"]),
        dd_soft=float(params["dd_soft"]),
        dd_hard=float(params["dd_hard"]),
    )
    for c in detail.columns:
        df[c] = detail[c].values

    cheap = float(params["cheap_pct"])
    expensive = float(params["expensive_pct"])
    df["size_cap"] = df["val_pct"].map(lambda v: valuation_size_cap(float(v) if pd.notna(v) else np.nan, cheap, expensive))
    df["factor_raw"] = (df["crash_score"] * df["size_cap"]).clip(0.0, 1.0)
    smooth = int(params.get("smooth") or 1)
    if smooth > 1:
        df["factor"] = df["factor_raw"].ewm(span=smooth, adjust=False).mean()
    else:
        df["factor"] = df["factor_raw"]
    df["universe"] = universe_id
    df["universe_name"] = meta["name"]
    return df.reset_index(drop=True)


def build_dip_buy_daily_factor(
    params: Optional[Dict[str, Any]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    refresh_valuation: bool = False,
) -> pd.DataFrame:
    """合并多宇宙：每日取 factor 最强的宇宙作为主信号，并保留各宇宙明细列。"""
    params = {**DEFAULT_PARAMS, **(params or {})}
    uids = list(params.get("universes") or ["csi300", "cyb", "csi500"])
    panels = []
    for uid in uids:
        if uid not in UNIVERSES:
            continue
        p = build_universe_panel(uid, params, start=start, end=end, refresh_valuation=refresh_valuation)
        if not p.empty:
            panels.append(p)
    if not panels:
        return pd.DataFrame()

    # align on union of dates using csi300 as primary close if present else first
    primary = next((p for p in panels if p["universe"].iloc[0] == "csi300"), panels[0])
    out = primary[["date", "close"]].rename(columns={"close": "close_primary"}).copy()
    factor_cols: List[str] = []
    uid_order: List[str] = []
    for p in panels:
        uid = str(p["universe"].iloc[0])
        sub = p[
            [
                "date",
                "close",
                "crash_score",
                "size_cap",
                "val_pct",
                "pe",
                "pb",
                "pe_pct",
                "pb_pct",
                "factor",
                "ret_short",
                "drawdown",
            ]
        ].copy()
        rename = {c: f"{uid}_{c}" for c in sub.columns if c != "date"}
        sub = sub.rename(columns=rename)
        out = pd.merge(out, sub, on="date", how="outer")
        factor_cols.append(f"{uid}_factor")
        uid_order.append(uid)

    out = out.sort_values("date").reset_index(drop=True)
    fac_mat = out[factor_cols].fillna(0.0)
    out["factor"] = fac_mat.max(axis=1)
    best_idx = fac_mat.values.argmax(axis=1)
    out["best_universe"] = [uid_order[i] for i in best_idx]
    # trading close: follow best universe close that day
    close_best = []
    for i, row in out.iterrows():
        uid = row["best_universe"]
        col = f"{uid}_close"
        close_best.append(row[col] if col in out.columns and pd.notna(row[col]) else row.get("close_primary"))
    out["close"] = close_best
    out["bench_ret"] = pd.Series(out["close_primary"]).pct_change()
    # if primary missing, use best close
    if out["bench_ret"].isna().all():
        out["bench_ret"] = pd.Series(out["close"]).pct_change()
    return out


def compute_dip_buy_signal(
    params: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    params = {**DEFAULT_PARAMS, **(params or {})}
    asof_dt = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now().date())
    uids = list(params.get("universes") or ["csi300", "cyb", "csi500"])

    components: Dict[str, Any] = {"asof": str(asof_dt.date()), "universes": {}}
    best = {"universe": None, "value": 0.0, "name": None}

    for uid in uids:
        if uid not in UNIVERSES:
            continue
        panel = build_universe_panel(uid, params, end=str(asof_dt.date()), refresh_valuation=False)
        if panel.empty:
            # try refresh valuation once
            panel = build_universe_panel(uid, params, end=str(asof_dt.date()), refresh_valuation=True)
        if panel.empty:
            components["universes"][uid] = {"error": "no_data"}
            continue
        row = panel[panel["date"] <= asof_dt].tail(1)
        if row.empty:
            components["universes"][uid] = {"error": "no_row"}
            continue
        r = row.iloc[0]
        snap = {
            "name": UNIVERSES[uid]["name"],
            "date": str(pd.Timestamp(r["date"]).date()),
            "close": float(r["close"]) if pd.notna(r["close"]) else None,
            "ret_short": float(r["ret_short"]) if pd.notna(r.get("ret_short")) else None,
            "drawdown": float(r["drawdown"]) if pd.notna(r.get("drawdown")) else None,
            "crash_score": float(r["crash_score"]) if pd.notna(r["crash_score"]) else 0.0,
            "pe": float(r["pe"]) if "pe" in r and pd.notna(r["pe"]) else None,
            "pb": float(r["pb"]) if "pb" in r and pd.notna(r["pb"]) else None,
            "pe_pct": float(r["pe_pct"]) if "pe_pct" in r and pd.notna(r["pe_pct"]) else None,
            "pb_pct": float(r["pb_pct"]) if "pb_pct" in r and pd.notna(r["pb_pct"]) else None,
            "val_pct": float(r["val_pct"]) if pd.notna(r.get("val_pct")) else None,
            "size_cap": float(r["size_cap"]) if pd.notna(r["size_cap"]) else 0.0,
            "value": float(r["factor"]) if pd.notna(r["factor"]) else 0.0,
        }
        components["universes"][uid] = snap
        if snap["value"] >= best["value"]:
            best = {"universe": uid, "value": snap["value"], "name": snap["name"]}

    value = float(best["value"] or 0.0)
    aggression = float(params.get("aggression") or 1.0)
    suggested_pos = min(1.0, value * aggression)
    thr = float(params.get("buy_threshold") or params.get("enter_threshold") or 0.18)
    if value >= thr:
        signal = "buy"
    else:
        signal = "neutral"

    etf_map = params.get("etf_map") or DEFAULT_PARAMS.get("etf_map") or {}
    trade_etf = etf_map.get(best.get("universe")) if best.get("universe") else None
    note = (
        f"best={best.get('name') or '-'} value={value:.3f} pos≈{suggested_pos:.2f}; "
        f"trade={trade_etf or '-'}; cash={float(params.get('cash_annual') or 0):.1%}/yr"
    )
    return {
        "factor_id": "dip_buy",
        "asof": asof_dt.to_pydatetime(),
        "signal": signal,
        "value": round(suggested_pos if signal == "buy" else value, 6),
        "components": {
            **components,
            "best_universe": best.get("universe"),
            "best_name": best.get("name"),
            "threshold": thr,
            "raw_value": round(value, 6),
            "aggression": aggression,
            "suggested_position": round(suggested_pos, 4),
            "trade_etf": trade_etf,
            "cash_annual": float(params.get("cash_annual") or 0.0),
        },
        "note": note,
    }


def apply_dip_buy_positions(factor: pd.Series, params: Optional[Dict[str, Any]] = None) -> pd.Series:
    """日度目标仓位 = factor × aggression（已含估值闸门）。

    回测约定：该仓位视为**当日收盘**调仓后的账面仓位；当日收益只按调仓前隔夜仓计算。
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    aggression = float(params.get("aggression") or 1.0)
    pos = (factor.fillna(0.0) * aggression).clip(0.0, 1.0)
    enter = float(params.get("enter_threshold") or 0.18)
    keep = float(params.get("min_pos_keep") or (enter * 0.4))
    # 弱信号归零；keep 略低于 enter，便于回调后再积极加仓
    pos = pos.where(pos >= keep, 0.0)
    return pos


def _stitch_etf_close_with_index(etf: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    """拼接 ETF 与指数收盘价，禁止把不同量纲绝对价直接拼在一起算涨跌。

    - ETF 上市前：用指数收盘价（仅该阶段内自洽）
    - ETF 有行情日：用 ETF 收盘价
    - ETF 缺日（如尚无更新）：用「上一 ETF 价 × (1+当日指数涨跌)」代理，避免 3.x → 3000+ 的伪涨幅
    """
    if etf is None or etf.empty:
        if idx is None or idx.empty:
            return pd.DataFrame()
        out = idx[["date", "close"]].copy()
        out["source"] = "index"
        return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    if idx is None or idx.empty:
        out = etf[["date", "close"]].copy()
        out["source"] = "etf"
        return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    etf_s = (
        etf.assign(date=pd.to_datetime(etf["date"], errors="coerce"), close=pd.to_numeric(etf["close"], errors="coerce"))
        .dropna(subset=["date", "close"])
        .drop_duplicates("date", keep="last")
        .set_index("date")["close"]
        .sort_index()
    )
    idx_s = (
        idx.assign(date=pd.to_datetime(idx["date"], errors="coerce"), close=pd.to_numeric(idx["close"], errors="coerce"))
        .dropna(subset=["date", "close"])
        .drop_duplicates("date", keep="last")
        .set_index("date")["close"]
        .sort_index()
    )
    idx_ret = idx_s.pct_change()
    first_etf = etf_s.index.min()
    all_dates = etf_s.index.union(idx_s.index).sort_values()

    rows: List[Dict[str, Any]] = []
    last_etf_like: Optional[float] = None
    for dt in all_dates:
        if dt < first_etf:
            if dt in idx_s.index and pd.notna(idx_s.loc[dt]):
                rows.append({"date": dt, "close": float(idx_s.loc[dt]), "source": "index"})
            continue
        if dt in etf_s.index and pd.notna(etf_s.loc[dt]):
            last_etf_like = float(etf_s.loc[dt])
            rows.append({"date": dt, "close": last_etf_like, "source": "etf"})
            continue
        if last_etf_like is not None and dt in idx_ret.index and pd.notna(idx_ret.loc[dt]):
            last_etf_like = float(last_etf_like * (1.0 + float(idx_ret.loc[dt])))
            rows.append({"date": dt, "close": last_etf_like, "source": "index_proxy"})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def load_trade_asset_close(universe_id: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """交易标的收盘价：优先 ETF；缺失日用指数涨跌代理，避免量纲拼接炸收益。"""
    params = {**DEFAULT_PARAMS, **(params or {})}
    mode = str(params.get("trade_mode") or "best_etf")
    meta = UNIVERSES.get(universe_id) or {}

    if mode == "csi300":
        etf_code = "510300"
        idx_sym = "000300"
    elif mode == "index":
        etf_code = None
        idx_sym = str(meta.get("price_symbol") or "000300")
    else:  # best_etf
        etf_map = params.get("etf_map") or {}
        etf_code = etf_map.get(universe_id)
        idx_sym = str(meta.get("price_symbol") or "000300")

    idx = load_price_series(idx_sym)
    if not etf_code:
        if idx.empty:
            return pd.DataFrame()
        out = idx[["date", "close"]].copy()
        out["source"] = f"index:{idx_sym}"
        return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    etf = load_price_series(str(etf_code))
    out = _stitch_etf_close_with_index(etf, idx)
    if out.empty:
        return out
    # 保留可读 source 前缀
    out["source"] = out["source"].map(
        lambda s: f"etf:{etf_code}" if s == "etf" else (f"index:{idx_sym}" if s == "index" else f"index_proxy:{idx_sym}")
    )
    return out


def build_trade_return_series(
    panel: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """收盘调仓记账：当日收益只认隔夜仓，新增仓不吃当天涨跌。

    约定：
    - ``position``：当日收盘调仓后的目标仓位（信号日即成交日，成交价=当日收盘）
    - ``position_hold``：当日开盘带到收盘前的隔夜仓 = 昨收盘后仓位
    - ``strategy_ret`` = position_hold × 隔夜标的当日收益 + (1-hold)×现金利息 - 交易成本
      → 收盘新买入/加仓的部分当日收益为 0；减仓部分在当日仍按 hold 计入（持有到收盘卖出）
    - 成本：佣金×(买+卖)名义仓位 + 卖出印花税×卖出名义仓位；换宇宙按先卖后买计双边
    - ``universe_hold``：隔夜持有的宇宙；``universe_eod``：收盘调仓后的宇宙
    - ``trade_close``：收盘成交参考价（调仓后宇宙对应 ETF/指数收盘价）

    兼容：若面板只有旧列 ``position_exec``（曾表示 T+1 执行仓），则视为已经是隔夜仓。
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    mode = str(params.get("trade_mode") or "best_etf")
    cash_ann = float(params.get("cash_annual") or 0.0)
    cash_daily = cash_ann / 365.0
    commission = float(params.get("commission_rate") or 0.0)
    stamp = float(params.get("stamp_tax_sell") or 0.0)

    need_cols = ["date", "best_universe"]
    out = panel[need_cols].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")

    if "position" in panel.columns:
        out["position"] = pd.to_numeric(panel["position"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
        out["position_hold"] = out["position"].shift(1).fillna(0.0)
    elif "position_exec" in panel.columns:
        # 旧口径：传入的已是隔夜仓
        out["position_hold"] = pd.to_numeric(panel["position_exec"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
        out["position"] = out["position_hold"]
    else:
        out["position"] = 0.0
        out["position_hold"] = 0.0

    if mode == "csi300":
        out["universe_eod"] = "csi300"
        out["universe_hold"] = "csi300"
    else:
        out["universe_eod"] = out["best_universe"]
        out["universe_hold"] = out["best_universe"].shift(1).fillna(out["best_universe"])

    # 兼容旧字段名：执行/持有宇宙 = 隔夜宇宙（决定当日 asset_ret）
    out["universe_exec"] = out["universe_hold"]
    # 兼容旧字段名：position_exec = 隔夜仓（决定当日 strategy_ret）
    out["position_exec"] = out["position_hold"]

    uids = sorted(
        {
            str(u)
            for u in pd.concat([out["universe_hold"], out["universe_eod"]], ignore_index=True).dropna().unique()
        }
    )
    ret_map: Dict[str, pd.Series] = {}
    close_map: Dict[str, pd.Series] = {}
    for uid in uids:
        px = load_trade_asset_close(uid, params)
        if px.empty:
            continue
        s = px.set_index("date")["close"].sort_index()
        close_map[uid] = s
        ret_map[uid] = s.pct_change()

    asset_rets = []
    trade_closes = []
    hold_closes = []
    buy_turnovers = []
    sell_turnovers = []
    for _, row in out.iterrows():
        dt = row["date"]
        uid_hold = str(row["universe_hold"])
        uid_eod = str(row["universe_eod"])
        hold_pos = float(row["position_hold"] or 0.0)
        eod_pos = float(row["position"] or 0.0)
        r = float("nan")
        c_hold = float("nan")
        c_eod = float("nan")
        if uid_hold in ret_map and dt in ret_map[uid_hold].index:
            r = float(ret_map[uid_hold].loc[dt])
            c_hold = float(close_map[uid_hold].loc[dt])
        if uid_eod in close_map and dt in close_map[uid_eod].index:
            c_eod = float(close_map[uid_eod].loc[dt])
        asset_rets.append(0.0 if pd.isna(r) else r)
        hold_closes.append(c_hold if not pd.isna(c_hold) else None)
        # 收盘成交价：按调仓后宇宙（新买入标的）的收盘
        trade_closes.append(c_eod if not pd.isna(c_eod) else (c_hold if not pd.isna(c_hold) else None))

        # 换宇宙：先卖旧仓再买新仓；同宇宙：只计仓位增减
        switched = uid_hold != uid_eod and (hold_pos > 1e-12 or eod_pos > 1e-12)
        if switched:
            sell_t = hold_pos
            buy_t = eod_pos
        else:
            delta = eod_pos - hold_pos
            buy_t = max(delta, 0.0)
            sell_t = max(-delta, 0.0)
        buy_turnovers.append(buy_t)
        sell_turnovers.append(sell_t)

    out["asset_ret"] = asset_rets
    out["hold_close"] = hold_closes
    out["trade_close"] = trade_closes
    out["cash_ret"] = cash_daily
    out["buy_turnover"] = buy_turnovers
    out["sell_turnover"] = sell_turnovers
    out["cost_ret"] = (
        commission * (out["buy_turnover"] + out["sell_turnover"]) + stamp * out["sell_turnover"]
    )
    hold = out["position_hold"].fillna(0.0).clip(0.0, 1.0)
    # 新增仓位在收盘买入，不计入当日 asset_ret；现金腿按隔夜空仓比例计息；收盘扣交易成本
    out["strategy_ret_gross"] = hold * out["asset_ret"] + (1.0 - hold) * out["cash_ret"]
    out["strategy_ret"] = out["strategy_ret_gross"] - out["cost_ret"]
    out["position_delta"] = out["position"] - out["position_hold"]
    return out


# 保守旧参（对比用）
BASELINE_PARAMS: Dict[str, Any] = {
    **DEFAULT_PARAMS,
    "ret_short_soft": -0.04,
    "ret_short_hard": -0.08,
    "ret_mid_soft": -0.08,
    "ret_mid_hard": -0.15,
    "dd_soft": -0.08,
    "dd_hard": -0.18,
    "cheap_pct": 25.0,
    "expensive_pct": 70.0,
    "enter_threshold": 0.25,
    "buy_threshold": 0.25,
    "smooth": 3,
    "aggression": 1.0,
    "min_pos_keep": 0.125,
    "trade_mode": "csi300",
    "cash_annual": 0.0,
}