# -*- coding: utf-8 -*-
"""红利 ETF 向上倾斜网格（lahm 策略中心正式版）。

规则（回测最优默认）：
- 中枢 center = max(历史中枢, MA90)，只升不降（扫描端用当日 MA90 近似）
- 步长 0.8%；10 档；至少保留 2 档底仓
- 标的以红利 ETF 为主
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.strategies.common import cached_scan, now_iso, safe_float
from app.services.strategies.etf_grid_backtest import (
    DEFAULT_PARAMS_V3,
    DIVIDEND_ETFS,
    run_dividend_grid_batch,
    save_batch_outputs,
)

logger = logging.getLogger("webapi.strategies.etf_grid")

ROOT = Path(__file__).resolve().parents[3]
BT_JSON = ROOT / "data" / "strategies" / "etf_grid_dividend_backtest_v3.json"

# 正式参数 = v3 扫描最优
STEP_PCT = float(DEFAULT_PARAMS_V3["step_pct"])  # 0.008
N_GRIDS = int(DEFAULT_PARAMS_V3["n_grids"])  # 10
MIN_LAYERS = int(DEFAULT_PARAMS_V3["min_layers"])  # 2
MA_CENTER = int(DEFAULT_PARAMS_V3["ma_center"])  # 90

# 展示/交易宇宙：红利为主
UNIVERSE: List[Tuple[str, str]] = [(c, n) for c, n, _ in DIVIDEND_ETFS]


def _fetch_etf_spot() -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_spot_em()


def _ma_center(code: str) -> Optional[float]:
    """用本地/拉取日线算 MA90，作为倾斜中枢。"""
    try:
        from app.services.factors.dividend_etf_swing import load_or_fetch_etf

        df = load_or_fetch_etf(code, start="20180101", force=False)
        if df is None or df.empty or "close" not in df.columns:
            return None
        s = df.sort_values("date")["close"].astype(float)
        if len(s) < MA_CENTER:
            return float(s.iloc[-1])
        return float(s.rolling(MA_CENTER).mean().iloc[-1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("ma_center %s failed: %s", code, exc)
        return None


def _slope_levels(center: float, price: float, step_pct: float, n: int) -> Dict[str, Any]:
    buys = [round(center * (1 - step_pct * i), 4) for i in range(1, n + 1)]
    sells = [round(center * (1 + step_pct * i), 4) for i in range(1, n + 1)]
    dist = (price / center - 1.0) if center > 0 else 0.0
    if dist <= -step_pct:
        zone = "加仓区"
        hint = f"现价低于中枢 {abs(dist)*100:.1f}%：可按买档加仓，最多 {N_GRIDS} 档"
    elif dist >= step_pct:
        zone = "减仓区"
        hint = f"现价高于中枢 {dist*100:.1f}%：可减一层，但至少保留 {MIN_LAYERS} 档底仓"
    else:
        zone = "中枢附近"
        hint = "贴近倾斜中枢：观望或按最小档微调"
    return {
        "center": round(center, 4),
        "buy_levels": buys,
        "sell_levels": sells,
        "zone": zone,
        "dist_to_center_pct": round(dist * 100, 2),
        "hint": hint,
    }


def _load_backtest_table(*, refresh: bool = False) -> Dict[str, Any]:
    if refresh or not BT_JSON.exists():
        try:
            batch = run_dividend_grid_batch(
                include_compare=False,
                start="2018-01-01",
                force_fetch=False,
                params=dict(DEFAULT_PARAMS_V3),
                version="v3",
            )
            save_batch_outputs(batch)
        except Exception as exc:  # noqa: BLE001
            logger.exception("etf_grid backtest refresh failed: %s", exc)
            if not BT_JSON.exists():
                return {"error": str(exc), "summary_table": []}
    try:
        payload = json.loads(BT_JSON.read_text(encoding="utf-8"))
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "summary_table": []}


def _scan(*, refresh_bt: bool = False) -> Dict[str, Any]:
    try:
        spot = _fetch_etf_spot()
        code_col = "代码" if "代码" in spot.columns else "code"
        by_code = {str(r[code_col]).zfill(6): r for _, r in spot.iterrows()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("etf spot fetch failed: %s", exc)
        by_code = {}

    bt = _load_backtest_table(refresh=refresh_bt)
    bt_by_code = {
        str(r.get("code")).zfill(6): r
        for r in (bt.get("summary_table") or [])
        if isinstance(r, dict) and r.get("code")
    }

    items: List[Dict[str, Any]] = []
    for code, name in UNIVERSE:
        r = by_code.get(code)
        center = _ma_center(code)
        bt_row = bt_by_code.get(code) or {}

        if r is None:
            px = None
            item: Dict[str, Any] = {
                "code": code,
                "name": name,
                "available": center is not None,
                "price": None,
            }
        else:
            px = safe_float(r.get("最新价"))
            item = {
                "code": code,
                "name": str(r.get("名称") or name),
                "available": bool(px and px > 0 and center),
                "price": px,
                "iopv": safe_float(r.get("IOPV实时估值")),
                "discount_pct": safe_float(r.get("基金折价率")),
                "change_pct": safe_float(r.get("涨跌幅")),
                "amount": safe_float(r.get("成交额")),
            }

        if center and px and px > 0:
            item.update(_slope_levels(center, px, STEP_PCT, N_GRIDS))
            item["step_pct"] = round(STEP_PCT * 100, 2)
            item["n_grids"] = N_GRIDS
            item["min_layers"] = MIN_LAYERS
            item["ma_center"] = MA_CENTER
            item["style"] = "slope_up"
        elif center:
            item["center"] = round(center, 4)
            item["step_pct"] = round(STEP_PCT * 100, 2)
            item["hint"] = "无现价，仅给出中枢参考"
            item["available"] = False
        else:
            item["hint"] = "行情/均线不足"
            item["available"] = False

        if bt_row:
            item["bt_cagr"] = bt_row.get("grid_cagr")
            item["bt_bh_cagr"] = bt_row.get("bh_cagr")
            item["bt_excess"] = bt_row.get("excess_cagr")
            item["bt_sharpe"] = bt_row.get("grid_sharpe")
            item["bt_max_dd"] = bt_row.get("grid_max_dd")

        items.append(item)

    ready = sum(1 for x in items if x.get("available"))
    return {
        "asof": now_iso(),
        "strategy": "etf_grid",
        "variant": "slope_up_v3",
        "source": "akshare.fund_etf_spot_em + local etf daily MA90",
        "params": {
            "step_pct": STEP_PCT,
            "n_grids": N_GRIDS,
            "min_layers": MIN_LAYERS,
            "ma_center": MA_CENTER,
            "commission_rate": DEFAULT_PARAMS_V3.get("commission_rate"),
        },
        "summary": {
            "n_universe": len(UNIVERSE),
            "n_ready": ready,
            "step_pct": f"{STEP_PCT*100:.1f}%",
            "ma": f"MA{MA_CENTER}",
            "min_layers": MIN_LAYERS,
        },
        "items": items,
        "backtest": {
            "rule": bt.get("rule"),
            "asof": bt.get("asof"),
            "summary_table": bt.get("summary_table") or [],
            "notes": bt.get("notes") or [],
        },
        "notes": [
            "正式版：红利 ETF 向上倾斜网格（中枢只跟均线上移，不贴日线抬升）。",
            f"参数：步长 {STEP_PCT*100:.1f}% · {N_GRIDS} 档 · 底仓≥{MIN_LAYERS} · 中枢 MA{MA_CENTER}。",
            "卖出不少于底仓档；适合红利慢牛 + 回踩加仓。",
            "下方回测为 2018 至今、佣金万一；强制刷新时会重算。",
            "QMT 就绪后可按 buy/sell_levels 挂单（接口已预留）。",
        ],
    }


def get_scan(*, refresh: bool = False, ttl_sec: int = 300) -> Dict[str, Any]:
    # refresh 时顺带重算回测
    if refresh:
        return cached_scan("etf_grid_slope_v3", lambda: _scan(refresh_bt=True), refresh=True, ttl_sec=0)
    return cached_scan("etf_grid_slope_v3", lambda: _scan(refresh_bt=False), refresh=False, ttl_sec=ttl_sec)
