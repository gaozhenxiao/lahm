# -*- coding: utf-8 -*-
"""UI#189 ``ipo_2y5_earn_break`` 宽网格再优化；**绝不改 #189**，有提升则新增因子。

基线：当前 morph188 参数（stabilize / hold120 / mp14）。
主分：时间加权 tw_score（近年权重大）+ 近2年表现。
宇宙 csi_core；腾讯 qfq；BaoStock 禁用。

用法：
  .venv\\Scripts\\python.exe scripts/opt_ipo_189_wide_new.py
  .venv\\Scripts\\python.exe scripts/opt_ipo_189_wide_new.py --apply
  .venv\\Scripts\\python.exe scripts/opt_ipo_189_wide_new.py --limit 20   # 冒烟
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402
from scripts.enhance_ipo_188_morph import (  # noqa: E402
    CUT,
    MIN_ACCEPTED,
    SIG_KEYS,
    START,
    _bs_disabled,
    _entries_cache,
    _fmt_param_block,
    _mongo_targets,
    _rank_key,
    _sig_key,
    _slice_metrics,
    attach_list_dates,
    eval_params,
    load_list_dates,
)

BASE_FID = "ipo_2y5_earn_break"
BASE_UI = 189
OUT_DIR = ROOT / "data" / "factors" / "opt_ipo_189_wide_new"
OUT_STEM = OUT_DIR / "opt_report"
SEED = 18941

# 当前 #189 落库参数（勿改此文档，仅作基线）
BASELINE: Dict[str, Any] = {
    "universe": "csi_core",
    "exclude_st": True,
    "price_start": "2010-01-01",
    "price_end": "2026-07-30",
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "ipo_age_lo": 2.4,
    "ipo_age_hi": 3.0,
    "require_ipo_crash": True,
    "ipo_crash_months": 18,
    "ipo_crash_dd": -0.45,
    "require_consol": True,
    "consol_window": 100,
    "consol_amp_max": 0.32,
    "consol_ma_band": 0.08,
    "entry_mode": "stabilize",
    "break_days": 40,
    "brk_soft": 0.985,
    "use_break": True,
    "require_ma20": False,
    "require_rev": False,
    "margin_improve": 0.003,
    "np_improve": 0.003,
    "funda_lag": 28,
    "hold_days": 120,
    "stop_loss": 0.15,
    "take_profit": 0.45,
    "max_positions": 14,
    "fixed_leg_weight": False,
    "position_display": "actual",
    "position_logic": BASE_FID,
    "note": "IPO #189 baseline",
}


def build_wide_morphs() -> List[Dict[str, Any]]:
    """比 morph188 更宽的形态网格 + 随机扰动。"""
    ages = [
        (2.0, 2.8),
        (2.2, 2.8),
        (2.3, 2.9),
        (2.4, 3.0),
        (2.5, 3.0),
        (2.5, 3.2),
        (2.6, 3.2),
        (2.0, 3.0),
    ]
    crashes = [
        (12, -0.35),
        (12, -0.40),
        (18, -0.40),
        (18, -0.45),
        (18, -0.50),
        (24, -0.40),
        (24, -0.45),
    ]
    consols = [
        (80, 0.28, 0.06),
        (100, 0.30, 0.08),
        (100, 0.32, 0.08),
        (120, 0.35, 0.08),
        (120, 0.38, 0.10),
        (150, 0.40, 0.10),
    ]
    entries = [
        ("soft", 35, 0.985),
        ("soft", 40, 0.985),
        ("soft", 55, 0.98),
        ("stabilize", 40, 0.985),
        ("stabilize", 55, 0.98),
        ("stabilize", 70, 0.985),
        ("break", 40, 0.99),
        ("break", 60, 0.985),
    ]
    fins = [
        (0.0, 0.0, 28),
        (0.002, 0.002, 28),
        (0.003, 0.003, 21),
        (0.003, 0.003, 28),
        (0.003, 0.003, 35),
        (0.005, 0.005, 28),
        (0.008, 0.005, 28),
    ]

    morphs: List[Dict[str, Any]] = []
    # A) 基线邻域（强制包含当前 #189 形态）
    morphs.append(
        {
            "ipo_age_lo": 2.4,
            "ipo_age_hi": 3.0,
            "ipo_crash_months": 18,
            "ipo_crash_dd": -0.45,
            "consol_window": 100,
            "consol_amp_max": 0.32,
            "consol_ma_band": 0.08,
            "entry_mode": "stabilize",
            "break_days": 40,
            "brk_soft": 0.985,
            "margin_improve": 0.003,
            "np_improve": 0.003,
            "funda_lag": 28,
        }
    )
    # B) 轴扫描：每次只动 1–2 维，覆盖更广
    for lo, hi in ages:
        morphs.append(
            {
                **morphs[0],
                "ipo_age_lo": lo,
                "ipo_age_hi": hi,
            }
        )
    for cm, dd in crashes:
        morphs.append({**morphs[0], "ipo_crash_months": cm, "ipo_crash_dd": dd})
    for cw, amp, band in consols:
        morphs.append(
            {
                **morphs[0],
                "consol_window": cw,
                "consol_amp_max": amp,
                "consol_ma_band": band,
            }
        )
    for em, brk, soft in entries:
        morphs.append(
            {
                **morphs[0],
                "entry_mode": em,
                "break_days": brk,
                "brk_soft": soft,
            }
        )
    for mi, ni, lag in fins:
        morphs.append(
            {
                **morphs[0],
                "margin_improve": mi,
                "np_improve": ni,
                "funda_lag": lag,
            }
        )

    # C) 交叉块：年龄×大跌×入场（固定横盘/财务）
    for (lo, hi), (cm, dd), (em, brk, soft) in itertools.product(
        ages[:5], crashes[:5], entries[:5]
    ):
        morphs.append(
            {
                "ipo_age_lo": lo,
                "ipo_age_hi": hi,
                "ipo_crash_months": cm,
                "ipo_crash_dd": dd,
                "consol_window": 100,
                "consol_amp_max": 0.32,
                "consol_ma_band": 0.08,
                "entry_mode": em,
                "break_days": brk,
                "brk_soft": soft,
                "margin_improve": 0.003,
                "np_improve": 0.003,
                "funda_lag": 28,
            }
        )

    # D) 随机大幅扰动
    rng = random.Random(SEED)
    for _ in range(80):
        lo, hi = rng.choice(ages)
        cm, dd = rng.choice(crashes)
        cw, amp, band = rng.choice(consols)
        em, brk, soft = rng.choice(entries)
        mi, ni, lag = rng.choice(fins)
        morphs.append(
            {
                "ipo_age_lo": lo,
                "ipo_age_hi": hi,
                "ipo_crash_months": cm,
                "ipo_crash_dd": dd,
                "consol_window": cw,
                "consol_amp_max": amp,
                "consol_ma_band": band,
                "entry_mode": em,
                "break_days": brk,
                "brk_soft": soft,
                "margin_improve": mi,
                "np_improve": ni,
                "funda_lag": lag,
            }
        )

    seen = set()
    uniq: List[Dict[str, Any]] = []
    for m in morphs:
        p = {**BASELINE, **m, "hold_days": 120, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.45}
        k = _sig_key(p)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def build_exit_grid() -> List[Dict[str, Any]]:
    """出场宽搜，但控规模（~36 组），避免 phase2 爆炸。"""
    must = [
        {"hold_days": 120, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.45},
        {"hold_days": 100, "max_positions": 14, "stop_loss": 0.12, "take_profit": 0.45},
        {"hold_days": 100, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.40},
        {"hold_days": 80, "max_positions": 14, "stop_loss": 0.12, "take_profit": 0.35},
        {"hold_days": 80, "max_positions": 16, "stop_loss": 0.12, "take_profit": 0.45},
        {"hold_days": 150, "max_positions": 12, "stop_loss": 0.15, "take_profit": 0.55},
        {"hold_days": 150, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.45},
        {"hold_days": 180, "max_positions": 10, "stop_loss": 0.18, "take_profit": 0.55},
        {"hold_days": 60, "max_positions": 16, "stop_loss": 0.12, "take_profit": 0.30},
        {"hold_days": 120, "max_positions": 12, "stop_loss": 0.12, "take_profit": 0.55},
        {"hold_days": 120, "max_positions": 16, "stop_loss": 0.15, "take_profit": 0.45},
        {"hold_days": 120, "max_positions": 18, "stop_loss": 0.15, "take_profit": 0.45},
        {"hold_days": 100, "max_positions": 12, "stop_loss": 0.10, "take_profit": 0.45},
        {"hold_days": 100, "max_positions": 16, "stop_loss": 0.18, "take_profit": 0.55},
        {"hold_days": 90, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.45},
        {"hold_days": 140, "max_positions": 14, "stop_loss": 0.15, "take_profit": 0.50},
    ]
    # 再扩一圈 hold×mp×sl×tp 精简笛卡尔
    extra = []
    for hold, mp, sl, tp in itertools.product(
        (70, 110, 130, 160),
        (11, 13, 15),
        (0.12, 0.15),
        (0.35, 0.45, 0.55),
    ):
        extra.append(
            {"hold_days": hold, "max_positions": mp, "stop_loss": sl, "take_profit": tp}
        )
    rng = random.Random(SEED + 3)
    picked = must + rng.sample(extra, min(20, len(extra)))
    out = []
    seen = set()
    for e in picked:
        e = {
            **e,
            "fixed_leg_weight": False,
            "position_display": "actual",
        }
        k = json.dumps(e, sort_keys=True)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def _new_factor_id(p: Dict[str, Any]) -> str:
    lo = str(p.get("ipo_age_lo")).replace(".", "")
    cm = p.get("ipo_crash_months")
    dd = abs(int(round(float(p.get("ipo_crash_dd") or 0) * 100)))
    em = str(p.get("entry_mode") or "x")[:3]
    h = p.get("hold_days")
    fid = f"ipo_2y5_earn_a{lo}_c{cm}_dd{dd}_{em}_h{h}_opt189"
    fid = re.sub(r"[^a-zA-Z0-9_]", "_", fid)[:56]
    # 避免撞车
    if fid in FACTOR_IMPL or fid == BASE_FID:
        fid = f"{fid}_v2"
    return fid


def make_desc(p: Dict[str, Any]) -> str:
    return (
        f"由 UI#189 宽网格再优化新增（不改 #189）。"
        f"形态：上市后0–{p.get('ipo_crash_months')}月最大回撤≤{p.get('ipo_crash_dd')}；"
        f"横盘窗{p.get('consol_window')}振幅≤{p.get('consol_amp_max')}/ma±{p.get('consol_ma_band')}；"
        f"年龄∈[{p.get('ipo_age_lo')},{p.get('ipo_age_hi')})；"
        f"入场={p.get('entry_mode')}(brk{p.get('break_days')}/soft{p.get('brk_soft')})；"
        f"hold={p.get('hold_days')}/mp={p.get('max_positions')}/sl={p.get('stop_loss')}/tp={p.get('take_profit')}；"
        f"满仓等权1/n；宇宙csi_core；腾讯qfq。opt189_wide。"
    )


def _improved(best: Dict[str, Any], baseline: Dict[str, Any]) -> Tuple[bool, str]:
    """是否值得新增：tw 提升或近2年显著更好且全样本不塌。"""
    bt = baseline.get("tw_score")
    bb = best.get("tw_score")
    if bb is None:
        return False, "best_tw_missing"
    if bt is None:
        return True, "baseline_tw_missing_accept_best"
    bt = float(bt)
    bb = float(bb)
    bsh = float(best.get("sharpe") or -9)
    ash = float(baseline.get("sharpe") or -9)
    br2 = float(best.get("recent2y_sharpe") or -9)
    ar2 = float(baseline.get("recent2y_sharpe") or -9)
    if bb >= bt + 0.05 and bsh >= ash - 0.08:
        return True, f"tw+{bb - bt:.3f} (sh ok)"
    if br2 >= ar2 + 0.15 and bsh >= ash - 0.05 and bb >= bt - 0.02:
        return True, f"r2y_sh+{br2 - ar2:.3f}"
    if bb > bt + 0.02 and bsh > ash + 0.05:
        return True, f"tw+sh both up"
    return False, f"no_improve tw {bb:.3f} vs {bt:.3f} sh {bsh:.3f} vs {ash:.3f}"


def insert_new_factor(best_row: Dict[str, Any], list_map: Dict[str, pd.Timestamp]) -> Dict[str, Any]:
    """新增 registry + Mongo + 回测产物；不动 BASE_FID。"""
    params = deepcopy(best_row["params"])
    fid = _new_factor_id(params)
    name = (
        f"IPO大跌横盘≈2.5年+业绩(优化自#189·"
        f"{params.get('entry_mode')}/h{params.get('hold_days')}/mp{params.get('max_positions')})"
    )
    params["position_logic"] = fid
    params["note"] = name
    params["fixed_leg_weight"] = False
    params["position_display"] = "actual"
    desc = make_desc(params)

    # registry append before last? after ipo_2y5 block
    path = ROOT / "app" / "services" / "factors" / "factor_registry.py"
    text = path.read_text(encoding="utf-8")
    if f'"{fid}"' in text:
        raise RuntimeError(f"registry already has {fid}")
    anchor = '    "ipo_2y5_earn_break": {'
    start = text.find(anchor)
    if start < 0:
        raise RuntimeError("anchor ipo_2y5_earn_break not found")
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
        raise RuntimeError("parse fail")

    param_block = _fmt_param_block(
        {
            **params,
            "fixed_leg_weight": False,
            "position_display": "actual",
        }
    )
    # _fmt_param_block may miss fixed_leg_weight — append
    if "fixed_leg_weight" not in param_block:
        param_block += "\n            fixed_leg_weight=False,\n            position_display=\"actual\","

    new_block = (
        f'\n    "{fid}": {{\n'
        f'        "name": "{name}",\n'
        '        "category": "fundamental",\n'
        '        "description": (\n'
        f'            "{desc.replace(chr(34), chr(39))}"\n'
        "        ),\n"
        '        "tags": ["IPO", "大跌", "横盘", "解禁代理", "业绩改善", "突破", '
        '"基本面", "技术面", "csi_core", "qfq", "expt_ipo_2y5", "opt189_wide"],\n'
        '        "title": "IPO morph opt from UI#189",\n'
        '        "need_profit": True,\n'
        '        "need_growth": False,\n'
        '        "signal": sig.signal_ipo_age_earn_break,\n'
        '        "params": _p(\n'
        f"{param_block}\n"
        "        ),\n"
        "    },"
    )
    path.write_text(text[:j] + new_block + text[j:], encoding="utf-8")
    print(f"[registry] inserted {fid} after {BASE_FID}", flush=True)

    # backtest artifacts under new id
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    panel = prepare_shared_panel(params, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    summary = run_factor_pipeline(
        fid,
        name,
        sig.signal_ipo_age_earn_break,
        params,
        need_profit=False,
        price_map=panel,
        start=START,
    )
    daily_path = ROOT / "data" / "factors" / f"{fid}_backtest.csv"
    late: Dict[str, Any] = {}
    if daily_path.exists():
        late = _slice_metrics(pd.read_csv(daily_path), CUT, None)

    # Mongo insert at max created_at + 1h (primary + mirrors that have factors)
    targets, client = _mongo_targets()
    now = datetime.now()
    mongo_res = []
    for dbn in targets:
        db = client[dbn]
        if "factors" not in db.list_collection_names():
            continue
        if db.factors.find_one({"factor_id": fid}):
            print(f"[mongo] skip exists {dbn}.{fid}", flush=True)
            continue
        latest = db.factors.find_one(
            {"created_at": {"$ne": None}},
            sort=[("created_at", -1)],
            projection={"created_at": 1},
        )
        ca = now
        if latest and latest.get("created_at") is not None:
            try:
                ca = latest["created_at"] + timedelta(hours=1)
            except Exception:  # noqa: BLE001
                ca = now
            if now > ca:
                ca = now
        # count for planned UI
        n_before = db.factors.count_documents({})
        payload = {
            "factor_id": fid,
            "name": name,
            "category": "fundamental",
            "description": desc,
            "tags": [
                "IPO",
                "大跌",
                "横盘",
                "解禁代理",
                "业绩改善",
                "突破",
                "基本面",
                "技术面",
                "csi_core",
                "qfq",
                "expt_ipo_2y5",
                "opt189_wide",
            ],
            "status": "active",
            "builtin": True,
            "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
            "signal": "signal_ipo_age_earn_break",
            "created_at": ca,
            "updated_at": now,
            "source_opt": "opt_ipo_189_wide_new",
            "parent_factor_id": BASE_FID,
            "parent_ui": BASE_UI,
        }
        db.factors.insert_one(payload)
        docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))
        docs = sorted(
            docs,
            key=lambda x: (str(x.get("created_at") or ""), str(x.get("factor_id") or "")),
        )
        seq = next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == fid), None)
        mongo_res.append(
            {
                "db": dbn,
                "factor_id": fid,
                "created_at": str(ca),
                "ui": seq,
                "count_before": n_before,
                "count_after": len(docs),
            }
        )
        print(f"[mongo] insert {dbn} UI#{seq} {fid}", flush=True)

    # sync FACTOR_IMPL in-process for ensure_builtins on next boot
    FACTOR_IMPL[fid] = {
        "name": name,
        "category": "fundamental",
        "description": desc,
        "tags": ["IPO", "opt189_wide", "csi_core", "qfq"],
        "signal": sig.signal_ipo_age_earn_break,
        "params": params,
        "need_profit": True,
        "need_growth": False,
    }
    return {
        "factor_id": fid,
        "name": name,
        "description": desc,
        "params": params,
        "summary": {
            k: summary.get(k)
            for k in (
                "total_return",
                "annual_return",
                "sharpe",
                "max_drawdown",
                "n_legs_accepted",
                "avg_position",
            )
        },
        "late": late,
        "mongo": mongo_res,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="有提升才新增；绝不改 #189")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--top-morph", type=int, default=10)
    args = ap.parse_args()

    t0 = time.time()
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    list_map = load_list_dates()
    print(f"[list_date] n={len(list_map)}", flush=True)

    morphs = build_wide_morphs()
    exits = build_exit_grid()
    if args.limit:
        morphs = morphs[: args.limit]
    print(f"[grid] morph={len(morphs)} exits={len(exits)} top_morph={args.top_morph}", flush=True)

    print("[panel] prepare csi_core", flush=True)
    panel = prepare_shared_panel(BASELINE, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        str(BASELINE.get("price_start") or "2010-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache,
    )

    # baseline
    print("[baseline] eval #189 current params", flush=True)
    base_ents = _entries_cache(panel, BASELINE)
    baseline = eval_params("baseline_189", BASELINE, panel, bench, base_ents)
    print(
        f"  baseline tw={baseline.get('tw_score')} sh={baseline.get('sharpe')} "
        f"r2y={baseline.get('recent2y_sharpe')} legs={baseline.get('n_legs_accepted')}",
        flush=True,
    )

    results: List[Dict[str, Any]] = [baseline]
    entries_memo: Dict[str, Dict[str, pd.DataFrame]] = {_sig_key(BASELINE): base_ents}

    for i, sp in enumerate(morphs, 1):
        sk = _sig_key(sp)
        if sk not in entries_memo:
            entries_memo[sk] = _entries_cache(panel, sp)
        row = eval_params(f"morph_{i}", sp, panel, bench, entries_memo[sk])
        results.append(row)
        if i % 10 == 0 or i == len(morphs):
            print(
                f"  [{i}/{len(morphs)}] tw={row.get('tw_score')} sh={row.get('sharpe')} "
                f"r2y={row.get('recent2y_sharpe')} legs={row.get('n_legs_accepted')} "
                f"flags={row.get('tw_flags')}",
                flush=True,
            )

    morph_ranked = sorted(results, key=_rank_key, reverse=True)
    # 排除 baseline 自己占 top 时仍用其形态扫出场
    top = []
    seen_sk = set()
    for r in morph_ranked:
        sk = _sig_key(r["params"])
        if sk in seen_sk:
            continue
        seen_sk.add(sk)
        top.append(r)
        if len(top) >= args.top_morph:
            break
    print(f"[phase2] exit sweep top {len(top)} × {len(exits)}", flush=True)

    phase2: List[Dict[str, Any]] = []
    for mi, mrow in enumerate(top, 1):
        base_p = dict(mrow["params"])
        sk = _sig_key(base_p)
        ents = entries_memo.get(sk) or _entries_cache(panel, base_p)
        for ei, ex in enumerate(exits, 1):
            p = {**base_p, **ex}
            row = eval_params(f"top{mi}_ex{ei}", p, panel, bench, ents)
            phase2.append(row)
        best_local = max(phase2[-len(exits) :], key=_rank_key)
        print(
            f"  morph#{mi} local_best tw={best_local.get('tw_score')} sh={best_local.get('sharpe')}",
            flush=True,
        )

    all_rows = results + phase2
    ranked = sorted(all_rows, key=_rank_key, reverse=True)
    best = ranked[0] if ranked else None
    ok, reason = _improved(best, baseline) if best else (False, "no_best")

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "base_factor_id": BASE_FID,
        "base_ui": BASE_UI,
        "n_morph": len(morphs),
        "n_phase2": len(phase2),
        "baseline": {
            k: baseline.get(k)
            for k in (
                "tw_score",
                "sharpe",
                "total_return",
                "recent2y_sharpe",
                "recent2y_return",
                "n_legs_accepted",
                "max_drawdown",
            )
        },
        "best": best,
        "improved": ok,
        "improve_reason": reason,
        "top8": [
            {
                k: r.get(k)
                for k in (
                    "cfg_id",
                    "tw_score",
                    "sharpe",
                    "total_return",
                    "recent2y_sharpe",
                    "recent2y_return",
                    "n_legs_accepted",
                    "params",
                )
            }
            for r in ranked[:8]
        ],
        "elapsed_sec": round(time.time() - t0, 1),
        "note": "never modify UI#189 / ipo_2y5_earn_break",
    }

    if args.apply:
        if ok and best:
            payload["apply"] = insert_new_factor(best, list_map)
        else:
            payload["apply"] = {"skipped": True, "reason": reason}
            print(f"[apply] skipped: {reason}", flush=True)

    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md = [
        "# UI#189 宽网格再优化（新增不改旧）",
        "",
        f"- generated: {payload['generated_at']}",
        f"- elapsed: {payload['elapsed_sec']}s",
        f"- morph/phase2: {payload['n_morph']}/{payload['n_phase2']}",
        f"- improved: {ok} ({reason})",
        "",
        "## Baseline #189",
        "",
        f"```json\n{json.dumps(payload['baseline'], ensure_ascii=False, indent=2)}\n```",
        "",
        "## Best",
        "",
        f"```json\n{json.dumps(best, ensure_ascii=False, indent=2, default=str) if best else 'null'}\n```",
    ]
    OUT_STEM.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(f"[write] {OUT_STEM}.json/.md", flush=True)
    if best:
        print(
            f"[best] improved={ok} ({reason}) tw={best.get('tw_score')} "
            f"sh={best.get('sharpe')} r2y={best.get('recent2y_sharpe')} "
            f"legs={best.get('n_legs_accepted')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
