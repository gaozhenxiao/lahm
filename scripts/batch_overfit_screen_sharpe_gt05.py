#!/usr/bin/env python3
"""Batch overfitting screen for factors with Sharpe > 0.5.

Reads existing backtest CSVs / trade histories / rebacktest summary.
No re-run of backtests.

Usage (on server):
  .venv/bin/python scripts/batch_overfit_screen_sharpe_gt05.py
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FACTORS = ROOT / "data" / "factors"
OUT_JSON = FACTORS / "overfit_screen_sharpe_gt05.json"
OUT_MD = FACTORS / "overfit_screen_sharpe_gt05.md"
OUT_CSV = FACTORS / "overfit_screen_sharpe_gt05.csv"

RECENT2Y_CUT = "2024-08-01"
SEGMENTS = {
    "y2018_2021": ("2018-01-01", "2021-12-31"),
    "y2022_2023": ("2022-01-01", "2023-12-31"),
    "y2024_now": ("2024-01-01", None),
}

# factor_id patterns that strongly suggest grid / wave mining
MINE_PATTERNS = [
    (r"_sm[12]$", "struct_mass"),
    (r"_r2n$", "csi_round2"),
    (r"_r3$", "csi_round3"),
    (r"_causal$", "causal_mine"),
    (r"_yoy$", "yoy_mine"),
    (r"_opt\d+$", "opt_grid"),
    (r"_hold5[0-9]$", "hold_tune"),
    (r"_tp35$", "tp_tune"),
    (r"_champ", "champion"),
    (r"gross_expand_champ", "overnight_champ"),
    (r"_lag\d+", "lag_tune"),
    (r"_brk\d+", "brk_tune"),
    (r"_m1[0-9]_", "m_hold_tune"),
    (r"_imp0", "imp_tune"),
    (r"_h\d+_?", "hold_embed"),
]


def _sharpe(rets: pd.Series) -> Optional[float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 30:
        return None
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return None
    return float(r.mean() / sd * math.sqrt(252))


def _total_return(equity: pd.Series) -> Optional[float]:
    e = pd.to_numeric(equity, errors="coerce").dropna()
    if e.empty:
        return None
    return float(e.iloc[-1] / e.iloc[0] - 1.0)


def _max_dd(equity: pd.Series) -> Optional[float]:
    e = pd.to_numeric(equity, errors="coerce").dropna()
    if e.empty:
        return None
    peak = e.cummax()
    dd = e / peak - 1.0
    return float(dd.min())


def _slice_metrics(daily: pd.DataFrame, start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    df = daily
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    if df.empty:
        return {"empty": True}
    return {
        "empty": False,
        "sharpe": _sharpe(df["strategy_ret"]),
        "total_return": _total_return(df["equity"]),
        "max_drawdown": _max_dd(df["equity"]),
        "n_days": int(len(df)),
        "start": str(df["date"].iloc[0].date()),
        "end": str(df["date"].iloc[-1].date()),
    }


def _mine_tags(fid: str) -> List[str]:
    tags = []
    for pat, name in MINE_PATTERNS:
        if re.search(pat, fid):
            tags.append(name)
    # numeric soup: many underscore-separated numeric tokens
    nums = re.findall(r"(?:^|_)(?:clacc|y|brk|ar|ry|ox|gp|inv|lag|h|m|tp|imp|racc|qacc|dd|sof|a|c)\d+", fid)
    if len(nums) >= 3:
        tags.append("param_soup")
    return sorted(set(tags))


def _family_key(fid: str) -> str:
    # strip trailing tuned suffixes for sibling grouping
    s = fid
    s = re.sub(r"_(sm[12]|r2n|r3|causal|yoy)$", "", s)
    s = re.sub(r"_opt\d+$", "", s)
    # keep leading family token(s)
    parts = s.split("_")
    if len(parts) >= 2:
        return "_".join(parts[:2])
    return parts[0]


def _concentration(trades: pd.DataFrame) -> Dict[str, Any]:
    if trades.empty or "nav_pnl" not in trades.columns:
        return {"top10_share": None, "n_codes": 0}
    t = trades.copy()
    t["nav_pnl"] = pd.to_numeric(t["nav_pnl"], errors="coerce")
    # close legs often have pnl
    closed = t[t["nav_pnl"].notna()]
    if closed.empty:
        return {"top10_share": None, "n_codes": int(t["code"].nunique()) if "code" in t.columns else 0}
    by = closed.groupby("code")["nav_pnl"].sum().sort_values(ascending=False)
    pos = by[by > 0]
    if pos.empty or float(pos.sum()) <= 0:
        return {"top10_share": 0.0, "n_codes": int(by.shape[0]), "top5": []}
    top10 = float(pos.head(10).sum() / pos.sum())
    return {
        "top10_share": top10,
        "n_codes": int(by.shape[0]),
        "top5": [{"code": str(i), "pnl": float(v)} for i, v in pos.head(5).items()],
    }


def _end_load(daily: pd.DataFrame) -> Optional[float]:
    """Fraction of log-equity growth in last calendar year vs full sample."""
    if daily.empty:
        return None
    e = daily.set_index("date")["equity"].astype(float)
    if e.iloc[0] <= 0 or e.iloc[-1] <= 0:
        return None
    full = math.log(e.iloc[-1] / e.iloc[0])
    if abs(full) < 1e-9:
        return None
    last_year_start = e.index.max() - pd.DateOffset(years=1)
    e2 = e[e.index >= last_year_start]
    if len(e2) < 20:
        return None
    last = math.log(e2.iloc[-1] / e2.iloc[0])
    return float(last / full)


def analyze_one(fid: str, summary_row: Dict[str, Any]) -> Dict[str, Any]:
    csv_path = FACTORS / f"{fid}_backtest.csv"
    trade_path = FACTORS / f"{fid}_trade_history.csv"
    daily = pd.read_csv(csv_path, parse_dates=["date"])
    trades = pd.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()

    segs = {k: _slice_metrics(daily, a, b) for k, (a, b) in SEGMENTS.items()}
    recent2y = _slice_metrics(daily, RECENT2Y_CUT, None)

    # calendar year sharpes
    yearly: Dict[str, Optional[float]] = {}
    for y, g in daily.groupby(daily["date"].dt.year):
        yearly[str(int(y))] = _sharpe(g["strategy_ret"])

    mine_tags = _mine_tags(fid)
    conc = _concentration(trades)
    end_load = _end_load(daily)

    sharpe = summary_row.get("sharpe")
    annual = summary_row.get("annual_return")
    mdd = summary_row.get("max_drawdown")
    total = summary_row.get("total_return")
    n_legs = int(summary_row.get("n_legs_accepted") or 0)

    flags: List[str] = []
    early_sh = (segs.get("y2018_2021") or {}).get("sharpe")
    late_sh = (segs.get("y2024_now") or {}).get("sharpe")
    mid_sh = (segs.get("y2022_2023") or {}).get("sharpe")
    r2_sh = recent2y.get("sharpe")
    r2_ret = recent2y.get("total_return")

    if mine_tags:
        flags.append("mined_params")
    if n_legs < 30:
        flags.append(f"few_legs<{n_legs}")
    if n_legs < 40 and total is not None and float(total) > 8:
        flags.append("high_ret_few_legs")
    if n_legs < 15:
        flags.append("tiny_sample")
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if r2_sh is not None and float(r2_sh) < 0:
        flags.append("recent2y_neg")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")
    if late_sh is not None and float(late_sh) < 0 and early_sh is not None and float(early_sh) > 0.8:
        flags.append("late_collapse")
    # any calendar year sharply negative while full sharpe high
    neg_years = [y for y, s in yearly.items() if s is not None and s < -0.2]
    if len(neg_years) >= 2 and sharpe is not None and float(sharpe) > 0.8:
        flags.append(f"multi_neg_years:{','.join(neg_years)}")
    if yearly.get("2025") is not None and yearly["2025"] < 0:
        flags.append("y2025_neg")
    if conc.get("top10_share") is not None and conc["top10_share"] > 0.45:
        flags.append("concentrated_top10")
    if end_load is not None and end_load > 0.55 and sharpe is not None and float(sharpe) > 0.8:
        flags.append("end_loaded")
    if sharpe is not None and float(sharpe) > 1.2 and annual is not None and float(annual) > 0.35:
        flags.append("implausible_mag")
    if mdd is not None and float(mdd) < -0.55 and sharpe is not None and float(sharpe) > 0.9:
        flags.append("high_sharpe_deep_dd")

    # risk rating
    hard = {
        "early_inflated_recent_poor",
        "recent2y_big_loss",
        "high_ret_few_legs",
        "tiny_sample",
        "implausible_mag",
    }
    hard_hit = [f for f in flags if f in hard or f.startswith("few_legs") and n_legs < 10]
    soft = [
        "mined_params",
        "recent2y_neg",
        "recent2y_neg_sharpe",
        "late_collapse",
        "y2025_neg",
        "concentrated_top10",
        "end_loaded",
        "high_sharpe_deep_dd",
    ]
    soft_hit = [f for f in flags if f in soft or f.startswith("multi_neg_years")]

    if hard_hit or ( "mined_params" in flags and ("y2025_neg" in flags or "late_collapse" in flags or "implausible_mag" in flags)):
        risk = "high"
    elif ("mined_params" in flags and len(soft_hit) >= 2) or len(soft_hit) >= 3 or ("mined_params" in flags and float(sharpe or 0) > 1.0):
        risk = "high" if float(sharpe or 0) > 1.15 else "medium"
    elif soft_hit or "mined_params" in flags:
        risk = "medium"
    else:
        risk = "low"

    # classic tech with many legs → prefer not high unless time broken
    classic_tech = fid in {
        "volume_breakout",
        "narrow_range_breakout",
        "boll_lower_reclaim",
        "dual_ma_volume",
        "new_high_pullback",
        "turn_surge_ma_reclaim",
        "ret20_extreme_bounce",
        "amount_shrink_breakout",
    }
    if classic_tech and n_legs >= 500 and "early_inflated_recent_poor" not in flags:
        if risk == "high" and not hard_hit:
            risk = "medium"
        elif risk == "medium" and not soft_hit:
            risk = "low"

    return {
        "factor_id": fid,
        "family": _family_key(fid),
        "sharpe": sharpe,
        "annual_return": annual,
        "max_drawdown": mdd,
        "total_return": total,
        "n_legs_accepted": n_legs,
        "mine_tags": mine_tags,
        "flags": flags,
        "risk": risk,
        "early_sharpe": early_sh,
        "mid_sharpe": mid_sh,
        "late_sharpe": late_sh,
        "recent2y_sharpe": r2_sh,
        "recent2y_return": r2_ret,
        "y2024_sharpe": yearly.get("2024"),
        "y2025_sharpe": yearly.get("2025"),
        "y2026_sharpe": yearly.get("2026"),
        "yearly": yearly,
        "top10_share": conc.get("top10_share"),
        "end_load": end_load,
        "segments": segs,
    }


def sibling_penalty(rows: List[Dict[str, Any]]) -> None:
    by_fam: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r)
    for fam, items in by_fam.items():
        if len(items) < 2:
            continue
        sharpes = [float(x["sharpe"]) for x in items if x.get("sharpe") is not None]
        if len(sharpes) < 2:
            continue
        mx, mn = max(sharpes), min(sharpes)
        drop = (mx - mn) / mx if mx > 0 else 0.0
        for x in items:
            x["family_n"] = len(items)
            x["family_sharpe_max"] = mx
            x["family_sharpe_min"] = mn
            x["family_drop_pct"] = drop
            if drop > 0.25 and float(x.get("sharpe") or 0) >= mx - 1e-9:
                x["flags"] = list(dict.fromkeys([*(x.get("flags") or []), "family_peak_fragile"]))
                # bump risk if mined
                if "mined_params" in (x.get("flags") or []) and x.get("risk") == "medium":
                    x["risk"] = "high"
                elif x.get("risk") == "low":
                    x["risk"] = "medium"


def main() -> None:
    summary = json.loads((FACTORS / "rebacktest_all_summary.json").read_text(encoding="utf-8"))
    results = summary.get("results") or {}
    ids = []
    for fid, r in results.items():
        if not isinstance(r, dict):
            continue
        sh = r.get("sharpe")
        if sh is None:
            continue
        try:
            if float(sh) > 0.5:
                ids.append(fid)
        except Exception:
            continue
    ids = sorted(ids, key=lambda x: -float(results[x].get("sharpe") or 0))
    print(f"[overfit] screening n={len(ids)}", flush=True)

    rows: List[Dict[str, Any]] = []
    for i, fid in enumerate(ids, 1):
        try:
            row = analyze_one(fid, results[fid])
            rows.append(row)
            print(
                f"[{i}/{len(ids)}] {row['risk']:6} sh={row['sharpe']:.3f} "
                f"{fid} flags={row['flags']}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(ids)}] ERROR {fid}: {exc}", flush=True)
            rows.append(
                {
                    "factor_id": fid,
                    "risk": "unknown",
                    "sharpe": results[fid].get("sharpe"),
                    "flags": [f"error:{exc}"],
                    "error": str(exc),
                }
            )

    sibling_penalty(rows)

    # recount after sibling bump
    by_risk = defaultdict(list)
    for r in rows:
        by_risk[r.get("risk") or "unknown"].append(r)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n": len(rows),
        "counts": {k: len(v) for k, v in sorted(by_risk.items())},
        "high": [x["factor_id"] for x in by_risk.get("high", [])],
        "medium": [x["factor_id"] for x in by_risk.get("medium", [])],
        "low": [x["factor_id"] for x in by_risk.get("low", [])],
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV flat
    flat = []
    for r in rows:
        flat.append(
            {
                "risk": r.get("risk"),
                "sharpe": r.get("sharpe"),
                "annual_return": r.get("annual_return"),
                "max_drawdown": r.get("max_drawdown"),
                "n_legs": r.get("n_legs_accepted"),
                "factor_id": r.get("factor_id"),
                "family": r.get("family"),
                "mine_tags": "|".join(r.get("mine_tags") or []),
                "flags": "|".join(r.get("flags") or []),
                "early_sharpe": r.get("early_sharpe"),
                "mid_sharpe": r.get("mid_sharpe"),
                "late_sharpe": r.get("late_sharpe"),
                "recent2y_sharpe": r.get("recent2y_sharpe"),
                "y2025_sharpe": r.get("y2025_sharpe"),
                "top10_share": r.get("top10_share"),
                "end_load": r.get("end_load"),
                "family_drop_pct": r.get("family_drop_pct"),
            }
        )
    pd.DataFrame(flat).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    def _fmt_list(items: List[Dict[str, Any]], limit: int = 40) -> str:
        lines = []
        for r in sorted(items, key=lambda x: -float(x.get("sharpe") or 0))[:limit]:
            flags = ",".join(r.get("flags") or [])
            lines.append(
                f"| {float(r.get('sharpe') or 0):.2f} | `{r['factor_id']}` | "
                f"{r.get('y2025_sharpe')} | {flags} |"
            )
        return "\n".join(lines) if lines else "_无_"

    md = []
    md.append("# Sharpe>0.5 过拟合批量体检")
    md.append("")
    md.append(f"- 生成时间: `{payload['generated_at']}`")
    md.append(f"- 样本数: **{payload['n']}**")
    md.append(f"- 风险计数: `{payload['counts']}`")
    md.append("")
    md.append("## 判定规则（摘要）")
    md.append("- **高**: 挖矿参数 +（近年转负 / 量级不可信 / 远年虚高近年崩）或极少腿高收益等硬伤")
    md.append("- **中**: 挖矿来源或时间/集中度/同族脆弱等软伤")
    md.append("- **低**: 非明显网格挖矿，时间段相对平稳，腿数充足")
    md.append("")
    md.append("## 高风险")
    md.append("| Sharpe | factor_id | 2025 Sharpe | flags |")
    md.append("|---:|---|---:|---|")
    md.append(_fmt_list(by_risk.get("high", []), 80))
    md.append("")
    md.append("## 中风险")
    md.append("| Sharpe | factor_id | 2025 Sharpe | flags |")
    md.append("|---:|---|---:|---|")
    md.append(_fmt_list(by_risk.get("medium", []), 80))
    md.append("")
    md.append("## 低风险")
    md.append("| Sharpe | factor_id | 2025 Sharpe | flags |")
    md.append("|---:|---|---:|---|")
    md.append(_fmt_list(by_risk.get("low", []), 80))
    md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False), flush=True)
    print(f"[ok] -> {OUT_JSON}", flush=True)
    print(f"[ok] -> {OUT_MD}", flush=True)
    print(f"[ok] -> {OUT_CSV}", flush=True)


if __name__ == "__main__":
    main()
