"""IPO≈2.5年解禁窗口 × 业绩释放：研究对照 + 可选因子原型。

背景假设：大股东常约 3 年锁定期；IPO 后 ~2.5 年窗口业绩开始释放（本脚本无解禁明细，
用上市年龄作代理，并在报告中写明）。

数据：
- 上市日：本地财务库 ``中国A股与公司基本资料.S_INFO_LISTDATE``（fin_db.fetch_basic）
- 行情：腾讯 qfq 本地缓存；BaoStock 禁用
- 财务：profit cache（净利/营收/毛利率/净利率）

产出：``data/factors/expt_ipo_2y5_unlock_earn.{json,md}``
可选 ``--backtest`` / ``--insert``（INSERT max+1 ≥188，不覆盖）。

用法：
  .venv\\Scripts\\python.exe scripts/expt_ipo_2y5_unlock_earn.py
  .venv\\Scripts\\python.exe scripts/expt_ipo_2y5_unlock_earn.py --universe csi_core --backtest
  .venv\\Scripts\\python.exe scripts/expt_ipo_2y5_unlock_earn.py --backtest --insert
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    prepare_shared_panel,
    run_factor_pipeline,
)

OUT_STEM = ROOT / "data" / "factors" / "expt_ipo_2y5_unlock_earn"
CUT = "2024-08-01"
MIN_UI = 188
FACTOR_ID = "ipo_2y5_earn_break"
FACTOR_NAME = "IPO≈2.5年窗+业绩改善突破(代理解禁)"

# 研究窗口（年）
WINDOWS: Dict[str, Tuple[float, float]] = {
    "w0_1": (0.0, 1.0),
    "w1_2": (1.0, 2.0),
    "w2_3": (2.0, 3.0),
    "w2p25_2p75": (2.25, 2.75),
    "w2_2p5": (2.0, 2.5),
    "w2p5_3": (2.5, 3.0),
    "w3_4": (3.0, 4.0),
}
TARGET_KEYS = ("w2_3", "w2p25_2p75", "w2_2p5", "w2p5_3")
CTRL_KEYS = ("w0_1", "w1_2", "w3_4")
FWD_DAYS = (63, 126, 252)  # ≈3/6/12月


def _bs_disabled(*_a, **_k):
    raise RuntimeError("BaoStock disabled (qfq local-cache only)")


def _to_dec(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.where(x.abs() <= 5.0, x / 100.0)


def _parse_list_date(v: Any) -> Optional[pd.Timestamp]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.normalize()
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "nat"):
        return None
    if len(s) == 8 and s.isdigit():
        return pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
    try:
        return pd.Timestamp(s).normalize()
    except Exception:  # noqa: BLE001
        return None


def _year_weight(ts: pd.Timestamp) -> float:
    """近年加权：2018=1.0 … 2024+=2.0。"""
    y = int(ts.year)
    if y >= 2024:
        return 2.0
    if y >= 2022:
        return 1.6
    if y >= 2020:
        return 1.3
    return 1.0


def _wmean(vals: List[float], wts: List[float]) -> Optional[float]:
    if not vals:
        return None
    a = np.asarray(vals, dtype=float)
    w = np.asarray(wts, dtype=float)
    m = np.isfinite(a) & np.isfinite(w) & (w > 0)
    if not m.any():
        return None
    return float(np.average(a[m], weights=w[m]))


def _sharpe(rets: pd.Series) -> float:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or r.std(ddof=0) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=0) * math.sqrt(252))


def _max_dd(eq: pd.Series) -> float:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if e.empty:
        return float("nan")
    peak = e.cummax()
    return float((e / peak - 1.0).min())


def _slice_metrics(daily: pd.DataFrame, cut: str) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    late = d[d["date"] >= pd.Timestamp(cut)].copy()
    if late.empty or "equity" not in late.columns:
        return {"label": "late", "empty": True}
    eq0 = float(late["equity"].iloc[0])
    eq1 = float(late["equity"].iloc[-1])
    total_ret = eq1 / eq0 - 1.0 if eq0 else float("nan")
    day_ret = late["equity"].pct_change()
    return {
        "label": "late",
        "start": str(late["date"].iloc[0].date()),
        "end": str(late["date"].iloc[-1].date()),
        "bars": int(len(late)),
        "total_return": float(total_ret),
        "sharpe": _sharpe(day_ret.iloc[1:]),
        "max_drawdown": _max_dd(late["equity"]),
    }


def load_list_dates() -> Dict[str, pd.Timestamp]:
    basic = fin_db.fetch_basic()
    out: Dict[str, pd.Timestamp] = {}
    if basic is None or basic.empty:
        return out
    for _, r in basic.iterrows():
        code = r.get("code")
        ld = _parse_list_date(r.get("S_INFO_LISTDATE"))
        if code and ld is not None:
            out[str(code)] = ld
    return out


def _profit_path(cache: Path, code: str) -> Path:
    return cache / "profit" / f"{code.replace('.', '_')}.parquet"


def _daily_path(cache: Path, code: str) -> Path:
    return cache / "daily" / f"{code.replace('.', '_')}.parquet"


def _windows_of(age: float) -> List[str]:
    """返回所有命中窗口（允许重叠，便于 2.0–3.0 与 2.5± 子窗同时统计）。"""
    hits = []
    for k, (lo, hi) in WINDOWS.items():
        if lo <= age < hi:
            hits.append(k)
    return hits


def _cond_fwd_from_earn(
    codes: List[str],
    list_map: Dict[str, pd.Timestamp],
    cache: Path,
    earn_df: pd.DataFrame,
) -> Dict[str, Any]:
    """窗内披露日若业绩改善，则从下一交易日起算 3/6/12 月收益（条件事件）。"""
    if earn_df is None or earn_df.empty:
        return {}
    # 只取有改善标记的行
    improve_cols = ["yoy_np_pos", "gp_up", "npm_up"]
    rows_out: List[dict] = []
    # 按 code 分组加速
    by_code = {c: g for c, g in earn_df.groupby("code")}
    for i, code in enumerate(codes):
        if code not in by_code:
            continue
        ld = list_map.get(code)
        dp = _daily_path(cache, code)
        if ld is None or not dp.exists():
            continue
        try:
            px = pd.read_parquet(dp)
        except Exception:  # noqa: BLE001
            continue
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if len(px) < 30:
            continue
        dates = px["date"].values
        closes = px["close"].astype(float).values
        eg = by_code[code]
        for _, er in eg.iterrows():
            # 至少一项改善为 True
            flags = [er.get(c) for c in improve_cols]
            if not any(f is True for f in flags):
                continue
            pub = pd.Timestamp(er["pubDate"])
            ts = np.datetime64(pub)
            idx = int(np.searchsorted(dates, ts, side="left"))
            # 用公告日下一交易日（避免用到公告日收盘已知）
            if idx < len(dates) and pd.Timestamp(dates[idx]).normalize() == pub.normalize():
                idx += 1
            if idx >= len(px):
                continue
            c0 = closes[idx]
            if not np.isfinite(c0) or c0 <= 0:
                continue
            entry_ts = pd.Timestamp(dates[idx])
            row: Dict[str, Any] = {
                "code": code,
                "win": er["win"],
                "entry": str(entry_ts.date()),
                "wt": _year_weight(entry_ts),
                "late": int(entry_ts >= pd.Timestamp(CUT)),
            }
            for h in FWD_DAYS:
                j2 = idx + h
                if j2 < len(closes) and np.isfinite(closes[j2]) and closes[j2] > 0:
                    row[f"ret_{h}"] = float(closes[j2] / c0 - 1.0)
                else:
                    row[f"ret_{h}"] = None
            rows_out.append(row)
    df = pd.DataFrame(rows_out)
    out: Dict[str, Any] = {}
    if df.empty:
        return out
    for wk in WINDOWS:
        sub = df[df["win"] == wk]
        cell: Dict[str, Any] = {"n": int(len(sub))}
        for h in FWD_DAYS:
            col = f"ret_{h}"
            s = sub.dropna(subset=[col]) if col in sub.columns else sub.iloc[0:0]
            vals = s[col].astype(float).tolist() if len(s) else []
            wts = s["wt"].astype(float).tolist() if len(s) else []
            cell[col] = {
                "n": int(len(vals)),
                "mean": round(float(np.mean(vals)), 4) if vals else None,
                "wmean": round(float(_wmean(vals, wts) or float("nan")), 4) if vals else None,
                "hit": round(float(np.mean([v > 0 for v in vals])), 4) if vals else None,
            }
        out[wk] = cell
    return out


def _same_period_yoy(df: pd.DataFrame, col: str) -> pd.Series:
    """按报告期同季度同比：当期 / 去年同期 - 1。"""
    x = pd.to_numeric(df[col], errors="coerce")
    sd = pd.to_datetime(df["statDate"], errors="coerce")
    y = sd.dt.year
    q = sd.dt.month
    mp: Dict[Tuple[int, int], float] = {}
    for i in range(len(df)):
        yi, qi = y.iloc[i], q.iloc[i]
        if pd.isna(yi) or pd.isna(qi):
            continue
        vi = x.iloc[i]
        if pd.notna(vi):
            mp[(int(yi), int(qi))] = float(vi)
    out: List[float] = []
    for i in range(len(df)):
        yi, qi = y.iloc[i], q.iloc[i]
        cur = x.iloc[i]
        if pd.isna(yi) or pd.isna(qi) or pd.isna(cur):
            out.append(float("nan"))
            continue
        ly = mp.get((int(yi) - 1, int(qi)))
        if ly is None or not np.isfinite(ly) or abs(ly) < 1e-9:
            out.append(float("nan"))
        else:
            out.append(float(cur) / ly - 1.0)
    return pd.Series(out, index=df.index, dtype=float)

def analyze_universe(
    codes: List[str],
    list_map: Dict[str, pd.Timestamp],
    cache: Path,
) -> Dict[str, Any]:
    """季度改善频率 + 进入窗后前瞻收益。"""
    earn_rows: List[dict] = []
    fwd_rows: List[dict] = []
    n_list = 0
    n_profit = 0
    n_daily = 0

    for i, code in enumerate(codes):
        if (i + 1) % 100 == 0:
            print(f"[research] {i+1}/{len(codes)}", flush=True)
        ld = list_map.get(code)
        if ld is None:
            continue
        n_list += 1
        pp = _profit_path(cache, code)
        dp = _daily_path(cache, code)
        if not pp.exists() or not dp.exists():
            continue
        try:
            pr = pd.read_parquet(pp)
            px = pd.read_parquet(dp)
        except Exception:  # noqa: BLE001
            continue
        if pr.empty or px.empty:
            continue
        n_profit += 1
        n_daily += 1

        pr = pr.copy()
        pr["pubDate"] = pd.to_datetime(pr["pubDate"], errors="coerce")
        pr["statDate"] = pd.to_datetime(pr["statDate"], errors="coerce")
        pr = pr.dropna(subset=["pubDate", "statDate"]).sort_values("pubDate")
        # 去重同公告日
        pr = pr.drop_duplicates(subset=["pubDate"], keep="last").reset_index(drop=True)
        if len(pr) < 3:
            continue

        age = (pr["pubDate"] - ld).dt.days / 365.25
        pr["ipo_age"] = age

        np_ = pd.to_numeric(pr.get("netProfit"), errors="coerce")
        rev = pd.to_numeric(pr.get("MBRevenue"), errors="coerce")
        gp = _to_dec(pr["gpMargin"]) if "gpMargin" in pr.columns else pd.Series(np.nan, index=pr.index)
        npm = _to_dec(pr["npMargin"]) if "npMargin" in pr.columns else pd.Series(np.nan, index=pr.index)
        ros = np_ / rev.replace(0, np.nan)

        # 同比（同报告期）
        yoy_np = _same_period_yoy(pr, "netProfit") if "netProfit" in pr.columns else pd.Series(np.nan, index=pr.index)
        yoy_rev = _same_period_yoy(pr, "MBRevenue") if "MBRevenue" in pr.columns else pd.Series(np.nan, index=pr.index)

        # 环比/连续披露改善（利润率）；净利同比加速
        gp_up = (gp - gp.shift(1)) > 0.0
        npm_up = (npm - npm.shift(1)) > 0.0
        ros_up = (ros - ros.shift(1)) > 0.0
        yoy_np_acc = (yoy_np - yoy_np.shift(1)) > 0.0
        yoy_np_pos = yoy_np > 0.0
        yoy_rev_pos = yoy_rev > 0.0

        for j in range(len(pr)):
            wins = _windows_of(float(pr.at[j, "ipo_age"]))
            if not wins:
                continue
            pdj = pd.Timestamp(pr.at[j, "pubDate"])
            if pdj < pd.Timestamp("2016-01-01"):
                continue
            base = {
                "code": code,
                "pubDate": str(pdj.date()),
                "year": int(pdj.year),
                "ipo_age": float(pr.at[j, "ipo_age"]),
                "wt": _year_weight(pdj),
                "late": int(pdj >= pd.Timestamp(CUT)),
                "yoy_np_pos": bool(yoy_np_pos.iloc[j]) if pd.notna(yoy_np.iloc[j]) else None,
                "yoy_rev_pos": bool(yoy_rev_pos.iloc[j]) if pd.notna(yoy_rev.iloc[j]) else None,
                "yoy_np_acc": bool(yoy_np_acc.iloc[j]) if pd.notna(yoy_np.iloc[j]) and pd.notna(yoy_np.shift(1).iloc[j]) else None,
                "gp_up": bool(gp_up.iloc[j]) if pd.notna(gp.iloc[j]) and pd.notna(gp.shift(1).iloc[j]) else None,
                "npm_up": bool(npm_up.iloc[j]) if pd.notna(npm.iloc[j]) and pd.notna(npm.shift(1).iloc[j]) else None,
                "ros_up": bool(ros_up.iloc[j]) if pd.notna(ros.iloc[j]) and pd.notna(ros.shift(1).iloc[j]) else None,
            }
            for w in wins:
                earn_rows.append({**base, "win": w})

        # 前瞻收益：进入各窗的首个交易日
        px = px.copy()
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if len(px) < 30:
            continue
        closes = px["close"].astype(float).values
        dates = px["date"].values

        for wk, (lo, hi) in WINDOWS.items():
            enter = ld + pd.Timedelta(days=int(lo * 365.25))
            ts = np.datetime64(pd.Timestamp(enter))
            idx = int(np.searchsorted(dates, ts, side="left"))
            if idx >= len(px):
                continue
            # 还需仍在窗内（年龄 < hi）
            age_e = (pd.Timestamp(px.at[idx, "date"]) - ld).days / 365.25
            if age_e >= hi or age_e < lo - 0.05:
                continue
            entry_ts = pd.Timestamp(px.at[idx, "date"])
            row_f: Dict[str, Any] = {
                "code": code,
                "win": wk,
                "entry": str(entry_ts.date()),
                "year": int(entry_ts.year),
                "wt": _year_weight(entry_ts),
                "late": int(entry_ts >= pd.Timestamp(CUT)),
                "ipo_age": float(age_e),
            }
            c0 = closes[idx]
            if not np.isfinite(c0) or c0 <= 0:
                continue
            for h in FWD_DAYS:
                j2 = idx + h
                if j2 < len(closes) and np.isfinite(closes[j2]) and closes[j2] > 0:
                    row_f[f"ret_{h}"] = float(closes[j2] / c0 - 1.0)
                else:
                    row_f[f"ret_{h}"] = None
            fwd_rows.append(row_f)

    earn_df = pd.DataFrame(earn_rows)
    fwd_df = pd.DataFrame(fwd_rows)

    def _rate_table(df: pd.DataFrame, col: str, late_only: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        d0 = df if not late_only else df[df["late"] == 1]
        for wk in WINDOWS:
            sub = d0[d0["win"] == wk]
            vals = sub[col]
            mask = vals.notna() if hasattr(vals, "notna") else pd.Series([v is not None for v in vals])
            sub2 = sub.loc[mask]
            if sub2.empty:
                out[wk] = {"n": 0, "rate": None, "wrate": None}
                continue
            flags = sub2[col].astype(float).tolist()
            wts = sub2["wt"].astype(float).tolist()
            out[wk] = {
                "n": int(len(flags)),
                "rate": round(float(np.mean(flags)), 4),
                "wrate": round(float(_wmean(flags, wts) or float("nan")), 4),
            }
        return out

    earn_metrics = {
        "yoy_np_pos": _rate_table(earn_df, "yoy_np_pos"),
        "yoy_rev_pos": _rate_table(earn_df, "yoy_rev_pos"),
        "yoy_np_acc": _rate_table(earn_df, "yoy_np_acc"),
        "gp_up": _rate_table(earn_df, "gp_up"),
        "npm_up": _rate_table(earn_df, "npm_up"),
        "ros_up": _rate_table(earn_df, "ros_up"),
        "yoy_np_pos_late": _rate_table(earn_df, "yoy_np_pos", late_only=True),
        "gp_up_late": _rate_table(earn_df, "gp_up", late_only=True),
        "npm_up_late": _rate_table(earn_df, "npm_up", late_only=True),
    }

    def _fwd_table(late_only: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        d0 = fwd_df if not late_only else fwd_df[fwd_df["late"] == 1]
        for wk in WINDOWS:
            sub = d0[d0["win"] == wk]
            cell: Dict[str, Any] = {"n": int(len(sub))}
            for h in FWD_DAYS:
                col = f"ret_{h}"
                if sub.empty or col not in sub.columns:
                    cell[col] = {"n": 0, "mean": None, "wmean": None, "hit": None}
                    continue
                s = sub.dropna(subset=[col])
                vals = s[col].astype(float).tolist()
                wts = s["wt"].astype(float).tolist()
                cell[col] = {
                    "n": int(len(vals)),
                    "mean": round(float(np.mean(vals)), 4) if vals else None,
                    "wmean": round(float(_wmean(vals, wts) or float("nan")), 4) if vals else None,
                    "hit": round(float(np.mean([v > 0 for v in vals])), 4) if vals else None,
                }
            out[wk] = cell
        return out

    return {
        "coverage": {
            "n_codes": len(codes),
            "n_with_list_date": n_list,
            "n_with_profit_daily": n_profit,
            "n_earn_events": int(len(earn_df)),
            "n_fwd_events": int(len(fwd_df)),
            "list_date_source": "fin_db.中国A股与公司基本资料.S_INFO_LISTDATE",
            "unlock_data": None,
            "unlock_proxy_note": "无解禁明细；IPO年龄≈2.5年作代理，对应大股东常3年锁定期前的业绩/减持窗口",
        },
        "earn_improve": earn_metrics,
        "forward_returns": {"all": _fwd_table(False), "late": _fwd_table(True)},
        "cond_improve_forward": _cond_fwd_from_earn(codes, list_map, cache, earn_df),
    }


def score_windows(research: Dict[str, Any]) -> Dict[str, Any]:
    """综合打分：业绩改善频率 + 前瞻收益，挑最强窗。

    对照默认用成熟窗 w1_2 / w3_4（排除上市蜜月 w0_1，避免虚高对照）。
    """
    earn = research["earn_improve"]
    fwd = research["forward_returns"]["all"]
    cond = research.get("cond_improve_forward") or {}
    mature_ctrl = ("w1_2", "w3_4")
    scores: Dict[str, float] = {}
    detail: Dict[str, Any] = {}
    for wk in WINDOWS:
        parts = []
        for metric in ("yoy_np_pos", "gp_up", "npm_up", "yoy_np_acc"):
            cell = (earn.get(metric) or {}).get(wk) or {}
            r = cell.get("wrate")
            if r is not None:
                parts.append(float(r))
        earn_s = float(np.mean(parts)) if parts else 0.0
        fr = fwd.get(wk) or {}
        rets = []
        for h in (126, 252):
            cell = fr.get(f"ret_{h}") or {}
            m = cell.get("wmean")
            if m is not None:
                rets.append(float(m))
        ret_s = float(np.mean(rets)) if rets else 0.0
        # 条件改善后前瞻
        cr = cond.get(wk) or {}
        crets = []
        for h in (126, 252):
            cell = cr.get(f"ret_{h}") or {}
            m = cell.get("wmean")
            if m is not None:
                crets.append(float(m))
        cond_s = float(np.mean(crets)) if crets else None
        score = (earn_s - 0.5) * 2.0 + ret_s
        scores[wk] = round(score, 4)
        detail[wk] = {
            "earn_wrate_avg": round(earn_s, 4),
            "fwd_wmean_avg_6_12m": round(ret_s, 4),
            "cond_improve_fwd_6_12m": round(cond_s, 4) if cond_s is not None else None,
            "score": scores[wk],
            "is_target": wk in TARGET_KEYS,
            "is_ctrl": wk in CTRL_KEYS,
            "is_mature_ctrl": wk in mature_ctrl,
        }
    best = max(scores, key=scores.get) if scores else None
    best_target = max(TARGET_KEYS, key=lambda k: scores.get(k, -9e9))
    ctrl_earn = float(np.mean([detail[k]["earn_wrate_avg"] for k in mature_ctrl]))
    ctrl_ret = float(np.mean([detail[k]["fwd_wmean_avg_6_12m"] for k in mature_ctrl]))
    tgt = detail[best_target]
    # 相对成熟对照：改善不低于对照、收益优于对照
    supported = bool(
        tgt["earn_wrate_avg"] >= ctrl_earn - 0.005
        and tgt["fwd_wmean_avg_6_12m"] > ctrl_ret + 0.02
        and tgt["fwd_wmean_avg_6_12m"] > 0
    )
    soft_supported = bool(
        tgt["fwd_wmean_avg_6_12m"] >= min(detail[k]["fwd_wmean_avg_6_12m"] for k in mature_ctrl) - 0.01
        and tgt["earn_wrate_avg"] >= ctrl_earn - 0.02
        and (
            (tgt.get("cond_improve_fwd_6_12m") or -1)
            > max((detail[k].get("cond_improve_fwd_6_12m") or -1) for k in mature_ctrl)
        )
    )
    # 子窗中前瞻最强
    best_target_by_ret = max(TARGET_KEYS, key=lambda k: detail[k]["fwd_wmean_avg_6_12m"])
    return {
        "scores": scores,
        "detail": detail,
        "best_overall": best,
        "best_target": best_target,
        "best_target_by_ret": best_target_by_ret,
        "mature_ctrl": list(mature_ctrl),
        "ctrl_earn_avg": round(ctrl_earn, 4),
        "ctrl_ret_avg": round(ctrl_ret, 4),
        "supported": supported,
        "soft_supported": soft_supported,
        "note": "成熟对照=w1_2+w3_4（排除上市蜜月w0_1）",
    }


# ---------- 因子信号（实现见 signal_specs.signal_ipo_age_earn_break） ----------


def signal_ipo_age_earn_break(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    return sig.signal_ipo_age_earn_break(px, params)


def attach_list_dates(price_map: Dict[str, pd.DataFrame], list_map: Dict[str, pd.Timestamp]) -> Dict[str, pd.DataFrame]:
    out = {}
    for code, px in price_map.items():
        df = px.copy()
        ld = list_map.get(code)
        df["list_date"] = ld if ld is not None else pd.NaT
        out[code] = df
    return out


def default_bt_params(universe: str, age_lo: float, age_hi: float) -> Dict[str, Any]:
    return {
        "universe": universe,
        "exclude_st": True,
        "price_start": "2016-01-01",
        "price_end": "2026-07-30",
        "max_positions": 8,
        "commission_rate": 0.0001,
        "stamp_tax_sell": 0.001,
        "request_interval_sec": 0.35,
        "bench_code": "sh.000300",
        "hold_days": 50,
        "stop_loss": 0.12,
        "take_profit": 0.35,
        "break_days": 60,
        "funda_lag": 28,
        "require_ma20": True,
        "margin_improve": 0.003,
        "np_improve": 0.003,
        "ipo_age_lo": age_lo,
        "ipo_age_hi": age_hi,
        "position_logic": FACTOR_ID,
        "note": FACTOR_NAME,
    }


def run_backtests(
    universe: str,
    list_map: Dict[str, pd.Timestamp],
    best_win: str,
    *,
    also_hs300: bool = True,
) -> Dict[str, Any]:
    lo, hi = WINDOWS[best_win]
    results: Dict[str, Any] = {}
    universes = [universe]
    if also_hs300 and universe != "hs300":
        universes.append("hs300")

    for uni in universes:
        params = default_bt_params(uni, lo, hi)
        print(f"[bt] panel {uni} profit=True", flush=True)
        # monkeypatch baostock paths if any
        kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
        panel = prepare_shared_panel(params, need_profit=True, need_growth=False)
        panel = attach_list_dates(panel, list_map)
        fid = f"{FACTOR_ID}_{uni}" if uni != universe else FACTOR_ID
        # 主宇宙用正式 id；对照宇宙加后缀只写报告不占正式名
        if uni != universe:
            params = {**params, "universe": uni, "position_logic": fid}
        title = f"{FACTOR_NAME} [{lo},{hi}) {uni}"
        summary = run_factor_pipeline(
            fid,
            title,
            signal_ipo_age_earn_break,
            params,
            need_profit=False,
            price_map=panel,
            start="2018-01-01",
        )
        daily_path = ROOT / "data" / "factors" / f"{fid}_backtest.csv"
        late = {}
        if daily_path.exists():
            daily = pd.read_csv(daily_path)
            late = _slice_metrics(daily, CUT)
        results[uni] = {
            "factor_id": fid,
            "window": {"key": best_win, "lo": lo, "hi": hi},
            "summary": {
                k: summary.get(k)
                for k in (
                    "total_return",
                    "annual_return",
                    "sharpe",
                    "max_drawdown",
                    "n_trades",
                    "win_rate",
                    "avg_position",
                )
                if k in summary or True
            },
            "summary_raw": {k: v for k, v in summary.items() if not str(k).startswith("_") and not isinstance(v, (pd.DataFrame, pd.Series))},
            "late": late,
        }
        # 精简 summary
        sr = results[uni]["summary_raw"]
        results[uni]["summary"] = {
            "total_return": sr.get("total_return"),
            "annual_return": sr.get("annual_return"),
            "sharpe": sr.get("sharpe"),
            "max_drawdown": sr.get("max_drawdown"),
            "n_trades": sr.get("n_trades") or sr.get("trades"),
            "win_rate": sr.get("win_rate"),
            "avg_position": sr.get("avg_position"),
        }
        del results[uni]["summary_raw"]
    return results


def try_insert(bt: Dict[str, Any], best_win: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """仅当回测像样时 INSERT max+1（≥188）。"""
    from datetime import timedelta

    from pymongo import MongoClient

    from app.core.config import settings
    from scripts.mine_factor_dedup import DedupIndex, build_inventory, fingerprint

    uni = str(params.get("universe") or "hs300")
    main = bt.get(uni) or next(iter(bt.values()), {})
    sharpe = (main.get("summary") or {}).get("sharpe")
    late_sh = (main.get("late") or {}).get("sharpe")
    ok_metric = (sharpe is not None and float(sharpe) >= 0.35) or (
        late_sh is not None and float(late_sh) >= 0.8
    )
    if not ok_metric:
        return {"inserted": False, "reason": f"metrics weak sharpe={sharpe} late={late_sh}"}

    fp = fingerprint(signal_ipo_age_earn_break, uni, params)
    inv = build_inventory()
    dedup = DedupIndex(inv)
    skip, reason, hit = dedup.check(signal_ipo_age_earn_break, uni, {**params, "universe": uni})
    if skip:
        # 允许「刚写入 FACTOR_IMPL、尚未入 Mongo」的自命中
        same = (
            isinstance(hit, dict)
            and hit.get("factor_id") == FACTOR_ID
            and hit.get("source") in ("factor_impl", "session")
        )
        if not same:
            return {"inserted": False, "reason": f"dedup:{reason}", "hit": hit, "fp": fp}

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    targets = list(
        dict.fromkeys(
            [
                settings.MONGO_DB,
                "lahm",
                "lahm_v0_gaozx-laptop-rren219t",
                "lahm_v0_gaozx-desktop-v0c4gt8",
            ]
        )
    )
    targets = [t for t in targets if t and t in client.list_database_names()]
    results = []
    for dbn in targets:
        db = client[dbn]
        docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))
        docs.sort(key=lambda x: (str(x.get("created_at") or ""), str(x.get("factor_id") or "")))
        max_ui = len(docs)
        next_ui = max_ui + 1
        if next_ui < MIN_UI:
            results.append({"db": dbn, "abort": f"next_ui={next_ui}<{MIN_UI}"})
            continue
        if db.factors.find_one({"factor_id": FACTOR_ID}, {"_id": 1}):
            results.append({"db": dbn, "abort": f"exists {FACTOR_ID}"})
            continue
        mx_ca = None
        for d in docs:
            ca = d.get("created_at")
            if ca is not None and (mx_ca is None or ca > mx_ca):
                mx_ca = ca
        if isinstance(mx_ca, datetime):
            ca = mx_ca + timedelta(minutes=1)
        else:
            ca = datetime.now()
        lo, hi = WINDOWS[best_win]
        doc = {
            "factor_id": FACTOR_ID,
            "name": FACTOR_NAME,
            "created_at": ca,
            "updated_at": datetime.now(),
            "params": params,
            "tags": [
                "IPO",
                "解禁代理",
                "业绩改善",
                "突破",
                "qfq",
                f"age_{lo}_{hi}",
                "expt_ipo_2y5",
            ],
            "description": (
                f"IPO年龄∈[{lo},{hi})年（大股东约3年锁定期前的代理窗）+ "
                "净利/毛利率/净利率改善确认 + 突破确认。无解禁明细。"
            ),
            "signal": "signal_ipo_age_earn_break",
            "fingerprint": fp,
            "ui_planned": next_ui,
            "source_expt": "expt_ipo_2y5_unlock_earn",
            "backtest_summary": main.get("summary"),
            "late_summary": main.get("late"),
        }
        # 确保 artifacts 用正式 factor_id
        src_csv = ROOT / "data" / "factors" / f"{FACTOR_ID}_backtest.csv"
        if not src_csv.exists():
            # 可能写在带宇宙后缀
            alt = ROOT / "data" / "factors" / f"{main.get('factor_id')}_backtest.csv"
            if alt.exists() and main.get("factor_id") != FACTOR_ID:
                for suf in ("_backtest.csv", "_backtest.json", "_trade_history.csv", "_equity_curve.png"):
                    a = ROOT / "data" / "factors" / f"{main.get('factor_id')}{suf}"
                    b = ROOT / "data" / "factors" / f"{FACTOR_ID}{suf}"
                    if a.exists() and not b.exists():
                        b.write_bytes(a.read_bytes())
        ins = db.factors.insert_one(doc)
        docs2 = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))
        docs2.sort(key=lambda x: (str(x.get("created_at") or ""), str(x.get("factor_id") or "")))
        seq = next((i for i, x in enumerate(docs2, 1) if x.get("factor_id") == FACTOR_ID), None)
        results.append({"db": dbn, "inserted_id": str(ins.inserted_id), "ui": seq, "planned": next_ui})
        print(f"[mongo] INSERT {dbn}.{FACTOR_ID} UI#{seq} (planned {next_ui})", flush=True)

    # 注册到 FACTOR_IMPL（运行时）；持久化靠 Mongo + signal 名
    return {"inserted": True, "fp": fp, "dbs": results}


def write_report(payload: Dict[str, Any]) -> None:
    OUT_STEM.parent.mkdir(parents=True, exist_ok=True)
    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    r = payload.get("research") or {}
    sc = payload.get("score") or {}
    cov = r.get("coverage") or {}
    lines = [
        "# IPO≈2.5年解禁窗口 × 业绩释放 — 实验报告",
        "",
        f"- 生成时间：{payload.get('generated_at')}",
        f"- 宇宙：`{payload.get('universe')}`",
        f"- 上市日来源：{cov.get('list_date_source')}",
        f"- 解禁数据：无（代理说明：{cov.get('unlock_proxy_note')}）",
        f"- 覆盖：codes={cov.get('n_codes')} list_date={cov.get('n_with_list_date')} "
        f"earn_events={cov.get('n_earn_events')} fwd_events={cov.get('n_fwd_events')}",
        "",
        "## 结论",
        "",
        f"- **规律是否成立**：{'倾向成立' if sc.get('supported') else ('弱支撑' if sc.get('soft_supported') else '证据不足')}"
        f"（supported={sc.get('supported')}, soft={sc.get('soft_supported')}）",
        f"- **最有效目标窗**：`{sc.get('best_target')}`（综合分）；按前瞻最强=`{sc.get('best_target_by_ret')}`；全局最高分窗=`{sc.get('best_overall')}`",
        f"- 成熟对照({sc.get('mature_ctrl')}) 改善均值={sc.get('ctrl_earn_avg')}；前瞻均值={sc.get('ctrl_ret_avg')}；{sc.get('note')}",
        "",
        "## 窗口综合分",
        "",
        "| 窗口 | 改善加权率 | 6/12月前瞻加权均收益 | 综合分 | 类型 |",
        "|---|---:|---:|---:|---|",
    ]
    for wk, d in (sc.get("detail") or {}).items():
        kind = "目标" if d.get("is_target") else ("对照" if d.get("is_ctrl") else "其他")
        lines.append(
            f"| {wk} | {d.get('earn_wrate_avg')} | {d.get('fwd_wmean_avg_6_12m')} | {d.get('score')} | {kind} |"
        )

    lines += ["", "## 业绩改善频率（近年加权 wrate）", ""]
    earn = r.get("earn_improve") or {}
    for metric in ("yoy_np_pos", "yoy_rev_pos", "yoy_np_acc", "gp_up", "npm_up", "ros_up"):
        lines.append(f"### {metric}")
        lines.append("")
        lines.append("| 窗口 | n | rate | wrate |")
        lines.append("|---|---:|---:|---:|")
        for wk, cell in (earn.get(metric) or {}).items():
            lines.append(f"| {wk} | {cell.get('n')} | {cell.get('rate')} | {cell.get('wrate')} |")
        lines.append("")

    lines += ["## 进入窗后前瞻收益（加权均值）", ""]
    fwd = (r.get("forward_returns") or {}).get("all") or {}
    lines.append("| 窗口 | n | ret_63 | ret_126 | ret_252 | hit_126 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for wk, cell in fwd.items():
        r63 = (cell.get("ret_63") or {}).get("wmean")
        r126 = (cell.get("ret_126") or {}).get("wmean")
        r252 = (cell.get("ret_252") or {}).get("wmean")
        hit = (cell.get("ret_126") or {}).get("hit")
        lines.append(f"| {wk} | {cell.get('n')} | {r63} | {r126} | {r252} | {hit} |")

    cond = r.get("cond_improve_forward") or {}
    if cond:
        lines += ["", "## 窗内业绩改善后前瞻（条件事件）", ""]
        lines.append("| 窗口 | n | ret_63 | ret_126 | ret_252 | hit_126 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for wk, cell in cond.items():
            r63 = (cell.get("ret_63") or {}).get("wmean")
            r126 = (cell.get("ret_126") or {}).get("wmean")
            r252 = (cell.get("ret_252") or {}).get("wmean")
            hit = (cell.get("ret_126") or {}).get("hit")
            lines.append(f"| {wk} | {cell.get('n')} | {r63} | {r126} | {r252} | {hit} |")

    bt = payload.get("backtest") or {}
    if bt:
        lines += ["", "## 因子回测", ""]
        for uni, cell in bt.items():
            s = cell.get("summary") or {}
            late = cell.get("late") or {}
            lines.append(f"### {uni} / `{cell.get('factor_id')}`")
            lines.append("")
            lines.append(
                f"- 窗={cell.get('window')} 全样本 sharpe={s.get('sharpe')} "
                f"ann={s.get('annual_return')} mdd={s.get('max_drawdown')} trades={s.get('n_trades')}"
            )
            lines.append(
                f"- 近2年({CUT}+) sharpe={late.get('sharpe')} ret={late.get('total_return')} "
                f"mdd={late.get('max_drawdown')}"
            )
            lines.append("")

    ins = payload.get("insert")
    if ins:
        lines += ["## Mongo INSERT", "", f"```json\n{json.dumps(ins, ensure_ascii=False, indent=2)}\n```", ""]

    lines += [
        "",
        "## 方法备注",
        "",
        "- 同比：同报告期（Q1/Q2/Q3/Q4）净利/营收 YoY",
        "- 环比：连续披露期毛利率/净利率差分（与因子库 `_funda_event` 惯例一致）",
        "- 前瞻：上市年龄刚进入窗口下沿的首个交易日买入，持有 63/126/252 交易日",
        "- 近年加权：2018=1.0 / 2020=1.3 / 2022=1.6 / 2024+=2.0",
        "",
    ]
    OUT_STEM.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {OUT_STEM}.json / .md", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="csi_core", help="hs300 | csi_core")
    ap.add_argument("--backtest", action="store_true", help="规律有支撑时跑因子回测")
    ap.add_argument("--force-backtest", action="store_true", help="即使证据弱也回测")
    ap.add_argument("--insert", action="store_true", help="回测达标则 INSERT max+1")
    ap.add_argument("--limit", type=int, default=0, help="调试限票数")
    args = ap.parse_args()

    t0 = time.time()
    # 禁用 baostock
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore

    cache = kit.shared_cache_dir()
    list_map = load_list_dates()
    print(f"[list_date] n={len(list_map)} source=fin_db.S_INFO_LISTDATE", flush=True)

    limiter = kit.RateLimiter(0.01)
    codes = kit.fetch_universe_codes(args.universe, limiter, cache)
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]
    print(f"[universe] {args.universe} n={len(codes)}", flush=True)

    research = analyze_universe(codes, list_map, cache)
    score = score_windows(research)
    print(
        f"[score] best_target={score['best_target']} supported={score['supported']} "
        f"soft={score['soft_supported']} detail={score['detail'].get(score['best_target'])}",
        flush=True,
    )

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "universe": args.universe,
        "windows": {k: {"lo": v[0], "hi": v[1]} for k, v in WINDOWS.items()},
        "research": research,
        "score": score,
        "hypothesis": {
            "claim": "IPO后约2.5年窗口业绩释放；对应大股东常3年锁定期前",
            "proxy": "ipo_age≈2.5y（无解禁明细）",
        },
    }

    do_bt = args.force_backtest or (
        args.backtest and (score["supported"] or score["soft_supported"])
    )
    if args.backtest and not do_bt:
        do_bt = True
        payload["backtest_note"] = "证据偏弱仍按 --backtest 试跑"
    if do_bt or args.force_backtest:
        # 优先用前瞻最强目标窗；若与综合分一致则用综合
        best = score.get("best_target_by_ret") or score.get("best_target") or "w2_3"
        print(f"[bt] start window={best}", flush=True)
        bt = run_backtests(args.universe, list_map, best, also_hs300=True)
        payload["backtest"] = bt
        lo, hi = WINDOWS[best]
        params = default_bt_params(args.universe, lo, hi)
        if args.insert:
            payload["insert"] = try_insert(bt, best, params)
        else:
            payload["insert"] = {"inserted": False, "reason": "no --insert flag"}
    else:
        payload["backtest"] = None
        payload["insert"] = {"inserted": False, "reason": "skip: pattern not supported / no --backtest"}

    payload["elapsed_sec"] = round(time.time() - t0, 1)
    write_report(payload)
    print(json.dumps({"score": score, "elapsed": payload["elapsed_sec"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
