"""营收/净利 YoY 增速及其变化趋势 · Round1（时间加权 + 去重）。

角度：
- 净利 YoY（growth.YOYNI）再加速 / 由负转正 / 连续两季改善
- 单季净利 YoY（fin_db q_np_yoy）再加速（非 q_np_gap 断层）
- 累计营收 YoY（fin_rev_yoy）再加速；营收+净利双加速
- 技术：突破 / 回踩（entry=break|pullback）

- 主分 = 0.2×Sh(2018–21)+0.3×Sh(2022–23)+0.5×Sh(2024+)
- 近2年大幅亏损且远年虚高 → 剔除
- 去重：Mongo + 锚点 + mine_*；不写 Mongo
- 产物：data/factors/mine_yoy_accel_round1/
- 静态成分有幸存者偏差（非 PIT）；腾讯 qfq；BaoStock 禁用

用法:
  .venv\\Scripts\\python.exe scripts/mine_yoy_accel_round1.py --skip-build
  .venv\\Scripts\\python.exe scripts/mine_yoy_accel_round1.py --universes hs300 --skip-build
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

OUT_ROOT = ROOT / "data" / "factors" / "mine_yoy_accel_round1"
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
    """YoY 趋势新结构网格（参数刻意避开 overnight dual_yoy / q_np_gap 指纹）。"""
    rows: List[GridRow] = []

    # ---- 净利 YoY（YOYNI）再加速 ----
    for tag, extra, ng, nf in [
        (
            "accel05_g08_brk60_h40",
            _exit_pack(
                40, tp=0.30, lag=28, brk=60, entry="break",
                growth_accel=0.05, growth_min=0.08,
            ),
            True,
            False,
        ),
        (
            "accel08_g10_brk80_h45",
            _exit_pack(
                45, tp=0.32, lag=26, brk=80, entry="break",
                growth_accel=0.08, growth_min=0.10, roe_min=0.08,
            ),
            True,
            False,
        ),
        (
            "accel05_g08_pull_h38",
            _exit_pack(
                38, tp=0.28, lag=30, brk=60, entry="pullback",
                growth_accel=0.05, growth_min=0.08, dd_need=0.03,
            ),
            True,
            False,
        ),
        (
            "accel06_g12_brk55_h42_np06",
            _exit_pack(
                42, tp=0.30, lag=29, brk=55, entry="break",
                growth_accel=0.06, growth_min=0.12, np_min=0.06,
            ),
            True,
            False,
        ),
    ]:
        rows.append(
            (
                f"ni_yoy_acc__{tag}",
                "ni_yoy_accel",
                sig.signal_ni_yoy_accel_break,
                extra,
                True,
                ng,
                nf,
                False,
            )
        )

    # ---- 由负转正 ----
    for tag, extra in [
        (
            "turn0_jump05_brk60_h40",
            _exit_pack(
                40, tp=0.30, lag=28, brk=60, entry="break",
                turn_from=0.0, turn_to=0.0, growth_accel=0.05,
            ),
        ),
        (
            "turn0_to05_brk70_h45",
            _exit_pack(
                45, tp=0.32, lag=26, brk=70, entry="break",
                turn_from=0.0, turn_to=0.05, growth_accel=0.08,
            ),
        ),
        (
            "turn0_pull_h36",
            _exit_pack(
                36, tp=0.28, lag=30, brk=60, entry="pullback",
                turn_from=0.0, turn_to=0.0, growth_accel=0.04, dd_need=0.035,
            ),
        ),
    ]:
        rows.append(
            (
                f"ni_yoy_turn__{tag}",
                "ni_yoy_turn",
                sig.signal_ni_yoy_turn_pos_break,
                extra,
                True,
                True,
                False,
                False,
            )
        )

    # ---- 连续两季改善 ----
    for tag, extra in [
        (
            "c2_step03_g05_brk60_h42",
            _exit_pack(
                42, tp=0.30, lag=28, brk=60, entry="break",
                growth_accel=0.03, growth_min=0.05,
            ),
        ),
        (
            "c2_step05_g08_brk80_h48",
            _exit_pack(
                48, tp=0.35, lag=27, brk=80, entry="break",
                growth_accel=0.05, growth_min=0.08, roe_min=0.06,
            ),
        ),
        (
            "c2_step03_pull_h40",
            _exit_pack(
                40, tp=0.28, lag=30, brk=60, entry="pullback",
                growth_accel=0.03, growth_min=0.06, dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (
                f"ni_yoy_c2__{tag}",
                "ni_yoy_consec2",
                sig.signal_ni_yoy_consec2_break,
                extra,
                True,
                True,
                False,
                False,
            )
        )

    # ---- 单季净利 YoY 再加速（fin_db；非 gap）----
    for tag, extra in [
        (
            "qacc10_g15_brk60_h38",
            _exit_pack(
                38, tp=0.30, lag=5, brk=60, entry="break",
                growth_accel=0.10, growth_min=0.15,
            ),
        ),
        (
            "qacc15_g20_brk80_h35",
            _exit_pack(
                35, tp=0.32, lag=4, brk=80, entry="break",
                growth_accel=0.15, growth_min=0.20,
            ),
        ),
        (
            "qacc08_g12_pull_h40",
            _exit_pack(
                40, tp=0.28, lag=6, brk=60, entry="pullback",
                growth_accel=0.08, growth_min=0.12, dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (
                f"q_np_yoy_acc__{tag}",
                "q_np_yoy_accel",
                sig.signal_q_np_yoy_accel_break,
                extra,
                False,
                False,
                True,
                False,
            )
        )

    # ---- 营收 YoY 再加速（fin_rev_yoy）----
    for tag, extra in [
        (
            "racc05_g08_brk60_h40",
            _exit_pack(
                40, tp=0.30, lag=28, brk=60, entry="break",
                growth_accel=0.05, growth_min=0.08,
            ),
        ),
        (
            "racc08_g10_brk70_h45",
            _exit_pack(
                45, tp=0.32, lag=26, brk=70, entry="break",
                growth_accel=0.08, growth_min=0.10,
            ),
        ),
        (
            "racc05_pull_h38",
            _exit_pack(
                38, tp=0.28, lag=30, brk=60, entry="pullback",
                growth_accel=0.05, growth_min=0.08, dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (
                f"rev_yoy_acc__{tag}",
                "rev_yoy_accel",
                sig.signal_rev_yoy_accel_break,
                extra,
                True,
                False,
                True,
                False,
            )
        )

    # ---- 营收+净利双加速 ----
    for tag, extra in [
        (
            "dual04_g06_brk60_h42",
            _exit_pack(
                42, tp=0.30, lag=28, brk=60, entry="break",
                growth_accel=0.04, growth_min=0.06,
            ),
        ),
        (
            "dual06_g08_brk80_h45",
            _exit_pack(
                45, tp=0.32, lag=27, brk=80, entry="break",
                growth_accel=0.06, growth_min=0.08, roe_min=0.06,
            ),
        ),
        (
            "dual04_pull_h40",
            _exit_pack(
                40, tp=0.28, lag=30, brk=60, entry="pullback",
                growth_accel=0.04, growth_min=0.06, dd_need=0.03,
            ),
        ),
    ]:
        rows.append(
            (
                f"dual_rev_np_yoy__{tag}",
                "dual_rev_np_yoy",
                sig.signal_dual_rev_np_yoy_accel_break,
                extra,
                True,
                True,
                True,
                False,
            )
        )

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
    }
    for u in UNIVERSES:
        codes = kit.fetch_universe_codes(u, kit.RateLimiter(0.01), cache, force=force)
        daily = cache / "daily"
        have = sum(1 for c in codes if (daily / f"{c.replace('.', '_')}.parquet").exists())
        profit = cache / "profit"
        have_p = sum(1 for c in codes if (profit / f"{c.replace('.', '_')}.parquet").exists())
        growth = cache / "growth"
        have_g = sum(1 for c in codes if (growth / f"{c.replace('.', '_')}.parquet").exists())
        meta["universes"][u] = {
            "n_codes": len(codes),
            "n_daily": have,
            "n_profit": have_p,
            "n_growth": have_g,
            "bench": BENCH[u],
        }
        print(
            f"[universe] {u}: n={len(codes)} daily={have} profit={have_p} growth={have_g}",
            flush=True,
        )
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
    print(f"\n======== mine yoy_accel r1 {universe} ========", flush=True)
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
        f"[panel] {universe} n={len(panel)} growth={need_growth} fin_db={need_fin}",
        flush=True,
    )
    # 抽样检查 YoY 列
    if panel:
        sample = next(iter(panel.values()))
        cols = [
            c
            for c in (
                "YOYNI",
                "fin_rev_yoy",
                "fin_np_yoy",
                "q_np_yoy",
                "q_np",
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
        "yoy_口径": {
            "YOYNI": "growth 缓存净利润同比（小数）",
            "fin_rev_yoy": "累计营业收入同报告期 YoY（正式报表）",
            "fin_np_yoy": "累计归母净利同报告期 YoY",
            "q_np_yoy": "单季净利 YoY（累计差分）",
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
        f"# YoY Accel Round1 · {universe}",
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


def write_round_summary(all_univ: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# 营收/净利 YoY 增速趋势挖掘 · Round1（时间加权 + 去重）",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 行情：腾讯前复权 `_shared/daily`；BaoStock 禁用",
        "- 成分：中证官网静态 xls（**幸存者偏差**；非 PIT）",
        "- Mongo：未写入（先挖再选择性入库；下一号 ≥197）",
        "- 去重：`scripts/mine_factor_dedup.py`",
        "",
        "## 口径",
        "",
        "| 字段 | 含义 |",
        "|------|------|",
        "| `YOYNI` | growth 净利润同比（小数） |",
        "| `fin_rev_yoy` | 累计营收同报告期 YoY（正式报表） |",
        "| `fin_np_yoy` | 累计归母净利同报告期 YoY |",
        "| `q_np_yoy` | 单季净利 YoY（累计差分；非预告） |",
        "| 二阶/加速 | 本期 YoY − 上期 YoY（披露事件对齐） |",
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
        "- **主排序键**：`tw_score`；辅看近2年 Sharpe/收益",
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
            lines.append(
                f"  - SKIP `{s.get('cfg_id')}` <- {s.get('reason')}"
            )
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
            f"{_fmt(r.get('recent2y_return'))} | {r.get('family')} | "
            f"{r.get('n_legs_accepted')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 与 #188 IPO / Round3 #189–#196 并行；本目录独立，不覆盖 188",
            "- 入库前：`DedupIndex.check` + `max(序号)+1`（≥197）；宁少勿滥",
            "- 成分：静态 xls **幸存者偏差**（非 PIT）",
            "",
        ]
    )
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "global_top.json").write_text(
        json.dumps(
            {
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "global_top": [
                    {
                        "universe": r.get("universe"),
                        "cfg_id": r.get("cfg_id"),
                        "family": r.get("family"),
                        "signal": r.get("signal"),
                        "tw_score": r.get("tw_score"),
                        "sharpe": r.get("sharpe"),
                        "recent2y_sharpe": r.get("recent2y_sharpe"),
                        "recent2y_return": r.get("recent2y_return"),
                        "n_legs_accepted": r.get("n_legs_accepted"),
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
        f"-> {inv_path}",
        flush=True,
    )
    build_universes(force=not args.skip_build)
    grid = _grid()
    print(f"[grid] n_cfgs={len(grid)}", flush=True)

    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in UNIVERSES:
        prev = OUT_ROOT / u / "results.json"
        if prev.exists() and u not in univs:
            try:
                all_univ[u] = json.loads(prev.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass

    for u in univs:
        payload = mine_universe(u, grid, dedup=dedup)
        all_univ[u] = payload
        summary = write_round_summary(all_univ)
        print(f"[checkpoint] {u} -> {summary}", flush=True)

    summary = write_round_summary(all_univ)
    print(f"\n[done] summary -> {summary}", flush=True)
    try:
        print(summary.read_text(encoding="utf-8"), flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(summary.read_text(encoding="utf-8").encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
