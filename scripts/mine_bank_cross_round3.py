"""银行业截面分化挖掘 Round3 · 2018–2025。

动机：J66 内个股走势差异极大（2018–25 累计约 -70% ~ +280%），
同质化估值/行业信号不够；本轮用同行百分位与分层内相对强弱选股。

- 宇宙：ind_j66
- 面板：profit + fin_db + bank_peer 截面标注
- 产物：data/factors/mine_bank_cross_round3/

用法:
  .venv\\Scripts\\python.exe scripts/mine_bank_cross_round3.py
  .venv\\Scripts\\python.exe scripts/mine_bank_cross_round3.py --limit 6
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
from app.services.factors.bank_peer import annotate_bank_peer_panel  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_bank_cross_round3"
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

    # 同行强势 + 质量
    for tag, extra in [
        ("m70_aq60_q40_h40", _exit_pack(40, cs_mom_min=0.70, cs_impair_max=0.60, cs_quality_min=0.40)),
        ("m75_aq50_q50_h45", _exit_pack(45, cs_mom_min=0.75, cs_impair_max=0.50, cs_quality_min=0.50)),
        ("m70_brk_h40", _exit_pack(40, cs_mom_min=0.70, cs_impair_max=0.65, entry="break")),
        ("m80_aq55_h50", _exit_pack(50, cs_mom_min=0.80, cs_impair_max=0.55, cs_quality_min=0.45, sl=0.08)),
    ]:
        rows.append(
            (f"csmom__{tag}", "cs_mom_quality", sig.signal_bank_cs_mom_quality, extra, True, False, True, False)
        )

    # 相对低估高质量
    for tag, extra in [
        ("pb35_roe60_h40", _exit_pack(40, cs_pb_max=0.35, cs_roe_min=0.60, cs_quality_min=0.45)),
        ("pb30_roe65_h45", _exit_pack(45, cs_pb_max=0.30, cs_roe_min=0.65, cs_quality_min=0.50)),
        ("pb40_roe55_brk_h40", _exit_pack(40, cs_pb_max=0.40, cs_roe_min=0.55, entry="break")),
        ("pb25_roe70_h50", _exit_pack(50, cs_pb_max=0.25, cs_roe_min=0.70, cs_quality_min=0.55)),
    ]:
        rows.append(
            (f"cscq__{tag}", "cs_cheap_quality", sig.signal_bank_cs_cheap_quality, extra, True, False, True, False)
        )

    # 中收领先
    for tag, extra in [
        ("fee70_h40", _exit_pack(40, cs_fee_min=0.70, require_fee_improve=True, fee_share_improve=0.0)),
        ("fee75_h45", _exit_pack(45, cs_fee_min=0.75, require_fee_improve=False)),
        ("fee70_brk_h40", _exit_pack(40, cs_fee_min=0.70, require_fee_improve=False, entry="break")),
        ("fee80_imp_h50", _exit_pack(50, cs_fee_min=0.80, require_fee_improve=True, fee_share_improve=0.002)),
    ]:
        rows.append(
            (f"csfee__{tag}", "cs_fee_leader", sig.signal_bank_cs_fee_leader, extra, True, False, True, False)
        )

    # 资产质量领先
    for tag, extra in [
        ("aq30_p45_h40", _exit_pack(40, cs_impair_max=0.30, cs_prov_min=0.45, cs_roe_min=0.40)),
        ("aq25_p50_h45", _exit_pack(45, cs_impair_max=0.25, cs_prov_min=0.50, cs_roe_min=0.45)),
        ("aq35_brk_h40", _exit_pack(40, cs_impair_max=0.35, cs_prov_min=0.40, entry="break")),
    ]:
        rows.append(
            (f"csaq__{tag}", "cs_aq_leader", sig.signal_bank_cs_aq_leader, extra, True, False, True, False)
        )

    # 扩表领先
    for tag, extra in [
        ("lg70_aq65_h40", _exit_pack(40, cs_loan_min=0.70, cs_impair_max=0.65)),
        ("lg75_aq55_h45", _exit_pack(45, cs_loan_min=0.75, cs_impair_max=0.55)),
        ("lg70_brk_h40", _exit_pack(40, cs_loan_min=0.70, cs_impair_max=0.70, entry="break")),
    ]:
        rows.append(
            (f"csloan__{tag}", "cs_loan_leader", sig.signal_bank_cs_loan_leader, extra, True, False, True, False)
        )

    # 息差领先
    for tag, extra in [
        ("nim65_h40", _exit_pack(40, cs_nim_min=0.65, require_nim_improve=False)),
        ("nim70_imp_h45", _exit_pack(45, cs_nim_min=0.70, require_nim_improve=True, nim_improve=0.0)),
        ("nim65_brk_h40", _exit_pack(40, cs_nim_min=0.65, entry="break")),
    ]:
        rows.append(
            (f"csnim__{tag}", "cs_nim_leader", sig.signal_bank_cs_nim_leader, extra, True, False, True, False)
        )

    # 错杀反转
    for tag, extra in [
        ("w35_n50_q50_h40", _exit_pack(40, weak_lag=20, cs_weak_max=0.35, cs_now_min=0.50, cs_quality_min=0.50)),
        ("w30_n55_q55_h45", _exit_pack(45, weak_lag=20, cs_weak_max=0.30, cs_now_min=0.55, cs_quality_min=0.55)),
        ("w40_n45_lag40_h50", _exit_pack(50, weak_lag=40, cs_weak_max=0.40, cs_now_min=0.45, cs_quality_min=0.50)),
        ("w35_brk_h40", _exit_pack(40, weak_lag=20, cs_weak_max=0.35, cs_now_min=0.50, cs_quality_min=0.45, entry="break")),
    ]:
        rows.append(
            (f"cscatch__{tag}", "cs_catchup", sig.signal_bank_cs_catchup, extra, True, False, True, False)
        )

    # 分层内强势
    for tag, extra in [
        ("t75_h40", _exit_pack(40, cs_tier_mom_min=0.75, cs_tier_roe_min=0.40)),
        ("t80_h45", _exit_pack(45, cs_tier_mom_min=0.80, cs_tier_roe_min=0.45)),
        ("t75_city_h40", _exit_pack(40, cs_tier_mom_min=0.75, tier_only="city")),
        ("t75_joint_h40", _exit_pack(40, cs_tier_mom_min=0.75, tier_only="joint")),
        ("t75_big_h40", _exit_pack(40, cs_tier_mom_min=0.75, tier_only="big")),
        ("t80_brk_h40", _exit_pack(40, cs_tier_mom_min=0.80, entry="break")),
    ]:
        rows.append(
            (f"cstier__{tag}", "cs_tier_mom", sig.signal_bank_cs_tier_mom, extra, True, False, True, False)
        )

    # 综合质量突破
    for tag, extra in [
        ("q70_h40", _exit_pack(40, cs_quality_min=0.70, cs_mom20_min=0.45, entry="break")),
        ("q75_h45", _exit_pack(45, cs_quality_min=0.75, cs_mom20_min=0.50, entry="break")),
        ("q70_reclaim_h40", _exit_pack(40, cs_quality_min=0.70, cs_mom20_min=0.40, entry="reclaim")),
        ("q80_h50", _exit_pack(50, cs_quality_min=0.80, cs_mom20_min=0.45, entry="break", sl=0.08)),
    ]:
        rows.append(
            (f"csqbrk__{tag}", "cs_quality_break", sig.signal_bank_cs_quality_break, extra, True, False, True, False)
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
        "late_sharpe": tw.get("late_sharpe"),
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
    if fp.exists():
        return pd.read_parquet(fp)["code"].astype(str).tolist()
    ind = pd.read_parquet(cache / "industry_map.parquet")
    codes = kit.drop_st_codes(
        ind[ind["industry"].astype(str).str.startswith("J66")]["code"].astype(str).tolist()
    )
    pd.DataFrame({"code": codes}).to_parquet(fp, index=False)
    return codes


def mine(*, limit: int = 0) -> Dict[str, Any]:
    codes = load_codes()
    print(f"\n======== bank cross r3 n={len(codes)} {START}→{END} ========", flush=True)
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

    panel = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        codes=codes,
    )
    print(f"[panel] raw n={len(panel)} — annotate peer CS …", flush=True)
    t0 = time.time()
    panel = annotate_bank_peer_panel(panel)
    print(f"[peer] done in {time.time()-t0:.1f}s", flush=True)
    if panel:
        sample = next(iter(panel.values()))
        cols = [c for c in sample.columns if c.startswith("cs_") or c in ("tier", "x_ret_60")]
        print(f"[peer-cols] {cols[:20]} … n={len(cols)}", flush=True)

    cache = kit.shared_cache_dir()
    bench = pd.read_parquet(cache / "daily" / "sh_000300.parquet")
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results: List[Dict[str, Any]] = []
    for i, (cfg_id, family, fn, extra, *_rest) in enumerate(grid, 1):
        full_id = f"j66c3__{cfg_id}"
        params = {**base_params, **extra, "_codes": codes, "universe": UNIVERSE}
        print(f"  [{i}/{len(grid)}] {full_id}", flush=True)
        try:
            row = _eval_one(full_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": full_id,
                "family": family,
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
    best_by_fam: Dict[str, Dict[str, Any]] = {}
    for r in ok_clean:
        fam = str(r.get("family") or "")
        if fam not in best_by_fam:
            best_by_fam[fam] = r
    top_diverse = sorted(best_by_fam.values(), key=base._rank_key, reverse=True)
    top = (top_diverse + [r for r in ok_clean if r not in top_diverse])[:TOP_N]

    payload = {
        "universe": UNIVERSE,
        "theme": "bank_cross_section_dispersion",
        "n_codes": len(codes),
        "n_panel": len(panel),
        "window": {"start": START, "end": END},
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "dispersion_note": "J66 2018-25 ret range roughly -70% to +280%; CS ranks target differentiation",
        "top": top,
        "top_by_family": top_diverse,
        "all": results,
    }
    udir = OUT_ROOT / UNIVERSE
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Bank Cross Round3 · J66 截面分化",
        "",
        f"- window: {START} → {END}",
        f"- n={len(codes)} grid={len(grid)} ok_clean={len(ok_clean)}",
        "- idea: 同行百分位 / 分层内相对强弱 / 高质量错杀反转",
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
            f"early={base._fmt(r.get('early_sharpe'))} mid={base._fmt(r.get('mid_sharpe'))} "
            f"legs={r.get('n_legs_accepted')}"
        )
    (udir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "ROUND_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done] top={len(top)} families={len(top_diverse)} -> {udir}", flush=True)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    mine(limit=args.limit)


if __name__ == "__main__":
    main()
