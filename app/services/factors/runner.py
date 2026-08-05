"""通用「基本面闸门 + K 线确认」因子运行器。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services.factors import bs_kit as kit

logger = logging.getLogger("webapi.factors.runner")

SignalBuilder = Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame]
# input: daily bars with ma/percentile columns + optional funda cols; output: subset of rows that are entry signals
# must contain columns date, close at minimum; builder adds signal bool or returns entry rows


def prepare_price_panel(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    out = kit.attach_ma(df, (20, 60, 120))
    win = int(params.get("val_window") or 756)
    if "pbMRQ" in out.columns:
        out["pb_pct"] = kit.rolling_percentile(out["pbMRQ"], win)
    if "peTTM" in out.columns:
        out["pe_pct"] = kit.rolling_percentile(out["peTTM"], win)
    out["ret_20"] = out["close"].pct_change(20)
    out["ret_60"] = out["close"].pct_change(60)
    out["dd_20"] = out["close"] / out["close"].rolling(20).max() - 1.0
    out["high_60"] = out["high"].rolling(60).max()
    out["vol_60"] = out["close"].pct_change().rolling(60).std()
    return out


def merge_asof_funda(price: pd.DataFrame, funda: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    if funda is None or funda.empty:
        for c in cols:
            price[c] = np.nan
        return price
    f = funda.dropna(subset=["pubDate"]).sort_values("pubDate")
    keep = ["pubDate"] + [c for c in cols if c in f.columns]
    f = f[keep].copy()
    p = price.sort_values("date")
    merged = pd.merge_asof(
        p,
        f.rename(columns={"pubDate": "date"}),
        on="date",
        direction="backward",
    )
    return merged


def build_legs_from_entries(
    entries: pd.DataFrame,
    price: pd.DataFrame,
    *,
    hold_days: int,
    stop_loss: float,
    take_profit: float | None = None,
    trail_stop: float | None = None,
    trail_activate: float | None = None,
) -> List[dict]:
    """由入场点生成交易腿。

    持有期超出行情末日时不强制平仓（reason=open，exit_date 落在末日之后），
    回测净值继续盯市，交易史不写清仓。

    trail_stop：相对持仓峰值回撤出场。
    trail_activate：可选；仅当峰值相对成本浮盈 ≥ 该阈值后，才启用 trail_stop。
    take_profit 与 trail 可叠加（任一先触发）。
    """
    if entries is None or entries.empty:
        return []
    p = price.sort_values("date").reset_index(drop=True)
    by_date = {pd.Timestamp(r["date"]): i for i, r in p.iterrows()}
    last_i = len(p) - 1
    legs = []
    for _, e in entries.iterrows():
        dt = pd.Timestamp(e["date"])
        if dt not in by_date:
            continue
        i = by_date[dt]
        entry_px = float(p.loc[i, "close"])
        target_exit_i = i + int(hold_days)
        truncated = target_exit_i > last_i
        exit_i = min(target_exit_i, last_i)
        reason = "hold_end"
        exit_px = float(p.loc[exit_i, "close"])
        exit_dt = pd.Timestamp(p.loc[exit_i, "date"])
        peak = entry_px
        for j in range(i + 1, exit_i + 1):
            cl = p.loc[j, "close"]
            if pd.isna(cl):
                continue
            clf = float(cl)
            if clf > peak:
                peak = clf
            if clf <= entry_px * (1.0 - stop_loss):
                exit_i = j
                exit_px = clf
                exit_dt = pd.Timestamp(p.loc[j, "date"])
                reason = "stop_loss"
                truncated = False
                break
            if take_profit is not None and clf >= entry_px * (1.0 + float(take_profit)):
                exit_i = j
                exit_px = clf
                exit_dt = pd.Timestamp(p.loc[j, "date"])
                reason = "take_profit"
                truncated = False
                break
            if trail_stop is not None:
                activated = True
                if trail_activate is not None:
                    activated = peak >= entry_px * (1.0 + float(trail_activate))
                if activated and clf <= peak * (1.0 - float(trail_stop)):
                    exit_i = j
                    exit_px = clf
                    exit_dt = pd.Timestamp(p.loc[j, "date"])
                    reason = "trail_stop"
                    truncated = False
                    break
        if reason == "hold_end" and truncated:
            # 行情不够持满：保持持仓，不在末日伪造清仓
            reason = "open"
            exit_px = float(p.loc[last_i, "close"])
            exit_dt = pd.Timestamp(p.loc[last_i, "date"]) + pd.Timedelta(days=1)
        legs.append(
            {
                "code": str(e.get("code") or p.loc[i, "code"]),
                "entry_date": dt,
                "entry_price": entry_px,
                "exit_date": exit_dt,
                "exit_price": exit_px,
                "reason": reason,
                "note": str(e.get("note") or ""),
            }
        )
    return legs


def load_or_fetch_universe_prices(
    codes: Sequence[str],
    params: Dict[str, Any],
    cache_dir: Path,
    *,
    progress_every: int = 25,
) -> Dict[str, pd.DataFrame]:
    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    start = str(params.get("price_start") or "2016-01-01")
    end = str(params.get("price_end") or datetime.now().strftime("%Y-%m-%d"))
    out: Dict[str, pd.DataFrame] = {}
    kit.clear_proxy()
    bs = None
    cache_only = False
    try:
        bs = kit.bs_login()
    except Exception as exc:  # noqa: BLE001
        cache_only = True
        logger.warning("login fail, cache only: %s", exc)
        print(f"login fail, cache only: {exc}", flush=True)
    try:
        for i, code in enumerate(codes, 1):
            try:
                raw = kit.fetch_daily_valuation(
                    code,
                    start,
                    end,
                    limiter,
                    cache_dir,
                    bs=bs,
                    cache_only=cache_only,
                )
                if raw.empty:
                    continue
                raw = prepare_price_panel(raw, params)
                raw["code"] = code
                out[code] = raw
            except Exception as exc:  # noqa: BLE001
                logger.warning("daily %s: %s", code, exc)
            if progress_every and i % progress_every == 0:
                print(f"[daily] {i}/{len(codes)}", flush=True)
    finally:
        if bs is not None:
            bs.logout()
    return out


def enrich_with_profit(
    price_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    cache_dir: Path,
) -> Dict[str, pd.DataFrame]:
    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    years = kit.years_range(2015)
    kit.clear_proxy()
    bs = None
    try:
        bs = kit.bs_login()
    except Exception as exc:  # noqa: BLE001
        logger.warning("profit login fail: %s", exc)
    out = {}
    try:
        for i, (code, px) in enumerate(price_map.items(), 1):
            try:
                profit = kit.fetch_profit_quarters(code, years, limiter, cache_dir, bs=bs)
                out[code] = merge_asof_funda(
                    px,
                    profit,
                    [
                        "roeAvg",
                        "npMargin",
                        "gpMargin",
                        "netProfit",
                        "epsTTM",
                        "MBRevenue",
                        "totalShare",
                        "liqaShare",
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("profit merge %s: %s", code, exc)
                out[code] = px
            if i % 25 == 0:
                print(f"[profit] {i}/{len(price_map)}")
    finally:
        if bs is not None:
            bs.logout()
    return out


def enrich_with_growth(
    price_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    cache_dir: Path,
) -> Dict[str, pd.DataFrame]:
    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    years = kit.years_range(2015)
    kit.clear_proxy()
    bs = None
    try:
        bs = kit.bs_login()
    except Exception as exc:  # noqa: BLE001
        logger.warning("growth login fail: %s", exc)
    out = {}
    try:
        for i, (code, px) in enumerate(price_map.items(), 1):
            try:
                growth = kit.fetch_growth_quarters(code, years, limiter, cache_dir, bs=bs)
                cols = [c for c in growth.columns if c not in ("code", "pubDate", "statDate")]
                out[code] = merge_asof_funda(px, growth, cols[:8])
            except Exception as exc:  # noqa: BLE001
                logger.warning("growth merge %s: %s", code, exc)
                out[code] = px
            if i % 25 == 0:
                print(f"[growth] {i}/{len(price_map)}")
    finally:
        if bs is not None:
            bs.logout()
    return out


def collect_legs(
    price_map: Dict[str, pd.DataFrame],
    signal_fn: SignalBuilder,
    params: Dict[str, Any],
) -> pd.DataFrame:
    hold = int(params.get("hold_days") or 20)
    stop = float(params.get("stop_loss") or 0.15)
    tp_raw = params.get("take_profit")
    take_profit = float(tp_raw) if tp_raw is not None else None
    tr_raw = params.get("trail_stop")
    trail_stop = float(tr_raw) if tr_raw is not None else None
    ta_raw = params.get("trail_activate")
    trail_activate = float(ta_raw) if ta_raw is not None else None
    all_legs: List[dict] = []
    for code, px in price_map.items():
        try:
            entries = signal_fn(px, params)
            if entries is None or entries.empty:
                continue
            entries = entries.copy()
            entries["code"] = code
            all_legs.extend(
                build_legs_from_entries(
                    entries,
                    px,
                    hold_days=hold,
                    stop_loss=stop,
                    take_profit=take_profit,
                    trail_stop=trail_stop,
                    trail_activate=trail_activate,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("signal %s: %s", code, exc)
    if not all_legs:
        return pd.DataFrame()
    legs = pd.DataFrame(all_legs)
    # 同股重叠腿：按 entry 去重保留先发
    legs = legs.sort_values(["code", "entry_date"]).drop_duplicates(["code", "entry_date"], keep="first")
    return legs.reset_index(drop=True)


def legs_to_trade_history(
    legs: pd.DataFrame,
    *,
    max_positions: int = 8,
    weight_mode: str = "fixed",
) -> pd.DataFrame:
    """将入账腿写成交易流水。

    weight_mode:
      - fixed（默认）：每腿买/卖仓位 = 1/max_positions（历史口径，其它因子不变）
      - actual：按开仓腿等权 1/n 再平衡；buy_position=开仓日收盘后权重；
        nav_pnl≈股价涨跌×持有期隔夜平均权重（与引擎满仓等权近似一致）
    """
    if legs is None or legs.empty:
        return pd.DataFrame()
    mode = str(weight_mode or "fixed").strip().lower()
    max_pos = max(1, int(max_positions or 8))
    fixed_w = 1.0 / max_pos

    df = legs.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df = df.sort_values(["entry_date", "code"]).reset_index(drop=True)
    df["_leg_id"] = np.arange(len(df), dtype=np.int64)
    df["_reason"] = df.get("reason", "").astype(str).fillna("").str.strip()

    entry_w: Dict[int, float] = {}
    avg_w: Dict[int, float] = {}
    if mode == "actual":
        # 隔夜：entry < day <= exit（exit 当日仍吃涨跌，随后平仓）
        # 开仓后权重：entry <= day 且 (exit > day 或 reason=open)
        day_lo = df["entry_date"].min()
        day_hi = df["exit_date"].max()
        cal = pd.bdate_range(day_lo, day_hi)
        w_sum: Dict[int, float] = {int(i): 0.0 for i in df["_leg_id"]}
        w_cnt: Dict[int, int] = {int(i): 0 for i in df["_leg_id"]}
        for day in cal:
            overnight = df[(df["entry_date"] < day) & (df["exit_date"] >= day)]
            if len(overnight) > 0:
                w = 1.0 / len(overnight)
                for lid in overnight["_leg_id"].astype(int):
                    w_sum[lid] += w
                    w_cnt[lid] += 1
            # 开仓日收盘后持仓（已平当日腿已剔除）
            opened_today = df[df["entry_date"] == day]
            if len(opened_today) == 0:
                continue
            held_eod = df[
                (df["entry_date"] <= day)
                & (
                    (df["exit_date"] > day)
                    | ((df["exit_date"] == day) & (df["_reason"] == "open"))
                )
            ]
            if len(held_eod) > 0:
                w_eod = 1.0 / len(held_eod)
                for lid in opened_today["_leg_id"].astype(int):
                    if lid in set(held_eod["_leg_id"].astype(int)):
                        entry_w[lid] = w_eod
        for lid in df["_leg_id"].astype(int):
            if lid not in entry_w:
                row = df.loc[df["_leg_id"] == lid].iloc[0]
                ed = pd.Timestamp(row["entry_date"])
                before_close = df[(df["entry_date"] <= ed) & (df["exit_date"] >= ed)]
                entry_w[lid] = 1.0 / max(1, len(before_close))
            avg_w[lid] = (
                w_sum[lid] / w_cnt[lid] if w_cnt[lid] > 0 else entry_w[lid]
            )
    else:
        for lid in df["_leg_id"].astype(int):
            entry_w[lid] = fixed_w
            avg_w[lid] = fixed_w

    rows = []
    for _, r in df.iterrows():
        lid = int(r["_leg_id"])
        w = float(entry_w.get(lid, fixed_w))
        w_nav = float(avg_w.get(lid, w))
        entry = float(r["entry_price"])
        exit_px = float(r["exit_price"])
        ret = exit_px / entry - 1.0 if entry else 0.0
        nav = ret * w_nav
        entry_date = pd.Timestamp(r["entry_date"]).strftime("%Y-%m-%d")
        exit_date = pd.Timestamp(r["exit_date"]).strftime("%Y-%m-%d")
        reason = str(r.get("_reason") or r.get("reason") or "").strip()
        rows.append(
            {
                "date": entry_date,
                "action": "开仓",
                "code": r["code"],
                "name": "",
                "buy_position": round(w, 4),
                "nav_pnl": "",
                "price": round(entry, 4),
                "note": r.get("note") or "",
            }
        )
        # 末日未平仓：只保留开仓，不写伪造清仓
        if reason == "open":
            continue
        sell_note = f"买入{entry_date} 成本价{entry:.4f}"
        if reason:
            sell_note = f"{reason}；{sell_note}"
        rows.append(
            {
                "date": exit_date,
                "action": "清仓",
                "code": r["code"],
                "name": "",
                "buy_position": round(w, 4),
                "nav_pnl": f"{nav * 100:.2f}%",
                "price": round(exit_px, 4),
                "day_ret": f"{ret * 100:.2f}%",
                "note": sell_note,
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def _trade_history_weight_mode(params: Dict[str, Any]) -> str:
    """fixed_leg_weight → fixed；position_display=actual → actual；默认 fixed。"""
    if bool(params.get("fixed_leg_weight")):
        return "fixed"
    if str(params.get("position_display") or "").strip().lower() == "actual":
        return "actual"
    return "fixed"


def enrich_with_balance(
    price_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    cache_dir: Path,
) -> Dict[str, pd.DataFrame]:
    """合并合同负债/预收款。本地 A 股财务库优先，缺失再回退东财。"""
    from app.services.factors import ashare_fin_db as fin_db

    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    use_local = fin_db.db_available()
    if use_local:
        print(f"[balance] prefer local fin db: {fin_db.resolve_db_path()}", flush=True)
    out = {}
    n = len(price_map)
    bal_cols = ["contract_liab", "advance_recv", "contract_liab_raw", "contract_liab_yoy"]
    for i, (code, px) in enumerate(price_map.items(), 1):
        try:
            bal = pd.DataFrame()
            if use_local:
                try:
                    bal = fin_db.fetch_contract_bundle(code)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("local balance %s: %s", code, exc)
                    bal = pd.DataFrame()
            if bal is None or bal.empty or "contract_liab" not in getattr(bal, "columns", []):
                bal = kit.fetch_contract_liab(code, cache_dir, limiter=limiter)
            out[code] = merge_asof_funda(px, bal, bal_cols)
        except Exception as exc:  # noqa: BLE001
            logger.warning("balance merge %s: %s", code, exc)
            out[code] = px
        if i % 10 == 0 or i == n:
            print(f"[balance] {i}/{n}", flush=True)
    return out


def enrich_with_ashare_fin(
    price_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    cache_dir: Path,
) -> Dict[str, pd.DataFrame]:
    """合并本地 Wind 风格三大表 + 预告/快报宽表。"""
    from app.services.factors import ashare_fin_db as fin_db

    if not fin_db.db_available():
        print("[fin_db] unavailable, skip", flush=True)
        return price_map
    print(f"[fin_db] enrich from {fin_db.resolve_db_path()}", flush=True)
    out = {}
    n = len(price_map)
    for i, (code, px) in enumerate(price_map.items(), 1):
        try:
            out[code] = fin_db.enrich_price_with_fin_db(px, code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fin_db merge %s: %s", code, exc)
            out[code] = px
        if i % 10 == 0 or i == n:
            print(f"[fin_db] {i}/{n}", flush=True)
    return out


def run_factor_pipeline(
    factor_id: str,
    title: str,
    signal_fn: SignalBuilder,
    params: Dict[str, Any],
    *,
    need_profit: bool = False,
    need_growth: bool = False,
    need_balance: bool = False,
    need_fin_db: bool = False,
    limit: int = 0,
    start: str = "2018-01-01",
    price_map: Optional[Dict[str, pd.DataFrame]] = None,
    shared: bool = True,
) -> Dict[str, Any]:
    params = dict(params)
    params["position_logic"] = factor_id
    factor_dir = kit.factor_cache_dir(factor_id)
    cache_dir = kit.shared_cache_dir() if shared else factor_dir
    params["_cache_dir"] = str(cache_dir)
    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    if price_map is None:
        universe = str(params.get("universe") or "hs300")
        override = params.get("_codes") or params.get("codes")
        if override:
            codes = [str(c) for c in override]
        else:
            codes = kit.fetch_universe_codes(universe, limiter, cache_dir)
        if limit and limit > 0:
            codes = codes[:limit]
        print(f"[{factor_id}] codes={len(codes)} cache={cache_dir.name}", flush=True)
        price_map = load_or_fetch_universe_prices(codes, params, cache_dir)
        if need_profit:
            price_map = enrich_with_profit(price_map, params, cache_dir)
        if need_growth:
            price_map = enrich_with_growth(price_map, params, cache_dir)
        if need_fin_db:
            price_map = enrich_with_ashare_fin(price_map, params, cache_dir)
        if need_balance:
            sample = next(iter(price_map.values()), pd.DataFrame())
            if sample is None or "contract_liab" not in getattr(sample, "columns", []):
                price_map = enrich_with_balance(price_map, params, cache_dir)
    else:
        print(f"[{factor_id}] reuse panel n={len(price_map)}", flush=True)
        sample = next(iter(price_map.values()), pd.DataFrame())
        if need_fin_db and (sample is None or "fin_oper_rev" not in getattr(sample, "columns", [])):
            price_map = enrich_with_ashare_fin(price_map, params, cache_dir)
            sample = next(iter(price_map.values()), pd.DataFrame())
        if need_balance and (sample is None or "contract_liab" not in getattr(sample, "columns", [])):
            price_map = enrich_with_balance(price_map, params, cache_dir)

    legs = collect_legs(price_map, signal_fn, params)
    print(f"[{factor_id}] legs={len(legs)}", flush=True)
    legs_path = factor_dir / "trade_legs.parquet"
    if not legs.empty:
        legs.to_parquet(legs_path, index=False)

    # bench
    bench_code = str(params.get("bench_code") or "sh.000300")
    bench = kit.fetch_daily_valuation(
        bench_code,
        str(params.get("price_start") or "2016-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
    )
    params["note"] = title
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=start
    )
    if daily.empty:
        print(f"[{factor_id}] backtest empty: {summary}", flush=True)
        return summary
    # 交易历史只写组合实际入账的腿（与净值一致；已按 start 过滤）
    trades = legs_to_trade_history(
        accepted,
        max_positions=int(params.get("max_positions") or 8),
        weight_mode=_trade_history_weight_mode(params),
    )
    kit.write_factor_artifacts(factor_id, daily, summary, trades, params=params, title=title)
    return summary


def prepare_shared_panel(
    params: Dict[str, Any],
    *,
    need_profit: bool = False,
    need_growth: bool = False,
    need_balance: bool = False,
    need_fin_db: bool = False,
    limit: int = 0,
    codes: Optional[Sequence[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """批量跑多个因子时先准备一次面板。

    codes: 显式股票池（行业/自定义范围）；缺省则按 params['universe'] 拉取。
    """
    cache_dir = kit.shared_cache_dir()
    limiter = kit.RateLimiter(float(params.get("request_interval_sec") or 0.35))
    if codes is not None:
        code_list = [str(c) for c in codes]
    else:
        override = params.get("_codes") or params.get("codes")
        if override:
            code_list = [str(c) for c in override]
        else:
            universe = str(params.get("universe") or "hs300")
            code_list = kit.fetch_universe_codes(universe, limiter, cache_dir)
    if limit and limit > 0:
        code_list = code_list[:limit]
    print(
        f"[panel] codes={len(code_list)} profit={need_profit} growth={need_growth} "
        f"balance={need_balance} fin_db={need_fin_db}",
        flush=True,
    )
    price_map = load_or_fetch_universe_prices(code_list, params, cache_dir)
    if need_profit:
        price_map = enrich_with_profit(price_map, params, cache_dir)
    if need_growth:
        price_map = enrich_with_growth(price_map, params, cache_dir)
    if need_fin_db:
        price_map = enrich_with_ashare_fin(price_map, params, cache_dir)
    if need_balance:
        sample = next(iter(price_map.values()), pd.DataFrame())
        if sample is None or "contract_liab" not in getattr(sample, "columns", []):
            price_map = enrich_with_balance(price_map, params, cache_dir)
    return price_map


def latest_candidates(
    factor_id: str,
    signal_fn: SignalBuilder,
    params: Dict[str, Any],
    *,
    need_profit: bool = False,
    need_growth: bool = False,
    need_balance: bool = False,
    need_fin_db: bool = False,
    asof: Optional[str] = None,
    lookback_codes: int = 80,
) -> Dict[str, Any]:
    """用缓存粗算今日信号（限速：只扫部分有缓存的股票）。"""
    from app.services.factors import ashare_fin_db as fin_db

    cache_dir = kit.shared_cache_dir()
    asof_dt = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now().date())
    daily_dir = cache_dir / "daily"
    candidates = []
    if not daily_dir.exists():
        return {
            "factor_id": factor_id,
            "asof": asof_dt.to_pydatetime(),
            "signal": "neutral",
            "value": 0.0,
            "note": "无缓存，请先 refresh/backtest",
        }
    files = sorted(daily_dir.glob("*.parquet"))[:lookback_codes]
    for fp in files:
        code = fp.stem.replace("_", ".", 1) if fp.stem.count("_") == 1 else fp.stem.replace("_", ".")
        # sh_600000 -> sh.600000
        parts = fp.stem.split("_")
        code = ".".join(parts) if len(parts) >= 2 else fp.stem
        px = pd.read_parquet(fp)
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = prepare_price_panel(px, params)
        px["code"] = code
        if need_profit:
            profit = kit.fetch_profit_quarters(
                code, kit.years_range(2018), kit.RateLimiter(0.05), cache_dir
            )
            px = merge_asof_funda(
                px,
                profit,
                [
                    "roeAvg",
                    "npMargin",
                    "gpMargin",
                    "netProfit",
                    "epsTTM",
                    "MBRevenue",
                    "totalShare",
                    "liqaShare",
                ],
            )
        if need_growth:
            growth = kit.fetch_growth_quarters(
                code, kit.years_range(2018), kit.RateLimiter(0.05), cache_dir
            )
            cols = [c for c in growth.columns if c not in ("code", "pubDate", "statDate")]
            px = merge_asof_funda(px, growth, cols[:8])
        if need_fin_db and fin_db.db_available():
            px = fin_db.enrich_price_with_fin_db(px, code)
        if need_balance and "contract_liab" not in px.columns:
            bal = pd.DataFrame()
            if fin_db.db_available():
                try:
                    bal = fin_db.fetch_contract_bundle(code)
                except Exception:  # noqa: BLE001
                    bal = pd.DataFrame()
            if bal is None or bal.empty:
                bal = kit.fetch_contract_liab(code, cache_dir, limiter=kit.RateLimiter(0.05))
            px = merge_asof_funda(
                px,
                bal,
                ["contract_liab", "advance_recv", "contract_liab_raw", "contract_liab_yoy"],
            )
        entries = signal_fn(px, params)
        if entries is None or entries.empty:
            continue
        entries["date"] = pd.to_datetime(entries["date"])
        hit = entries[entries["date"] == asof_dt]
        if hit.empty:
            # 允许 T-1
            hit = entries[entries["date"] >= asof_dt - pd.Timedelta(days=3)]
        for _, r in hit.iterrows():
            candidates.append(
                {
                    "code": code,
                    "entry": str(pd.Timestamp(r["date"]).date()),
                    "note": r.get("note") or "",
                }
            )
    return {
        "factor_id": factor_id,
        "asof": asof_dt.to_pydatetime(),
        "signal": "buy" if candidates else "neutral",
        "value": float(len(candidates)),
        "components": {"candidates": candidates[:30]},
        "note": f"{factor_id} 缓存信号",
    }
