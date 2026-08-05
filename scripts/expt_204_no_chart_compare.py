"""对照：#204 完整规则 vs 去掉技术入场（纯财务日开仓）。

- 基线：clyoyaccel_clacc14_y18_brk75_csi500_sm1（合同负债 YoY 加速 + 75 日突破）
- 对照：同一财务参数，entry=财务闸门日（无 break / 无 MA20）
- 宇宙 CSI500；出场 hold/sl/tp 与 #204 相同
- 腾讯 qfq；BaoStock 禁用；不写 Mongo / 无新 UI 号
- 产物：data/factors/expt_204_no_chart_compare.{json,md}
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

CUT = "2024-08-01"
START = "2018-01-01"
BASE_ID = "clyoyaccel_clacc14_y18_brk75_csi500_sm1"
OUT_STEM = ROOT / "data" / "factors" / "expt_204_no_chart_compare"
WK_CODE = "sh.600390"
WK_NAME = "五矿资本"
WK_WIN = ("2024-09-01", "2024-10-15")


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
    return float((e / peak - 1.0).min())


def _slice_metrics(daily: pd.DataFrame, cut: str) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    cut_ts = pd.Timestamp(cut)
    late = d[d["date"] >= cut_ts].copy()
    if late.empty or "equity" not in late.columns:
        return {"label": "late", "empty": True}
    eq0 = float(late["equity"].iloc[0])
    eq1 = float(late["equity"].iloc[-1])
    total_ret = eq1 / eq0 - 1.0 if eq0 else float("nan")
    day_ret = late["equity"].pct_change()
    return {
        "label": "late",
        "start": str(late["date"].iloc[0].date()),
        "end": str(late["date"].iloc[-1].date()),
        "bars": int(len(late)),
        "total_return": float(total_ret),
        "sharpe": _sharpe(day_ret.iloc[1:]),
        "max_drawdown": _max_dd(late["equity"]),
    }


def _load_daily(factor_id: str) -> pd.DataFrame:
    p = ROOT / "data" / "factors" / f"{factor_id}_backtest.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _load_trades(factor_id: str) -> pd.DataFrame:
    p = ROOT / "data" / "factors" / f"{factor_id}_trade_history.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def signal_cl_yoy_accel_funda_day(px: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """与 signal_cl_yoy_accel_break 同财务闸门，但仅在财务事件日开仓（无突破/无均线）。"""
    if "contract_liab_yoy" not in px.columns:
        return pd.DataFrame(columns=["date", "close", "note"])
    yoy = pd.to_numeric(px["contract_liab_yoy"], errors="coerce").astype(float)
    yoy = yoy.where(yoy.abs() <= 5.0, yoy / 100.0)
    evt, delta = sig._yoy_event_delta(px["contract_liab_yoy"], yoy)
    accel = float(params.get("cl_accel") or params.get("growth_accel") or params.get("accel_min") or 0.08)
    ymin = float(params.get("yoy_min") or 0.10)
    cl_pos = pd.Series(True, index=px.index)
    if "contract_liab" in px.columns:
        cl_pos = pd.to_numeric(px["contract_liab"], errors="coerce") > 0
    gate = evt & delta.notna() & (delta >= accel) & yoy.notna() & (yoy >= ymin) & cl_pos.fillna(False)
    # 与基线同过滤器；不扩热窗等突破——纯财务日 = gate 且过滤通过
    hot = sig._yoy_gate_hot(px, gate.fillna(False), params)
    m = gate.fillna(False) & hot.fillna(False)
    out = px.loc[m.astype(bool), ["date", "close"]].copy()
    out["note"] = "合同负债YoY再加速·纯财务日"
    return out


def _wk_entries(factor_id: str) -> List[Dict[str, Any]]:
    tr = _load_trades(factor_id)
    if tr.empty:
        return []
    cols = {c.lower(): c for c in tr.columns}
    code_col = cols.get("code") or cols.get("symbol")
    act_col = cols.get("action") or cols.get("side") or cols.get("操作")
    date_col = cols.get("date") or cols.get("日期")
    if not code_col or not date_col:
        # trade_history 常见：date, action, code, ...
        if len(tr.columns) >= 3:
            date_col = tr.columns[0]
            act_col = tr.columns[1]
            code_col = tr.columns[2]
        else:
            return []
    d = tr.copy()
    d["_dt"] = pd.to_datetime(d[date_col], errors="coerce")
    d["_code"] = d[code_col].astype(str)
    lo, hi = pd.Timestamp(WK_WIN[0]), pd.Timestamp(WK_WIN[1])
    mask = (d["_code"] == WK_CODE) & (d["_dt"] >= lo) & (d["_dt"] <= hi)
    if act_col:
        mask = mask & d[act_col].astype(str).str.contains("开|buy|Buy", regex=True, na=False)
    rows = d.loc[mask].sort_values("_dt")
    out: List[Dict[str, Any]] = []
    for _, r in rows.iterrows():
        item = {"date": str(r["_dt"].date()), "code": WK_CODE, "name": WK_NAME}
        for k in ("price", "close", "entry_price", "开仓价", "price_fill"):
            if k in r.index and pd.notna(r[k]):
                try:
                    item["price"] = float(r[k])
                    break
                except Exception:
                    pass
        # positional fallback: trade_history often has price around col 6
        if "price" not in item:
            for c in r.index:
                if "价" in str(c) or str(c).lower() in ("price", "px"):
                    try:
                        item["price"] = float(r[c])
                        break
                    except Exception:
                        continue
        out.append(item)
    return out


def _fmt_pct(x: Any) -> str:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return "—"
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "—"


def _fmt_num(x: Any, nd: int = 3) -> str:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return "—"
        return f"{float(x):.{nd}f}"
    except Exception:
        return "—"


def _run_arm(
    factor_id: str,
    title: str,
    signal_fn: Callable,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
) -> Dict[str, Any]:
    p = dict(params)
    p["position_logic"] = factor_id
    p["note"] = title
    print(f"\n=== RUN {factor_id} ===", flush=True)
    summary = run_factor_pipeline(
        factor_id,
        title,
        signal_fn,
        p,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        limit=0,
        start=START,
        price_map=panel,
    )
    daily = _load_daily(factor_id)
    late = _slice_metrics(daily, CUT) if not daily.empty else {"empty": True}
    return {
        "factor_id": factor_id,
        "title": title,
        "summary": summary if isinstance(summary, dict) else {"error": str(summary)},
        "late": late,
        "params": {k: v for k, v in p.items() if not str(k).startswith("_")},
        "wk_entries": _wk_entries(factor_id),
    }


def _md_table(baseline: Dict[str, Any], nochart: Dict[str, Any]) -> str:
    def row(label: str, b: Any, n: Any) -> str:
        return f"| {label} | {b} | {n} |"

    bs, ns = baseline.get("summary") or {}, nochart.get("summary") or {}
    bl, nl = baseline.get("late") or {}, nochart.get("late") or {}
    lines = [
        "| 指标 | #204 基线（含突破） | 对照（纯财务日） |",
        "|---|---:|---:|",
        row("全样本 Sharpe", _fmt_num(bs.get("sharpe")), _fmt_num(ns.get("sharpe"))),
        row("全样本 总收益", _fmt_num(bs.get("total_return"), 2), _fmt_num(ns.get("total_return"), 2)),
        row("全样本 MDD", _fmt_pct(bs.get("max_drawdown")), _fmt_pct(ns.get("max_drawdown"))),
        row("腿数 raw / accepted", f"{bs.get('n_legs_raw')} / {bs.get('n_legs_accepted')}", f"{ns.get('n_legs_raw')} / {ns.get('n_legs_accepted')}"),
        row("近2年 Sharpe (2024-08+)", _fmt_num(None if bl.get("empty") else bl.get("sharpe")), _fmt_num(None if nl.get("empty") else nl.get("sharpe"))),
        row("近2年 收益", _fmt_pct(None if bl.get("empty") else bl.get("total_return")), _fmt_pct(None if nl.get("empty") else nl.get("total_return"))),
        row("近2年 MDD", _fmt_pct(None if bl.get("empty") else bl.get("max_drawdown")), _fmt_pct(None if nl.get("empty") else nl.get("max_drawdown"))),
    ]
    return "\n".join(lines)


def _verdict(baseline: Dict[str, Any], nochart: Dict[str, Any]) -> str:
    bs, ns = baseline.get("summary") or {}, nochart.get("summary") or {}
    bl, nl = baseline.get("late") or {}, nochart.get("late") or {}
    sh_b = bs.get("sharpe")
    sh_n = ns.get("sharpe")
    late_b = None if bl.get("empty") else bl.get("sharpe")
    late_n = None if nl.get("empty") else nl.get("sharpe")
    if sh_b is None or sh_n is None:
        return "结果不完整，无法判定。"
    # 主判据：全样本 Sharpe；近2年作辅助
    if float(sh_b) > float(sh_n) + 0.05:
        msg = f"#204 基线（含突破）更好：全样本 Sharpe {sh_b:.3f} > 纯财务 {sh_n:.3f}"
    elif float(sh_n) > float(sh_b) + 0.05:
        msg = f"纯财务日对照更好：全样本 Sharpe {sh_n:.3f} > 基线 {sh_b:.3f}"
    else:
        msg = f"两者接近：全样本 Sharpe 基线 {sh_b:.3f} vs 纯财务 {sh_n:.3f}"
    if late_b is not None and late_n is not None:
        msg += f"；近2年 Sharpe 基线 {late_b:.3f} / 纯财务 {late_n:.3f}"
    return msg + "。"


def main() -> None:
    kit.bs_login = _bs_disabled  # type: ignore[assignment]
    meta = FACTOR_IMPL[BASE_ID]
    base_params = dict(meta["params"])
    # 对照：去掉技术入场标记（脚本信号忽略 entry/break）
    nochart_params = {
        **base_params,
        "entry": "funda_day",
        "require_ma20": False,
    }

    print(f"[expt] base={BASE_ID} end={base_params.get('price_end')}", flush=True)
    print("[panel] prepare CSI500 profit+fin_db …", flush=True)
    panel = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        limit=0,
    )
    sample = next(iter(panel.values()), pd.DataFrame())
    has_cl = sample is not None and "contract_liab_yoy" in getattr(sample, "columns", [])
    print(f"[panel] n={len(panel)} contract_liab_yoy={has_cl}", flush=True)
    if not has_cl:
        raise RuntimeError("面板缺 contract_liab_yoy，无法对比")

    baseline = _run_arm(
        "expt_204_baseline_chart",
        "#204基线·合同负债YoY加速+75日突破",
        sig.signal_cl_yoy_accel_break,
        base_params,
        panel,
    )
    nochart = _run_arm(
        "expt_204_no_chart_funda",
        "#204对照·合同负债YoY加速·纯财务日",
        signal_cl_yoy_accel_funda_day,
        nochart_params,
        panel,
    )

    verdict = _verdict(baseline, nochart)
    table = _md_table(baseline, nochart)
    payload = {
        "experiment": "expt_204_no_chart_compare",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "note": (
            "基线=#204 完整规则；对照=同财务参数、纯财务事件日开仓（无 break/MA20）；"
            "不写 Mongo / 无新 UI 号；腾讯 qfq；BaoStock 禁用。"
        ),
        "verdict": verdict,
        "baseline": baseline,
        "no_chart": nochart,
        "wk_focus": {
            "code": WK_CODE,
            "name": WK_NAME,
            "window": list(WK_WIN),
            "baseline_entries": baseline.get("wk_entries"),
            "no_chart_entries": nochart.get("wk_entries"),
        },
    }

    OUT_STEM.parent.mkdir(parents=True, exist_ok=True)
    json_path = OUT_STEM.with_suffix(".json")
    md_path = OUT_STEM.with_suffix(".md")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    wk_b = baseline.get("wk_entries") or []
    wk_n = nochart.get("wk_entries") or []
    md = "\n".join(
        [
            "# expt_204_no_chart_compare",
            "",
            f"**结论**：{verdict}",
            "",
            "## 设定",
            "",
            "- 基线：`clyoyaccel_clacc14_y18_brk75_csi500_sm1`（cl_accel=0.14, yoy_min=0.18, funda_lag=25, break_days=75, hold=48, sl=0.12, tp=0.34）",
            "- 对照：同一财务闸门，**纯财务事件日开仓**（关闭突破/MA20；funda_lag 仅参数对齐）",
            "- 宇宙 CSI500；腾讯 qfq；BaoStock 禁用；不入库",
            "",
            "## 对照表",
            "",
            table,
            "",
            "## 2024-09 五矿资本（sh.600390）开仓",
            "",
            f"- 基线：{wk_b if wk_b else '窗口内无开仓'}",
            f"- 对照：{wk_n if wk_n else '窗口内无开仓'}",
            "",
            f"生成时间：{payload['created_at']}",
            "",
        ]
    )
    md_path.write_text(md, encoding="utf-8")
    print("\n" + table, flush=True)
    print(f"\n[verdict] {verdict}", flush=True)
    print(f"[ok] {json_path}", flush=True)
    print(f"[ok] {md_path}", flush=True)


if __name__ == "__main__":
    main()
