"""分宇宙挖因子：沪深300 / 中证500 / 中证1000（+ 合并对照）。

- 成分：中证官网静态 xls（幸存者偏差，报告需写明）
- 行情：_shared/daily 腾讯前复权；BaoStock 黑名单
- 财务：本地 profit cache / 财务库
- 不写 Mongo；结果写入 data/factors/mine_csi300_500_1000_*/

用法:
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000.py
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000.py --universes hs300,csi500
  .venv\\Scripts\\python.exe scripts/mine_csi300_500_1000.py --skip-build
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_csi300_500_1000_round1"
START = "2018-01-01"
MIN_ACCEPTED_LEGS = 25  # 过少视为样本不足
TOP_N = 3

UNIVERSES = ("hs300", "csi500", "csi1000", "csi300_500_1000")

BENCH = {
    "hs300": "sh.000300",
    "csi500": "sh.000905",
    "csi1000": "sh.000852",
    "csi300_500_1000": "sh.000300",
}

SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame]


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


def _grid() -> List[Tuple[str, str, SignalFn, Dict[str, Any], bool, bool]]:
    """(cfg_id, family, signal_fn, param_overrides, need_profit, need_growth)."""
    rows: List[Tuple[str, str, SignalFn, Dict[str, Any], bool, bool]] = []

    # ---- gross_expand 家族（已验证强势）----
    ge = sig.signal_gross_expand_break
    for tag, extra in [
        ("m16_imp006_lag29_h51_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m17_imp0065_lag29_h51_tp35", dict(margin_improve=0.0065, margin_min=0.17, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m18_imp006_lag29_h51_tp35", dict(margin_improve=0.006, margin_min=0.18, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag28_h51_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=28, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag30_h51_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=30, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag29_h45_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=45, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag29_h55_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=55, stop_loss=0.12, take_profit=0.35)),
        ("m14_imp005_lag29_h51_tp35", dict(margin_improve=0.005, margin_min=0.14, np_min=0.08, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m20_imp007_lag29_h51_tp35", dict(margin_improve=0.007, margin_min=0.20, np_min=0.12, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag29_h51_tp30", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.30)),
        ("m16_imp006_lag29_h51_notp", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12)),
        ("m16_imp006_lag29_brk80_h51", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=80, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_imp006_lag29_np1e9", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35, net_profit_min=1e9)),
        ("m16_imp006_lag29_np5e8", dict(margin_improve=0.006, margin_min=0.16, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35, net_profit_min=5e8)),
        ("m17_imp006_lag29_h51_tp35", dict(margin_improve=0.006, margin_min=0.17, np_min=0.10, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
    ]:
        rows.append((f"gross_expand__{tag}", "gross_expand", ge, extra, True, False))

    # ---- gp_np 双扩张 ----
    gp = sig.signal_gp_np_expand_break
    for tag, extra in [
        ("base_lag29_h51_tp35", dict(margin_improve=0.005, margin_min=0.16, np_improve=0.004, np_min=0.08, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("tight_lag28_h51_tp35", dict(margin_improve=0.006, margin_min=0.17, np_improve=0.005, np_min=0.10, funda_lag=28, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("loose_lag29_h45_tp35", dict(margin_improve=0.004, margin_min=0.14, np_improve=0.003, np_min=0.06, funda_lag=29, break_days=60, hold_days=45, stop_loss=0.12, take_profit=0.35)),
    ]:
        rows.append((f"gp_np_expand__{tag}", "gp_np_expand", gp, extra, True, False))

    # ---- dual_improve ----
    du = sig.signal_dual_improve_breakout
    for tag, extra in [
        ("base_lag28_h50_tp35", dict(margin_improve=0.005, margin_min=0.15, np_improve=0.004, funda_lag=28, break_days=60, hold_days=50, stop_loss=0.12, take_profit=0.35)),
        ("tight_lag29_h51_tp35", dict(margin_improve=0.006, margin_min=0.17, np_improve=0.005, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("wide_lag29_h45_tp35", dict(margin_improve=0.004, margin_min=0.14, np_improve=0.003, funda_lag=29, break_days=60, hold_days=45, stop_loss=0.12, take_profit=0.35)),
    ]:
        rows.append((f"dual_improve__{tag}", "dual_improve", du, extra, True, False))

    # ---- gross_high_np ----
    hn = sig.signal_gross_high_np_break
    for tag, extra in [
        ("m17_lag30_h51_tp35", dict(margin_improve=0.006, margin_min=0.17, np_min=0.10, funda_lag=30, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
        ("m16_lag29_h51_tp35", dict(margin_improve=0.006, margin_min=0.16, np_min=0.12, funda_lag=29, break_days=60, hold_days=51, stop_loss=0.12, take_profit=0.35)),
    ]:
        rows.append((f"gross_high_np__{tag}", "gross_high_np", hn, extra, True, False))

    return rows


def _overfit_flags(summary: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    n = int(summary.get("n_legs_accepted") or 0)
    if n < MIN_ACCEPTED_LEGS:
        flags.append(f"few_legs<{MIN_ACCEPTED_LEGS}")
    if n > 0 and n < 40 and float(summary.get("total_return") or 0) > 8:
        flags.append("high_ret_few_legs")
    sharpe = summary.get("sharpe")
    if sharpe is not None and float(sharpe) > 2.5 and n < 40:
        flags.append("sus_sharpe_few_legs")
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
        "n_legs_accepted": summary.get("n_legs_accepted", 0 if accepted is None else len(accepted)),
        "avg_position": summary.get("avg_position"),
        "error": summary.get("error"),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    out["overfit_flags"] = _overfit_flags(out)
    out["ok"] = out.get("error") is None and out.get("sharpe") is not None
    return out


def build_universes(force: bool = True) -> Dict[str, Any]:
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
            "cache": str(cache / f"universe_{u}.parquet"),
        }
        print(
            f"[universe] {u}: n={len(codes)} daily={have} profit={have_p}",
            flush=True,
        )
        # 补齐缺失 profit（本地财务库）
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


def mine_universe(universe: str, grid: List[Tuple], write_top_artifacts: bool = True) -> Dict[str, Any]:
    print(f"\n======== mine {universe} ========", flush=True)
    base = _base(universe)
    need_growth = any(g[5] for g in grid)
    panel = prepare_shared_panel(base, need_profit=True, need_growth=need_growth, limit=0)
    print(f"[panel] {universe} n={len(panel)}", flush=True)

    cache = kit.shared_cache_dir()
    bench_code = BENCH[universe]
    bench_path = cache / "daily" / f"{bench_code.replace('.', '_')}.parquet"
    if not bench_path.exists():
        # 基准缺失时回退沪深300
        print(f"[warn] bench {bench_code} missing, fallback sh.000300", flush=True)
        bench_code = "sh.000300"
        bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results: List[Dict[str, Any]] = []
    for i, (cfg_id, family, fn, extra, _np, _ng) in enumerate(grid, 1):
        params = {**base, **extra, "bench_code": BENCH[universe]}
        params["_cache_dir"] = str(cache)
        try:
            row = _eval_one(cfg_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": cfg_id,
                "family": family,
                "universe": universe,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "traceback": traceback.format_exc()[-800:],
            }
        results.append(row)
        sh = row.get("sharpe")
        print(
            f"  [{i}/{len(grid)}] {cfg_id}: sharpe={sh} ret={row.get('total_return')} "
            f"dd={row.get('max_drawdown')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('overfit_flags')}",
            flush=True,
        )

    def _rank_key(r: Dict[str, Any]):
        if not r.get("ok") or r.get("overfit_flags"):
            return (-999.0, -999.0)
        return (float(r.get("sharpe") or -999), float(r.get("total_return") or -999))

    ranked = sorted(results, key=_rank_key, reverse=True)
    # 也给出「不过滤 overfit」的纯 sharpe 榜，便于对照
    ranked_raw = sorted(
        [r for r in results if r.get("ok")],
        key=lambda r: (float(r.get("sharpe") or -999), float(r.get("total_return") or -999)),
        reverse=True,
    )
    top = [r for r in ranked if r.get("ok") and not r.get("overfit_flags")][:TOP_N]
    if len(top) < TOP_N:
        # 放宽：允许 few_legs 以外的进榜说明
        extra = [
            r
            for r in ranked_raw
            if r not in top and "sus_sharpe_few_legs" not in (r.get("overfit_flags") or [])
        ]
        top = (top + extra)[:TOP_N]

    udir = OUT_ROOT / universe
    udir.mkdir(parents=True, exist_ok=True)
    payload = {
        "universe": universe,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_panel": len(panel),
        "n_cfgs": len(results),
        "min_accepted_legs": MIN_ACCEPTED_LEGS,
        "survivor_bias_note": "静态成分；非 PIT",
        "top": top,
        "ranked_all_ok": ranked_raw[:15],
        "all": results,
    }
    (udir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if write_top_artifacts and top:
        from app.services.factors.runner import run_factor_pipeline

        for r in top:
            fid = f"mine_csi_{universe}__{r['cfg_id']}"
            params = {**_base(universe), **{k: v for k, v in (r.get("params") or {}).items() if k != "universe"}}
            params["universe"] = universe
            fn = next((g[2] for g in grid if g[0] == r["cfg_id"]), None)
            if fn is None:
                continue
            print(f"[artifact] {fid}", flush=True)
            summary = run_factor_pipeline(
                fid,
                f"{universe} {r['cfg_id']}",
                fn,
                params,
                need_profit=True,
                need_growth=False,
                start=START,
                price_map=panel,
            )
            r["artifact_factor_id"] = fid
            r["artifact_summary"] = {
                k: summary.get(k)
                for k in (
                    "sharpe",
                    "total_return",
                    "max_drawdown",
                    "n_legs_accepted",
                    "annual_return",
                )
            }
        (udir / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return payload


def write_round_summary(all_univ: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# 三宇宙分挖因子 · Round1",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 行情：腾讯前复权 `_shared/daily`；BaoStock 黑名单",
        "- 成分：中证官网静态 xls（**幸存者偏差**；非 PIT）",
        "- 财务：本地 profit cache / 财务库",
        "- Mongo：未写入",
        "",
    ]
    merge = all_univ.get("csi300_500_1000")
    for u in ("hs300", "csi500", "csi1000"):
        payload = all_univ.get(u) or {}
        lines.append(f"## {u}")
        tops = payload.get("top") or []
        if not tops:
            lines.append("- （无合格候选）")
            lines.append("")
            continue
        for i, r in enumerate(tops, 1):
            lines.append(
                f"{i}. **{r.get('cfg_id')}**  Sharpe={r.get('sharpe')}  "
                f"ret={r.get('total_return')}  dd={r.get('max_drawdown')}  "
                f"legs={r.get('n_legs_accepted')}  family={r.get('family')}  "
                f"flags={r.get('overfit_flags') or []}"
            )
            if r.get("artifact_factor_id"):
                lines.append(f"   - 可挂 lahm 候选 id：`{r['artifact_factor_id']}`（尚未写 Mongo）")
        lines.append("")

    lines.append("## 合并宇宙对照 `csi300_500_1000`")
    if merge and merge.get("top"):
        r0 = merge["top"][0]
        lines.append(
            f"- 最佳：`{r0.get('cfg_id')}` Sharpe={r0.get('sharpe')} "
            f"ret={r0.get('total_return')} legs={r0.get('n_legs_accepted')}"
        )
    else:
        lines.append("- （无合格）")
    lines.append("")

    # 分宇宙 vs 合并：同一 cfg 对比
    lines.append("## 参数是否分宇宙更优")
    by_cfg: Dict[str, Dict[str, Any]] = {}
    for u, payload in all_univ.items():
        for r in payload.get("all") or []:
            if not r.get("ok"):
                continue
            by_cfg.setdefault(r["cfg_id"], {})[u] = r.get("sharpe")
    better_split = 0
    better_merge = 0
    compared = 0
    for cfg, umap in by_cfg.items():
        if "csi300_500_1000" not in umap:
            continue
        m = umap["csi300_500_1000"]
        if m is None:
            continue
        for u in ("hs300", "csi500", "csi1000"):
            if u not in umap or umap[u] is None:
                continue
            compared += 1
            if float(umap[u]) > float(m) + 0.05:
                better_split += 1
            elif float(m) > float(umap[u]) + 0.05:
                better_merge += 1
    lines.append(
        f"- 同配置对比次数={compared}：分宇宙 Sharpe 明显高于合并（>+0.05）={better_split}；"
        f"合并更高={better_merge}"
    )
    if better_split > better_merge:
        lines.append("- **结论倾向：参数分宇宙更优**（多数配置在子宇宙上更好）。")
    elif better_merge > better_split:
        lines.append("- **结论倾向：合并宇宙不差**；但仍建议保留分宇宙变体。")
    else:
        lines.append("- **结论：分宇宙与合并互有胜负**；建议按子宇宙保留最优变体。")
    lines.append("")
    lines.append("## 下一步")
    lines.append("- 扩大网格：利润断层 `q_np_gap`、demand_pricing（需 balance）、持有/止盈细网格")
    lines.append("- 若有 PIT 成分近似，做稳健性复核")
    lines.append("- 扎实候选再考虑挂 Mongo / lahm id")

    path = OUT_ROOT / "ROUND1_SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # machine-readable
    (OUT_ROOT / "round1_index.json").write_text(
        json.dumps(
            {
                "out_root": str(OUT_ROOT),
                "universes": {
                    u: {
                        "top": (all_univ.get(u) or {}).get("top"),
                        "n_cfgs": (all_univ.get(u) or {}).get("n_cfgs"),
                    }
                    for u in UNIVERSES
                },
                "split_vs_merge": {
                    "compared": compared,
                    "better_split": better_split,
                    "better_merge": better_merge,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default=",".join(UNIVERSES))
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-artifacts", action="store_true")
    args = ap.parse_args()
    univs = [u.strip() for u in args.universes.split(",") if u.strip()]

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not args.skip_build:
        build_universes(force=True)
    else:
        build_universes(force=False)

    grid = _grid()
    print(f"[grid] n_cfgs={len(grid)}", flush=True)

    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in univs:
        all_univ[u] = mine_universe(
            u, grid, write_top_artifacts=not args.no_artifacts
        )

    summary = write_round_summary(all_univ)
    print(f"\n[done] summary -> {summary}", flush=True)
    print(summary.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
