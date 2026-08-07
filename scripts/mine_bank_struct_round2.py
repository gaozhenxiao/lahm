"""银行业特色结构挖掘 Round2 · 2018–2025。

相对 Round1（纯估值/ROE），本轮主挖银行资产负债表与利润表特色：
净息收入、息差代理、中收占比、信用减值、贷款扩张、拨备夯实。

- 宇宙：ind_j66（需已有 universe_ind_j66.parquet）
- 交易窗：2018-01-01 ~ 2025-12-31
- need_fin_db=True（扩展 INCOME/BALANCE 银行列）
- 估值只作软闸，不作主逻辑
- 产物：data/factors/mine_bank_struct_round2/

用法:
  .venv\\Scripts\\python.exe scripts/mine_bank_struct_round2.py
  .venv\\Scripts\\python.exe scripts/mine_bank_struct_round2.py --limit 6
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

OUT_ROOT = ROOT / "data" / "factors" / "mine_bank_struct_round2"
IND_CODE = "J66"
UNIVERSE = "ind_j66"
BENCH = "sh.000300"
START = "2018-01-01"
END = "2025-12-31"
RECENT2Y_CUT = "2024-01-01"
MIN_ACCEPTED_LEGS = 12
TOP_N = 10

SEGMENTS: List[Tuple[str, str, Optional[str], float]] = [
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_2025", "2024-01-01", "2025-12-31", 0.50),
]

base.OUT_ROOT = OUT_ROOT
base.START = START
base.RECENT2Y_CUT = RECENT2Y_CUT
base.SEGMENTS = SEGMENTS
base.MIN_ACCEPTED_LEGS = MIN_ACCEPTED_LEGS
base.TOP_N = TOP_N


def _exit_pack(hold: int, sl: float = 0.10, tp: float = 0.22, lag: int = 20, **more: Any) -> Dict[str, Any]:
    return {
        "funda_lag": lag,
        "break_days": int(more.pop("brk", 60)),
        "hold_days": hold,
        "stop_loss": sl,
        "take_profit": tp,
        "entry": more.pop("entry", "reclaim"),
        "ma_days": more.pop("ma_days", 20),
        **more,
    }


def _grid() -> List[base.GridRow]:
    rows: List[base.GridRow] = []

    # ---- 息差代理改善 ----
    for tag, extra in [
        ("nim1e4_h40", _exit_pack(40, nim_improve=1e-4, roe_min=0.08)),
        ("nim2e4_pb50_h45", _exit_pack(45, nim_improve=2e-4, pb_pct_max=0.50, roe_min=0.08)),
        ("nim1e4_brk_h40", _exit_pack(40, nim_improve=1e-4, entry="break", brk=60)),
        ("nim15e5_h50", _exit_pack(50, nim_improve=1.5e-4, sl=0.08, tp=0.18)),
    ]:
        rows.append(
            (f"nim__{tag}", "bank_nim", sig.signal_bank_nim_improve_reclaim, extra, True, False, True, False)
        )

    # ---- 净息 YoY ----
    for tag, extra in [
        ("niy00_imp01_h40", _exit_pack(40, net_int_yoy_min=0.0, yoy_improve=0.01)),
        ("niy03_imp02_h45", _exit_pack(45, net_int_yoy_min=0.03, yoy_improve=0.02)),
        ("niy00_acc02_h40", _exit_pack(40, net_int_yoy_min=0.0, net_int_accel=0.02, entry="break")),
        ("niy05_pb55_h50", _exit_pack(50, net_int_yoy_min=0.05, yoy_improve=0.01, pb_pct_max=0.55)),
    ]:
        rows.append(
            (f"netint__{tag}", "bank_net_int", sig.signal_bank_net_int_yoy_break, extra, True, False, True, False)
        )

    # ---- 中收占比 / YoY ----
    for tag, extra in [
        ("fee005_lv05_h40", _exit_pack(40, fee_share_improve=0.005, fee_share_min=0.05, roe_min=0.08)),
        ("fee008_lv08_h45", _exit_pack(45, fee_share_improve=0.008, fee_share_min=0.08)),
        ("fee003_pb50_h50", _exit_pack(50, fee_share_improve=0.003, fee_share_min=0.05, pb_pct_max=0.50)),
    ]:
        rows.append(
            (f"feemix__{tag}", "bank_fee_mix", sig.signal_bank_fee_mix_improve, extra, True, False, True, False)
        )

    for tag, extra in [
        ("fy08_h40", _exit_pack(40, fee_yoy_min=0.08)),
        ("fy12_h45", _exit_pack(45, fee_yoy_min=0.12, entry="break")),
        ("fy08_acc03_h40", _exit_pack(40, fee_yoy_min=0.08, fee_yoy_accel=0.03)),
        ("fy05_pb50_h50", _exit_pack(50, fee_yoy_min=0.05, pb_pct_max=0.50)),
    ]:
        rows.append(
            (f"feeyoy__{tag}", "bank_fee_yoy", sig.signal_bank_fee_yoy_break, extra, True, False, True, False)
        )

    # ---- 减值缓解 ----
    for tag, extra in [
        ("imp02_h40", _exit_pack(40, impair_ease=0.02, impair_max=0.80, roe_min=0.08)),
        ("imp03_h45", _exit_pack(45, impair_ease=0.03, impair_max=0.70)),
        ("imp015_pb1_h50", _exit_pack(50, impair_ease=0.015, pb_max=1.05, entry="reclaim")),
        ("imp02_brk_h40", _exit_pack(40, impair_ease=0.02, entry="break")),
    ]:
        rows.append(
            (f"impair__{tag}", "bank_impair_ease", sig.signal_bank_impair_ease_reclaim, extra, True, False, True, False)
        )

    # ---- 质量扩表 ----
    for tag, extra in [
        ("lg05_h40", _exit_pack(40, loan_growth_min=0.05, impair_worsen_max=0.03, roe_min=0.08)),
        ("lg08_h45", _exit_pack(45, loan_growth_min=0.08, impair_worsen_max=0.02)),
        ("lg05_pb50_h50", _exit_pack(50, loan_growth_min=0.05, pb_pct_max=0.50)),
        ("lg03_brk_h40", _exit_pack(40, loan_growth_min=0.03, entry="break")),
    ]:
        rows.append(
            (f"loanq__{tag}", "bank_loan_quality", sig.signal_bank_loan_growth_quality, extra, True, False, True, False)
        )

    # ---- 拨备夯实 ----
    for tag, extra in [
        ("prov001_h40", _exit_pack(40, prov_improve=0.001, prov_loan_min=0.015)),
        ("prov002_h45", _exit_pack(45, prov_improve=0.002, prov_loan_min=0.018)),
        ("prov001_pb50_h50", _exit_pack(50, prov_improve=0.001, pb_pct_max=0.50)),
    ]:
        rows.append(
            (f"prov__{tag}", "bank_prov", sig.signal_bank_prov_thicken, extra, True, False, True, False)
        )

    # ---- 利息收支差 ----
    for tag, extra in [
        ("sp005_h40", _exit_pack(40, spread_improve=0.005, spread_min=0.35)),
        ("sp008_h45", _exit_pack(45, spread_improve=0.008, spread_min=0.40)),
        ("sp005_pb50_h50", _exit_pack(50, spread_improve=0.005, pb_pct_max=0.50)),
    ]:
        rows.append(
            (f"spread__{tag}", "bank_spread", sig.signal_bank_int_spread_improve, extra, True, False, True, False)
        )

    # ---- 净息+中收双增 ----
    for tag, extra in [
        ("dual_ni00_f05_h40", _exit_pack(40, net_int_yoy_min=0.0, fee_yoy_min=0.05, roe_min=0.08)),
        ("dual_ni03_f08_h45", _exit_pack(45, net_int_yoy_min=0.03, fee_yoy_min=0.08)),
        ("dual_ni00_f05_brk_h40", _exit_pack(40, net_int_yoy_min=0.0, fee_yoy_min=0.05, entry="break")),
        ("dual_pb50_h50", _exit_pack(50, net_int_yoy_min=0.0, fee_yoy_min=0.05, pb_pct_max=0.50)),
    ]:
        rows.append(
            (f"dualif__{tag}", "bank_dual_int_fee", sig.signal_bank_dual_int_fee, extra, True, False, True, False)
        )

    # ---- 资产质量拐点 ----
    for tag, extra in [
        ("aq_imp015_h40", _exit_pack(40, impair_ease=0.015, impair_prior_min=0.25, prov_loan_min=0.015, lag=24)),
        ("aq_imp02_h45", _exit_pack(45, impair_ease=0.02, impair_prior_min=0.30, prov_loan_min=0.018, lag=24)),
        ("aq_pb1_h50", _exit_pack(50, impair_ease=0.015, impair_prior_min=0.25, pb_max=1.05, lag=28)),
    ]:
        rows.append(
            (f"aqturn__{tag}", "bank_aq_turn", sig.signal_bank_impair_turn_prov, extra, True, False, True, False)
        )

    return rows


def _eval_one(
    cfg_id: str,
    family: str,
    signal_fn: base.SignalFn,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
) -> Dict[str, Any]:
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


def load_codes() -> List[str]:
    cache = kit.shared_cache_dir()
    fp = cache / f"universe_{UNIVERSE}.parquet"
    if not fp.exists():
        # 回退：从 industry_map 重建
        ind = pd.read_parquet(cache / "industry_map.parquet")
        codes = kit.drop_st_codes(
            ind[ind["industry"].astype(str).str.startswith(IND_CODE)]["code"].astype(str).tolist()
        )
        pd.DataFrame({"code": codes}).to_parquet(fp, index=False)
        return codes
    return pd.read_parquet(fp)["code"].astype(str).tolist()


def mine(*, limit: int = 0) -> Dict[str, Any]:
    codes = load_codes()
    print(f"\n======== bank struct r2 n={len(codes)} window={START}→{END} ========", flush=True)
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

    panel = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        need_balance=False,
        limit=0,
        codes=codes,
    )
    print(f"[panel] n={len(panel)}", flush=True)
    if panel:
        sample = next(iter(panel.values()))
        cols = [
            c
            for c in (
                "fin_net_int_inc",
                "fin_nim_proxy",
                "fin_fee_share",
                "fin_impair_to_op",
                "fin_loan_growth",
                "fin_prov_loan",
                "fin_int_spread",
                "fin_net_int_yoy",
                "fin_fee_yoy",
            )
            if c in sample.columns
        ]
        print(f"[panel-bank-cols] {cols}", flush=True)
        # coverage
        for c in cols:
            nn = int(sample[c].notna().sum())
            print(f"  sample {c}: non-null={nn}/{len(sample)}", flush=True)

    cache = kit.shared_cache_dir()
    bench = pd.read_parquet(cache / "daily" / "sh_000300.parquet")
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results: List[Dict[str, Any]] = []
    for i, (cfg_id, family, fn, extra, *_rest) in enumerate(grid, 1):
        full_id = f"j66s2__{cfg_id}"
        params = {**base_params, **extra, "_codes": codes, "universe": UNIVERSE}
        print(f"  [{i}/{len(grid)}] {full_id}", flush=True)
        try:
            row = _eval_one(full_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": full_id,
                "family": family,
                "universe": UNIVERSE,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "rejected": True,
            }
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
            json.dumps({"all": results}, ensure_ascii=False, indent=2, default=str),
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
    # 按 family 去重取最优，再补全局 top
    best_by_fam: Dict[str, Dict[str, Any]] = {}
    for r in ok_clean:
        fam = str(r.get("family") or "")
        if fam not in best_by_fam:
            best_by_fam[fam] = r
    top_diverse = list(best_by_fam.values())
    top_diverse = sorted(top_diverse, key=base._rank_key, reverse=True)
    top = (top_diverse + [r for r in ok_clean if r not in top_diverse])[:TOP_N]

    payload = {
        "universe": UNIVERSE,
        "ind_code": IND_CODE,
        "n_codes": len(codes),
        "n_panel": len(panel),
        "window": {"start": START, "end": END},
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "theme": "bank_struct_r2_nim_fee_impair_loan_prov",
        "top": top,
        "top_by_family": top_diverse,
        "all": results,
    }
    udir = OUT_ROOT / UNIVERSE
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Bank Struct Round2 · J66 特色结构",
        "",
        f"- window: {START} → {END}",
        f"- n_codes={len(codes)} panel={len(panel)} grid={len(grid)}",
        "- themes: NIM代理 / 净息YoY / 中收 / 减值缓解 / 质量扩表 / 拨备 / 收支差 / 双增 / AQ拐点",
        "",
        "## Top (family-diverse first)",
        "",
        "| cfg | family | tw | sh | r2y | legs | ret |",
        "|-----|--------|----|----|-----|------|-----|",
    ]
    for r in top:
        lines.append(
            f"| `{r.get('cfg_id')}` | {r.get('family')} | {base._fmt(r.get('tw_score'))} | "
            f"{base._fmt(r.get('sharpe'))} | {base._fmt(r.get('recent2y_sharpe'))} | "
            f"{r.get('n_legs_accepted')} | {base._fmt(r.get('total_return'))} |"
        )
    lines += ["", "## Best per family", ""]
    for r in top_diverse:
        lines.append(
            f"- **{r.get('family')}** `{r.get('cfg_id')}` tw={base._fmt(r.get('tw_score'))} "
            f"sh={base._fmt(r.get('sharpe'))} r2y={base._fmt(r.get('recent2y_sharpe'))} "
            f"legs={r.get('n_legs_accepted')} ret={base._fmt(r.get('total_return'))}"
        )
    (udir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "ROUND_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done] top={len(top)} ok_clean={len(ok_clean)} families={len(top_diverse)} -> {udir}", flush=True)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    mine(limit=args.limit)


if __name__ == "__main__":
    main()
