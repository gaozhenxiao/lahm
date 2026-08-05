"""因子 #188 ``ipo_2y5_earn_break`` 大幅度参数优化。

目标：近年加权（2024+ 权重大）+ 近2年（2024-08+）表现；全样本不能崩到不可用。
宇宙：主搜 csi_core，对照试 hs300；腾讯 qfq；BaoStock 禁用。
动作：更新同一 factor_id=#188（不 commit / 不 push）。

用法：
  .venv\\Scripts\\python.exe scripts/opt_ipo_2y5_earn_break_188.py
  .venv\\Scripts\\python.exe scripts/opt_ipo_2y5_earn_break_188.py --phase all --apply
  .venv\\Scripts\\python.exe scripts/opt_ipo_2y5_earn_break_188.py --apply --from-report
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    build_legs_from_entries,
    collect_legs,
    prepare_shared_panel,
    run_factor_pipeline,
)

FACTOR_ID = "ipo_2y5_earn_break"
FACTOR_UI = 188
FACTOR_NAME = "IPO≈2.5年窗+业绩改善突破(代理解禁·csi_core)"
OUT_DIR = ROOT / "data" / "factors" / "opt_ipo_2y5_earn_break_188"
OUT_STEM = OUT_DIR / "opt_report"
CUT = "2024-08-01"
START = "2018-01-01"
MIN_ACCEPTED = 25
SEED = 18825

SEGMENTS = (
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_now", "2024-01-01", None, 0.50),
)

BASE_PARAMS: Dict[str, Any] = {
    "universe": "csi_core",
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
    "ipo_age_lo": 2.5,
    "ipo_age_hi": 3.0,
    "use_break": True,
    "require_rev": False,
    "position_logic": FACTOR_ID,
    "note": FACTOR_NAME,
}

SIGNAL_KEYS = (
    "ipo_age_lo",
    "ipo_age_hi",
    "margin_improve",
    "np_improve",
    "funda_lag",
    "break_days",
    "use_break",
    "require_ma20",
    "require_rev",
    "np_min",
    "net_profit_min",
    "brk_soft",
)


def _bs_disabled(*_a, **_k):
    raise RuntimeError("BaoStock disabled (qfq local-cache only)")


def _parse_list_date(v: Any) -> Optional[pd.Timestamp]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
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


def attach_list_dates(
    price_map: Dict[str, pd.DataFrame], list_map: Dict[str, pd.Timestamp]
) -> Dict[str, pd.DataFrame]:
    out = {}
    for code, px in price_map.items():
        df = px.copy()
        ld = list_map.get(code)
        df["list_date"] = ld if ld is not None else pd.NaT
        out[code] = df
    return out


def _sharpe(rets: pd.Series) -> Optional[float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or r.std(ddof=0) == 0:
        return None
    return float(r.mean() / r.std(ddof=0) * math.sqrt(252))


def _max_dd(eq: pd.Series) -> Optional[float]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if e.empty:
        return None
    peak = e.cummax()
    return float((e / peak - 1.0).min())


def _slice_metrics(daily: pd.DataFrame, start: str, end: Optional[str]) -> Dict[str, Any]:
    if daily is None or daily.empty or "equity" not in daily.columns:
        return {"empty": True}
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    mask = d["date"] >= pd.Timestamp(start)
    if end:
        mask &= d["date"] <= pd.Timestamp(end)
    part = d.loc[mask]
    if len(part) < 5:
        return {"empty": True, "bars": int(len(part))}
    eq0 = float(part["equity"].iloc[0])
    eq1 = float(part["equity"].iloc[-1])
    total_ret = eq1 / eq0 - 1.0 if eq0 else None
    day_ret = part["equity"].pct_change()
    return {
        "empty": False,
        "start": str(part["date"].iloc[0].date()),
        "end": str(part["date"].iloc[-1].date()),
        "bars": int(len(part)),
        "total_return": float(total_ret) if total_ret is not None else None,
        "sharpe": _sharpe(day_ret.iloc[1:]),
        "max_drawdown": _max_dd(part["equity"]),
    }


def _time_weight_score(daily: pd.DataFrame) -> Dict[str, Any]:
    segs: Dict[str, Any] = {}
    score_num = 0.0
    score_den = 0.0
    for label, s, e, w in SEGMENTS:
        m = _slice_metrics(daily, s, e)
        segs[label] = {**m, "weight": w}
        sh = m.get("sharpe")
        if sh is not None and not m.get("empty"):
            score_num += w * float(sh)
            score_den += w
    tw_sharpe = score_num / score_den if score_den > 0 else None
    recent2y = _slice_metrics(daily, CUT, None)
    early = segs.get("y2018_2021") or {}
    late = segs.get("y2024_now") or {}

    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    early_sh = early.get("sharpe")
    full_sh = None
    if "equity" in daily.columns and len(daily) > 5:
        full_sh = _sharpe(daily["equity"].pct_change().iloc[1:])

    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")
    if full_sh is not None and float(full_sh) < 0.05:
        flags.append("full_near_zero")
    if full_sh is not None and float(full_sh) < -0.1:
        flags.append("full_crash")

    penalty = 0.0
    if "early_inflated_recent_poor" in flags:
        penalty += 0.50
    elif "recent2y_big_loss" in flags:
        penalty += 0.35
    elif "recent2y_neg_sharpe" in flags:
        penalty += 0.20
    if "full_crash" in flags:
        penalty += 0.40
    elif "full_near_zero" in flags:
        penalty += 0.15

    # 近2年额外加权到主分
    r2_bonus = 0.0
    if r2_sh is not None:
        r2_bonus = 0.25 * float(r2_sh)

    tw_adj = None
    if tw_sharpe is not None:
        tw_adj = float(tw_sharpe) + r2_bonus - penalty

    return {
        "segments": segs,
        "tw_sharpe": tw_sharpe,
        "tw_score": tw_adj,
        "tw_penalty": penalty,
        "r2_bonus": r2_bonus,
        "recent2y": recent2y,
        "late_sharpe": late.get("sharpe"),
        "late_return": late.get("total_return"),
        "early_sharpe": early.get("sharpe"),
        "full_sharpe_from_eq": full_sh,
        "tw_flags": flags,
    }


def _sig_key(p: Dict[str, Any]) -> str:
    parts = []
    for k in SIGNAL_KEYS:
        v = p.get(k)
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return "|".join(parts)


def _cfg_id(p: Dict[str, Any], prefix: str = "") -> str:
    lo = p.get("ipo_age_lo")
    hi = p.get("ipo_age_hi")
    brk = "nobrk" if not p.get("use_break", True) or int(p.get("break_days") or 0) <= 0 else f"b{p.get('break_days')}"
    bits = [
        f"a{lo}_{hi}",
        f"m{p.get('margin_improve')}",
        f"n{p.get('np_improve')}",
        f"lag{p.get('funda_lag')}",
        brk,
        f"h{p.get('hold_days')}",
        f"sl{p.get('stop_loss')}",
        f"tp{p.get('take_profit')}",
        f"mp{p.get('max_positions')}",
    ]
    if p.get("require_rev"):
        bits.append("rev")
    if p.get("np_min") is not None:
        bits.append(f"npm{p.get('np_min')}")
    if p.get("trail_stop") is not None:
        bits.append(f"tr{p.get('trail_activate')}_{p.get('trail_stop')}")
    if p.get("max_name_weight") is not None:
        bits.append(f"conc{p.get('max_name_weight')}")
    if not p.get("require_ma20", True):
        bits.append("noma")
    return (prefix + "__" if prefix else "") + "_".join(str(x) for x in bits)


def build_signal_grid() -> List[Dict[str, Any]]:
    """粗网格：IPO 窗 × 财务 × 突破。出场固定基线。约 90–120 组。"""
    windows = [
        (2.0, 3.0),
        (2.5, 3.0),
        (2.25, 2.75),
        (2.3, 2.7),
        (2.4, 2.8),
        (2.2, 2.8),
        (2.5, 2.9),
        (2.0, 2.5),
        (2.35, 2.85),
        (2.6, 3.0),
    ]
    margin_np = [
        (0.0, 0.0),
        (0.002, 0.002),
        (0.003, 0.003),
        (0.005, 0.005),
        (0.008, 0.005),
    ]
    lags = [21, 28, 35, 42]
    breaks = [
        {"use_break": True, "break_days": 40, "require_ma20": True},
        {"use_break": True, "break_days": 60, "require_ma20": True},
        {"use_break": True, "break_days": 80, "require_ma20": True},
        {"use_break": True, "break_days": 60, "require_ma20": False},
        {"use_break": False, "break_days": 0, "require_ma20": True},
    ]
    np_mins: List[Optional[float]] = [None, 0.06, 0.10]

    cfgs: List[Dict[str, Any]] = []
    # 1) 窗扫描（基线财务/突破）
    for lo, hi in windows:
        p = deepcopy(BASE_PARAMS)
        p.update({"ipo_age_lo": lo, "ipo_age_hi": hi})
        cfgs.append(p)
    # 2) 基线窗上：财务 × lag × 突破（无 rev）；lag 取主档
    for (mi, ni), lag, brk in itertools.product(margin_np, [21, 28, 35], breaks):
        p = deepcopy(BASE_PARAMS)
        p.update({"margin_improve": mi, "np_improve": ni, "funda_lag": lag, **brk})
        cfgs.append(p)
    # 3) 关键组合：require_rev / np_min / 窗交叉（精简）
    for lo, hi in [(2.5, 3.0), (2.25, 2.75), (2.3, 2.7), (2.0, 3.0)]:
        for rev, npm, brk in itertools.product(
            [False, True], [None, 0.10], breaks[:3]
        ):
            p = deepcopy(BASE_PARAMS)
            p.update(
                {
                    "ipo_age_lo": lo,
                    "ipo_age_hi": hi,
                    "require_rev": rev,
                    "np_min": npm,
                    **brk,
                }
            )
            cfgs.append(p)
    # 4) 随机大幅扰动
    rng = random.Random(SEED)
    for _ in range(40):
        lo, hi = rng.choice(windows)
        mi, ni = rng.choice(margin_np + [(0.004, 0.004), (0.006, 0.003)])
        p = deepcopy(BASE_PARAMS)
        p.update(
            {
                "ipo_age_lo": lo,
                "ipo_age_hi": hi,
                "margin_improve": mi,
                "np_improve": ni,
                "funda_lag": rng.choice(lags + [25, 30]),
                **rng.choice(
                    breaks
                    + [{"use_break": True, "break_days": 100, "require_ma20": True}]
                ),
                "require_rev": rng.choice([False, False, True]),
                "np_min": rng.choice(np_mins),
                "net_profit_min": rng.choice([None, None, 5e8]),
            }
        )
        cfgs.append(p)
    seen = set()
    uniq = []
    for p in cfgs:
        k = _sig_key(p)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def build_exit_grid(base_sig: Dict[str, Any]) -> List[Dict[str, Any]]:
    """出场细化：约 45–55 组/信号。"""
    holds = [30, 40, 50, 60, 80]
    sls = [0.08, 0.10, 0.12, 0.15]
    tps: List[Optional[float]] = [None, 0.25, 0.35, 0.45]
    max_pos = [5, 8, 10, 12]
    trails = [
        {},
        {"trail_activate": 0.15, "trail_stop": 0.08},
        {"trail_activate": 0.18, "trail_stop": 0.09},
        {"trail_activate": 0.20, "trail_stop": 0.10},
    ]
    concs = [
        {},
        {"max_name_weight": 0.25},
        {"max_name_weight": 0.20, "max_industry_names": 2},
    ]
    out: List[Dict[str, Any]] = []
    # hold × tp（sl=0.12）
    for h, tp in itertools.product(holds, tps):
        p = deepcopy(base_sig)
        p.update({"hold_days": h, "stop_loss": 0.12, "take_profit": tp, "max_positions": 8})
        out.append(p)
    # sl 扫描（hold=50, tp=0.35）
    for sl in sls:
        p = deepcopy(base_sig)
        p.update({"hold_days": 50, "stop_loss": sl, "take_profit": 0.35, "max_positions": 8})
        out.append(p)
    # max_positions
    for mp in max_pos:
        p = deepcopy(base_sig)
        p["max_positions"] = mp
        out.append(p)
    # trail / conc 随机
    rng = random.Random(SEED + 7)
    for _ in range(20):
        p = deepcopy(base_sig)
        p.update(
            {
                "hold_days": rng.choice(holds),
                "stop_loss": rng.choice(sls),
                "take_profit": rng.choice(tps),
                "max_positions": rng.choice(max_pos),
                **rng.choice(trails),
                **rng.choice(concs),
            }
        )
        out.append(p)
    seen = set()
    uniq = []
    for p in out:
        k = json.dumps(
            {
                kk: p.get(kk)
                for kk in list(SIGNAL_KEYS)
                + [
                    "hold_days",
                    "stop_loss",
                    "take_profit",
                    "max_positions",
                    "trail_activate",
                    "trail_stop",
                    "max_name_weight",
                    "max_industry_names",
                ]
            },
            sort_keys=True,
            default=str,
        )
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq

def _entries_cache(
    panel: Dict[str, pd.DataFrame], sig_params: Dict[str, Any]
) -> Dict[str, pd.DataFrame]:
    """按信号参数缓存各股 entries。"""
    cache: Dict[str, pd.DataFrame] = {}
    for code, px in panel.items():
        try:
            e = sig.signal_ipo_age_earn_break(px, sig_params)
            if e is None or e.empty:
                continue
            ee = e.copy()
            ee["code"] = code
            cache[code] = ee
        except Exception:  # noqa: BLE001
            continue
    return cache


def _legs_from_entries_cache(
    entries_by_code: Dict[str, pd.DataFrame],
    panel: Dict[str, pd.DataFrame],
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
    for code, entries in entries_by_code.items():
        px = panel.get(code)
        if px is None or entries is None or entries.empty:
            continue
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
    if not all_legs:
        return pd.DataFrame()
    legs = pd.DataFrame(all_legs)
    legs = legs.sort_values(["code", "entry_date"]).drop_duplicates(
        ["code", "entry_date"], keep="first"
    )
    return legs.reset_index(drop=True)


def eval_params(
    cfg_id: str,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    *,
    entries_by_code: Optional[Dict[str, pd.DataFrame]] = None,
    family: str = "grid",
) -> Dict[str, Any]:
    t0 = time.time()
    p = dict(params)
    p["_cache_dir"] = str(kit.shared_cache_dir())
    p["position_logic"] = FACTOR_ID
    if entries_by_code is not None:
        legs = _legs_from_entries_cache(entries_by_code, panel, p)
    else:
        legs = collect_legs(panel, sig.signal_ipo_age_earn_break, p)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=p, bench_daily=bench, start=START
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    tw = (
        _time_weight_score(daily)
        if isinstance(daily, pd.DataFrame) and not daily.empty
        else {
            "tw_sharpe": None,
            "tw_score": None,
            "tw_penalty": 0.0,
            "recent2y": {"empty": True},
            "tw_flags": ["no_daily"],
            "segments": {},
        }
    )
    n_acc = summary.get("n_legs_accepted", 0 if accepted is None else len(accepted))
    flags = list(tw.get("tw_flags") or [])
    if int(n_acc or 0) < MIN_ACCEPTED:
        flags.append(f"few_legs<{MIN_ACCEPTED}")
    rejected = "early_inflated_recent_poor" in flags or "full_crash" in flags
    out = {
        "cfg_id": cfg_id,
        "family": family,
        "universe": p.get("universe"),
        "params": {k: v for k, v in p.items() if not str(k).startswith("_")},
        "sharpe": summary.get("sharpe"),
        "total_return": summary.get("total_return"),
        "annual_return": summary.get("annual_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "n_legs_raw": summary.get("n_legs_raw", len(legs) if legs is not None else 0),
        "n_legs_accepted": n_acc,
        "avg_position": summary.get("avg_position"),
        "error": summary.get("error"),
        "elapsed_sec": round(time.time() - t0, 2),
        "tw_sharpe": tw.get("tw_sharpe"),
        "tw_score": tw.get("tw_score"),
        "tw_penalty": tw.get("tw_penalty"),
        "r2_bonus": tw.get("r2_bonus"),
        "recent2y_sharpe": (tw.get("recent2y") or {}).get("sharpe"),
        "recent2y_return": (tw.get("recent2y") or {}).get("total_return"),
        "recent2y_max_dd": (tw.get("recent2y") or {}).get("max_drawdown"),
        "late_sharpe": tw.get("late_sharpe"),
        "late_return": tw.get("late_return"),
        "early_sharpe": tw.get("early_sharpe"),
        "segments": tw.get("segments"),
        "flags": flags,
        "rejected": rejected,
        "ok": summary.get("error") is None and summary.get("sharpe") is not None,
    }
    return out


def _rank_key(r: Dict[str, Any]) -> Tuple:
    if r.get("rejected") or not r.get("ok"):
        return (-999.0, -999.0, -999.0)
    # 全样本崩到不可用：sharpe < 0 大幅降权
    full_sh = float(r.get("sharpe") if r.get("sharpe") is not None else -9)
    if full_sh < 0.10:
        return (-500.0 + full_sh, float(r.get("tw_score") or -999), float(r.get("recent2y_sharpe") or -999))
    return (
        float(r.get("tw_score") if r.get("tw_score") is not None else -999),
        float(r.get("recent2y_sharpe") if r.get("recent2y_sharpe") is not None else -999),
        float(r.get("recent2y_return") if r.get("recent2y_return") is not None else -999),
    )


def _mongo_targets():
    uri = settings.MONGO_URI or "mongodb://admin:lahm123@localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
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
    return [t for t in targets if t and t in client.list_database_names()], client


def update_factor_registry(best_params: Dict[str, Any], desc: str) -> None:
    """就地改 FACTOR_IMPL 中 #188 的 params/description。"""
    path = ROOT / "app" / "services" / "factors" / "factor_registry.py"
    text = path.read_text(encoding="utf-8")
    start = text.find('    "ipo_2y5_earn_break": {')
    if start < 0:
        raise RuntimeError("ipo_2y5_earn_break block not found in factor_registry")
    brace = 0
    i = start
    j = None
    while i < len(text):
        ch = text[i]
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
            if brace == 0:
                j = i + 1
                if j < len(text) and text[j] == ",":
                    j += 1
                break
        i += 1
    if j is None:
        raise RuntimeError("failed to parse ipo_2y5_earn_break block")

    lo = best_params.get("ipo_age_lo", 2.5)
    hi = best_params.get("ipo_age_hi", 3.0)
    mi = best_params.get("margin_improve", 0.003)
    ni = best_params.get("np_improve", 0.003)
    lag = best_params.get("funda_lag", 28)
    brk = best_params.get("break_days", 60)
    hold = best_params.get("hold_days", 50)
    sl = best_params.get("stop_loss", 0.12)
    tp = best_params.get("take_profit", 0.35)
    mp = best_params.get("max_positions", 8)
    use_brk = best_params.get("use_break", True)
    req_ma = best_params.get("require_ma20", True)
    req_rev = bool(best_params.get("require_rev"))
    npm = best_params.get("np_min")
    trail_a = best_params.get("trail_activate")
    trail_s = best_params.get("trail_stop")
    max_nw = best_params.get("max_name_weight")
    max_ind = best_params.get("max_industry_names")

    kw_lines = [
        '            universe="csi_core",',
        "            exclude_st=True,",
        '            price_end="2026-07-30",',
        f"            ipo_age_lo={lo},",
        f"            ipo_age_hi={hi},",
        f"            margin_improve={mi},",
        f"            np_improve={ni},",
        f"            funda_lag={int(lag)},",
    ]
    if not use_brk or int(brk or 0) <= 0:
        kw_lines += ["            use_break=False,", "            break_days=0,"]
    else:
        kw_lines.append(f"            break_days={int(brk)},")
    kw_lines.append(f"            require_ma20={'True' if req_ma else 'False'},")
    if req_rev:
        kw_lines.append("            require_rev=True,")
    if npm is not None:
        kw_lines.append(f"            np_min={npm},")
    kw_lines.append(f"            hold_days={int(hold)},")
    kw_lines.append(f"            stop_loss={sl},")
    if tp is not None:
        kw_lines.append(f"            take_profit={tp},")
    kw_lines.append(f"            max_positions={int(mp)},")
    if trail_a is not None:
        kw_lines.append(f"            trail_activate={trail_a},")
    if trail_s is not None:
        kw_lines.append(f"            trail_stop={trail_s},")
    if max_nw is not None:
        kw_lines.append(f"            max_name_weight={max_nw},")
    if max_ind is not None:
        kw_lines.append(f"            max_industry_names={int(max_ind)},")

    desc_escaped = desc.replace("\\", "\\\\").replace('"', '\\"')
    new_block = (
        '    "ipo_2y5_earn_break": {\n'
        f'        "name": "{FACTOR_NAME}",\n'
        '        "category": "fundamental",\n'
        '        "description": (\n'
        f'            "{desc_escaped}"\n'
        "        ),\n"
        '        "tags": ["IPO", "解禁代理", "业绩改善", "突破", "基本面", "技术面", '
        '"csi_core", "qfq", "expt_ipo_2y5", "opt188"],\n'
        '        "title": "IPO 2.5y unlock-proxy earn break",\n'
        '        "need_profit": True,\n'
        '        "need_growth": False,\n'
        '        "signal": sig.signal_ipo_age_earn_break,\n'
        '        "params": _p(\n'
        + "\n".join(kw_lines)
        + "\n"
        "        ),\n"
        "    },"
    )
    path.write_text(text[:start] + new_block + text[j:], encoding="utf-8")
    print(f"[registry] updated {path}", flush=True)


def update_mongo(best_params: Dict[str, Any], summary: Dict[str, Any], late: Dict[str, Any], desc: str) -> List[dict]:
    targets, client = _mongo_targets()
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    summary_dst = {k: v for k, v in summary.items() if not str(k).startswith("_")}
    summary_dst["position_logic"] = FACTOR_ID
    for k in ("recent2y_sharpe", "recent2y_return", "recent2y_max_drawdown"):
        if k == "recent2y_sharpe":
            summary_dst[k] = late.get("sharpe")
        elif k == "recent2y_return":
            summary_dst[k] = late.get("total_return")
        else:
            summary_dst[k] = late.get("max_drawdown")
    payload = {
        "name": FACTOR_NAME,
        "description": desc,
        "tags": [
            "IPO",
            "解禁代理",
            "业绩改善",
            "突破",
            "基本面",
            "技术面",
            "csi_core",
            "qfq",
            "expt_ipo_2y5",
            "opt188",
        ],
        "params": {k: v for k, v in best_params.items() if not str(k).startswith("_")},
        "updated_at": now,
        "signal": "signal_ipo_age_earn_break",
        "backtest_summary": {
            "available": True,
            "primary_logic": FACTOR_ID,
            "logics": {FACTOR_ID: summary_dst},
            "updated_at": now_s,
            # 兼容旧扁平结构
            **{
                k: summary_dst.get(k)
                for k in (
                    "total_return",
                    "annual_return",
                    "sharpe",
                    "max_drawdown",
                    "n_trades",
                    "win_rate",
                    "avg_position",
                    "recent2y_sharpe",
                    "recent2y_return",
                    "recent2y_max_drawdown",
                )
            },
        },
        "late_summary": late,
        "source_opt": "opt_ipo_2y5_earn_break_188",
    }
    results = []
    for dbn in targets:
        r = client[dbn].factors.update_one({"factor_id": FACTOR_ID}, {"$set": payload}, upsert=False)
        results.append(
            {"db": dbn, "matched": r.matched_count, "modified": r.modified_count}
        )
        print(
            f"[mongo] update {dbn}.{FACTOR_ID} matched={r.matched_count} mod={r.modified_count}",
            flush=True,
        )
    return results


def write_report(payload: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    baseline = payload.get("baseline") or {}
    best = payload.get("best") or {}
    top = payload.get("top") or []
    lines = [
        "# 因子 #188 `ipo_2y5_earn_break` 参数优化报告",
        "",
        f"- 生成时间：{payload.get('generated_at')}",
        f"- 宇宙：主=`csi_core`；对照试跑=`hs300`（见对照节）",
        f"- 行情：腾讯 qfq；BaoStock 禁用",
        f"- 搜索配置数：{payload.get('n_cfgs')}（信号相{payload.get('n_signal_cfgs')} + 出场细化）",
        f"- 主分：`tw_score` = 0.2·Sh(2018-21)+0.3·Sh(2022-23)+0.5·Sh(2024+) + 0.25·近2年Sh − penalty",
        f"- 近2年切点：{CUT}",
        f"- 耗时：{payload.get('elapsed_sec')}s",
        "",
        "## 原 #188 vs 优后",
        "",
        "| 指标 | 原 | 优后 |",
        "|---|---:|---:|",
        f"| tw_score | {baseline.get('tw_score')} | {best.get('tw_score')} |",
        f"| 全样本 sharpe | {baseline.get('sharpe')} | {best.get('sharpe')} |",
        f"| 全样本 return | {baseline.get('total_return')} | {best.get('total_return')} |",
        f"| 全样本 mdd | {baseline.get('max_drawdown')} | {best.get('max_drawdown')} |",
        f"| 近2年 sharpe | {baseline.get('recent2y_sharpe')} | {best.get('recent2y_sharpe')} |",
        f"| 近2年 return | {baseline.get('recent2y_return')} | {best.get('recent2y_return')} |",
        f"| 近2年 mdd | {baseline.get('recent2y_max_dd')} | {best.get('recent2y_max_dd')} |",
        f"| accepted legs | {baseline.get('n_legs_accepted')} | {best.get('n_legs_accepted')} |",
        "",
        "## 最优参数",
        "",
        "```json",
        json.dumps(best.get("params") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Top 配置",
        "",
        "| # | cfg | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | legs | flags |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, r in enumerate(top[:15], 1):
        lines.append(
            f"| {i} | `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | {_fmt(r.get('sharpe'))} | "
            f"{_fmt(r.get('total_return'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('n_legs_accepted')} | "
            f"{','.join(r.get('flags') or [])} |"
        )
    hs = payload.get("hs300_check")
    if hs:
        lines += [
            "",
            "## hs300 对照（最优参数迁宇宙）",
            "",
            f"- sharpe={hs.get('sharpe')} ret={hs.get('total_return')} "
            f"r2y_sh={hs.get('recent2y_sharpe')} r2y_ret={hs.get('recent2y_return')} "
            f"tw={hs.get('tw_score')}",
        ]
    apply = payload.get("apply")
    if apply:
        lines += ["", "## 应用（更新 #188）", "", f"```json\n{json.dumps(apply, ensure_ascii=False, indent=2, default=str)}\n```"]
    lines += [
        "",
        "## 搜索空间摘要",
        "",
        "- IPO 年龄窗：中心≈2.3–2.7 / [2.0,3.0]/[2.5,3.0)/[2.25,2.75]/[2.4,2.8] 等",
        "- 财务：margin/np improve、np_min、require_rev、funda_lag、net_profit_min",
        "- 技术：break_days / use_break / require_ma20",
        "- 出场：hold / sl / tp / trail / max_name_weight / max_positions",
        "",
    ]
    OUT_STEM.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {OUT_STEM}.json / .md", flush=True)


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.4f}"
    except Exception:  # noqa: BLE001
        return str(v)


def apply_best(best: Dict[str, Any], list_map: Dict[str, pd.Timestamp]) -> Dict[str, Any]:
    params = deepcopy(best["params"])
    params["position_logic"] = FACTOR_ID
    params["note"] = FACTOR_NAME
    lo = params.get("ipo_age_lo")
    hi = params.get("ipo_age_hi")
    desc = (
        f"IPO年龄∈[{lo},{hi})年（无解禁明细，大股东约3年锁定期前代理）+ "
        f"毛利/净利率/净利改善"
        f"{'+营收改善' if params.get('require_rev') else ''}"
        f"{'+突破' if params.get('use_break', True) and int(params.get('break_days') or 0) > 0 else '(无突破)'}"
        f"；hold={params.get('hold_days')}/sl={params.get('stop_loss')}/tp={params.get('take_profit')}；"
        f"宇宙 csi_core；行情=腾讯 qfq。opt188 优化。"
    )
    # 正式回测写产物
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    panel = prepare_shared_panel(params, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    summary = run_factor_pipeline(
        FACTOR_ID,
        f"{FACTOR_NAME} [{lo},{hi})",
        sig.signal_ipo_age_earn_break,
        params,
        need_profit=False,
        price_map=panel,
        start=START,
    )
    daily_path = ROOT / "data" / "factors" / f"{FACTOR_ID}_backtest.csv"
    late = {}
    if daily_path.exists():
        daily = pd.read_csv(daily_path)
        late = _slice_metrics(daily, CUT, None)
    update_factor_registry(params, desc)
    mongo_res = update_mongo(params, summary, late, desc)
    return {
        "params": params,
        "description": desc,
        "summary": {k: summary.get(k) for k in (
            "total_return", "annual_return", "sharpe", "max_drawdown",
            "n_legs_accepted", "avg_position",
        )},
        "late": late,
        "mongo": mongo_res,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all", choices=["all", "signal", "exit", "apply-only"])
    ap.add_argument("--apply", action="store_true", help="用最优参数更新 #188 产物+Mongo+registry")
    ap.add_argument("--from-report", action="store_true", help="直接读已有报告最优，跳过搜索")
    ap.add_argument("--limit-cfgs", type=int, default=0, help="调试限配置数")
    ap.add_argument("--also-hs300", action="store_true", default=True)
    args = ap.parse_args()

    t0 = time.time()
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    list_map = load_list_dates()
    print(f"[list_date] n={len(list_map)}", flush=True)

    if args.from_report and OUT_STEM.with_suffix(".json").exists():
        payload = json.loads(OUT_STEM.with_suffix(".json").read_text(encoding="utf-8"))
        best = payload.get("best")
        if not best:
            raise SystemExit("report has no best")
        if args.apply:
            payload["apply"] = apply_best(best, list_map)
            payload["generated_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
            write_report(payload)
        print(json.dumps({"best_tw": best.get("tw_score"), "applied": args.apply}, ensure_ascii=False))
        return

    # panel
    params0 = deepcopy(BASE_PARAMS)
    print("[panel] prepare csi_core profit=True", flush=True)
    panel = prepare_shared_panel(params0, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        str(params0.get("price_start") or "2016-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache,
    )
    params0["_cache_dir"] = str(cache)

    results: List[Dict[str, Any]] = []
    # baseline
    print("[eval] baseline #188", flush=True)
    baseline = eval_params("baseline_188", deepcopy(BASE_PARAMS), panel, bench, family="baseline")
    results.append(baseline)
    print(
        f"  baseline tw={baseline.get('tw_score')} sh={baseline.get('sharpe')} "
        f"r2y={baseline.get('recent2y_sharpe')}/{baseline.get('recent2y_return')}",
        flush=True,
    )

    signal_cfgs = build_signal_grid()
    if args.limit_cfgs:
        signal_cfgs = signal_cfgs[: args.limit_cfgs]
    print(f"[phase1] signal configs={len(signal_cfgs)}", flush=True)

    entries_memo: Dict[str, Dict[str, pd.DataFrame]] = {}
    if args.phase in ("all", "signal"):
        for i, sp in enumerate(signal_cfgs, 1):
            sk = _sig_key(sp)
            if sk not in entries_memo:
                entries_memo[sk] = _entries_cache(panel, sp)
            cid = _cfg_id(sp, "sig")
            row = eval_params(
                cid, sp, panel, bench, entries_by_code=entries_memo[sk], family="signal"
            )
            results.append(row)
            if i % 5 == 0 or i == len(signal_cfgs):
                print(
                    f"  [{i}/{len(signal_cfgs)}] {cid}: tw={row.get('tw_score')} "
                    f"sh={row.get('sharpe')} r2y_sh={row.get('recent2y_sharpe')} "
                    f"legs={row.get('n_legs_accepted')} flags={row.get('flags')}",
                    flush=True,
                )
            # checkpoint
            if i % 20 == 0:
                (OUT_DIR / "checkpoint_results.json").write_text(
                    json.dumps(results, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )

    # phase2: top signal → exit refine
    ranked_sig = sorted(
        [r for r in results if r.get("family") in ("signal", "baseline")],
        key=_rank_key,
        reverse=True,
    )
    top_sigs = ranked_sig[:5]
    if args.phase in ("all", "exit"):
        print(f"[phase2] exit refine on top {len(top_sigs)} signals", flush=True)
        for ts in top_sigs:
            base_p = deepcopy(ts["params"])
            # keep signal keys; wipe exit to be overwritten
            exit_cfgs = build_exit_grid(base_p)
            if args.limit_cfgs:
                exit_cfgs = exit_cfgs[: max(8, args.limit_cfgs // 2)]
            sk = _sig_key(base_p)
            if sk not in entries_memo:
                entries_memo[sk] = _entries_cache(panel, base_p)
            for j, ep in enumerate(exit_cfgs, 1):
                cid = _cfg_id(ep, "ex")
                row = eval_params(
                    cid, ep, panel, bench, entries_by_code=entries_memo[sk], family="exit"
                )
                results.append(row)
                if j % 10 == 0 or j == len(exit_cfgs):
                    print(
                        f"  exit[{ts.get('cfg_id')}] {j}/{len(exit_cfgs)} "
                        f"tw={row.get('tw_score')} r2y_sh={row.get('recent2y_sharpe')}",
                        flush=True,
                    )

    ranked = sorted(results, key=_rank_key, reverse=True)
    best = ranked[0]
    top = ranked[:20]

    hs300_check = None
    if args.also_hs300 and best:
        print("[hs300] check best params on hs300", flush=True)
        hp = deepcopy(best["params"])
        hp["universe"] = "hs300"
        hpanel = prepare_shared_panel(hp, need_profit=True, need_growth=False)
        hpanel = attach_list_dates(hpanel, list_map)
        hs300_check = eval_params("best_on_hs300", hp, hpanel, bench, family="hs300")

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "factor_id": FACTOR_ID,
        "ui": FACTOR_UI,
        "n_cfgs": len(results),
        "n_signal_cfgs": len(signal_cfgs),
        "baseline": baseline,
        "best": best,
        "top": top,
        "hs300_check": hs300_check,
        "search_space": {
            "ipo_windows": "2.0-3.0 / 2.5-3.0 / 2.25-2.75 / 2.3-2.7 / 2.4-2.8 / ...",
            "funda": "margin/np improve, np_min, require_rev, funda_lag, net_profit_min",
            "tech": "break_days, use_break, require_ma20",
            "exit": "hold, sl, tp, trail, max_name_weight, max_positions",
        },
        "elapsed_sec": round(time.time() - t0, 1),
        "all_results_path": str(OUT_DIR / "all_results.json"),
    }
    (OUT_DIR / "all_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    if args.apply:
        payload["apply"] = apply_best(best, list_map)

    write_report(payload)
    print(
        json.dumps(
            {
                "baseline_tw": baseline.get("tw_score"),
                "best_tw": best.get("tw_score"),
                "best_sh": best.get("sharpe"),
                "best_r2y_sh": best.get("recent2y_sharpe"),
                "best_cfg": best.get("cfg_id"),
                "elapsed": payload["elapsed_sec"],
                "applied": bool(args.apply),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
