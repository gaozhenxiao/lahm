"""因子 #188 ``ipo_2y5_earn_break``：按「大跌→横盘→≈2.5年+业绩改善」形态增强并试跑。

覆盖旧 opt188 参数搜索结果；更新同一 factor_id（UI#188）。不 git commit。

用法：
  .venv\\Scripts\\python.exe scripts/enhance_ipo_188_morph.py
  .venv\\Scripts\\python.exe scripts/enhance_ipo_188_morph.py --apply
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    build_legs_from_entries,
    prepare_shared_panel,
    run_factor_pipeline,
)

FACTOR_ID = "ipo_2y5_earn_break"
FACTOR_UI = 188
FACTOR_NAME = "IPO大跌横盘≈2.5年+业绩改善(csi_core)"
OUT_DIR = ROOT / "data" / "factors" / "enhance_ipo_188_morph"
OUT_STEM = OUT_DIR / "morph_report"
CUT = "2024-08-01"
START = "2018-01-01"
MIN_ACCEPTED = 20

SEGMENTS = (
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_now", "2024-01-01", None, 0.50),
)

BASE: Dict[str, Any] = {
    "universe": "csi_core",
    "exclude_st": True,
    "price_start": "2010-01-01",
    "price_end": "2026-07-30",
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.003,
    "np_improve": 0.003,
    "funda_lag": 28,
    "require_ipo_crash": True,
    "require_consol": True,
    "entry_mode": "soft",
    "use_break": True,
    "require_ma20": False,
    "require_rev": False,
    "position_logic": FACTOR_ID,
    "note": FACTOR_NAME,
}

SIG_KEYS = (
    "ipo_age_lo",
    "ipo_age_hi",
    "ipo_crash_months",
    "ipo_crash_dd",
    "require_ipo_crash",
    "consol_window",
    "consol_amp_max",
    "consol_ma_band",
    "require_consol",
    "entry_mode",
    "break_days",
    "brk_soft",
    "require_ma20",
    "use_break",
    "margin_improve",
    "np_improve",
    "funda_lag",
    "np_min",
)


def _bs_disabled(*_a, **_k):
    raise RuntimeError("BaoStock disabled (qfq local-cache only)")


def _parse_list_date(v: Any) -> Optional[pd.Timestamp]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.normalize()
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "nat"):
        return None
    if len(s) == 8 and s.isdigit():
        return pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
    try:
        return pd.Timestamp(s).normalize()
    except Exception:  # noqa: BLE001
        return None


def load_list_dates() -> Dict[str, pd.Timestamp]:
    basic = fin_db.fetch_basic()
    out: Dict[str, pd.Timestamp] = {}
    if basic is None or basic.empty:
        return out
    for _, r in basic.iterrows():
        code = r.get("code")
        ld = _parse_list_date(r.get("S_INFO_LISTDATE"))
        if code and ld is not None:
            out[str(code)] = ld
    return out


def attach_list_dates(
    price_map: Dict[str, pd.DataFrame], list_map: Dict[str, pd.Timestamp]
) -> Dict[str, pd.DataFrame]:
    out = {}
    for code, px in price_map.items():
        df = px.copy()
        ld = list_map.get(code)
        df["list_date"] = ld if ld is not None else pd.NaT
        out[code] = df
    return out


def _sharpe(rets: pd.Series) -> Optional[float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or r.std(ddof=0) == 0:
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
    recent2y = _slice_metrics(daily, CUT, None)
    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    full_sh = None
    if "equity" in daily.columns and len(daily) > 5:
        full_sh = _sharpe(daily["equity"].pct_change().iloc[1:])
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if full_sh is not None and float(full_sh) < 0.05:
        flags.append("full_near_zero")
    if full_sh is not None and float(full_sh) < -0.1:
        flags.append("full_crash")
    penalty = 0.0
    if "recent2y_big_loss" in flags:
        penalty += 0.35
    elif "recent2y_neg_sharpe" in flags:
        penalty += 0.20
    if "full_crash" in flags:
        penalty += 0.40
    elif "full_near_zero" in flags:
        penalty += 0.15
    r2_bonus = 0.25 * float(r2_sh) if r2_sh is not None else 0.0
    tw_adj = (float(tw_sharpe) + r2_bonus - penalty) if tw_sharpe is not None else None
    return {
        "segments": segs,
        "tw_sharpe": tw_sharpe,
        "tw_score": tw_adj,
        "tw_flags": flags,
        "recent2y": recent2y,
        "full_sharpe_from_eq": full_sh,
    }


def build_cfgs() -> List[Dict[str, Any]]:
    """紧凑网格：形态 × 出场；近年加权选参。"""
    morph = []
    for age_lo, age_hi in ((2.4, 3.0), (2.5, 3.0)):
        for crash_m, crash_dd in ((12, -0.40), (18, -0.40), (18, -0.45), (18, -0.50)):
            for cwin, camp in ((100, 0.32), (120, 0.35)):
                for entry, brk, soft in (
                    ("soft", 40, 0.985),
                    ("soft", 55, 0.98),
                    ("stabilize", 40, 0.985),
                ):
                    morph.append(
                        {
                            "ipo_age_lo": age_lo,
                            "ipo_age_hi": age_hi,
                            "ipo_crash_months": crash_m,
                            "ipo_crash_dd": crash_dd,
                            "consol_window": cwin,
                            "consol_amp_max": camp,
                            "consol_ma_band": 0.08,
                            "entry_mode": entry,
                            "break_days": brk,
                            "brk_soft": soft,
                            "margin_improve": 0.003,
                            "np_improve": 0.003,
                            "funda_lag": 28,
                        }
                    )

    exits = []
    for hold, mp, sl, tp in itertools.product(
        (80, 100, 120),
        (12, 14, 15),
        (0.12, 0.15),
        (0.35, 0.45),
    ):
        exits.append({"hold_days": hold, "max_positions": mp, "stop_loss": sl, "take_profit": tp})

    phase1 = []
    seen = set()
    for m in morph:
        p = {**BASE, **m, "hold_days": 100, "max_positions": 14, "stop_loss": 0.12, "take_profit": 0.40}
        k = tuple((kk, p.get(kk)) for kk in SIG_KEYS)
        if k in seen:
            continue
        seen.add(k)
        phase1.append(p)
    return phase1, exits  # type: ignore[return-value]


def _entries_cache(panel: Dict[str, pd.DataFrame], sig_params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    cache: Dict[str, pd.DataFrame] = {}
    for code, px in panel.items():
        try:
            e = sig.signal_ipo_age_earn_break(px, sig_params)
            if e is None or e.empty:
                continue
            ee = e.copy()
            ee["code"] = code
            cache[code] = ee
        except Exception:  # noqa: BLE001
            continue
    return cache


def _legs_from_cache(
    entries_by_code: Dict[str, pd.DataFrame],
    panel: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> pd.DataFrame:
    hold = int(params.get("hold_days") or 20)
    stop = float(params.get("stop_loss") or 0.15)
    tp_raw = params.get("take_profit")
    take_profit = float(tp_raw) if tp_raw is not None else None
    all_legs: List[dict] = []
    for code, entries in entries_by_code.items():
        px = panel.get(code)
        if px is None or entries is None or entries.empty:
            continue
        all_legs.extend(
            build_legs_from_entries(
                entries, px, hold_days=hold, stop_loss=stop, take_profit=take_profit
            )
        )
    if not all_legs:
        return pd.DataFrame()
    legs = pd.DataFrame(all_legs)
    legs = legs.sort_values(["code", "entry_date"]).drop_duplicates(
        ["code", "entry_date"], keep="first"
    )
    return legs.reset_index(drop=True)


def eval_params(
    cfg_id: str,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    entries_by_code: Dict[str, pd.DataFrame],
) -> Dict[str, Any]:
    p = dict(params)
    p["_cache_dir"] = str(kit.shared_cache_dir())
    p["position_logic"] = FACTOR_ID
    legs = _legs_from_cache(entries_by_code, panel, p)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=p, bench_daily=bench, start=START
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    tw = (
        _time_weight_score(daily)
        if isinstance(daily, pd.DataFrame) and not daily.empty
        else {"tw_score": None, "recent2y": {"empty": True}, "tw_flags": ["no_daily"]}
    )
    n_acc = int(summary.get("n_legs_accepted") or 0)
    flags = list(tw.get("tw_flags") or [])
    if n_acc < MIN_ACCEPTED:
        flags.append("too_few_legs")
    r2 = tw.get("recent2y") or {}
    return {
        "cfg_id": cfg_id,
        "params": {k: v for k, v in p.items() if not str(k).startswith("_")},
        "tw_score": tw.get("tw_score"),
        "tw_sharpe": tw.get("tw_sharpe"),
        "tw_flags": flags,
        "sharpe": summary.get("sharpe"),
        "total_return": summary.get("total_return"),
        "annual_return": summary.get("annual_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "n_legs_accepted": n_acc,
        "avg_position": summary.get("avg_position"),
        "recent2y_sharpe": r2.get("sharpe"),
        "recent2y_return": r2.get("total_return"),
        "recent2y_max_drawdown": r2.get("max_drawdown"),
        "segments": tw.get("segments"),
    }


def _rank_key(r: Dict[str, Any]) -> Tuple[float, float, float]:
    bad = 1 if (r.get("tw_flags") and "too_few_legs" in r["tw_flags"]) else 0
    if bad:
        return (-999.0, -999.0, -999.0)
    return (
        float(r.get("tw_score") if r.get("tw_score") is not None else -999),
        float(r.get("recent2y_sharpe") if r.get("recent2y_sharpe") is not None else -999),
        float(r.get("recent2y_return") if r.get("recent2y_return") is not None else -999),
    )


def _sig_key(p: Dict[str, Any]) -> str:
    return "|".join(f"{k}={p.get(k)}" for k in SIG_KEYS if p.get(k) is not None)


def _mongo_targets():
    uri = settings.MONGO_URI or "mongodb://admin:lahm123@localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    targets = list(
        dict.fromkeys(
            [
                settings.MONGO_DB,
                "lahm",
                "lahm_v0_gaozx-laptop-rren219t",
                "lahm_v0_gaozx-desktop-v0c4gt8",
            ]
        )
    )
    return [t for t in targets if t and t in client.list_database_names()], client


def _fmt_param_block(best: Dict[str, Any]) -> str:
    keys = [
        "universe",
        "exclude_st",
        "price_start",
        "price_end",
        "ipo_age_lo",
        "ipo_age_hi",
        "require_ipo_crash",
        "ipo_crash_months",
        "ipo_crash_dd",
        "require_consol",
        "consol_window",
        "consol_amp_max",
        "consol_ma_band",
        "entry_mode",
        "break_days",
        "brk_soft",
        "use_break",
        "require_ma20",
        "margin_improve",
        "np_improve",
        "funda_lag",
        "hold_days",
        "stop_loss",
        "take_profit",
        "max_positions",
    ]
    lines = []
    for k in keys:
        if k not in best:
            continue
        v = best[k]
        if isinstance(v, str):
            lines.append(f'            {k}="{v}",')
        elif isinstance(v, bool):
            lines.append(f"            {k}={'True' if v else 'False'},")
        else:
            lines.append(f"            {k}={v},")
    return "\n".join(lines)


def update_registry(best: Dict[str, Any], desc: str) -> None:
    path = ROOT / "app" / "services" / "factors" / "factor_registry.py"
    text = path.read_text(encoding="utf-8")
    start = text.find('    "ipo_2y5_earn_break": {')
    if start < 0:
        raise RuntimeError("ipo_2y5_earn_break block not found")
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
        raise RuntimeError("failed to parse block")
    desc_esc = desc.replace("\\", "\\\\").replace('"', '\\"')
    new_block = (
        '    "ipo_2y5_earn_break": {\n'
        f'        "name": "{FACTOR_NAME}",\n'
        '        "category": "fundamental",\n'
        '        "description": (\n'
        f'            "{desc_esc}"\n'
        "        ),\n"
        '        "tags": ["IPO", "大跌", "横盘", "解禁代理", "业绩改善", "突破", '
        '"基本面", "技术面", "csi_core", "qfq", "expt_ipo_2y5", "morph188"],\n'
        '        "title": "IPO crash-base 2.5y earn soft entry",\n'
        '        "need_profit": True,\n'
        '        "need_growth": False,\n'
        '        "signal": sig.signal_ipo_age_earn_break,\n'
        '        "params": _p(\n'
        f"{_fmt_param_block(best)}\n"
        "        ),\n"
        "    },"
    )
    path.write_text(text[:start] + new_block + text[j:], encoding="utf-8")
    print(f"[registry] updated {path}", flush=True)


def update_mongo(best: Dict[str, Any], summary: Dict[str, Any], late: Dict[str, Any], desc: str):
    targets, client = _mongo_targets()
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    summary_dst = {k: v for k, v in summary.items() if not str(k).startswith("_")}
    summary_dst["position_logic"] = FACTOR_ID
    summary_dst["recent2y_sharpe"] = late.get("sharpe")
    summary_dst["recent2y_return"] = late.get("total_return")
    summary_dst["recent2y_max_drawdown"] = late.get("max_drawdown")
    payload = {
        "name": FACTOR_NAME,
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
            "morph188",
        ],
        "params": {k: v for k, v in best.items() if not str(k).startswith("_")},
        "updated_at": now,
        "signal": "signal_ipo_age_earn_break",
        "backtest_summary": {
            "available": True,
            "primary_logic": FACTOR_ID,
            "logics": {FACTOR_ID: summary_dst},
            "updated_at": now_s,
            **{
                k: summary_dst.get(k)
                for k in (
                    "total_return",
                    "annual_return",
                    "sharpe",
                    "max_drawdown",
                    "avg_position",
                    "recent2y_sharpe",
                    "recent2y_return",
                    "recent2y_max_drawdown",
                )
            },
        },
        "late_summary": late,
        "source_opt": "enhance_ipo_188_morph",
    }
    results = []
    for dbn in targets:
        r = client[dbn].factors.update_one({"factor_id": FACTOR_ID}, {"$set": payload}, upsert=False)
        results.append({"db": dbn, "matched": r.matched_count, "modified": r.modified_count})
        print(
            f"[mongo] update {dbn}.{FACTOR_ID} matched={r.matched_count} mod={r.modified_count}",
            flush=True,
        )
    return results


def make_desc(p: Dict[str, Any]) -> str:
    return (
        f"形态：上市后0–{p.get('ipo_crash_months')}月最大回撤≤{p.get('ipo_crash_dd')}；"
        f"随后横盘(窗{p.get('consol_window')}日振幅≤{p.get('consol_amp_max')}或贴ma60±{p.get('consol_ma_band')})；"
        f"年龄∈[{p.get('ipo_age_lo')},{p.get('ipo_age_hi')})+毛利/净利改善；"
        f"入场={p.get('entry_mode')}(brk{p.get('break_days')}/soft{p.get('brk_soft')})；"
        f"hold={p.get('hold_days')}/mp={p.get('max_positions')}/sl={p.get('stop_loss')}/tp={p.get('take_profit')}；"
        f"宇宙csi_core；腾讯qfq。morph188。"
    )


def apply_best(best_row: Dict[str, Any], list_map: Dict[str, pd.Timestamp]) -> Dict[str, Any]:
    params = deepcopy(best_row["params"])
    params["position_logic"] = FACTOR_ID
    params["note"] = FACTOR_NAME
    desc = make_desc(params)
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    panel = prepare_shared_panel(params, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    summary = run_factor_pipeline(
        FACTOR_ID,
        FACTOR_NAME,
        sig.signal_ipo_age_earn_break,
        params,
        need_profit=False,
        price_map=panel,
        start=START,
    )
    daily_path = ROOT / "data" / "factors" / f"{FACTOR_ID}_backtest.csv"
    late: Dict[str, Any] = {}
    if daily_path.exists():
        daily = pd.read_csv(daily_path)
        late = _slice_metrics(daily, CUT, None)
    update_registry(params, desc)
    mongo_res = update_mongo(params, summary, late, desc)
    return {
        "params": params,
        "description": desc,
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
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--top-morph", type=int, default=8, help="形态 topN 再扫出场")
    args = ap.parse_args()

    t0 = time.time()
    if hasattr(kit, "fetch_daily_from_baostock"):
        kit.fetch_daily_from_baostock = _bs_disabled  # type: ignore
    kit.login_baostock = _bs_disabled  # type: ignore[attr-defined]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    list_map = load_list_dates()
    print(f"[list_date] n={len(list_map)}", flush=True)

    phase1, exits = build_cfgs()
    if args.limit:
        phase1 = phase1[: args.limit]
    print(f"[phase1] morph configs={len(phase1)}", flush=True)

    params0 = deepcopy(BASE)
    params0.update(
        {
            "ipo_age_lo": 2.4,
            "ipo_age_hi": 3.0,
            "ipo_crash_months": 18,
            "ipo_crash_dd": -0.45,
            "consol_window": 120,
            "consol_amp_max": 0.32,
            "hold_days": 100,
            "max_positions": 14,
            "stop_loss": 0.12,
            "take_profit": 0.40,
            "break_days": 40,
            "brk_soft": 0.985,
        }
    )
    print("[panel] prepare csi_core", flush=True)
    panel = prepare_shared_panel(params0, need_profit=True, need_growth=False)
    panel = attach_list_dates(panel, list_map)
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        str(params0.get("price_start") or "2016-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache,
    )

    results: List[Dict[str, Any]] = []
    entries_memo: Dict[str, Dict[str, pd.DataFrame]] = {}

    for i, sp in enumerate(phase1, 1):
        sk = _sig_key(sp)
        if sk not in entries_memo:
            entries_memo[sk] = _entries_cache(panel, sp)
        n_ent = sum(len(v) for v in entries_memo[sk].values())
        row = eval_params(f"morph_{i}", sp, panel, bench, entries_memo[sk])
        results.append(row)
        if i % 5 == 0 or i == len(phase1):
            print(
                f"  [{i}/{len(phase1)}] tw={row.get('tw_score')} sh={row.get('sharpe')} "
                f"r2y_sh={row.get('recent2y_sharpe')} legs={row.get('n_legs_accepted')} "
                f"entries={n_ent} flags={row.get('tw_flags')}",
                flush=True,
            )

    morph_ranked = sorted(results, key=_rank_key, reverse=True)
    top = morph_ranked[: max(1, args.top_morph)]
    print(f"[phase2] exit sweep on top {len(top)} morph × {len(exits)} exits", flush=True)

    phase2: List[Dict[str, Any]] = []
    for mi, mrow in enumerate(top, 1):
        base_p = dict(mrow["params"])
        sk = _sig_key(base_p)
        ents = entries_memo.get(sk) or _entries_cache(panel, base_p)
        for ei, ex in enumerate(exits, 1):
            p = {**base_p, **ex}
            row = eval_params(f"top{mi}_ex{ei}", p, panel, bench, ents)
            phase2.append(row)
        print(
            f"  morph#{mi} best so far tw={max((_rank_key(r)[0] for r in phase2), default=-999)}",
            flush=True,
        )

    all_rows = results + phase2
    ranked = sorted(all_rows, key=_rank_key, reverse=True)
    best = ranked[0] if ranked else None
    payload = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "factor_id": FACTOR_ID,
        "ui": FACTOR_UI,
        "n_phase1": len(results),
        "n_phase2": len(phase2),
        "best": best,
        "top10": ranked[:10],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if args.apply and best:
        payload["apply"] = apply_best(best, list_map)

    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        f"# #188 morph enhance report",
        "",
        f"- generated: {payload['generated_at']}",
        f"- elapsed: {payload['elapsed_sec']}s",
        f"- phase1/phase2: {payload['n_phase1']}/{payload['n_phase2']}",
        "",
        "## Best",
        "",
        f"```json\n{json.dumps(best, ensure_ascii=False, indent=2, default=str)}\n```",
    ]
    OUT_STEM.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {OUT_STEM}.json/.md", flush=True)
    if best:
        print(
            f"[best] tw={best.get('tw_score')} sh={best.get('sharpe')} "
            f"ret={best.get('total_return')} r2y_sh={best.get('recent2y_sharpe')} "
            f"r2y_ret={best.get('recent2y_return')} legs={best.get('n_legs_accepted')}",
            flush=True,
        )
        print(json.dumps(best.get("params"), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
