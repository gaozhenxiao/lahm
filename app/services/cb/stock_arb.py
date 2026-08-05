# -*- coding: utf-8 -*-
"""转债 ↔ 正股套利扫描。"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("webapi.cb.stock_arb")

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "data" / "cb"
CACHE_FP = CACHE_DIR / "stock_arb_latest.json"
DEFAULT_TTL_SEC = 300

# 费用粗估：转债买入万 0.5 + 正股卖出印花税万 5 + 佣金万 0.5
_CB_BUY_FEE = 0.00005
_STOCK_SELL_FEE = 0.00055


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _is_junk_row(r: pd.Series) -> bool:
    name = str(r.get("债券简称") or "")
    stock = str(r.get("正股简称") or "")
    if "退" in name:
        return True
    if stock.startswith("R") or "ST" in stock:
        return True
    if pd.isna(r.get("债现价")):
        return True
    return False


def _approx_convertible(list_date: Any) -> Optional[bool]:
    """上市满约 6 个月视为进入转股期（近似；以公告为准）。"""
    lt = pd.to_datetime(list_date, errors="coerce")
    if pd.isna(lt):
        return None
    start = lt + pd.DateOffset(months=6)
    return bool(pd.Timestamp.now() >= start)


def _net_edge_pct(cb: float, cv: float) -> Optional[float]:
    if not (math.isfinite(cb) and math.isfinite(cv)) or cb <= 0:
        return None
    return round((cv * (1.0 - _STOCK_SELL_FEE) - cb * (1.0 + _CB_BUY_FEE)) / cb * 100.0, 3)


def _row_flags(premium: float, cb: float, amount: Optional[float]) -> List[str]:
    flags: List[str] = []
    if premium < 0:
        flags.append("折价")
        if cb >= 110:
            flags.append("高价折价·请核强赎/公告")
    if 0 <= premium <= 1:
        flags.append("近似平价")
    if amount is not None and amount >= 1e8:
        flags.append("高成交")
    return flags


def _fetch_cov_df() -> pd.DataFrame:
    import akshare as ak

    df = ak.bond_zh_cov()
    for c in ("转股价", "转股价值", "债现价", "转股溢价率", "正股价"):
        if c in df.columns:
            df[c] = _to_num(df[c])
    return df


def _fetch_spot_map() -> Dict[str, Dict[str, Any]]:
    """code -> {amount, volume, changepercent, trade, ticktime}"""
    try:
        import akshare as ak

        spot = ak.bond_zh_hs_cov_spot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bond_zh_hs_cov_spot failed: %s", exc)
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    if spot is None or spot.empty:
        return out
    code_col = "code" if "code" in spot.columns else None
    if not code_col:
        return out
    for _, r in spot.iterrows():
        code = str(r.get(code_col) or "").strip()
        if not code:
            continue
        out[code] = {
            "trade": _safe_float(r.get("trade")),
            "changepercent": _safe_float(r.get("changepercent")),
            "volume": _safe_float(r.get("volume")),
            "amount": _safe_float(r.get("amount")),
            "ticktime": str(r.get("ticktime") or "") or None,
        }
    return out


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _record_from_row(r: pd.Series, spot: Dict[str, Any]) -> Dict[str, Any]:
    code = str(r.get("债券代码") or "").strip()
    cb = _safe_float(r.get("债现价"))
    # 现货价优先（更贴近盘口）
    if spot.get("trade") is not None:
        cb = float(spot["trade"])
    cv = _safe_float(r.get("转股价值"))
    stock_px = _safe_float(r.get("正股价"))
    conv_px = _safe_float(r.get("转股价"))
    premium = _safe_float(r.get("转股溢价率"))
    if cb is not None and cv is not None and cv > 0 and premium is None:
        premium = round((cb - cv) / cv * 100.0, 3)
    # 若用了现货价，重算溢价
    if cb is not None and cv is not None and cv > 0 and spot.get("trade") is not None:
        premium = round((cb - cv) / cv * 100.0, 3)

    amount = spot.get("amount")
    dual_low = None
    if cb is not None and premium is not None:
        dual_low = round(cb + premium, 3)

    list_date = r.get("上市时间")
    list_s = None
    if pd.notna(list_date):
        list_s = str(pd.to_datetime(list_date))[:10]

    return {
        "bond_code": code,
        "bond_name": str(r.get("债券简称") or ""),
        "stock_code": str(r.get("正股代码") or ""),
        "stock_name": str(r.get("正股简称") or ""),
        "bond_price": cb,
        "stock_price": stock_px,
        "conversion_price": conv_px,
        "conversion_value": cv,
        "premium_pct": premium,
        "net_edge_pct": _net_edge_pct(cb, cv) if cb is not None and cv is not None else None,
        "dual_low": dual_low,
        "rating": str(r.get("信用评级") or "") or None,
        "list_date": list_s,
        "approx_in_convert_period": _approx_convertible(list_date),
        "change_pct": spot.get("changepercent"),
        "amount": amount,
        "volume": spot.get("volume"),
        "ticktime": spot.get("ticktime"),
        "flags": _row_flags(premium or 0.0, cb or 0.0, amount),
    }


def scan_stock_arb(
    *,
    discount_max: float = -0.3,
    near_parity_max: float = 3.0,
    dual_low_max_price: float = 130.0,
    dual_low_max_premium: float = 25.0,
    dual_low_top_n: int = 30,
    near_parity_top_n: int = 40,
) -> Dict[str, Any]:
    """拉取全市场转债并分类。"""
    df = _fetch_cov_df()
    spot_map = _fetch_spot_map()

    alive = df[~df.apply(_is_junk_row, axis=1)].copy()
    # 债价卡在 100 多为未上市/无成交噪声
    traded = alive[
        ~((alive["债现价"] >= 99.99) & (alive["债现价"] <= 100.01))
    ].copy()

    records: List[Dict[str, Any]] = []
    for _, r in traded.iterrows():
        code = str(r.get("债券代码") or "").strip()
        rec = _record_from_row(r, spot_map.get(code, {}))
        if rec["premium_pct"] is None or rec["bond_price"] is None:
            continue
        records.append(rec)

    discount = [
        x
        for x in records
        if x["premium_pct"] is not None and x["premium_pct"] <= discount_max
    ]
    discount.sort(key=lambda x: x["premium_pct"])

    near = [
        x
        for x in records
        if x["premium_pct"] is not None
        and 0 <= x["premium_pct"] <= near_parity_max
        and (x["bond_price"] or 0) >= 95
    ]
    near.sort(key=lambda x: x["premium_pct"])

    dual = [
        x
        for x in records
        if x["dual_low"] is not None
        and (x["bond_price"] or 999) <= dual_low_max_price
        and (x["premium_pct"] or 999) <= dual_low_max_premium
    ]
    dual.sort(key=lambda x: x["dual_low"])

    return {
        "asof": _now_iso(),
        "source": "akshare.bond_zh_cov + bond_zh_hs_cov_spot",
        "params": {
            "discount_max": discount_max,
            "near_parity_max": near_parity_max,
            "dual_low_max_price": dual_low_max_price,
            "dual_low_max_premium": dual_low_max_premium,
        },
        "summary": {
            "n_alive": int(len(alive)),
            "n_traded": int(len(traded)),
            "n_discount": len(discount),
            "n_near_parity": len(near),
            "n_dual_low": len(dual),
        },
        "discount": discount,
        "near_parity": near[:near_parity_top_n],
        "dual_low": dual[:dual_low_top_n],
        "notes": [
            "折价套利存在 T+1 转股隔夜风险；净边为佣金/印花税粗估，未含滑点与融券息。",
            "上市+6 月仅为转股期近似，请以募集说明书/公告为准。",
            "高价折价常伴随强赎等事件，下单前务必核公告。",
            "双低=债价+溢价率，属于相对价值轮动，不是无风险套利。",
        ],
    }


def _read_cache() -> Optional[Dict[str, Any]]:
    if not CACHE_FP.exists():
        return None
    try:
        return json.loads(CACHE_FP.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("read cache failed: %s", exc)
        return None


def _write_cache(payload: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FP.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_age_sec(payload: Dict[str, Any]) -> Optional[float]:
    asof = payload.get("asof")
    if not asof:
        return None
    try:
        ts = datetime.fromisoformat(str(asof))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return (datetime.now(ts.tzinfo) - ts).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def get_stock_arb(
    *,
    refresh: bool = False,
    ttl_sec: int = DEFAULT_TTL_SEC,
    **scan_kwargs: Any,
) -> Dict[str, Any]:
    """带本地缓存的扫描结果。"""
    if not refresh:
        cached = _read_cache()
        if cached:
            age = _cache_age_sec(cached)
            if age is not None and age <= ttl_sec:
                out = dict(cached)
                out["cached"] = True
                out["cache_age_sec"] = int(age)
                return out

    payload = scan_stock_arb(**scan_kwargs)
    payload["cached"] = False
    payload["cache_age_sec"] = 0
    _write_cache(payload)
    return payload
