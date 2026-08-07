"""银行业(J66)因子挖掘 Round1 · 2018–2025。

样本：证监会 J66 货币金融服务（上市银行，~45 只）。
逻辑：银行更适合「低估值 + 质量/改善 + 均线确认」均值回归，
而非制造业的合同负债/存货/毛利扩张结构。

- 交易窗：2018-01-01 ~ 2025-12-31
- 主分 = 0.2×Sh(2018–21)+0.3×Sh(2022–23)+0.5×Sh(2024–25)
- 宇宙：`_shared/universe_ind_j66.parquet`
- 产物：`data/factors/mine_bank_industry_round1/`
- 默认不写 Mongo

用法:
  .venv\\Scripts\\python.exe scripts/mine_bank_industry_round1.py
  .venv\\Scripts\\python.exe scripts/mine_bank_industry_round1.py --limit 8
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mine_profit_causal_round1 as base  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_bank_industry_round1"
IND_CODE = "J66"
UNIVERSE = "ind_j66"
BENCH = "sh.000300"
START = "2018-01-01"
END = "2025-12-31"
RECENT2Y_CUT = "2024-01-01"
MIN_ACCEPTED_LEGS = 12
TOP_N = 8

SEGMENTS: List[Tuple[str, str, Optional[str], float]] = [
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_2025", "2024-01-01", "2025-12-31", 0.50),
]

# 挂到 base，复用 _time_weight_score / _overfit_flags / _rank_key
base.OUT_ROOT = OUT_ROOT
base.START = START
base.RECENT2Y_CUT = RECENT2Y_CUT
base.SEGMENTS = SEGMENTS
base.MIN_ACCEPTED_LEGS = MIN_ACCEPTED_LEGS
base.TOP_N = TOP_N


def _exit_pack(
    hold: int,
    sl: float = 0.10,
    tp: float = 0.22,
    lag: int = 20,
    brk: int = 60,
    entry: str = "reclaim",
    **more: Any,
) -> Dict[str, Any]:
    """银行波动更低：止盈/止损略收、持有略长。"""
    return {
        "funda_lag": lag,
        "break_days": brk,
        "hold_days": hold,
        "stop_loss": sl,
        "take_profit": tp,
        "entry": entry,
        **more,
    }


def _grid() -> List[base.GridRow]:
    """银行价值/质量网格。GridRow: id, family, fn, extra, need_profit, need_growth, need_fin, need_bal."""
    rows: List[base.GridRow] = []

    # ---- 破净 / 低 PB 回踩 ----
    for tag, extra in [
        ("pb1_ma20_h40", _exit_pack(40, pb_max=1.0)),
        ("pb09_ma20_h45", _exit_pack(45, pb_max=0.90)),
        ("pb085_ma20_h50", _exit_pack(50, pb_max=0.85, sl=0.08, tp=0.18)),
    ]:
        rows.append(
            (f"pb_below__{tag}", "pb_below_one", sig.signal_pb_below_one_reclaim, extra, True, False, False, False)
        )

    for tag, extra in [
        ("pct20_ma60_h40", _exit_pack(40, pb_pct_max=0.20, val_window=756)),
        ("pct25_ma60_h45", _exit_pack(45, pb_pct_max=0.25, val_window=756)),
        ("pct30_ma60_h50", _exit_pack(50, pb_pct_max=0.30, val_window=756, sl=0.08)),
        ("pct18_ma60_h35", _exit_pack(35, pb_pct_max=0.18, val_window=504, tp=0.20)),
    ]:
        rows.append(
            (f"pb_low__{tag}", "pb_low_ma", sig.signal_pb_low_ma_reclaim, extra, True, False, False, False)
        )

    # ---- 低估 + 高 ROE 急跌反弹 ----
    for tag, extra in [
        ("pe35_roe10_dd08_h40", _exit_pack(40, pe_pct_max=0.35, roe_min=0.10, dd_need=0.08, val_window=756)),
        ("pe40_roe12_dd10_h45", _exit_pack(45, pe_pct_max=0.40, roe_min=0.12, dd_need=0.10, val_window=756)),
        ("pe30_roe10_dd06_h35", _exit_pack(35, pe_pct_max=0.30, roe_min=0.10, dd_need=0.06, val_window=504, tp=0.18)),
    ]:
        rows.append(
            (f"cheap_roe__{tag}", "cheap_roe_bounce", sig.signal_cheap_roe_bounce, extra, True, False, False, False)
        )

    # ---- ROE 改善 + 低 PB ----
    for tag, extra in [
        ("imp005_pb35_h40", _exit_pack(40, roe_improve=0.005, pb_pct_max=0.35, val_window=756)),
        ("imp003_pb30_h45", _exit_pack(45, roe_improve=0.003, pb_pct_max=0.30, val_window=756)),
        ("imp008_pb40_h50", _exit_pack(50, roe_improve=0.008, pb_pct_max=0.40, val_window=756, sl=0.08)),
    ]:
        rows.append(
            (
                f"roe_imp_pb__{tag}",
                "roe_improve_pb",
                sig.signal_roe_improve_pb_cheap,
                extra,
                True,
                False,
                False,
                False,
            )
        )

    # ---- 高 ROE 低 PB 错配 ----
    for tag, extra in [
        ("roe12_pb30_h40", _exit_pack(40, roe_min=0.12, pb_pct_max=0.30, val_window=756)),
        ("roe10_pb25_h45", _exit_pack(45, roe_min=0.10, pb_pct_max=0.25, val_window=756)),
        ("roe15_pb35_h50", _exit_pack(50, roe_min=0.15, pb_pct_max=0.35, val_window=756)),
    ]:
        rows.append(
            (f"roe_pb_mis__{tag}", "roe_pb_misprice", sig.signal_roe_pb_misprice, extra, True, False, False, False)
        )

    # ---- 高 ROE 回踩 ----
    for tag, extra in [
        ("roe12_pe60_h40", _exit_pack(40, roe_min=0.12, pe_pct_max=0.60, val_window=756)),
        ("roe10_pe50_h45", _exit_pack(45, roe_min=0.10, pe_pct_max=0.50, val_window=756)),
        ("roe15_pe55_h50", _exit_pack(50, roe_min=0.15, pe_pct_max=0.55, val_window=756, sl=0.08)),
    ]:
        rows.append(
            (f"high_roe_pb__{tag}", "high_roe_pullback", sig.signal_high_roe_pullback, extra, True, False, False, False)
        )

    # ---- 优质打折 ----
    for tag, extra in [
        ("roe12_mgn08_dd10_h40", _exit_pack(40, roe_min=0.12, margin_min=0.08, dd_need=0.10)),
        ("roe10_mgn05_dd08_h45", _exit_pack(45, roe_min=0.10, margin_min=0.05, dd_need=0.08)),
    ]:
        rows.append(
            (f"qos__{tag}", "quality_on_sale", sig.signal_quality_on_sale, extra, True, False, False, False)
        )

    # ---- 成长价值（银行增速阈值放低）----
    for tag, extra in [
        ("g05_pb40_h40", _exit_pack(40, growth_min=0.05, pb_pct_max=0.40, val_window=756)),
        ("g08_pb35_h45", _exit_pack(45, growth_min=0.08, pb_pct_max=0.35, val_window=756)),
        ("g03_pb30_h50", _exit_pack(50, growth_min=0.03, pb_pct_max=0.30, val_window=756)),
    ]:
        rows.append(
            (f"dual_gv__{tag}", "dual_growth_value", sig.signal_dual_growth_value, extra, True, True, False, False)
        )

    # ---- PE 质量金叉 ----
    for tag, extra in [
        ("pe50_roe10_h40", _exit_pack(40, pe_pct_max=0.50, roe_min=0.10, val_window=756)),
        ("pe40_roe12_h45", _exit_pack(45, pe_pct_max=0.40, roe_min=0.12, val_window=756)),
    ]:
        rows.append(
            (f"pe_qual__{tag}", "pe_quality_cross", sig.signal_pe_quality_cross, extra, True, False, False, False)
        )

    # ---- MA60 拐头 + ROE 过滤 ----
    for tag, extra in [
        ("slope5_roe08_h40", _exit_pack(40, slope_lag=5, roe_min=0.08)),
        ("slope8_roe10_h45", _exit_pack(45, slope_lag=8, roe_min=0.10)),
        ("slope5_roe06_h50", _exit_pack(50, slope_lag=5, roe_min=0.06, sl=0.08, tp=0.20)),
    ]:
        rows.append(
            (f"ma60_turn__{tag}", "ma60_slope_turn", sig.signal_ma60_slope_turn, extra, True, False, False, False)
        )

    # ---- 低 PE 回踩 ----
    for tag, extra in [
        ("pe25_h40", _exit_pack(40, pe_pct_max=0.25, val_window=756)),
        ("pe30_h45", _exit_pack(45, pe_pct_max=0.30, val_window=756)),
    ]:
        rows.append(
            (f"pe_low__{tag}", "pe_low_ma", sig.signal_pe_low_ma_reclaim, extra, True, False, False, False)
        )

    # ---- PB 廉价 + 增长动量 ----
    for tag, extra in [
        ("pb35_g05_h40", _exit_pack(40, pb_pct_max=0.35, growth_min=0.05, val_window=756)),
        ("pb30_g08_h45", _exit_pack(45, pb_pct_max=0.30, growth_min=0.08, val_window=756)),
    ]:
        rows.append(
            (
                f"pb_g_mom__{tag}",
                "pb_cheap_growth_mom",
                sig.signal_pb_cheap_growth_mom,
                extra,
                True,
                True,
                False,
                False,
            )
        )

    return rows


def _eval_one_bank(
    cfg_id: str,
    family: str,
    signal_fn: base.SignalFn,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
) -> Dict[str, Any]:
    """与 base._eval_one 相同，但强制 end=END（截断到 2025）。"""
    t0 = time.time()
    legs = collect_legs(panel, signal_fn, params)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=START, end=END
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    tw = (
        base._time_weight_score(daily)
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
    # recent2y 也截到 END
    if isinstance(daily, pd.DataFrame) and not daily.empty:
        tw["recent2y"] = base._slice_stats(daily, RECENT2Y_CUT, END)
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
        "window": {"start": START, "end": END},
    }
    out["overfit_flags"] = base._overfit_flags(out, tw)
    out["ok"] = out.get("error") is None and out.get("sharpe") is not None
    out["rejected"] = "early_inflated_recent_poor" in (out.get("overfit_flags") or [])
    return out


def load_bank_pool(*, force: bool = False) -> Dict[str, Any]:
    cache = kit.shared_cache_dir()
    lim = kit.RateLimiter(0.05)
    ind = kit.fetch_industry_map(lim, cache, force=force)
    if ind is None or ind.empty:
        raise RuntimeError("industry_map empty")
    ind = ind.copy()
    ind["code"] = ind["code"].astype(str)
    ind["industry"] = ind["industry"].astype(str)
    mask = ind["industry"].str.startswith(IND_CODE)
    codes = kit.drop_st_codes(ind.loc[mask, "code"].astype(str).tolist())
    if len(codes) < 10:
        raise RuntimeError(f"bank pool too small: {len(codes)}")
    name = str(ind.loc[mask, "industry"].iloc[0])
    fp = cache / f"universe_{UNIVERSE}.parquet"
    pd.DataFrame({"code": codes}).to_parquet(fp, index=False)
    print(f"[pool] {IND_CODE} {name}: n={len(codes)} -> {fp.name}", flush=True)
    return {
        "ind_code": IND_CODE,
        "ind_name": name,
        "universe": UNIVERSE,
        "n": len(codes),
        "codes": codes,
        "label": "货币金融服务(银行)",
    }


def mine_banks(*, limit: int = 0) -> Dict[str, Any]:
    pool = load_bank_pool()
    codes = pool["codes"]
    print(f"\n======== bank mine {pool['label']} n={pool['n']} window={START}→{END} ========", flush=True)

    base_params = {
        **base._base("hs300"),
        "universe": UNIVERSE,
        "bench_code": BENCH,
        "price_start": "2016-01-01",
        "price_end": END,
        "max_positions": 6,
        "_codes": codes,
    }
    grid = _grid()
    if limit and limit > 0:
        grid = grid[:limit]
        print(f"[limit] grid={len(grid)}", flush=True)

    need_growth = any(g[5] for g in grid)
    panel = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=need_growth,
        need_fin_db=False,
        need_balance=False,
        limit=0,
        codes=codes,
    )
    print(f"[panel] {UNIVERSE} n={len(panel)}", flush=True)
    if panel:
        sample = next(iter(panel.values()))
        cols = [c for c in ("pbMRQ", "peTTM", "roeAvg", "pb_pct", "pe_pct", "YOYNI", "npMargin") if c in sample.columns]
        print(f"[panel-cols] {cols}", flush=True)

    cache = kit.shared_cache_dir()
    bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path) if bench_path.exists() else pd.DataFrame()
    if not bench.empty and "date" in bench.columns:
        bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results: List[Dict[str, Any]] = []
    for i, (cfg_id, family, fn, extra, *_rest) in enumerate(grid, 1):
        full_id = f"j66__{cfg_id}"
        params = {**base_params, **extra, "_codes": codes, "universe": UNIVERSE}
        print(f"  [{i}/{len(grid)}] {full_id}", flush=True)
        try:
            row = _eval_one_bank(full_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": full_id,
                "family": family,
                "universe": UNIVERSE,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "rejected": True,
            }
        row["ind_code"] = IND_CODE
        row["ind_name"] = pool["label"]
        results.append(row)
        print(
            f"    tw={row.get('tw_score')} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('overfit_flags')}",
            flush=True,
        )
        udir = OUT_ROOT / UNIVERSE
        udir.mkdir(parents=True, exist_ok=True)
        (udir / "results_partial.json").write_text(
            json.dumps(
                {"universe": UNIVERSE, "pool": {k: pool[k] for k in ("ind_code", "ind_name", "n", "label")}, "all": results},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    ranked = sorted(results, key=base._rank_key, reverse=True)
    ok_clean = [
        r
        for r in ranked
        if r.get("ok")
        and not r.get("rejected")
        and not any(str(f).startswith("few_legs") or str(f).startswith("sus_") for f in (r.get("overfit_flags") or []))
    ]
    top = ok_clean[:TOP_N]
    payload = {
        "universe": UNIVERSE,
        "ind_code": IND_CODE,
        "ind_name": pool["label"],
        "n_codes": pool["n"],
        "n_panel": len(panel),
        "window": {"start": START, "end": END},
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "top": top,
        "all": results,
    }
    udir = OUT_ROOT / UNIVERSE
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Bank Industry · {IND_CODE} {pool['label']}",
        "",
        f"- window: {START} → {END}",
        f"- n_codes={pool['n']} panel={len(panel)} grid={len(grid)}",
        f"- score: 0.2×2018-21 + 0.3×2022-23 + 0.5×2024-25",
        "",
        "| cfg | tw | sh | r2y | legs | family |",
        "|-----|----|----|-----|------|--------|",
    ]
    for r in top:
        lines.append(
            f"| `{r.get('cfg_id')}` | {base._fmt(r.get('tw_score'))} | "
            f"{base._fmt(r.get('sharpe'))} | {base._fmt(r.get('recent2y_sharpe'))} | "
            f"{r.get('n_legs_accepted')} | {r.get('family')} |"
        )
    lines += ["", "## All OK (ranked)", ""]
    for r in ok_clean[:20]:
        lines.append(
            f"- `{r.get('cfg_id')}` tw={base._fmt(r.get('tw_score'))} "
            f"sh={base._fmt(r.get('sharpe'))} r2y={base._fmt(r.get('recent2y_sharpe'))} "
            f"legs={r.get('n_legs_accepted')} ret={base._fmt(r.get('total_return'))}"
        )
    (udir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "ROUND_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done] top={len(top)} ok_clean={len(ok_clean)} -> {udir}", flush=True)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个配置（冒烟）")
    ap.add_argument("--force-industry", action="store_true")
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.force_industry:
        load_bank_pool(force=True)
    mine_banks(limit=args.limit)


if __name__ == "__main__":
    main()
