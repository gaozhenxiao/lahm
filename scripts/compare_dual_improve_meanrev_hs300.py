"""对照 #171 dual_improve breakout vs 反向技术 meanrev（同财务/仓位/HS300/qfq）。

- 全样本 + 近2年（equity 切片 2024-08-01～）
- 若 meanrev 近窗明显改善 → max(UI)+1 写入 lahm（不占 166/168/171）
- BaoStock 禁用；不 commit
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

REF_FACTOR = "dual_improve_hs300_mine_r1"
MEANREV_FACTOR = "dual_improve_hs300_meanrev_r1"
TITLE_MR = "双改善均值回归(HS300·反突破)"
NAME_MR = "双改善均值回归(财务同#171·弱势回撤企稳·HS300·qfq)"
CUT = "2024-08-01"
OUT_STEM = ROOT / "data" / "factors" / "dual_improve_breakout_vs_meanrev_hs300"

# 与 #171 财务/仓位一致；仅新增反向技术参数
BASE_PARAMS = {
    "universe": "hs300",
    "exclude_st": True,
    "price_start": "2016-01-01",
    "price_end": "2026-07-30",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.005,
    "margin_min": 0.15,
    "np_improve": 0.004,
    "funda_lag": 28,
    "break_days": 60,
    "hold_days": 50,
    "stop_loss": 0.12,
    "take_profit": 0.35,
}

TECH_MEANREV = {
    "pullback_min": 0.06,
    "dd_need": 0.04,
}

DESC_MR = (
    "财务闸门同 dual_improve_hs300_mine_r1(#171)：ROE/净利率环比改善热窗28日"
    f"（margin_improve={BASE_PARAMS['margin_improve']}）。"
    "技术反向突破：相对60日高回撤≥6%，近20日回撤或曾低于MA60，上穿MA20企稳；"
    "持有50日；止损12%；止盈35%；最多8仓。静态HS300；腾讯qfq。"
    "信号：signal_dual_improve_meanrev。"
)


def _bs_disabled(*_a, **_k):
    raise RuntimeError("BaoStock disabled (qfq local-cache only)")


def _sharpe(rets: pd.Series) -> float:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or r.std(ddof=0) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=0) * math.sqrt(252))


def _max_dd(eq: pd.Series) -> float:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if e.empty:
        return float("nan")
    peak = e.cummax()
    dd = e / peak - 1.0
    return float(dd.min())


def _slice_metrics(daily: pd.DataFrame, cut: str, trades: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    cut_ts = pd.Timestamp(cut)
    late = d[d["date"] >= cut_ts].copy()
    early = d[d["date"] < cut_ts].copy()

    def _one(part: pd.DataFrame, label: str) -> Dict[str, Any]:
        if part.empty or "equity" not in part.columns:
            return {"label": label, "empty": True}
        eq0 = float(part["equity"].iloc[0])
        eq1 = float(part["equity"].iloc[-1])
        # 切片内相对起点收益（与 diag 口径一致：用全局权益比值）
        total_ret = eq1 / eq0 - 1.0 if eq0 else float("nan")
        day_ret = part["equity"].pct_change()
        out: Dict[str, Any] = {
            "label": label,
            "start": str(part["date"].iloc[0].date()),
            "end": str(part["date"].iloc[-1].date()),
            "bars": int(len(part)),
            "total_return": float(total_ret),
            "sharpe": _sharpe(day_ret.iloc[1:]),
            "max_drawdown": _max_dd(part["equity"]),
            "avg_position": float(pd.to_numeric(part["position"], errors="coerce").mean())
            if "position" in part.columns
            else None,
            "equity_start": eq0,
            "equity_end": eq1,
        }
        if "bench_ret" in part.columns:
            bh = (1.0 + pd.to_numeric(part["bench_ret"], errors="coerce").fillna(0.0)).cumprod()
            out["bench_return"] = float(bh.iloc[-1] / bh.iloc[0] - 1.0) if len(bh) else float("nan")
            out["excess_vs_bench"] = out["total_return"] - out["bench_return"]
        return out

    early_m = _one(early, "early")
    late_m = _one(late, "late")

    if trades is not None and not trades.empty:
        th = trades.copy()
        th["date"] = pd.to_datetime(th["date"])
        sells = th[th["action"].astype(str).str.contains("卖|sell", case=False, na=False)]
        if sells.empty and "side" in th.columns:
            sells = th[th["side"].astype(str).str.lower().isin(["sell", "exit"])]
        late_sells = sells[sells["date"] >= cut_ts]
        if not late_sells.empty and "nav_pnl" in late_sells.columns:
            npnl = pd.to_numeric(late_sells["nav_pnl"], errors="coerce")
            late_m["n_sells"] = int(len(late_sells))
            late_m["win_rate"] = float((npnl > 0).mean()) if npnl.notna().any() else None
            if "exit_reason" in late_sells.columns:
                late_m["reason_counts"] = late_sells["exit_reason"].value_counts().to_dict()
            elif "note" in late_sells.columns:
                reasons = late_sells["note"].astype(str).str.extract(r"(stop_loss|take_profit|hold_end)")[0]
                late_m["reason_counts"] = reasons.value_counts().to_dict()

    return {"cut": cut, "early": early_m, "late": late_m}


def _load_daily(factor_id: str) -> pd.DataFrame:
    p = ROOT / "data" / "factors" / f"{factor_id}_backtest.csv"
    return pd.read_csv(p)


def _load_trades(factor_id: str) -> pd.DataFrame:
    p = ROOT / "data" / "factors" / f"{factor_id}_trade_history.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


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


def _next_created_at(db, exclude=None):
    exclude = exclude or set()
    mx = None
    for d in db.factors.find({}, {"factor_id": 1, "created_at": 1}):
        if d.get("factor_id") in exclude:
            continue
        ca = d.get("created_at")
        if ca is None:
            continue
        if mx is None or ca > mx:
            mx = ca
    if mx is None:
        return datetime(2026, 6, 23, 11, 0, 0)
    if not isinstance(mx, datetime):
        return datetime.now()
    return mx + timedelta(hours=1)


def _ui_seq(db, factor_id: str) -> Optional[int]:
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))

    def _key(x):
        ta = x.get("created_at") or ""
        if hasattr(ta, "isoformat"):
            ta = ta.isoformat(sep=" ")
        return (str(ta), str(x.get("factor_id") or ""))

    docs = sorted(docs, key=_key)
    return next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == factor_id), None)


def _write_mongo(summary: dict, params: dict) -> Dict[str, Any]:
    targets, client = _mongo_targets()
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    summary_dst = dict(summary)
    summary_dst["position_logic"] = MEANREV_FACTOR
    ui_map = {}
    for dbn in targets:
        created_at = _next_created_at(client[dbn], exclude={MEANREV_FACTOR})
        payload = {
            "factor_id": MEANREV_FACTOR,
            "name": NAME_MR,
            "category": "fundamental",
            "description": DESC_MR,
            "tags": ["基本面", "技术面", "双改善", "均值回归", "HS300", "qfq", "反突破"],
            "status": "active",
            "builtin": True,
            "params": dict(params),
            "created_at": created_at,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": MEANREV_FACTOR,
                "logics": {MEANREV_FACTOR: summary_dst},
                "updated_at": now_s,
            },
            "last_backtest_error": summary_dst.get("error"),
        }
        r = client[dbn].factors.update_one(
            {"factor_id": MEANREV_FACTOR},
            {"$set": payload},
            upsert=True,
        )
        seq = _ui_seq(client[dbn], MEANREV_FACTOR)
        ui_map[dbn] = {"ui": seq, "created_at": str(created_at), "matched": r.matched_count}
        print(
            f"[mongo] upsert {dbn}.{MEANREV_FACTOR} UI#{seq} created_at={created_at}",
            flush=True,
        )
        # 安全：确认未动 166/168/171 对应 id
        for keep in (
            "gross_expand_m16_tp35",
            "gross_expand_m16_tp35_hs300_qfq",
            REF_FACTOR,
        ):
            ok = bool(client[dbn].factors.find_one({"factor_id": keep}, {"factor_id": 1}))
            print(f"[safe] {dbn} keep {keep} exists={ok}", flush=True)
    return ui_map


def _decide_write(brk_late: dict, mr_late: dict, brk_full: dict, mr_full: dict) -> tuple[bool, str]:
    """近窗明显改善则入库；全样本允许略差。"""
    br = brk_late.get("total_return")
    mr = mr_late.get("total_return")
    bs = brk_late.get("sharpe")
    ms = mr_late.get("sharpe")
    if br is None or mr is None or (isinstance(mr, float) and math.isnan(mr)):
        return False, "近窗数字缺失，不入库"
    delta = float(mr) - float(br)
    # 近窗收益改善 ≥5ppt，或（收益改善且 Sharpe 更好）
    better_ret = delta >= 0.05
    better_both = delta > 0 and (
        ms is not None
        and bs is not None
        and not (isinstance(ms, float) and math.isnan(ms))
        and float(ms) > float(bs)
    )
    # 全样本别崩太狠：meanrev sharpe 不低于 breakout -0.25
    full_ok = True
    if brk_full.get("sharpe") is not None and mr_full.get("sharpe") is not None:
        full_ok = float(mr_full["sharpe"]) >= float(brk_full["sharpe"]) - 0.25
    if (better_ret or better_both) and full_ok:
        return True, f"近窗改善 delta_ret={delta:+.3f} sharpe {bs}->{ms}；全样本可接受"
    if better_ret or better_both:
        return True, f"近窗有改善 delta_ret={delta:+.3f}（优先入库方便看）；全样本 sharpe {mr_full.get('sharpe')}"
    return False, f"近窗改善不足 delta_ret={delta:+.3f}，不入库"


def main() -> None:
    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    params_brk = dict(BASE_PARAMS)
    params_brk["position_logic"] = REF_FACTOR
    params_brk["note"] = "breakout baseline (#171 params)"

    params_mr = dict(BASE_PARAMS)
    params_mr.update(TECH_MEANREV)
    params_mr["position_logic"] = MEANREV_FACTOR
    params_mr["note"] = "meanrev opposite tech / same funda as #171"

    print("[panel] prepare shared HS300 + profit …", flush=True)
    panel = prepare_shared_panel(params_mr, need_profit=True, need_growth=False, limit=0)

    # breakout：若已有 #171 产物且摘要接近，可复用；否则重跑
    reuse = False
    ref_json = ROOT / "data" / "factors" / f"{REF_FACTOR}_backtest.json"
    if ref_json.exists():
        try:
            meta = json.loads(ref_json.read_text(encoding="utf-8"))
            logics = (meta.get("backtest_summary") or meta).get("logics") or meta
            s = logics.get(REF_FACTOR) if isinstance(logics, dict) else None
            if not s and isinstance(meta, dict) and "total_return" in meta:
                s = meta
            if s and abs(float(s.get("total_return") or 0) - 10.8255) < 0.05:
                reuse = True
                print(f"[breakout] reuse existing {REF_FACTOR} artifacts", flush=True)
        except Exception as e:
            print(f"[breakout] reuse check fail: {e}", flush=True)

    if not reuse:
        print("[breakout] run pipeline …", flush=True)
        sum_brk = run_factor_pipeline(
            REF_FACTOR,
            "双改善突破(对照)",
            sig.signal_dual_improve_breakout,
            params_brk,
            need_profit=True,
            need_growth=False,
            limit=0,
            start="2018-01-01",
            price_map=panel,
        )
    else:
        bj = json.loads(ref_json.read_text(encoding="utf-8"))
        if "total_return" in bj:
            sum_brk = bj
        else:
            logics = (bj.get("backtest_summary") or {}).get("logics") or {}
            sum_brk = logics.get(REF_FACTOR) or bj.get("summary") or bj

    print("[meanrev] run pipeline …", flush=True)
    sum_mr = run_factor_pipeline(
        MEANREV_FACTOR,
        TITLE_MR,
        sig.signal_dual_improve_meanrev,
        params_mr,
        need_profit=True,
        need_growth=False,
        limit=0,
        start="2018-01-01",
        price_map=panel,
    )

    daily_brk = _load_daily(REF_FACTOR)
    daily_mr = _load_daily(MEANREV_FACTOR)
    trades_brk = _load_trades(REF_FACTOR)
    trades_mr = _load_trades(MEANREV_FACTOR)

    slice_brk = _slice_metrics(daily_brk, CUT, trades_brk)
    slice_mr = _slice_metrics(daily_mr, CUT, trades_mr)

    full_brk = {
        "total_return": sum_brk.get("total_return"),
        "sharpe": sum_brk.get("sharpe"),
        "max_drawdown": sum_brk.get("max_drawdown"),
        "n_legs_accepted": sum_brk.get("n_legs_accepted"),
        "avg_position": sum_brk.get("avg_position"),
        "start": sum_brk.get("start"),
        "end": sum_brk.get("end"),
    }
    full_mr = {
        "total_return": sum_mr.get("total_return"),
        "sharpe": sum_mr.get("sharpe"),
        "max_drawdown": sum_mr.get("max_drawdown"),
        "n_legs_accepted": sum_mr.get("n_legs_accepted"),
        "avg_position": sum_mr.get("avg_position"),
        "start": sum_mr.get("start"),
        "end": sum_mr.get("end"),
    }

    do_write, reason = _decide_write(slice_brk["late"], slice_mr["late"], full_brk, full_mr)
    ui_map: Dict[str, Any] = {}
    if do_write and not sum_mr.get("error"):
        ui_map = _write_mongo(sum_mr if isinstance(sum_mr, dict) else {}, params_mr)
    else:
        print(f"[mongo] skip write: {reason}", flush=True)

    report = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cut": CUT,
        "reverse_rule": {
            "signal": "signal_dual_improve_meanrev",
            "funda_same_as": "signal_dual_improve_breakout / #171",
            "funda": "ROE+净利率环比改善热窗 funda_lag=28；margin_improve=0.005",
            "tech_breakout": "收盘≥N日高 且 收盘>MA20",
            "tech_meanrev": (
                "非N日新高且相对N日高回撤≥pullback_min(6%)；"
                "dd_20≤-4% 或近3日曾低于MA60；上穿MA20企稳"
            ),
            "hold_sl_tp": "hold=50, sl=12%, tp=35%, max_pos=8",
        },
        "full_sample": {"breakout": full_brk, "meanrev": full_mr},
        "last2y_slice": {"breakout": slice_brk, "meanrev": slice_mr},
        "decision": {"write_mongo": do_write, "reason": reason, "ui_map": ui_map},
        "artifacts": {
            "meanrev_backtest": f"data/factors/{MEANREV_FACTOR}_backtest.csv",
            "meanrev_json": f"data/factors/{MEANREV_FACTOR}_backtest.json",
            "meanrev_trades": f"data/factors/{MEANREV_FACTOR}_trade_history.csv",
            "compare_json": str(OUT_STEM.with_suffix(".json").relative_to(ROOT)).replace("\\", "/"),
            "compare_md": str(OUT_STEM.with_suffix(".md").relative_to(ROOT)).replace("\\", "/"),
        },
    }

    OUT_STEM.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    def _fmt_ret(x):
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return "n/a"
        return f"{float(x)*100:+.1f}%" if abs(float(x)) < 50 else f"{float(x):+.2f}×"

    def _fmt_sh(x):
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return "n/a"
        return f"{float(x):.2f}"

    bl, ml = slice_brk["late"], slice_mr["late"]
    md = f"""# dual_improve：breakout vs meanrev（HS300）

- 对照日：{report['asof']}
- 宇宙：静态 HS300 / 腾讯 qfq / BaoStock 禁用
- 财务同 #171；技术：突破 → **弱势回撤企稳（meanrev）**
- 近2年切片：`{CUT}` ～ 样本末

## 反向规则

| | breakout (#171) | meanrev（本变体） |
|---|---|---|
| 财务 | ROE+净利率改善热窗28日 | **相同** |
| 技术 | 收盘≥60日高 且 >MA20 | **非新高**且相对60日高回撤≥6%；dd20≤-4%或曾低于MA60；**上穿MA20** |
| 仓位出场 | hold50 / sl12% / tp35% / 8仓 | **相同** |

## 全样本

| | 总收益 | Sharpe | 最大回撤 | 入账腿 | avg_pos |
|---|---|---|---|---|---|
| breakout | {_fmt_ret(full_brk.get('total_return'))} | {_fmt_sh(full_brk.get('sharpe'))} | {_fmt_sh(full_brk.get('max_drawdown'))} | {full_brk.get('n_legs_accepted')} | {_fmt_sh(full_brk.get('avg_position'))} |
| meanrev | {_fmt_ret(full_mr.get('total_return'))} | {_fmt_sh(full_mr.get('sharpe'))} | {_fmt_sh(full_mr.get('max_drawdown'))} | {full_mr.get('n_legs_accepted')} | {_fmt_sh(full_mr.get('avg_position'))} |

## 近2年（equity 切片）

| | 总收益 | Sharpe | 最大回撤 | vs基准超额 | 卖出笔 |
|---|---|---|---|---|---|
| breakout | {_fmt_ret(bl.get('total_return'))} | {_fmt_sh(bl.get('sharpe'))} | {_fmt_sh(bl.get('max_drawdown'))} | {_fmt_ret(bl.get('excess_vs_bench'))} | {bl.get('n_sells')} |
| meanrev | {_fmt_ret(ml.get('total_return'))} | {_fmt_sh(ml.get('sharpe'))} | {_fmt_sh(ml.get('max_drawdown'))} | {_fmt_ret(ml.get('excess_vs_bench'))} | {ml.get('n_sells')} |

## 入库决策

- **写入 Mongo**：{'是' if do_write else '否'}
- 原因：{reason}
- UI：{json.dumps(ui_map, ensure_ascii=False) if ui_map else '—'}

## 产物

- `{MEANREV_FACTOR}_*`
- `dual_improve_breakout_vs_meanrev_hs300.json` / `.md`
"""
    OUT_STEM.with_suffix(".md").write_text(md, encoding="utf-8")
    print(json.dumps(report["decision"], ensure_ascii=False, indent=2), flush=True)
    print(f"[ok] {OUT_STEM.with_suffix('.md')}", flush=True)
    if sum_mr.get("error"):
        raise SystemExit(f"meanrev error: {sum_mr.get('error')}")


if __name__ == "__main__":
    main()
