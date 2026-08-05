"""利润因果链 Round1：L2 驱动变量组合/二阶（时间加权 + 去重）。

因果：利润 ≈ 收入 × 利润率 → 挖合同负债 YoY 加速、毛利×营收双击、
费用率下行×营收加速、存货/应收强度改善等；与 #198–#200 纯 YoY 正交。

- 主分 = 0.2×Sh(2018–21)+0.3×Sh(2022–23)+0.5×Sh(2024+)
- 去重：Mongo + 锚点 + mine_*；默认不写 Mongo
- 产物：data/factors/mine_profit_causal_round1/
- 腾讯 qfq；BaoStock 禁用；本地财务库派生 fin_opex_ratio 等

用法:
  .venv\\Scripts\\python.exe scripts/mine_profit_causal_round1.py --skip-build
  .venv\\Scripts\\python.exe scripts/mine_profit_causal_round1.py --universes hs300 --skip-build
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
from mine_factor_dedup import DedupIndex, build_inventory, write_inventory_markdown  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_profit_causal_round1"
START = "2018-01-01"
MIN_ACCEPTED_LEGS = 25
TOP_N = 5
RECENT2Y_CUT = "2024-08-01"

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

SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame]
# cfg_id, family, fn, extras, need_profit, need_growth, need_fin_db, need_balance
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


def _exit_pack(
    hold: int,
    sl: float = 0.12,
    tp: float = 0.30,
    lag: int = 28,
    brk: int = 60,
    entry: str = "break",
    **more: Any,
) -> Dict[str, Any]:
    return {
        "funda_lag": lag,
        "break_days": brk,
        "hold_days": hold,
        "stop_loss": sl,
        "take_profit": tp,
        "entry": entry,
        **more,
    }


def _grid() -> List[GridRow]:
    """因果 L2 网格：参数刻意避开 #198–#200 / gross_expand / dual_improve / cl 水平扩张指纹。"""
    rows: List[GridRow] = []

    # ---- 合同负债 YoY 二阶加速（非 yoy_min 水平单闸）----
    for tag, extra in [
        (
            "clacc08_y10_brk60_h40",
            _exit_pack(40, tp=0.30, lag=28, brk=60, entry="break", cl_accel=0.08, yoy_min=0.10),
        ),
        (
            "clacc12_y15_brk70_h45",
            _exit_pack(45, tp=0.32, lag=26, brk=70, entry="break", cl_accel=0.12, yoy_min=0.15, np_min=0.04),
        ),
        (
            "clacc08_y10_pull_h38",
            _exit_pack(
                38, tp=0.28, lag=30, brk=60, entry="pullback", cl_accel=0.08, yoy_min=0.10, dd_need=0.03
            ),
        ),
    ]:
        rows.append(
            (f"cl_yoy_acc__{tag}", "cl_yoy_accel", sig.signal_cl_yoy_accel_break, extra, True, False, True, False)
        )

    # ---- 毛利 + 营收双击 ----
    for tag, extra in [
        (
            "gp05_ry08_brk60_h42",
            _exit_pack(
                42,
                tp=0.30,
                lag=28,
                brk=60,
                entry="break",
                gp_improve=0.005,
                rev_yoy_min=0.08,
                margin_min=0.14,
                np_min=0.05,
            ),
        ),
        (
            "gp06_ry10_racc04_brk55_h45",
            _exit_pack(
                45,
                tp=0.32,
                lag=29,
                brk=55,
                entry="break",
                gp_improve=0.006,
                rev_yoy_min=0.10,
                growth_accel=0.04,
                margin_min=0.15,
                np_min=0.06,
            ),
        ),
        (
            "gp05_ry08_pull_h40",
            _exit_pack(
                40,
                tp=0.28,
                lag=30,
                brk=60,
                entry="pullback",
                gp_improve=0.005,
                rev_yoy_min=0.08,
                margin_min=0.14,
                dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (f"gp_rev_dual__{tag}", "gp_rev_dual", sig.signal_gp_rev_dual_hit_break, extra, True, False, True, False)
        )

    # ---- 费用率下行 + 营收加速 ----
    for tag, extra in [
        (
            "ox05_racc05_g06_brk60_h40",
            _exit_pack(
                40,
                tp=0.30,
                lag=28,
                brk=60,
                entry="break",
                opex_improve=0.005,
                growth_accel=0.05,
                growth_min=0.06,
                opex_max=0.40,
            ),
        ),
        (
            "ox08_racc06_g08_brk70_h45_np04",
            _exit_pack(
                45,
                tp=0.32,
                lag=26,
                brk=70,
                entry="break",
                opex_improve=0.008,
                growth_accel=0.06,
                growth_min=0.08,
                opex_max=0.35,
                np_min=0.04,
            ),
        ),
        (
            "ox05_racc05_pull_h38",
            _exit_pack(
                38,
                tp=0.28,
                lag=30,
                brk=60,
                entry="pullback",
                opex_improve=0.005,
                growth_accel=0.05,
                growth_min=0.06,
                dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (
                f"opex_rev__{tag}",
                "opex_down_rev",
                sig.signal_opex_down_rev_accel_break,
                extra,
                True,
                False,
                True,
                False,
            )
        )

    # ---- 存货强度下行 + 营收 ----
    for tag, extra in [
        (
            "inv02_ry05_brk60_h40",
            _exit_pack(40, tp=0.30, lag=28, brk=60, entry="break", inv_improve=0.02, growth_min=0.05, inv_max=0.90),
        ),
        (
            "inv03_ry08_brk55_h42_np04",
            _exit_pack(
                42,
                tp=0.30,
                lag=29,
                brk=55,
                entry="break",
                inv_improve=0.03,
                growth_min=0.08,
                inv_max=0.70,
                np_min=0.04,
            ),
        ),
    ]:
        rows.append(
            (
                f"inv_delever__{tag}",
                "inv_delever_rev",
                sig.signal_inv_delever_rev_break,
                extra,
                True,
                False,
                True,
                False,
            )
        )

    # ---- 应收强度下行 + 营收 ----
    for tag, extra in [
        (
            "ar015_ry05_brk60_h40",
            _exit_pack(40, tp=0.30, lag=28, brk=60, entry="break", ar_improve=0.015, growth_min=0.05, ar_max=0.55),
        ),
        (
            "ar02_ry08_brk70_h42",
            _exit_pack(42, tp=0.30, lag=26, brk=70, entry="break", ar_improve=0.02, growth_min=0.08, ar_max=0.45, np_min=0.04),
        ),
    ]:
        rows.append(
            (
                f"ar_tighten__{tag}",
                "ar_tighten_rev",
                sig.signal_ar_tighten_rev_break,
                extra,
                True,
                False,
                True,
                False,
            )
        )

    return rows


def _slice_stats(daily: pd.DataFrame, start: str, end: Optional[str]) -> Dict[str, Any]:
    if daily is None or daily.empty or "date" not in daily.columns:
        return {"empty": True}
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    t0 = pd.Timestamp(start)
    t1 = pd.Timestamp(end) if end else d["date"].max()
    w = d[(d["date"] >= t0) & (d["date"] <= t1)]
    if w.empty or "equity" not in w.columns:
        return {"empty": True, "start": start, "end": str(end)}
    eq = pd.to_numeric(w["equity"], errors="coerce").dropna()
    if len(eq) < 5:
        return {"empty": True, "n": len(eq)}
    ret = eq.pct_change().dropna()
    if ret.empty:
        return {"empty": True}
    vol = float(ret.std())
    sharpe = float(ret.mean() / vol * (252**0.5)) if vol > 1e-12 else None
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    peak = eq.cummax()
    dd = float(((eq - peak) / peak.replace(0, pd.NA)).min())
    return {
        "empty": False,
        "start": str(w["date"].iloc[0].date()),
        "end": str(w["date"].iloc[-1].date()),
        "sharpe": sharpe,
        "total_return": total_return,
        "max_drawdown": dd,
        "n_bars": int(len(w)),
    }


def _time_weight_score(daily: pd.DataFrame) -> Dict[str, Any]:
    segs: Dict[str, Any] = {}
    tw = 0.0
    wsum = 0.0
    for label, a, b, w in SEGMENTS:
        st = _slice_stats(daily, a, b)
        segs[label] = st
        sh = st.get("sharpe")
        if sh is not None and not st.get("empty"):
            tw += float(sh) * w
            wsum += w
    tw_sharpe = (tw / wsum) if wsum > 0 else None
    recent2y = _slice_stats(daily, RECENT2Y_CUT, None)
    early = segs.get("y2018_2021") or {}
    mid = segs.get("y2022_2023") or {}
    late = segs.get("y2024_now") or {}
    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    early_sh = early.get("sharpe")
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")
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
    out["rejected"] = "early_inflated_recent_poor" in (out.get("overfit_flags") or [])
    return out


def build_universes(force: bool = False) -> Dict[str, Any]:
    cache = kit.shared_cache_dir()
    meta: Dict[str, Any] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "csindex_cons_xls_static",
        "survivor_bias_note": "静态「今天成分」有幸存者偏差；挖掘阶段先用静态，未用 PIT",
        "universes": {},
        "downloads": [],
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
            stats = fin_db.export_profit_cache_from_fin_db(profit, codes=codes, only_missing=True)
            print(f"[profit-export] {u}: {stats}", flush=True)
            meta["downloads"].append({"kind": "profit_export_from_fin_db", "universe": u, "stats": stats})
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
    print(f"\n======== mine profit_causal r1 {universe} ========", flush=True)
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
    print(f"[panel] {universe} n={len(panel)} fin_db={need_fin}", flush=True)
    if panel:
        sample = next(iter(panel.values()))
        cols = [
            c
            for c in (
                "gpMargin",
                "fin_rev_yoy",
                "fin_opex_ratio",
                "fin_inv_to_rev",
                "fin_ar_to_rev",
                "contract_liab_yoy",
                "contract_liab_yoy_accel",
            )
            if c in sample.columns
        ]
        print(f"[panel-cols] sample has: {cols}", flush=True)

    cache = kit.shared_cache_dir()
    bench_code = BENCH[universe]
    bench_path = cache / "daily" / f"{bench_code.replace('.', '_')}.parquet"
    if not bench_path.exists():
        bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    skipped: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
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
                print(f"  [{i}/{len(grid)}] SKIP {cfg_id}: {reason}", flush=True)
                continue
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
        # 增量落盘，避免长跑中断丢结果
        try:
            udir = OUT_ROOT / universe
            udir.mkdir(parents=True, exist_ok=True)
            (udir / "results_partial.json").write_text(
                json.dumps({"universe": universe, "n": len(results), "all": results}, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

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
        extra_rows = [r for r in ranked if r.get("ok") and r not in top and not r.get("rejected")]
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
        "causal_口径": {
            "fin_opex_ratio": "(销售费用+管理费用)/营业收入",
            "fin_inv_to_rev": "存货/营业收入",
            "fin_ar_to_rev": "应收账款/营业收入",
            "contract_liab_yoy_accel": "合同负债 YoY 的相邻报告差分",
            "gp_rev_dual": "gpMargin 环比升 × fin_rev_yoy",
        },
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
        f"# Profit Causal Round1 · {universe}",
        "",
        f"- 时间：{payload.get('built_at')}",
        f"- panel={payload.get('n_panel')} eval={payload.get('n_cfgs')} "
        f"skip={payload.get('n_skipped')} grid={payload.get('n_cfgs_grid')}",
        "- 主分：`tw_score` = 0.2*Sh(2018-21)+0.3*Sh(2022-23)+0.5*Sh(2024+) - penalty",
        f"- 近2年切：`{RECENT2Y_CUT}`~今",
        "",
        "## Top（按 tw_score）",
        "",
        "| # | cfg | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | legs | flags |",
        "|---|-----|----------|---------|----------|--------|--------|------|-------|",
    ]
    for i, r in enumerate(payload.get("top") or [], 1):
        lines.append(
            f"| {i} | `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
            f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
            f"{r.get('n_legs_accepted')} | {r.get('overfit_flags') or []} |"
        )
    lines.append("")
    path = OUT_ROOT / universe / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_round_summary(all_univ: Dict[str, Dict[str, Any]], univ_meta: Dict[str, Any]) -> Path:
    lines = [
        "# 利润因果链挖掘 · Round1（时间加权 + 去重）",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 因果树：`CAUSAL_TREE.md`",
        "- 行情：腾讯前复权 `_shared/daily`；BaoStock 禁用",
        "- 成分：中证官网静态 xls（**幸存者偏差**；非 PIT）",
        "- 财务：本地 `1.0_A股财务数据库.db` → 派生 `fin_opex_ratio` / `fin_inv_to_rev` / `fin_ar_to_rev`",
        "- Mongo：未写入（先挖再选择性入库；下一号 ≥201；不覆盖 #188/#189）",
        "- 去重：`scripts/mine_factor_dedup.py`",
        "",
        "## 下载了什么",
        "",
        "- **未新下东财/akshare**：本轮派生字段均可由本地三大表计算",
        "- profit cache：仅 `export_profit_cache_from_fin_db(only_missing=True)` 补洞（若有）",
        f"- universes_meta.downloads：`{json.dumps(univ_meta.get('downloads') or [], ensure_ascii=False)[:500]}`",
        "",
        "## 因果 → 信号族",
        "",
        "| family | 因果含义 | signal |",
        "|--------|----------|--------|",
        "| cl_yoy_accel | 合同负债 YoY 二阶（需求领先加速） | `signal_cl_yoy_accel_break` |",
        "| gp_rev_dual | 毛利↑ × 营收 YoY（收入×利润率双击） | `signal_gp_rev_dual_hit_break` |",
        "| opex_down_rev | 费用率↓ × 营收加速（规模/效率） | `signal_opex_down_rev_accel_break` |",
        "| inv_delever_rev | 存货强度↓ × 营收 | `signal_inv_delever_rev_break` |",
        "| ar_tighten_rev | 应收强度↓ × 营收 | `signal_ar_tighten_rev_break` |",
        "",
        "## 时间加权",
        "",
        "| 分段 | 区间 | 权重 |",
        "|------|------|------|",
        "| early | 2018-2021 | 0.20 |",
        "| mid | 2022-2023 | 0.30 |",
        "| late | 2024-今 | 0.50 |",
        "",
        f"- 近2年窗口：`{RECENT2Y_CUT}`~样本末",
        "- **主排序键**：`tw_score`",
        "",
        "## 各宇宙 Top",
        "",
    ]
    global_rows: List[Dict[str, Any]] = []
    for u in UNIVERSES:
        p = all_univ.get(u) or {}
        lines.append(f"### {u}")
        lines.append(
            f"- skip={p.get('n_skipped')} / grid={p.get('n_cfgs_grid')} / eval={p.get('n_cfgs')}"
        )
        for s in p.get("skipped") or []:
            lines.append(f"  - SKIP `{s.get('cfg_id')}` <- {s.get('reason')}")
        lines.append(
            "| cfg | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | late_sh | legs |"
        )
        lines.append(
            "|-----|----------|---------|----------|--------|--------|---------|------|"
        )
        for r in p.get("top") or []:
            lines.append(
                f"| `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
                f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
                f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
                f"{_fmt(r.get('late_sharpe'))} | {r.get('n_legs_accepted')} |"
            )
            if r.get("ok") and not r.get("rejected"):
                global_rows.append({**r, "universe": u})
        lines.append("")

    global_rows = sorted(global_rows, key=_rank_key, reverse=True)
    lines.extend(
        [
            "## 全局 Top 候选（近2年不崩优先，未入库，已去重）",
            "",
            "| univ | cfg | tw_score | full_sh | r2y_sh | r2y_ret | family | legs |",
            "|------|-----|----------|---------|--------|--------|--------|------|",
        ]
    )
    for r in global_rows[:12]:
        lines.append(
            f"| {r.get('universe')} | `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('family')} | {r.get('n_legs_accepted')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 与 #188/#189 IPO、#198–#200 YoY 并行；本目录独立，不覆盖",
            "- 入库前：`DedupIndex.check` + `max(序号)+1`（≥201）；宁少勿滥",
            "- 成分：静态 xls **幸存者偏差**（非 PIT）",
            "",
        ]
    )
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    top_payload = [
        {
            k: r.get(k)
            for k in (
                "universe",
                "cfg_id",
                "family",
                "signal",
                "tw_score",
                "sharpe",
                "total_return",
                "recent2y_sharpe",
                "recent2y_return",
                "n_legs_accepted",
                "overfit_flags",
                "params",
            )
        }
        for r in global_rows[:20]
    ]
    (OUT_ROOT / "global_top.json").write_text(
        json.dumps(top_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default="hs300,csi500,csi1000")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--force-build", action="store_true")
    args = ap.parse_args()

    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    univs = [u.strip() for u in str(args.universes).split(",") if u.strip()]
    for u in univs:
        if u not in UNIVERSES:
            raise SystemExit(f"unknown universe: {u}")

    print("[dedup] building inventory...", flush=True)
    inv = build_inventory()
    (OUT_ROOT / "existing_inventory.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_inventory_markdown(inv, OUT_ROOT / "EXISTING_INVENTORY.md")
    dedup = DedupIndex(inv)

    univ_meta: Dict[str, Any] = {}
    if not args.skip_build:
        univ_meta = build_universes(force=args.force_build)
    elif (OUT_ROOT / "universes_meta.json").exists():
        univ_meta = json.loads((OUT_ROOT / "universes_meta.json").read_text(encoding="utf-8"))
    else:
        univ_meta = build_universes(force=False)

    grid = _grid()
    print(f"[grid] n={len(grid)} families={sorted({g[1] for g in grid})}", flush=True)

    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in univs:
        all_univ[u] = mine_universe(u, grid, dedup=dedup)

    path = write_round_summary(all_univ, univ_meta)
    print(f"\n[done] summary -> {path}", flush=True)


if __name__ == "__main__":
    main()
