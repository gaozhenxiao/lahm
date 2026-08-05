"""单票匹配：基于 params 阈值与入场日面板值生成可读解释。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

# 阈值参数 → (中文名, 面板列, 比较方向, 是否按百分比展示面板值)
# direction: "le" 面板值应 ≤ 阈值；"ge" 应 ≥；"abs_le" 面板值应 ≤ -abs(阈值)（回撤类）
_PARAM_SPECS: Dict[str, tuple] = {
    "pb_pct_max": ("PB历史分位", "pb_pct", "le", "pct"),
    "pe_pct_max": ("PE历史分位", "pe_pct", "le", "pct"),
    "pb_max": ("PB(MRQ)", "pbMRQ", "le", "num"),
    "pe_max": ("PE(TTM)", "peTTM", "le", "num"),
    "roe_min": ("ROE", "roeAvg", "ge_roe", "roe"),
    "margin_min": ("净利率", "npMargin", "ge_roe", "roe"),
    "gp_margin_min": ("毛利率", "gpMargin", "ge_roe", "roe"),
    "growth_min": ("净利同比", "YOYNI", "ge_growth", "growth"),
    "dd_need": ("近20日回撤", "dd_20", "abs_le", "pct"),
    "mom_min": ("60日动量", "ret_60", "ge", "pct"),
    "ret20_max": ("20日涨幅", "ret_20", "le", "pct"),
    "ret20_min": ("20日涨幅", "ret_20", "ge", "pct"),
    "vol_mult": ("成交额/20日均额倍数阈值", None, "info", "num"),
    "surge_ratio": ("换手放大倍数阈值", None, "info", "num"),
    "amp_pct_max": ("振幅分位上限", None, "info", "pct"),
    "peg_max": ("PEG上限", None, "info", "num"),
}


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fmt_pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def _fmt_num(v: float, digits: int = 2) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.{digits}f}"


def _fmt_roe_like(v: float) -> str:
    """baostock ROE/利润率可能是小数或百分数。"""
    if abs(v) > 1.5:
        return f"{v:.1f}%"
    return _fmt_pct(v)


def _fmt_growth(v: float) -> str:
    if abs(v) > 2:
        return f"{v:.1f}%"
    return _fmt_pct(v)


def panel_row_at(px: pd.DataFrame, when: pd.Timestamp) -> Optional[pd.Series]:
    if px is None or px.empty or "date" not in px.columns:
        return None
    d = pd.Timestamp(when).normalize()
    hit = px.loc[pd.to_datetime(px["date"], errors="coerce").dt.normalize() == d]
    if hit.empty:
        return None
    return hit.iloc[-1]


def _growth_col(row: pd.Series) -> Optional[str]:
    for c in ("YOYNI", "YOYEPSBasic", "YOYEquity", "NIYOY"):
        if c in row.index and _safe_float(row.get(c)) is not None:
            return c
    return None


def _append_threshold_bits(
    bits: List[str],
    params: Dict[str, Any],
    row: Optional[pd.Series],
) -> None:
    if not params:
        return
    seen_cols: set = set()
    for key, (label, col, direction, kind) in _PARAM_SPECS.items():
        if key not in params:
            continue
        thr = _safe_float(params.get(key))
        if thr is None:
            continue

        use_col = col
        if key == "growth_min" and row is not None:
            use_col = _growth_col(row) or col

        if direction == "info" or use_col is None or row is None or use_col not in row.index:
            if kind == "pct":
                thr_s = _fmt_pct(thr) if abs(thr) <= 2 else _fmt_num(thr)
                bits.append(f"{label} {thr_s}")
            else:
                bits.append(f"{label} {_fmt_num(thr)}")
            continue

        if use_col in seen_cols:
            continue
        val = _safe_float(row.get(use_col))
        if val is None:
            continue
        seen_cols.add(use_col)

        if kind == "pct":
            v_s, t_s = _fmt_pct(val), _fmt_pct(abs(thr) if direction == "abs_le" else thr)
        elif kind == "roe":
            v_s, t_s = _fmt_roe_like(val), _fmt_roe_like(thr)
        elif kind == "growth":
            v_s, t_s = _fmt_growth(val), _fmt_growth(thr)
            label = f"{label}({use_col})"
        else:
            v_s, t_s = _fmt_num(val), _fmt_num(thr)

        if direction == "le":
            bits.append(f"{label} {v_s} ≤ 阈值 {t_s}")
        elif direction == "ge":
            bits.append(f"{label} {v_s} ≥ 阈值 {t_s}")
        elif direction == "ge_roe":
            # 兼容百分数存储：任一口径达标即展示实际值
            bits.append(f"{label} {v_s}（门槛 {_fmt_roe_like(thr)}）")
        elif direction == "ge_growth":
            bits.append(f"{label} {v_s}（门槛 {_fmt_growth(thr)}）")
        elif direction == "abs_le":
            need = -abs(thr)
            bits.append(f"{label} {v_s} ≤ {_fmt_pct(need)}")
        else:
            bits.append(f"{label} {v_s}（阈值 {t_s}）")


def _append_price_structure(bits: List[str], row: Optional[pd.Series]) -> None:
    if row is None:
        return
    close = _safe_float(row.get("close"))
    if close is None:
        return
    for ma_col, ma_name in (("ma20", "MA20"), ("ma60", "MA60"), ("ma120", "MA120")):
        ma = _safe_float(row.get(ma_col))
        if ma is None:
            continue
        rel = "站上" if close > ma else "低于"
        bits.append(f"收盘 {_fmt_num(close)} {rel}{ma_name} {_fmt_num(ma)}")
        break  # 只报一条主均线关系，避免冗长
    high60 = _safe_float(row.get("high_60"))
    if high60 is not None and close is not None and close >= high60 * 0.999:
        bits.append(f"触及/突破60日高 {_fmt_num(high60)}")


def build_hit_explanation(
    *,
    note: str = "",
    entry_date: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    panel_row: Optional[pd.Series] = None,
    extra: Optional[Sequence[str]] = None,
) -> str:
    """生成 hit 的中文详细解释（非 match=true 口号）。"""
    bits: List[str] = []
    note_s = str(note or "").strip()
    if note_s:
        bits.append(note_s)
    if entry_date:
        bits.append(f"入场日 {entry_date}")
    _append_threshold_bits(bits, params or {}, panel_row)
    _append_price_structure(bits, panel_row)
    if extra:
        for e in extra:
            e_s = str(e or "").strip()
            if e_s and e_s not in bits:
                bits.append(e_s)
    # 去重保序
    out: List[str] = []
    seen = set()
    for b in bits:
        if b not in seen:
            seen.add(b)
            out.append(b)
    if not out:
        return "当日触发入场信号（详见因子条件）"
    return "；".join(out)


def resolve_stock_name(bs_code: str) -> str:
    """优雅降级：查不到返回空串。"""
    try:
        from app.services.factors import bs_kit as kit

        sym = kit.code_to_symbol6(bs_code)
        return str(kit.load_stock_name_map().get(sym) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def close_at(px: pd.DataFrame, trade_date: pd.Timestamp) -> Optional[float]:
    row = panel_row_at(px, trade_date)
    if row is None:
        return None
    return _safe_float(row.get("close"))
