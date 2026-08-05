"""三宇宙 Round2：时间加权排序 + 新家族网格。

- 主分 = 0.2×Sharpe(2018–21) + 0.3×Sharpe(2022–23) + 0.5×Sharpe(2024+)
- 近2年(2024-08+)大幅亏损且远年虚高 → 降权/剔除（#171 教训）
- 报告同时给出全样本与近2年指标
- 不写 Mongo；产物 data/factors/mine_csi300_500_1000_round2/

用法:
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000_round2.py
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000_round2.py --universes hs300
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000_round2.py --universes hs300,csi500 --skip-build
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402
from mine_factor_dedup import (  # noqa: E402
    DedupIndex,
    build_inventory,
    write_inventory_markdown,
)

OUT_ROOT = ROOT / "data" / "factors" / "mine_csi300_500_1000_round2"
START = "2018-01-01"
MIN_ACCEPTED_LEGS = 25
TOP_N = 5
RECENT2Y_CUT = "2024-08-01"

# 时间加权分段：(label, start, end_inclusive_or_None, weight)
SEGMENTS: List[Tuple[str, str, Optional[str], float]] = [
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_now", "2024-01-01", None, 0.50),
]

UNIVERSES = ("hs300", "csi500", "csi1000")

BENCH = {
    "hs300": "sh.000300",
    "csi500": "sh.000905",
    "csi1000": "sh.000852",
}

EDGES_YUAN = [5e10, 2e11]
# 尚未在 fmkv_round1 用过的分档边（300亿 / 1200亿）
EDGES_YUAN_B = [3e10, 1.2e11]

SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame]
# grid row: cfg_id, family, fn, extras, need_profit, need_growth, need_fin_db, need_balance
GridRow = Tuple[str, str, SignalFn, Dict[str, Any], bool, bool, bool, bool]


def _base(universe: str) -> Dict[str, Any]:
    return {
        "universe": universe,
        "exclude_st": True,
        "price_start": "2016-01-01",
        "max_positions": 8,
        "commission_rate": 0.0001,
        "stamp_tax_sell": 0.001,
        "request_interval_sec": 0.05,
        "bench_code": BENCH.get(universe, "sh.000300"),
        "_cache_dir": str(kit.shared_cache_dir()),
    }


def _grid() -> List[GridRow]:
    """尚未覆盖优先：新信号结构 / 新 f(mkv) 边 / 过滤器组合。

    返回 (cfg_id, family, fn, extras, need_profit, need_growth, need_fin_db, need_balance)。
    经典 #166/#168/#171 / round1 常数族由 DedupIndex 在运行时 skip。
    """
    rows: List[GridRow] = []

    # ---- 新 f(mkv) 分档边 + 反向/非对称 ----
    ge = sig.signal_gross_expand_break
    for tag, extra in [
        (
            "fmkv_b_edges_mbrk",
            dict(
                margin_improve=0.006,
                np_min=0.10,
                funda_lag=29,
                hold_days=51,
                stop_loss=0.12,
                take_profit=0.35,
                margin_min_by_mkv={"edges": EDGES_YUAN_B, "values": [0.13, 0.16, 0.19]},
                break_days_by_mkv={"edges": EDGES_YUAN_B, "values": [90, 60, 45]},
            ),
        ),
        (
            "fmkv_b_soft_small",
            dict(
                margin_improve=0.005,
                np_min=0.08,
                funda_lag=30,
                hold_days=45,
                stop_loss=0.12,
                take_profit=0.30,
                margin_min_by_mkv={"edges": EDGES_YUAN_B, "values": [0.12, 0.15, 0.18]},
                break_days=70,
            ),
        ),
        (
            "npmin_1e9_m16_lag30",
            dict(
                margin_improve=0.006,
                margin_min=0.16,
                np_min=0.10,
                funda_lag=30,
                break_days=60,
                hold_days=51,
                stop_loss=0.12,
                take_profit=0.35,
                net_profit_min=1e9,
            ),
        ),
        (
            "dry_amt_m16_lag28",
            dict(
                margin_improve=0.006,
                margin_min=0.16,
                np_min=0.10,
                funda_lag=28,
                break_days=60,
                hold_days=45,
                stop_loss=0.12,
                take_profit=0.30,
                amt_dry_ratio=0.65,
            ),
        ),
        (
            "yoy15_pe45_m17",
            dict(
                margin_improve=0.006,
                margin_min=0.17,
                np_min=0.10,
                funda_lag=29,
                break_days=60,
                hold_days=51,
                stop_loss=0.12,
                take_profit=0.35,
                yoy_min=0.15,
                pe_pct_max=0.45,
            ),
        ),
        (
            "soft95_m15_lag27",
            dict(
                margin_improve=0.005,
                margin_min=0.15,
                np_min=0.09,
                funda_lag=27,
                break_days=60,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.28,
                brk_soft=0.98,
            ),
        ),
    ]:
        rows.append((f"ge_novel__{tag}", "gross_expand_novel", ge, extra, True, False, False, False))

    # ---- 新信号结构 ----
    for tag, fn, extra, nb in [
        (
            "demand_m15_lag28",
            sig.signal_demand_pricing_break,
            dict(
                margin_improve=0.005,
                margin_min=0.15,
                np_min=0.06,
                funda_lag=28,
                break_days=60,
                hold_days=45,
                stop_loss=0.12,
                take_profit=0.30,
            ),
            True,
        ),
        (
            "demand_m18_lag30",
            sig.signal_demand_pricing_break,
            dict(
                margin_improve=0.006,
                margin_min=0.18,
                np_min=0.08,
                funda_lag=30,
                break_days=60,
                hold_days=50,
                stop_loss=0.12,
                take_profit=0.35,
            ),
            True,
        ),
        (
            "parent_lead_lag28",
            sig.signal_parent_lead_break,
            dict(funda_lag=28, break_days=60, hold_days=40, stop_loss=0.12, take_profit=0.30),
            False,
        ),
        (
            "catchup_lag28_h45",
            sig.signal_gross_net_catchup_break,
            dict(funda_lag=28, break_days=60, hold_days=45, stop_loss=0.12, take_profit=0.30),
            False,
        ),
        (
            "np_cheap_pe40_lag28",
            sig.signal_np_expand_cheap_break,
            dict(
                margin_improve=0.005,
                np_min=0.08,
                pe_pct_max=0.40,
                funda_lag=28,
                break_days=60,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.30,
            ),
            False,
        ),
        (
            "rev_accel_base",
            sig.signal_rev_accel_base_break,
            dict(
                accel_min=0.06,
                growth_min=0.10,
                base_window=60,
                amp_max=0.24,
                funda_lag=25,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.30,
            ),
            False,
        ),
        (
            "roe_dip_reclaim",
            sig.signal_roe_dip_reclaim,
            dict(roe_min=0.10, funda_lag=25, hold_days=35, stop_loss=0.12, take_profit=0.28),
            False,
        ),
        (
            "rev_roe_sync",
            sig.signal_rev_roe_sync_break,
            dict(
                qoq_min=0.08,
                roe_improve=0.003,
                roe_min=0.08,
                funda_lag=28,
                break_days=60,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.30,
            ),
            False,
        ),
    ]:
        rows.append((f"struct__{tag}", "new_structure", fn, extra, True, False, False, nb))

    # ---- q_np 非默认变体（宇宙级去重会放行非 hs300）----
    qg = sig.signal_q_np_gap
    for tag, extra in [
        (
            "exp120_h35_tp30",
            dict(
                explosive_chg=120.0,
                prior_yoy_max=25.0,
                qoq_gap_min=60.0,
                funda_lag=3,
                require_ma20=True,
                hold_days=35,
                stop_loss=0.12,
                take_profit=0.30,
            ),
        ),
        (
            "exp60_h40_soft",
            dict(
                explosive_chg=60.0,
                prior_yoy_max=50.0,
                qoq_gap_min=30.0,
                funda_lag=5,
                require_ma20=True,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.25,
            ),
        ),
    ]:
        rows.append((f"q_np_gap__{tag}", "q_np_gap_novel", qg, extra, False, False, True, False))

    # ---- 中小市值宇宙友好：稍松毛利 + 更长确认 ----
    for tag, extra in [
        (
            "m13_brk90_h40",
            dict(
                margin_improve=0.004,
                margin_min=0.13,
                np_min=0.06,
                funda_lag=30,
                break_days=90,
                hold_days=40,
                stop_loss=0.12,
                take_profit=0.28,
            ),
        ),
        (
            "m12_mkv_cap5e10",
            dict(
                margin_improve=0.005,
                margin_min=0.12,
                np_min=0.05,
                funda_lag=28,
                break_days=80,
                hold_days=35,
                stop_loss=0.12,
                take_profit=0.25,
                mktcap_min=5e9,
            ),
        ),
    ]:
        rows.append((f"ge_mid__{tag}", "gross_expand_midcap", ge, extra, True, False, False, False))

    return rows


def _sharpe(rets: pd.Series) -> Optional[float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or float(r.std(ddof=0)) == 0:
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

    recent2y = _slice_metrics(daily, RECENT2Y_CUT, None)
    early = segs.get("y2018_2021") or {}
    mid = segs.get("y2022_2023") or {}
    late = segs.get("y2024_now") or {}

    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    early_sh = early.get("sharpe")
    # #171 教训：近2年大亏 + 远年虚高
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")

    # 近年权重惩罚
    penalty = 0.0
    if "early_inflated_recent_poor" in flags:
        penalty += 0.50
    elif "recent2y_big_loss" in flags:
        penalty += 0.35
    elif "recent2y_neg_sharpe" in flags:
        penalty += 0.20

    tw_adj = (tw_sharpe - penalty) if tw_sharpe is not None else None
    return {
        "segments": segs,
        "tw_sharpe": tw_sharpe,
        "tw_score": tw_adj,
        "tw_penalty": penalty,
        "recent2y": recent2y,
        "late_sharpe": late.get("sharpe"),
        "late_return": late.get("total_return"),
        "mid_sharpe": mid.get("sharpe"),
        "early_sharpe": early.get("sharpe"),
        "tw_flags": flags,
    }


def _overfit_flags(summary: Dict[str, Any], tw: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    n = int(summary.get("n_legs_accepted") or 0)
    if n < MIN_ACCEPTED_LEGS:
        flags.append(f"few_legs<{MIN_ACCEPTED_LEGS}")
    if n > 0 and n < 40 and float(summary.get("total_return") or 0) > 8:
        flags.append("high_ret_few_legs")
    sharpe = summary.get("sharpe")
    if sharpe is not None and float(sharpe) > 2.5 and n < 40:
        flags.append("sus_sharpe_few_legs")
    flags.extend(tw.get("tw_flags") or [])
    return flags


def _eval_one(
    cfg_id: str,
    family: str,
    signal_fn: SignalFn,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
) -> Dict[str, Any]:
    t0 = time.time()
    legs = collect_legs(panel, signal_fn, params)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=START
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    tw = _time_weight_score(daily) if isinstance(daily, pd.DataFrame) and not daily.empty else {
        "tw_sharpe": None,
        "tw_score": None,
        "tw_penalty": 0.0,
        "recent2y": {"empty": True},
        "tw_flags": ["no_daily"],
        "segments": {},
    }
    out = {
        "cfg_id": cfg_id,
        "family": family,
        "universe": params.get("universe"),
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "signal": getattr(signal_fn, "__name__", str(signal_fn)),
        "sharpe": summary.get("sharpe"),
        "total_return": summary.get("total_return"),
        "annual_return": summary.get("annual_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "n_legs_raw": summary.get("n_legs_raw", len(legs) if legs is not None else 0),
        "n_legs_accepted": summary.get(
            "n_legs_accepted", 0 if accepted is None else len(accepted)
        ),
        "avg_position": summary.get("avg_position"),
        "error": summary.get("error"),
        "elapsed_sec": round(time.time() - t0, 2),
        "tw_sharpe": tw.get("tw_sharpe"),
        "tw_score": tw.get("tw_score"),
        "tw_penalty": tw.get("tw_penalty"),
        "recent2y_sharpe": (tw.get("recent2y") or {}).get("sharpe"),
        "recent2y_return": (tw.get("recent2y") or {}).get("total_return"),
        "recent2y_max_dd": (tw.get("recent2y") or {}).get("max_drawdown"),
        "late_sharpe": tw.get("late_sharpe"),
        "late_return": tw.get("late_return"),
        "mid_sharpe": tw.get("mid_sharpe"),
        "early_sharpe": tw.get("early_sharpe"),
        "segments": tw.get("segments"),
        "tw_flags": tw.get("tw_flags") or [],
    }
    out["overfit_flags"] = _overfit_flags(out, tw)
    out["ok"] = out.get("error") is None and out.get("sharpe") is not None
    # 硬剔除：虚高远年 + 近年崩
    out["rejected"] = "early_inflated_recent_poor" in (out.get("overfit_flags") or [])
    return out


def build_universes(force: bool = False) -> Dict[str, Any]:
    cache = kit.shared_cache_dir()
    meta: Dict[str, Any] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "csindex_cons_xls_static",
        "survivor_bias_note": "静态「今天成分」有幸存者偏差；挖掘阶段先用静态，未用 PIT",
        "universes": {},
    }
    for u in UNIVERSES:
        codes = kit.fetch_universe_codes(u, kit.RateLimiter(0.01), cache, force=force)
        daily = cache / "daily"
        have = sum(1 for c in codes if (daily / f"{c.replace('.', '_')}.parquet").exists())
        profit = cache / "profit"
        have_p = sum(1 for c in codes if (profit / f"{c.replace('.', '_')}.parquet").exists())
        meta["universes"][u] = {
            "n_codes": len(codes),
            "n_daily": have,
            "n_profit": have_p,
            "bench": BENCH[u],
        }
        print(f"[universe] {u}: n={len(codes)} daily={have} profit={have_p}", flush=True)
        if fin_db.db_available():
            stats = fin_db.export_profit_cache_from_fin_db(
                profit, codes=codes, only_missing=True
            )
            print(f"[profit-export] {u}: {stats}", flush=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "universes_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def _rank_key(r: Dict[str, Any]) -> Tuple[float, float, float]:
    if not r.get("ok") or r.get("rejected"):
        return (-999.0, -999.0, -999.0)
    flags = r.get("overfit_flags") or []
    hard = [f for f in flags if f.startswith("few_legs") or f.startswith("sus_")]
    if hard:
        return (-500.0, float(r.get("tw_score") or -999), float(r.get("recent2y_sharpe") or -999))
    return (
        float(r.get("tw_score") if r.get("tw_score") is not None else -999),
        float(r.get("recent2y_sharpe") if r.get("recent2y_sharpe") is not None else -999),
        float(r.get("sharpe") or -999),
    )


def mine_universe(
    universe: str,
    grid: List[GridRow],
    dedup: Optional[DedupIndex] = None,
) -> Dict[str, Any]:
    print(f"\n======== mine round2 {universe} ========", flush=True)
    base = _base(universe)
    need_growth = any(g[5] for g in grid)
    need_fin = any(g[6] for g in grid)
    need_bal = any(g[7] for g in grid)
    panel = prepare_shared_panel(
        base,
        need_profit=True,
        need_growth=need_growth,
        need_fin_db=need_fin,
        need_balance=need_bal,
        limit=0,
    )
    print(
        f"[panel] {universe} n={len(panel)} fin_db={need_fin} balance={need_bal}",
        flush=True,
    )

    cache = kit.shared_cache_dir()
    bench_code = BENCH[universe]
    bench_path = cache / "daily" / f"{bench_code.replace('.', '_')}.parquet"
    if not bench_path.exists():
        print(f"[warn] bench {bench_code} missing, fallback sh.000300", flush=True)
        bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    skipped: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    n_eval = 0
    for i, (cfg_id, family, fn, extra, _np, _ng, _nf, _nb) in enumerate(grid, 1):
        params = {**base, **extra, "bench_code": BENCH[universe]}
        params["_cache_dir"] = str(cache)
        if dedup is not None:
            skip, reason, hit = dedup.check(fn, universe, {**extra, "universe": universe})
            if skip:
                skipped.append(
                    {
                        "cfg_id": cfg_id,
                        "family": family,
                        "signal": getattr(fn, "__name__", str(fn)),
                        "reason": reason,
                        "hit_factor_id": (hit or {}).get("factor_id"),
                        "hit_source": (hit or {}).get("source"),
                    }
                )
                print(
                    f"  [{i}/{len(grid)}] SKIP {cfg_id}: {reason}",
                    flush=True,
                )
                continue
        n_eval += 1
        try:
            row = _eval_one(cfg_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": cfg_id,
                "family": family,
                "universe": universe,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "rejected": True,
                "traceback": traceback.format_exc()[-800:],
            }
        results.append(row)
        if dedup is not None and row.get("ok"):
            dedup.add_seen(fn, universe, {**extra, "universe": universe}, factor_id=cfg_id)
        print(
            f"  [{i}/{len(grid)}] {cfg_id}: tw={row.get('tw_score')} "
            f"full_sh={row.get('sharpe')} r2y_sh={row.get('recent2y_sharpe')} "
            f"r2y_ret={row.get('recent2y_return')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('overfit_flags')}",
            flush=True,
        )

    ranked = sorted(results, key=_rank_key, reverse=True)
    ok_clean = [
        r
        for r in ranked
        if r.get("ok")
        and not r.get("rejected")
        and not any(
            str(f).startswith("few_legs") or str(f).startswith("sus_")
            for f in (r.get("overfit_flags") or [])
        )
    ]
    top = ok_clean[:TOP_N]
    if len(top) < TOP_N:
        extra_rows = [
            r for r in ranked if r.get("ok") and r not in top and not r.get("rejected")
        ]
        top = (top + extra_rows)[:TOP_N]

    udir = OUT_ROOT / universe
    udir.mkdir(parents=True, exist_ok=True)
    payload = {
        "universe": universe,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_panel": len(panel),
        "n_cfgs_grid": len(grid),
        "n_cfgs": len(results),
        "n_skipped": len(skipped),
        "skipped": skipped,
        "min_accepted_legs": MIN_ACCEPTED_LEGS,
        "time_weight": {
            "segments": [
                {"label": a, "start": b, "end": c, "weight": d} for a, b, c, d in SEGMENTS
            ],
            "recent2y_cut": RECENT2Y_CUT,
            "primary_metric": "tw_score = weighted_segment_sharpe - penalty",
        },
        "survivor_bias_note": "静态成分；非 PIT",
        "top": top,
        "ranked_by_tw": [
            {
                k: r.get(k)
                for k in (
                    "cfg_id",
                    "family",
                    "tw_score",
                    "tw_sharpe",
                    "tw_penalty",
                    "sharpe",
                    "total_return",
                    "recent2y_sharpe",
                    "recent2y_return",
                    "late_sharpe",
                    "mid_sharpe",
                    "early_sharpe",
                    "n_legs_accepted",
                    "max_drawdown",
                    "overfit_flags",
                    "rejected",
                    "signal",
                )
            }
            for r in ranked
            if r.get("ok")
        ][:20],
        "all": results,
    }
    (udir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _write_universe_md(universe, payload)
    return payload


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "-"
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _write_universe_md(universe: str, payload: Dict[str, Any]) -> Path:
    lines = [
        f"# Round2 · {universe}",
        "",
        f"- 时间：{payload.get('built_at')}",
        f"- panel={payload.get('n_panel')} eval={payload.get('n_cfgs')} "
        f"skip={payload.get('n_skipped')} grid={payload.get('n_cfgs_grid')}",
        "- 主分：`tw_score` = 0.2*Sh(2018-21)+0.3*Sh(2022-23)+0.5*Sh(2024+) - penalty",
        f"- 近2年切：`{RECENT2Y_CUT}`~今；虚高远年+近年崩 -> 剔除",
        "",
    ]
    skipped = payload.get("skipped") or []
    if skipped:
        lines.append(f"## 已跳过（n={len(skipped)}）")
        lines.append("")
        for s in skipped:
            lines.append(
                f"- `{s.get('cfg_id')}` <- {s.get('reason')} "
                f"(hit `{s.get('hit_factor_id')}` / {s.get('hit_source')})"
            )
        lines.append("")
    lines.extend(
        [
            "## Top（按 tw_score）",
            "",
            "| # | cfg | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | legs | flags |",
            "|---|-----|----------|---------|----------|--------|--------|------|-------|",
        ]
    )
    for i, r in enumerate(payload.get("top") or [], 1):
        lines.append(
            f"| {i} | `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
            f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
            f"{r.get('n_legs_accepted')} | {r.get('overfit_flags') or []} |"
        )
    lines.append("")
    lines.append("## Ranked（前 12，按 tw）")
    lines.append("")
    for r in (payload.get("ranked_by_tw") or [])[:12]:
        lines.append(
            f"- `{r.get('cfg_id')}` tw={_fmt(r.get('tw_score'))} "
            f"full={_fmt(r.get('sharpe'))}/{_fmt(r.get('total_return'))} "
            f"r2y={_fmt(r.get('recent2y_sharpe'))}/{_fmt(r.get('recent2y_return'))} "
            f"seg(sh)={_fmt(r.get('early_sharpe'))}/{_fmt(r.get('mid_sharpe'))}/{_fmt(r.get('late_sharpe'))} "
            f"legs={r.get('n_legs_accepted')} flags={r.get('overfit_flags')}"
        )
    path = OUT_ROOT / universe / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_round_summary(all_univ: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# 三宇宙分挖因子 · Round2（时间加权 + 去重）",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 行情：腾讯前复权 `_shared/daily`；BaoStock 禁用",
        "- 成分：中证官网静态 xls（**幸存者偏差**；非 PIT）",
        "- Mongo：未写入（先挖再选择性入库；入库前再 fingerprint 校验）",
        "- 去重：`scripts/mine_factor_dedup.py`（Mongo + FACTOR_IMPL + mine_* + overnight_keep + 锚点#166/#168/#171/meanrev）",
        "",
        "## 时间加权规则",
        "",
        "| 分段 | 区间 | 权重 |",
        "|------|------|------|",
        "| early | 2018-2021 | 0.20 |",
        "| mid | 2022-2023 | 0.30 |",
        "| late | 2024-今 | 0.50 |",
        "",
        f"- 近2年窗口：`{RECENT2Y_CUT}`~样本末",
        "- 过滤：近2年大幅亏损且 2018-21 Sharpe 虚高 -> `early_inflated_recent_poor` 剔除",
        "- **主排序键**：`tw_score`；辅看近2年 Sharpe/收益",
        "",
        "## 各宇宙 Top",
        "",
    ]
    global_rows: List[Dict[str, Any]] = []
    all_skips: List[Dict[str, Any]] = []
    for u in UNIVERSES:
        payload = all_univ.get(u) or {}
        lines.append(f"### {u}")
        sk = payload.get("skipped") or []
        if sk:
            lines.append(f"- skip={len(sk)} / grid={payload.get('n_cfgs_grid')} / eval={payload.get('n_cfgs')}")
            for s in sk[:8]:
                lines.append(
                    f"  - SKIP `{s.get('cfg_id')}` <- {s.get('reason')}"
                )
            if len(sk) > 8:
                lines.append(f"  - ... 另有 {len(sk) - 8} 项，见 `{u}/SUMMARY.md`")
            all_skips.extend([{**s, "universe": u} for s in sk])
        tops = payload.get("top") or []
        if not tops:
            lines.append("- （尚未完成 / 无合格）")
            lines.append("")
            continue
        lines.append(
            "| cfg | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | late_sh | legs |"
        )
        lines.append(
            "|-----|----------|---------|----------|--------|--------|---------|------|"
        )
        for r in tops:
            lines.append(
                f"| `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
                f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
                f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
                f"{_fmt(r.get('late_sharpe'))} | {r.get('n_legs_accepted')} |"
            )
            global_rows.append({**r, "universe": u})
        lines.append("")

    global_rows = [
        r
        for r in global_rows
        if r.get("ok") is not False
        and not r.get("rejected")
        and (r.get("recent2y_sharpe") is None or float(r.get("recent2y_sharpe") or -9) > -0.1)
    ]
    global_rows.sort(
        key=lambda r: (
            float(r.get("tw_score") or -999),
            float(r.get("recent2y_sharpe") or -999),
        ),
        reverse=True,
    )
    lines.append("## 全局 Top 候选（近2年不崩优先，未入库，已去重）")
    lines.append("")
    lines.append(
        "| univ | cfg | tw_score | full_sh | r2y_sh | r2y_ret | family | legs |"
    )
    lines.append("|------|-----|----------|---------|--------|--------|--------|------|")
    for r in global_rows[:12]:
        lines.append(
            f"| {r.get('universe')} | `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('family')} | {r.get('n_legs_accepted')} |"
        )
    lines.append("")
    lines.append(f"## 本轮累计 skip（n={len(all_skips)}）")
    lines.append("")
    lines.append("完整库存见 `EXISTING_INVENTORY.md`。经典锚点 #166/#168/#171 与 meanrev 不作为新发现。")
    lines.append("")
    lines.append("## 说明")
    lines.append("- Round1 主看全样本 Sharpe；本轮主看时间加权 + 近2年")
    lines.append("- dual_improve meanrev 留给并行任务；已删 meanrev 亦不反复报")
    lines.append("- 入库前：`DedupIndex.check` + `max(序号)+1`；宁少勿滥")

    path = OUT_ROOT / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "round2_index.json").write_text(
        json.dumps(
            {
                "out_root": str(OUT_ROOT),
                "time_weight": {
                    "segments": [
                        {"label": a, "start": b, "end": c, "weight": d}
                        for a, b, c, d in SEGMENTS
                    ],
                    "recent2y_cut": RECENT2Y_CUT,
                },
                "skipped": all_skips,
                "universes": {
                    u: {
                        "top": [
                            {
                                "cfg_id": r.get("cfg_id"),
                                "tw_score": r.get("tw_score"),
                                "sharpe": r.get("sharpe"),
                                "recent2y_sharpe": r.get("recent2y_sharpe"),
                                "recent2y_return": r.get("recent2y_return"),
                                "n_legs_accepted": r.get("n_legs_accepted"),
                            }
                            for r in ((all_univ.get(u) or {}).get("top") or [])
                        ],
                        "n_cfgs": (all_univ.get(u) or {}).get("n_cfgs"),
                        "n_skipped": (all_univ.get(u) or {}).get("n_skipped"),
                    }
                    for u in UNIVERSES
                },
                "global_top": [
                    {
                        "universe": r.get("universe"),
                        "cfg_id": r.get("cfg_id"),
                        "tw_score": r.get("tw_score"),
                        "sharpe": r.get("sharpe"),
                        "recent2y_sharpe": r.get("recent2y_sharpe"),
                        "recent2y_return": r.get("recent2y_return"),
                    }
                    for r in global_rows[:12]
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default=",".join(UNIVERSES))
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()
    univs = [u.strip() for u in args.universes.split(",") if u.strip()]

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    inv = build_inventory()
    inv_path = write_inventory_markdown(inv, OUT_ROOT / "EXISTING_INVENTORY.md")
    dedup = DedupIndex(inv)
    print(
        f"[dedup] records={inv.get('n_records')} fps={inv.get('n_unique_fp')} "
        f"families={inv.get('n_unique_family')} -> {inv_path}",
        flush=True,
    )

    build_universes(force=not args.skip_build)

    grid = _grid()
    print(f"[grid] n_cfgs={len(grid)} (novel; duplicates skipped at runtime)", flush=True)

    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in UNIVERSES:
        prev = OUT_ROOT / u / "results.json"
        # hs300 首波保留；本轮 novel 结果写到 wave2 子目录以免覆盖
        if prev.exists() and u not in univs:
            try:
                all_univ[u] = json.loads(prev.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass

    for u in univs:
        # novel 轮写入 {universe}_novel，同时更新主 SUMMARY 合并视角
        payload = mine_universe(u, grid, dedup=dedup)
        novel_dir = OUT_ROOT / f"{u}_novel"
        novel_dir.mkdir(parents=True, exist_ok=True)
        (novel_dir / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        # 宇宙主目录也更新为最新 novel（保留旧 hs300 到 hs300_wave1）
        wave1 = OUT_ROOT / u / "results.json"
        if wave1.exists() and u == "hs300":
            bak = OUT_ROOT / "hs300_wave1"
            bak.mkdir(parents=True, exist_ok=True)
            if not (bak / "results.json").exists():
                (bak / "results.json").write_text(
                    wave1.read_text(encoding="utf-8"), encoding="utf-8"
                )
                w1sum = OUT_ROOT / u / "SUMMARY.md"
                if w1sum.exists():
                    (bak / "SUMMARY.md").write_text(
                        w1sum.read_text(encoding="utf-8"), encoding="utf-8"
                    )
        all_univ[u] = payload
        summary = write_round_summary(all_univ)
        print(f"[checkpoint] {u} -> {summary}", flush=True)

    summary = write_round_summary(all_univ)
    print(f"\n[done] summary -> {summary}", flush=True)
    try:
        print(summary.read_text(encoding="utf-8"), flush=True)
    except UnicodeEncodeError:
        print(summary.read_text(encoding="utf-8").encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)


if __name__ == "__main__":
    main()
