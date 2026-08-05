"""f(mkv) 分档参数 vs 常数对照：分宇宙（HS300 / CSI500 / CSI1000）。

用法:
  .venv\\Scripts\\python.exe scripts/mine_csi_fmkv_round1.py
  .venv\\Scripts\\python.exe scripts/mine_csi_fmkv_round1.py --universes hs300,csi500

市值 mkv = close × totalShare（profit cache 股本）。
params 例:
  margin_min_by_mkv: {"edges": [5e10, 2e11], "values": [0.14, 0.16, 0.18]}
  break_days_by_mkv: {"edges": [5e10, 2e11], "values": [80, 60, 40]}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402

OUT = ROOT / "data" / "factors" / "mine_csi300_500_1000_fmkv_round1"
START = "2018-01-01"
MIN_LEGS = 25

BENCH = {
    "hs300": "sh.000300",
    "csi500": "sh.000905",
    "csi1000": "sh.000852",
    "csi300_500_1000": "sh.000300",
}

# 分档边：500亿 / 2000亿（元）
EDGES_YUAN = [5e10, 2e11]


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
        "margin_improve": 0.006,
        "np_min": 0.10,
        "funda_lag": 28,
        "hold_days": 51,
        "stop_loss": 0.12,
        "take_profit": 0.35,
    }


def _grid() -> List[Tuple[str, str, Dict[str, Any]]]:
    """(cfg_id, kind, overrides). kind=const|fmkv"""
    rows: List[Tuple[str, str, Dict[str, Any]]] = []
    # 常数对照（与 round1 最佳邻居对齐：lag28 / m16 / brk60）
    rows.append(
        (
            "const__m16_brk60",
            "const",
            {"margin_min": 0.16, "break_days": 60},
        )
    )
    rows.append(
        (
            "const__m16_brk80",
            "const",
            {"margin_min": 0.16, "break_days": 80},
        )
    )
    rows.append(
        (
            "const__m14_brk60",
            "const",
            {"margin_min": 0.14, "break_days": 60},
        )
    )
    rows.append(
        (
            "const__m18_brk60",
            "const",
            {"margin_min": 0.18, "break_days": 60},
        )
    )
    # f(mkv): 小市值更松毛利门槛 / 更大突破窗；大市值更严 / 更短窗
    rows.append(
        (
            "fmkv__margin_tier3",
            "fmkv",
            {
                "break_days": 60,
                "margin_min_by_mkv": {
                    "edges": EDGES_YUAN,
                    "values": [0.14, 0.16, 0.18],  # 小→大：门槛升高
                },
            },
        )
    )
    rows.append(
        (
            "fmkv__break_tier3",
            "fmkv",
            {
                "margin_min": 0.16,
                "break_days_by_mkv": {
                    "edges": EDGES_YUAN,
                    "values": [80, 60, 40],  # 小市值要更长突破确认
                },
            },
        )
    )
    rows.append(
        (
            "fmkv__margin_break_tier3",
            "fmkv",
            {
                "margin_min_by_mkv": {
                    "edges": EDGES_YUAN,
                    "values": [0.14, 0.16, 0.18],
                },
                "break_days_by_mkv": {
                    "edges": EDGES_YUAN,
                    "values": [80, 60, 40],
                },
            },
        )
    )
    # 反向分档（对照：若正向有经济含义，反向应更差）
    rows.append(
        (
            "fmkv__margin_tier3_rev",
            "fmkv",
            {
                "break_days": 60,
                "margin_min_by_mkv": {
                    "edges": EDGES_YUAN,
                    "values": [0.18, 0.16, 0.14],
                },
            },
        )
    )
    return rows


def _eval(cfg_id: str, kind: str, params: Dict[str, Any], panel, bench) -> Dict[str, Any]:
    t0 = time.time()
    legs = collect_legs(panel, sig.signal_gross_expand_break, params)
    _daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=START
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    n_acc = int(summary.get("n_legs_accepted") or (0 if accepted is None else len(accepted)))
    flags = []
    if n_acc < MIN_LEGS:
        flags.append(f"few_legs<{MIN_LEGS}")
    return {
        "cfg_id": cfg_id,
        "kind": kind,
        "universe": params.get("universe"),
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "sharpe": summary.get("sharpe"),
        "total_return": summary.get("total_return"),
        "annual_return": summary.get("annual_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "n_legs_raw": summary.get("n_legs_raw", len(legs) if legs is not None else 0),
        "n_legs_accepted": n_acc,
        "error": summary.get("error"),
        "overfit_flags": flags,
        "ok": summary.get("error") is None and summary.get("sharpe") is not None,
        "elapsed_sec": round(time.time() - t0, 2),
    }


def mine_one(universe: str) -> Dict[str, Any]:
    print(f"\n======== fmkv {universe} ========", flush=True)
    base = _base(universe)
    panel = prepare_shared_panel(base, need_profit=True, need_growth=False, limit=0)
    print(f"[panel] {universe} n={len(panel)}", flush=True)

    # 市值覆盖率
    n_mkv = 0
    for px in panel.values():
        if "totalShare" in px.columns and pd.to_numeric(px["totalShare"], errors="coerce").notna().any():
            n_mkv += 1
    print(f"[mkv] codes_with_totalShare={n_mkv}/{len(panel)}", flush=True)

    cache = kit.shared_cache_dir()
    bc = BENCH[universe]
    bp = cache / "daily" / f"{bc.replace('.', '_')}.parquet"
    if not bp.exists():
        bp = cache / "daily" / "sh_000300.parquet"
        bc = "sh.000300"
    bench = pd.read_parquet(bp)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results = []
    for cfg_id, kind, extra in _grid():
        params = {**base, **extra, "bench_code": BENCH[universe]}
        params["_cache_dir"] = str(cache)
        try:
            row = _eval(cfg_id, kind, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": cfg_id,
                "kind": kind,
                "universe": universe,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-600:],
            }
        results.append(row)
        print(
            f"  {cfg_id}: sharpe={row.get('sharpe')} ret={row.get('total_return')} "
            f"dd={row.get('max_drawdown')} legs={row.get('n_legs_accepted')} flags={row.get('overfit_flags')}",
            flush=True,
        )

    ok = [r for r in results if r.get("ok")]
    ranked = sorted(ok, key=lambda r: float(r.get("sharpe") or -999), reverse=True)
    best_f = next((r for r in ranked if r.get("kind") == "fmkv"), None)
    best_c = next((r for r in ranked if r.get("kind") == "const"), None)
    delta = None
    if best_f and best_c and best_f.get("sharpe") is not None and best_c.get("sharpe") is not None:
        delta = float(best_f["sharpe"]) - float(best_c["sharpe"])

    payload = {
        "universe": universe,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_panel": len(panel),
        "n_with_mkv": n_mkv,
        "edges_yuan": EDGES_YUAN,
        "edges_note": "500亿 / 2000亿",
        "survivor_bias_note": "静态成分；非 PIT",
        "best_const": best_c,
        "best_fmkv": best_f,
        "sharpe_fmkv_minus_best_const": delta,
        "ranked": ranked,
        "all": results,
    }
    udir = OUT / universe
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def write_summary(all_u: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# f(mkv) 分档参数 Round1",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 信号：`signal_gross_expand_break` + `margin_min_by_mkv` / `break_days_by_mkv`",
        "- 市值：`mkv = close × totalShare`（profit cache）",
        "- 分档边：500亿 / 2000亿",
        "- 行情：腾讯 qfq；BaoStock 禁用；未写 Mongo",
        "",
        "## 怎么用",
        "",
        "```python",
        "params = {",
        '  "margin_improve": 0.006, "np_min": 0.10, "funda_lag": 28,',
        '  "hold_days": 51, "stop_loss": 0.12, "take_profit": 0.35,',
        '  "margin_min_by_mkv": {"edges": [5e10, 2e11], "values": [0.14, 0.16, 0.18]},',
        '  "break_days_by_mkv": {"edges": [5e10, 2e11], "values": [80, 60, 40]},',
        "}",
        "# 未给 *_by_mkv 时仍用常数 margin_min / break_days",
        "```",
        "",
    ]
    for u, p in all_u.items():
        lines.append(f"## {u}")
        bc, bf = p.get("best_const"), p.get("best_fmkv")
        d = p.get("sharpe_fmkv_minus_best_const")
        if bc:
            lines.append(
                f"- 最佳常数：`{bc.get('cfg_id')}` Sharpe={bc.get('sharpe')} "
                f"ret={bc.get('total_return')} legs={bc.get('n_legs_accepted')}"
            )
        if bf:
            lines.append(
                f"- 最佳 f(mkv)：`{bf.get('cfg_id')}` Sharpe={bf.get('sharpe')} "
                f"ret={bf.get('total_return')} legs={bf.get('n_legs_accepted')}"
            )
        lines.append(f"- deltaSharpe(fmkv-const)={d}")
        lines.append("")
        for r in (p.get("ranked") or [])[:6]:
            lines.append(
                f"  - [{r.get('kind')}] {r.get('cfg_id')}: "
                f"sh={r.get('sharpe')} ret={r.get('total_return')} "
                f"dd={r.get('max_drawdown')} legs={r.get('n_legs_accepted')}"
            )
        lines.append("")

    wins = sum(
        1
        for p in all_u.values()
        if p.get("sharpe_fmkv_minus_best_const") is not None
        and float(p["sharpe_fmkv_minus_best_const"]) > 0.02
    )
    lines.append("## 结论（首批）")
    lines.append(
        f"- 分宇宙中 f(mkv) 优于最佳常数（deltaSharpe>+0.02）的宇宙数：{wins}/{len(all_u)}"
    )
    path = OUT / "FMKV_ROUND1_SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "index.json").write_text(
        json.dumps(
            {
                "universes": {
                    u: {
                        "best_const": (p.get("best_const") or {}).get("cfg_id"),
                        "best_fmkv": (p.get("best_fmkv") or {}).get("cfg_id"),
                        "delta_sharpe": p.get("sharpe_fmkv_minus_best_const"),
                    }
                    for u, p in all_u.items()
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default="hs300,csi500,csi1000")
    args = ap.parse_args()
    univs = [u.strip() for u in args.universes.split(",") if u.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    all_u = {}
    for u in univs:
        # 确保宇宙缓存存在（不强制重拉，避免踩 round1）
        kit.fetch_universe_codes(u, kit.RateLimiter(0.01), kit.shared_cache_dir(), force=False)
        all_u[u] = mine_one(u)
    path = write_summary(all_u)
    print(f"\n[done] {path}", flush=True)
    print(path.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
