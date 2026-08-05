"""单票 vs active 因子：当前入场/选股信号是否触发。

优先本地 `_shared` 日线/财务缓存与 ashare_fin；不逐因子全宇宙回测。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.services.factors import ashare_fin_db as fin_db
from app.services.factors import bs_kit as kit
from app.services.factors.factor_registry import FACTOR_IMPL
from app.services.factors.match_explain import (
    build_hit_explanation,
    close_at,
    panel_row_at,
    resolve_stock_name,
)
from app.services.factors.runner import merge_asof_funda, prepare_price_panel

logger = logging.getLogger("webapi.factors.match_stock")

# 非个股选股入场的特殊因子
UNSUPPORTED_SPECIAL: Dict[str, str] = {
    "national_team": "宏观/篮子择时，非个股选股入场",
    "dip_buy": "指数急跌×估值择时，非个股选股入场",
}

NEAR_ENTRY_DAYS = 3  # 与 latest_candidates 近窗一致


def normalize_stock_code(raw: str) -> Tuple[str, str]:
    """常见格式 → (baostock code, wind-like code)。

    支持 600887 / sh.600887 / 600887.SH。
    """
    s = str(raw or "").strip()
    if not s:
        raise ValueError("股票代码不能为空")
    wind = fin_db.bs_to_wind(s)
    bs = fin_db.wind_to_bs(wind)
    if not bs or "." not in bs:
        # 兜底：纯数字
        sym = kit.code_to_symbol6(s)
        if sym.isdigit() and len(sym) == 6:
            wind = fin_db.bs_to_wind(sym)
            bs = fin_db.wind_to_bs(wind)
    if not bs or "." not in bs or not kit.code_to_symbol6(bs).isdigit():
        raise ValueError(f"无法识别股票代码: {raw}")
    return bs, fin_db.bs_to_wind(bs)


def _daily_cache_path(code: str) -> Path:
    return kit.shared_cache_dir() / "daily" / f"{code.replace('.', '_')}.parquet"


def _load_daily(code: str) -> Optional[pd.DataFrame]:
    fp = _daily_cache_path(code)
    if not fp.exists():
        return None
    try:
        px = pd.read_parquet(fp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("read daily %s: %s", code, exc)
        return None
    if px is None or px.empty:
        return None
    px = px.copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    px["code"] = code
    return px if not px.empty else None


def _read_funda_cache(kind: str, code: str) -> Optional[pd.DataFrame]:
    fp = kit.shared_cache_dir() / kind / f"{code.replace('.', '_')}.parquet"
    if not fp.exists():
        return None
    try:
        df = pd.read_parquet(fp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("read %s %s: %s", kind, code, exc)
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    if "pubDate" in df.columns:
        df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")
    return df


def _resolve_trade_date(px: pd.DataFrame, asof: Optional[str]) -> pd.Timestamp:
    last = pd.Timestamp(px["date"].max()).normalize()
    if not asof:
        return last
    asof_dt = pd.Timestamp(asof).normalize()
    # 取 ≤ asof 的最近交易日
    eligible = px.loc[px["date"] <= asof_dt, "date"]
    if eligible.empty:
        return last
    return pd.Timestamp(eligible.max()).normalize()


def _entry_near(entries: pd.DataFrame, trade_date: pd.Timestamp) -> Optional[pd.Series]:
    if entries is None or entries.empty:
        return None
    e = entries.copy()
    e["date"] = pd.to_datetime(e["date"], errors="coerce")
    e = e.dropna(subset=["date"])
    if e.empty:
        return None
    hit = e[e["date"].dt.normalize() == trade_date]
    if hit.empty:
        lo = trade_date - pd.Timedelta(days=NEAR_ENTRY_DAYS)
        hit = e[(e["date"].dt.normalize() >= lo) & (e["date"].dt.normalize() <= trade_date)]
    if hit.empty:
        return None
    return hit.sort_values("date").iloc[-1]


def _enrich_base(
    px: pd.DataFrame,
    code: str,
    *,
    need_profit: bool,
    need_growth: bool,
    need_fin_db: bool,
    need_balance: bool,
) -> Tuple[pd.DataFrame, Dict[str, bool]]:
    """按最大需求 enrich 一次；仅本地缓存 / ashare_fin，不撞 BaoStock。"""
    flags = {
        "profit_ok": True,
        "growth_ok": True,
        "fin_db_ok": True,
        "balance_ok": True,
    }
    out = px.copy()

    if need_profit:
        profit = _read_funda_cache("profit", code)
        if profit is None:
            flags["profit_ok"] = False
        else:
            out = merge_asof_funda(
                out,
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
        growth = _read_funda_cache("growth", code)
        if growth is None:
            flags["growth_ok"] = False
        else:
            cols = [c for c in growth.columns if c not in ("code", "pubDate", "statDate")]
            out = merge_asof_funda(out, growth, cols[:8])

    if need_fin_db:
        if not fin_db.db_available():
            flags["fin_db_ok"] = False
        else:
            try:
                out = fin_db.enrich_price_with_fin_db(out, code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fin_db enrich %s: %s", code, exc)
                flags["fin_db_ok"] = False

    if need_balance:
        bal = pd.DataFrame()
        if fin_db.db_available():
            try:
                bal = fin_db.fetch_contract_bundle(code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("balance local %s: %s", code, exc)
                bal = pd.DataFrame()
        if bal is None or bal.empty or "contract_liab" not in getattr(bal, "columns", []):
            # 东财缓存（若有）；绝不发起网络
            bal_fp = kit.shared_cache_dir() / "balance" / f"{code.replace('.', '_')}.parquet"
            if bal_fp.exists():
                try:
                    bal = pd.read_parquet(bal_fp)
                    if "pubDate" in bal.columns:
                        bal["pubDate"] = pd.to_datetime(bal["pubDate"], errors="coerce")
                except Exception:  # noqa: BLE001
                    bal = pd.DataFrame()
        if bal is None or bal.empty or "contract_liab" not in getattr(bal, "columns", []):
            flags["balance_ok"] = False
        else:
            out = merge_asof_funda(
                out,
                bal,
                ["contract_liab", "advance_recv", "contract_liab_raw", "contract_liab_yoy"],
            )

    return out, flags


def _eval_registry_factor(
    factor_id: str,
    meta: Dict[str, Any],
    px_enriched: pd.DataFrame,
    flags: Dict[str, bool],
    trade_date: pd.Timestamp,
    override_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    name = meta.get("name") or factor_id
    need_profit = bool(meta.get("need_profit"))
    need_growth = bool(meta.get("need_growth"))
    need_balance = bool(meta.get("need_balance"))
    need_fin_db = bool(meta.get("need_fin_db"))

    missing: List[str] = []
    if need_profit and not flags.get("profit_ok"):
        missing.append("profit缓存")
    if need_growth and not flags.get("growth_ok"):
        missing.append("growth缓存")
    if need_fin_db and not flags.get("fin_db_ok"):
        missing.append("ashare_fin")
    if need_balance and not flags.get("balance_ok"):
        missing.append("balance/合同负债")
    if missing:
        reason = f"数据不足: {', '.join(missing)}"
        return {
            "factor_id": factor_id,
            "name": name,
            "match": False,
            "status": "insufficient_data",
            "signal": "neutral",
            "reason": reason,
            "entry_date": None,
            "note": "",
            "detail": reason,
            "explanation": reason,
        }

    params = {**(meta.get("params") or {}), **(override_params or {})}
    signal_fn = meta.get("signal")
    if signal_fn is None:
        reason = "无信号实现"
        return {
            "factor_id": factor_id,
            "name": name,
            "match": False,
            "status": "unsupported",
            "signal": "neutral",
            "reason": reason,
            "entry_date": None,
            "note": "",
            "detail": reason,
            "explanation": reason,
        }

    try:
        px = prepare_price_panel(px_enriched, params)
        # prepare 可能丢掉 code
        if "code" not in px.columns:
            px = px.copy()
            px["code"] = px_enriched["code"].iloc[0] if "code" in px_enriched.columns else ""
        entries = signal_fn(px, params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("signal eval %s: %s", factor_id, exc)
        reason = f"评估失败: {exc}"
        return {
            "factor_id": factor_id,
            "name": name,
            "match": False,
            "status": "insufficient_data",
            "signal": "neutral",
            "reason": reason,
            "entry_date": None,
            "note": "",
            "detail": reason,
            "explanation": reason,
        }

    row = _entry_near(entries, trade_date)
    if row is None:
        reason = f"最新交易日 {trade_date.date()} 未触发入场"
        return {
            "factor_id": factor_id,
            "name": name,
            "match": False,
            "status": "miss",
            "signal": "neutral",
            "reason": reason,
            "entry_date": None,
            "note": "",
            "detail": reason,
            "explanation": reason,
        }

    note = str(row.get("note") or "")
    entry_d = str(pd.Timestamp(row["date"]).date())
    panel_row = panel_row_at(px, pd.Timestamp(row["date"]))
    expl = build_hit_explanation(
        note=note,
        entry_date=entry_d,
        params=params,
        panel_row=panel_row,
    )
    return {
        "factor_id": factor_id,
        "name": name,
        "match": True,
        "status": "hit",
        "signal": "buy",
        "reason": f"入场日 {entry_d}" + (f"；{note}" if note else ""),
        "entry_date": entry_d,
        "note": note,
        "detail": expl,
        "explanation": expl,
    }


def _eval_earnings_forecast(
    code: str,
    px: pd.DataFrame,
    trade_date: pd.Timestamp,
    params: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    from app.services.factors.earnings_forecast import (
        DEFAULT_PARAMS,
        _data_dir,
        _find_entry,
    )

    name = "业绩预告双路径因子"

    def _pack(
        *,
        match: bool,
        status: str,
        signal: str,
        reason: str,
        entry_date: Optional[str] = None,
        note: str = "",
        explanation: Optional[str] = None,
    ) -> Dict[str, Any]:
        expl = explanation if explanation is not None else reason
        return {
            "factor_id": "earnings_forecast",
            "name": name,
            "match": match,
            "status": status,
            "signal": signal,
            "reason": reason,
            "entry_date": entry_date,
            "note": note,
            "detail": expl,
            "explanation": expl,
        }

    p = {**DEFAULT_PARAMS, **(params or {})}
    ev_path = _data_dir() / "positive_events.parquet"
    if not ev_path.exists():
        return _pack(
            match=False,
            status="insufficient_data",
            signal="neutral",
            reason="数据不足: 无 positive_events 缓存",
        )

    try:
        events = pd.read_parquet(ev_path)
    except Exception as exc:  # noqa: BLE001
        return _pack(
            match=False,
            status="insufficient_data",
            signal="neutral",
            reason=f"读取事件失败: {exc}",
        )

    if "code" not in events.columns:
        return _pack(
            match=False,
            status="insufficient_data",
            signal="neutral",
            reason="事件表缺少 code 列",
        )

    # 兼容 sh.600887 / 600887.SH / 600887
    sym6 = kit.code_to_symbol6(code)
    codeset = {code, fin_db.bs_to_wind(code), sym6, code.replace(".", "_")}
    ev_codes = events["code"].astype(str)
    mask = ev_codes.isin(codeset) | ev_codes.map(lambda c: kit.code_to_symbol6(c) == sym6)
    mine = events.loc[mask].copy()
    if mine.empty:
        return _pack(
            match=False,
            status="miss",
            signal="neutral",
            reason="近期无正面预告事件（或未覆盖该票）",
        )

    mine["profitForcastExpPubDate"] = pd.to_datetime(
        mine["profitForcastExpPubDate"], errors="coerce"
    )
    max_d = int(p.get("max_days_wait") or 45)
    recent = mine[mine["profitForcastExpPubDate"] >= trade_date - pd.Timedelta(days=max_d + 10)]
    if recent.empty:
        return _pack(
            match=False,
            status="miss",
            signal="neutral",
            reason="近期窗口内无正面预告",
        )

    bars = px[["date", "open", "high", "low", "close"]].copy() if "high" in px.columns else px.copy()
    best = None
    for _, ev in recent.iterrows():
        hit = _find_entry(bars, pd.Timestamp(ev["profitForcastExpPubDate"]), ev, p)
        if hit is None:
            continue
        entry_dt = pd.Timestamp(hit["entry_date"]).normalize()
        if entry_dt == trade_date or (
            trade_date - pd.Timedelta(days=NEAR_ENTRY_DAYS) <= entry_dt <= trade_date
        ):
            if best is None or entry_dt > pd.Timestamp(best["entry_date"]).normalize():
                best = hit

    if best is None:
        return _pack(
            match=False,
            status="miss",
            signal="neutral",
            reason=f"最新交易日 {trade_date.date()} 未触发双路径入场",
        )

    entry_d = str(pd.Timestamp(best["entry_date"]).date())
    note = f"{best.get('entry_mode')}/{best.get('surprise_tier')}"
    expl = build_hit_explanation(
        note=f"业绩预告双路径触发（{note}）",
        entry_date=entry_d,
        params=p,
        panel_row=panel_row_at(px, pd.Timestamp(best["entry_date"])),
        extra=[
            f"等待窗口≤{max_d}日",
            f"模式 {best.get('entry_mode')} / 超预期档 {best.get('surprise_tier')}",
        ],
    )
    return _pack(
        match=True,
        status="hit",
        signal="buy",
        reason=f"入场日 {entry_d}；{note}",
        entry_date=entry_d,
        note=note,
        explanation=expl,
    )


def _eval_dividend_etf(
    code: str,
    trade_date: pd.Timestamp,
    params: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    from app.services.factors.dividend_etf_swing import (
        DEFAULT_PARAMS,
        build_positions,
        resolve_etf_panel,
    )

    name = "红利ETF波段"

    def _pack(
        *,
        match: bool,
        status: str,
        signal: str,
        reason: str,
        entry_date: Optional[str] = None,
        note: str = "",
        explanation: Optional[str] = None,
    ) -> Dict[str, Any]:
        expl = explanation if explanation is not None else reason
        return {
            "factor_id": "dividend_etf_swing",
            "name": name,
            "match": match,
            "status": status,
            "signal": signal,
            "reason": reason,
            "entry_date": entry_date,
            "note": note,
            "detail": expl,
            "explanation": expl,
        }

    p = {**DEFAULT_PARAMS, **(params or {})}
    etf = str(p.get("etf_code") or "515080")
    fallbacks = [str(x) for x in (p.get("fallback_etfs") or [])]
    allowed = {kit.code_to_symbol6(etf), *[kit.code_to_symbol6(x) for x in fallbacks]}
    sym = kit.code_to_symbol6(code)
    if sym not in allowed:
        return _pack(
            match=False,
            status="unsupported",
            signal="neutral",
            reason=f"仅适用于红利ETF（默认 {etf}），非个股选股",
        )

    try:
        etf_code, raw = resolve_etf_panel(p)
        if raw is None or raw.empty:
            return _pack(
                match=False,
                status="insufficient_data",
                signal="neutral",
                reason="数据不足: 无红利ETF行情缓存",
            )
        raw = raw[raw["date"] <= trade_date]
        if raw.empty:
            return _pack(
                match=False,
                status="insufficient_data",
                signal="neutral",
                reason="数据不足: asof 前无行情",
            )
        panel = build_positions(raw, p)
        last = panel.iloc[-1]
        prev = float(panel.iloc[-2]["position"]) if len(panel) > 1 else 0.0
        pos = float(last["position"])
        asof_d = str(pd.Timestamp(last["date"]).date())
        if pos > 0.05 and prev <= 0.05:
            reason = f"{etf_code} 于 {asof_d} 触发买入（仓位 {pos:.0%}）"
            expl = build_hit_explanation(
                note="红利ETF波段新开仓",
                entry_date=asof_d,
                params=p,
                extra=[f"标的 {etf_code}", f"仓位由 {prev:.0%} → {pos:.0%}"],
            )
            return _pack(
                match=True,
                status="hit",
                signal="buy",
                reason=reason,
                entry_date=asof_d,
                note=f"position={pos:.4f}",
                explanation=expl,
            )
        if pos > 0.05:
            reason = f"{etf_code} 持仓中但非当日新入场（仓位 {pos:.0%}）"
            return _pack(
                match=False,
                status="miss",
                signal="hold",
                reason=reason,
                note=f"position={pos:.4f}",
            )
        return _pack(
            match=False,
            status="miss",
            signal="neutral",
            reason=f"{etf_code} 当前无入场信号",
        )
    except Exception as exc:  # noqa: BLE001
        return _pack(
            match=False,
            status="insufficient_data",
            signal="neutral",
            reason=f"评估失败: {exc}",
        )


def _match_item(
    *,
    factor_id: str,
    name: str,
    match: bool,
    status: str,
    signal: str,
    reason: str,
    entry_date: Optional[str] = None,
    note: str = "",
    explanation: Optional[str] = None,
) -> Dict[str, Any]:
    expl = explanation if explanation is not None else reason
    return {
        "factor_id": factor_id,
        "name": name,
        "match": match,
        "status": status,
        "signal": signal,
        "reason": reason,
        "entry_date": entry_date,
        "note": note,
        "detail": expl,
        "explanation": expl,
    }


def _ensure_match_explain_fields(m: Dict[str, Any]) -> Dict[str, Any]:
    """兼容旧路径：补齐 detail/explanation。"""
    reason = str(m.get("reason") or m.get("note") or "")
    expl = m.get("explanation") or m.get("detail") or reason
    m["detail"] = expl
    m["explanation"] = expl
    return m


def _stock_meta_payload(
    bs_code: str,
    px: Optional[pd.DataFrame],
    trade_date: Optional[pd.Timestamp],
) -> Dict[str, Any]:
    """名称 / 收盘价（前复权）/ 价格日期。"""
    stock_name = resolve_stock_name(bs_code)
    price = close_at(px, trade_date) if px is not None and trade_date is not None else None
    price_date = str(trade_date.date()) if trade_date is not None else None
    return {
        "name": stock_name or None,
        "stock_name": stock_name or None,
        "price": price,
        "close": price,
        "price_date": price_date,
        "price_adjust": "qfq",  # baostock adjustflag=2 前复权
        "price_adjust_label": "前复权",
    }


def match_stock_against_factors(
    code_raw: str,
    factor_docs: Sequence[Dict[str, Any]],
    *,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    """对 active 因子列表做单票当前信号匹配。

    factor_docs: Mongo/序列化后的因子文档（至少含 factor_id, name, status, params）。
    """
    bs_code, wind_code = normalize_stock_code(code_raw)
    px = _load_daily(bs_code)
    data_status = {
        "daily_cache": px is not None,
        "ashare_fin": fin_db.db_available(),
        "baostock": "cache_only",
        "daily_path": str(_daily_cache_path(bs_code)),
    }
    stock_meta = _stock_meta_payload(bs_code, None, None)

    active = [
        d
        for d in factor_docs
        if str(d.get("status") or "active").lower() == "active"
    ]

    if px is None:
        matches = []
        for d in active:
            fid = str(d.get("factor_id") or "")
            name = str(d.get("name") or fid)
            if fid in UNSUPPORTED_SPECIAL:
                matches.append(
                    _match_item(
                        factor_id=fid,
                        name=name,
                        match=False,
                        status="unsupported",
                        signal="neutral",
                        reason=UNSUPPORTED_SPECIAL[fid],
                    )
                )
            else:
                reason = (
                    f"本地无日线缓存（{_daily_cache_path(bs_code).name}），"
                    "BaoStock 不可用时无法评估"
                )
                matches.append(
                    _match_item(
                        factor_id=fid,
                        name=name,
                        match=False,
                        status="insufficient_data",
                        signal="neutral",
                        reason=reason,
                    )
                )
        summary = _summarize(matches)
        return {
            "code": bs_code,
            "code_norm": wind_code,
            **stock_meta,
            "asof": asof,
            "trade_date": None,
            "data_status": data_status,
            "error": "本地日线缓存缺失，请先同步该票日线或换有缓存的代码",
            "matches": matches,
            "summary": summary,
        }

    trade_date = _resolve_trade_date(px, asof)
    stock_meta = _stock_meta_payload(bs_code, px, trade_date)
    data_status["trade_date"] = str(trade_date.date())
    data_status["daily_rows"] = int(len(px))
    data_status["daily_last"] = str(pd.Timestamp(px["date"].max()).date())

    # 聚合 need_*，只 enrich 一次
    need_profit = need_growth = need_balance = need_fin_db = False
    for d in active:
        fid = str(d.get("factor_id") or "")
        meta = FACTOR_IMPL.get(fid)
        if not meta:
            continue
        need_profit = need_profit or bool(meta.get("need_profit"))
        need_growth = need_growth or bool(meta.get("need_growth"))
        need_balance = need_balance or bool(meta.get("need_balance"))
        need_fin_db = need_fin_db or bool(meta.get("need_fin_db"))

    px_enriched, flags = _enrich_base(
        px,
        bs_code,
        need_profit=need_profit,
        need_growth=need_growth,
        need_fin_db=need_fin_db,
        need_balance=need_balance,
    )
    data_status["enrich"] = flags

    matches: List[Dict[str, Any]] = []
    for d in active:
        fid = str(d.get("factor_id") or "")
        name = str(d.get("name") or fid)
        params = d.get("params") if isinstance(d.get("params"), dict) else {}

        if fid in UNSUPPORTED_SPECIAL:
            matches.append(
                _match_item(
                    factor_id=fid,
                    name=name,
                    match=False,
                    status="unsupported",
                    signal="neutral",
                    reason=UNSUPPORTED_SPECIAL[fid],
                )
            )
            continue

        if fid == "earnings_forecast":
            matches.append(
                _ensure_match_explain_fields(
                    _eval_earnings_forecast(bs_code, px, trade_date, params)
                )
            )
            continue

        if fid == "dividend_etf_swing":
            matches.append(
                _ensure_match_explain_fields(
                    _eval_dividend_etf(bs_code, trade_date, params)
                )
            )
            continue

        meta = FACTOR_IMPL.get(fid)
        if meta is None:
            matches.append(
                _match_item(
                    factor_id=fid,
                    name=name,
                    match=False,
                    status="unsupported",
                    signal="neutral",
                    reason="自定义/未注册实现，无法单票评估",
                )
            )
            continue

        row = _eval_registry_factor(
            fid,
            {**meta, "name": meta.get("name") or name},
            px_enriched,
            flags,
            trade_date,
            override_params=params,
        )
        matches.append(_ensure_match_explain_fields(row))

    # hit 优先，再 insufficient / unsupported / miss
    order = {"hit": 0, "insufficient_data": 1, "unsupported": 2, "miss": 3}
    matches.sort(key=lambda m: (order.get(str(m.get("status")), 9), str(m.get("factor_id"))))

    return {
        "code": bs_code,
        "code_norm": wind_code,
        **stock_meta,
        "asof": asof or str(trade_date.date()),
        "trade_date": str(trade_date.date()),
        "data_status": data_status,
        "matches": matches,
        "summary": _summarize(matches),
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _summarize(matches: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    out = {"hit": 0, "miss": 0, "unsupported": 0, "insufficient_data": 0, "total": len(matches)}
    for m in matches:
        st = str(m.get("status") or "miss")
        if st in out:
            out[st] += 1
        else:
            out["miss"] += 1
    return out
