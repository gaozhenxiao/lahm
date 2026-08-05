"""对照实验：快报/预告 ROS（或净利代理）+ 技术确认 vs 正式报利润率扩张路径。

- 宇宙：静态 HS300（与 #171/#168 可比）；可选一句 CSI500
- 行情：腾讯 qfq；BaoStock 禁用
- PIT：快报 ACTUAL_ANN_DT/ANN_DT；预告 FIRSTANNDATE；正式报利润字段公告日
- 评估：全样本 + 近2年（2024-08+）；近年权重更高
- 不写 Mongo；产物 data/factors/expt_fcst_ros_vs_formal.{json,md}
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

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

CUT = "2024-08-01"
OUT_STEM = ROOT / "data" / "factors" / "expt_fcst_ros_vs_formal"
START = "2018-01-01"

# 同出场（对齐 #171）
EXIT_COMMON = {
    "universe": "hs300",
    "exclude_st": True,
    "price_start": "2016-01-01",
    "price_end": "2026-07-30",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "hold_days": 50,
    "stop_loss": 0.12,
    "take_profit": 0.35,
    "break_days": 60,
    "funda_lag": 28,
    "require_ma20": True,
}


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


def _coverage_report(codes: List[str]) -> Dict[str, Any]:
    """预告/快报字段与覆盖率（HS300）。"""
    n = len(codes)
    n_expr = 0
    n_expr_ros = 0
    n_expr_dros = 0
    n_fcst = 0
    n_fcst_chg = 0
    expr_rows = 0
    dros_rows = 0
    fcst_rows = 0
    for c in codes:
        ex = fin_db.fetch_express(c)
        if ex is not None and not ex.empty:
            n_expr += 1
            expr_rows += len(ex)
            if "expr_ros" in ex.columns and pd.to_numeric(ex["expr_ros"], errors="coerce").notna().any():
                n_expr_ros += 1
            if "expr_dros" in ex.columns:
                dros = pd.to_numeric(ex["expr_dros"], errors="coerce")
                if dros.notna().any():
                    n_expr_dros += 1
                    dros_rows += int(dros.notna().sum())
        fc = fin_db.fetch_forecast(c)
        if fc is not None and not fc.empty:
            n_fcst += 1
            fcst_rows += len(fc)
            if "fcst_change_min" in fc.columns and pd.to_numeric(fc["fcst_change_min"], errors="coerce").notna().any():
                n_fcst_chg += 1
    return {
        "universe": "hs300",
        "n_codes": n,
        "express": {
            "codes_with_rows": n_expr,
            "coverage": round(n_expr / n, 3) if n else None,
            "codes_with_ros": n_expr_ros,
            "codes_with_dros": n_expr_dros,
            "rows": expr_rows,
            "dros_nonnull_rows": dros_rows,
            "fields": [
                "pubDate(ACTUAL_ANN_DT/ANN_DT)",
                "statDate(REPORT_PERIOD)",
                "expr_oper_rev",
                "expr_net_profit",
                "expr_ly_oper_rev",
                "expr_ly_net_profit",
                "expr_ros",
                "expr_dros",
                "expr_yoy_sales / expr_yoy_np_deducted",
            ],
            "note": "ROS=净利/营收；ΔROS 优先 LAST_YEAR 同行字段",
        },
        "forecast": {
            "codes_with_rows": n_fcst,
            "coverage": round(n_fcst / n, 3) if n else None,
            "codes_with_chg": n_fcst_chg,
            "rows": fcst_rows,
            "fields": [
                "pubDate(FIRSTANNDATE→DATE)",
                "statDate(PERIOD)",
                "fcst_style",
                "fcst_change_min/max",
                "fcst_np_min/max",
                "fcst_abstract",
            ],
            "note": "无营收 → 无法算真 ROS，仅净利增速代理",
        },
        "pit": {
            "express": "ACTUAL_ANN_DT fallback ANN_DT → merge_asof backward",
            "forecast": "S_PROFITNOTICE_FIRSTANNDATE fallback DATE → merge_asof",
            "formal_profit": "利润/增长字段公告日 asof（gross_expand / dual_improve）",
        },
    }


def _run_arm(
    factor_id: str,
    title: str,
    signal_fn: Callable,
    params: Dict[str, Any],
    *,
    need_profit: bool,
    need_fin_db: bool,
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
        need_profit=need_profit,
        need_growth=False,
        need_fin_db=need_fin_db,
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
        "params": p,
    }


def _fmt_pct(x: Any) -> str:
    try:
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


def _row_from_result(r: Dict[str, Any], arm: str) -> Dict[str, Any]:
    s = r.get("summary") or {}
    late = r.get("late") or {}
    return {
        "arm": arm,
        "factor_id": r.get("factor_id"),
        "title": r.get("title"),
        "sharpe": s.get("sharpe"),
        "total_return": s.get("total_return"),
        "max_drawdown": s.get("max_drawdown"),
        "n_legs_raw": s.get("n_legs_raw"),
        "n_legs_accepted": s.get("n_legs_accepted"),
        "late_sharpe": None if late.get("empty") else late.get("sharpe"),
        "late_return": None if late.get("empty") else late.get("total_return"),
        "error": s.get("error"),
    }


def main() -> None:
    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    assert fin_db.db_available(), "本地 ashare_fin_db 不可用"
    cache = kit.shared_cache_dir()
    codes = kit.fetch_universe_codes("hs300", kit.RateLimiter(0.01), cache, force=False)
    print(f"[universe] hs300={len(codes)} db={fin_db.resolve_db_path()}", flush=True)

    print("[coverage] scanning express/forecast …", flush=True)
    coverage = _coverage_report(codes)
    print(json.dumps(coverage, ensure_ascii=False, indent=2), flush=True)

    # 共享面板：正式报 profit + 本地 fin_db（含快报/预告）
    print("[panel] prepare HS300 profit+fin_db …", flush=True)
    panel = prepare_shared_panel(
        EXIT_COMMON,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        limit=0,
    )
    # 抽检列
    sample = next(iter(panel.values()), pd.DataFrame())
    sample_cols = list(sample.columns) if sample is not None else []
    has_expr = "expr_dros" in sample_cols or "expr_ros" in sample_cols
    has_fcst = "fcst_change_min" in sample_cols
    has_gp = "gpMargin" in sample_cols
    print(
        f"[panel] n={len(panel)} expr_ros={has_expr} fcst={has_fcst} gpMargin={has_gp}",
        flush=True,
    )

    arms: List[Dict[str, Any]] = []

    # --- A: 快报 ROS 改善 + 突破 ---
    params_a = {
        **EXIT_COMMON,
        "ros_improve": 0.005,
        "ros_min": 0.0,
    }
    if has_expr:
        arms.append(
            (
                "A",
                _run_arm(
                    "expt_arm_a_expr_ros",
                    "A·快报ROS改善+突破",
                    sig.signal_expr_ros_improve_break,
                    params_a,
                    need_profit=False,
                    need_fin_db=True,
                    panel=panel,
                ),
            )
        )
    else:
        arms.append(
            (
                "A",
                {
                    "factor_id": "expt_arm_a_expr_ros",
                    "title": "A·快报ROS改善+突破",
                    "summary": {"error": "面板缺 expr_ros/expr_dros，臂跳过"},
                    "late": {"empty": True},
                    "params": params_a,
                },
            )
        )

    # --- B: 预告净利代理（弱 ROS）+ 突破 ---
    params_b = {
        **EXIT_COMMON,
        "fcst_chg_min": 20.0,
    }
    if has_fcst:
        arms.append(
            (
                "B",
                _run_arm(
                    "expt_arm_b_fcst_np",
                    "B·预告净利代理+突破(弱ROS)",
                    sig.signal_fcst_np_proxy_break,
                    params_b,
                    need_profit=False,
                    need_fin_db=True,
                    panel=panel,
                ),
            )
        )
    else:
        arms.append(
            (
                "B",
                {
                    "factor_id": "expt_arm_b_fcst_np",
                    "title": "B·预告净利代理+突破(弱ROS)",
                    "summary": {"error": "面板缺 fcst_change_min，臂跳过"},
                    "late": {"empty": True},
                    "params": params_b,
                },
            )
        )

    # --- 对照：gross_expand（#168 财务闸门 + 同出场）---
    params_ge = {
        **EXIT_COMMON,
        "margin_improve": 0.006,
        "margin_min": 0.16,
        "np_min": 0.10,
        "funda_lag": 29,  # 保留 #168 热窗；出场已对齐
        "hold_days": 50,
    }
    if has_gp:
        arms.append(
            (
                "CTRL_GE",
                _run_arm(
                    "expt_ctrl_gross_expand",
                    "对照·毛利率扩张突破(#168闸门)",
                    sig.signal_gross_expand_break,
                    params_ge,
                    need_profit=True,
                    need_fin_db=False,
                    panel=panel,
                ),
            )
        )
    else:
        arms.append(
            (
                "CTRL_GE",
                {
                    "factor_id": "expt_ctrl_gross_expand",
                    "title": "对照·毛利率扩张突破",
                    "summary": {"error": "缺 gpMargin"},
                    "late": {"empty": True},
                    "params": params_ge,
                },
            )
        )

    # --- 对照：dual_improve（#171）---
    params_di = {
        **EXIT_COMMON,
        "margin_improve": 0.005,
        "margin_min": 0.15,
        "np_improve": 0.004,
        "funda_lag": 28,
    }
    arms.append(
        (
            "CTRL_DI",
            _run_arm(
                "expt_ctrl_dual_improve",
                "对照·双改善突破(#171)",
                sig.signal_dual_improve_breakout,
                params_di,
                need_profit=True,
                need_fin_db=False,
                panel=panel,
            ),
        )
    )

    # --- 对照：fcst_profit_gap（同出场；信号仍为爆发断层+MA20，非突破）---
    params_fg = {
        **EXIT_COMMON,
        "explosive_chg": 100.0,
        "funda_lag": 0,  # 原信号默认公告日事件
        "require_ma20": True,
    }
    if has_fcst:
        arms.append(
            (
                "CTRL_FCST",
                _run_arm(
                    "expt_ctrl_fcst_gap",
                    "对照·预告爆发利润断层(同出场)",
                    sig.signal_fcst_profit_gap,
                    params_fg,
                    need_profit=False,
                    need_fin_db=True,
                    panel=panel,
                ),
            )
        )
    else:
        arms.append(
            (
                "CTRL_FCST",
                {
                    "factor_id": "expt_ctrl_fcst_gap",
                    "title": "对照·预告爆发利润断层",
                    "summary": {"error": "缺 fcst；可参考已有 fcst_profit_gap 产物"},
                    "late": {"empty": True},
                    "params": params_fg,
                },
            )
        )

    # 可选 CSI500 一句：只跑 A 臂粗看腿数/夏普（有余力）
    csi500_note: Optional[Dict[str, Any]] = None
    try:
        params_500 = {**params_a, "universe": "csi500", "bench_code": "sh.000905"}
        print("\n[csi500] quick arm A …", flush=True)
        panel_500 = prepare_shared_panel(
            params_500, need_profit=False, need_growth=False, need_fin_db=True, limit=0
        )
        sum_500 = run_factor_pipeline(
            "expt_arm_a_expr_ros_csi500",
            "A·快报ROS·CSI500粗扫",
            sig.signal_expr_ros_improve_break,
            params_500,
            need_profit=False,
            need_fin_db=True,
            start=START,
            price_map=panel_500,
        )
        daily_500 = _load_daily("expt_arm_a_expr_ros_csi500")
        late_500 = _slice_metrics(daily_500, CUT) if not daily_500.empty else {"empty": True}
        csi500_note = {
            "factor_id": "expt_arm_a_expr_ros_csi500",
            "summary": sum_500 if isinstance(sum_500, dict) else {"error": str(sum_500)},
            "late": late_500,
        }
    except Exception as exc:  # noqa: BLE001
        csi500_note = {"error": str(exc)}

    table = [_row_from_result(r, arm) for arm, r in arms]

    # 结论启发式（近年权重更高）
    def _score(row: Dict[str, Any]) -> float:
        ls = row.get("late_sharpe")
        fs = row.get("sharpe")
        if ls is None or (isinstance(ls, float) and math.isnan(ls)):
            ls = -9.0
        if fs is None or (isinstance(fs, float) and math.isnan(fs)):
            fs = -9.0
        return 0.65 * float(ls) + 0.35 * float(fs)

    ranked = sorted(
        [t for t in table if not t.get("error")],
        key=_score,
        reverse=True,
    )
    best = ranked[0] if ranked else None
    a_row = next((t for t in table if t["arm"] == "A"), None)
    b_row = next((t for t in table if t["arm"] == "B"), None)
    ge_row = next((t for t in table if t["arm"] == "CTRL_GE"), None)
    di_row = next((t for t in table if t["arm"] == "CTRL_DI"), None)

    verdicts: List[str] = []
    # 1) A vs formal
    if a_row and not a_row.get("error") and ge_row and not ge_row.get("error"):
        a_ok = (a_row.get("late_sharpe") or -9) >= (ge_row.get("late_sharpe") or -9) * 0.85
        if (a_row.get("late_sharpe") or -9) > (ge_row.get("late_sharpe") or -9) and (
            a_row.get("n_legs_accepted") or 0
        ) >= 30:
            verdicts.append(
                f"快报ROS臂近2年 Sharpe={_fmt_num(a_row.get('late_sharpe'))}，"
                f"优于/接近毛利扩张对照({_fmt_num(ge_row.get('late_sharpe'))})，有继续挖的空间。"
            )
        elif a_ok and (a_row.get("n_legs_accepted") or 0) >= 20:
            verdicts.append(
                f"快报ROS臂近2年尚可(Sharpe={_fmt_num(a_row.get('late_sharpe'))})，"
                f"但未明显压过正式报毛利扩张；可作补充事件源而非替代。"
            )
        else:
            verdicts.append(
                f"快报ROS臂近2年表现弱于毛利扩张对照"
                f"（{_fmt_num(a_row.get('late_sharpe'))} vs {_fmt_num(ge_row.get('late_sharpe'))}），"
                f"暂不值得升格正式因子。"
            )
    elif a_row and a_row.get("error"):
        verdicts.append(f"快报ROS臂未跑通：{a_row.get('error')}。")
    else:
        verdicts.append("快报ROS与毛利对照缺一边结果，结论受限。")

    # 2) B weak proxy
    if b_row and not b_row.get("error"):
        if (b_row.get("late_sharpe") or -9) < 0.3 or (b_row.get("n_legs_accepted") or 0) < 15:
            verdicts.append(
                f"预告净利代理(弱ROS)近2年弱/腿少"
                f"（Sharpe={_fmt_num(b_row.get('late_sharpe'))}, "
                f"腿={b_row.get('n_legs_accepted')}），"
                f"不宜当作边际改善因子。"
            )
        else:
            verdicts.append(
                f"预告净利代理近2年 Sharpe={_fmt_num(b_row.get('late_sharpe'))}；"
                f"无营收只能作弱代理，解释力弱于快报ROS。"
            )
    else:
        verdicts.append("预告净利代理臂缺失，仅能依赖已有 fcst_profit_gap 路径作参照。")

    # 3) promote?
    promote = False
    if a_row and not a_row.get("error"):
        late_s = a_row.get("late_sharpe")
        full_s = a_row.get("sharpe")
        legs = a_row.get("n_legs_accepted") or 0
        beat_di = di_row and not di_row.get("error") and (late_s or -9) > (di_row.get("late_sharpe") or -9)
        if late_s is not None and full_s is not None and legs >= 40 and late_s >= 0.8 and (
            beat_di or late_s >= 1.0
        ):
            promote = True
            verdicts.append("建议继续挖成正式因子：近窗夏普够用、腿数充足，且不弱于双改善对照。")
        else:
            verdicts.append(
                "暂不建议升格正式因子：优先把快报ROS当研究臂/"
                "与正式报扩张组合的事件增强，而非独立冠军替换。"
            )
    while len(verdicts) > 3:
        verdicts.pop()

    payload = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": "expt_fcst_ros_vs_formal",
        "mongo_written": False,
        "universe": "hs300_static",
        "price": "tencent_qfq",
        "baostock": "disabled",
        "cut": CUT,
        "exit_common": EXIT_COMMON,
        "pit": coverage.get("pit"),
        "coverage": coverage,
        "panel_flags": {"expr_ros": has_expr, "fcst": has_fcst, "gpMargin": has_gp},
        "table": table,
        "arms_detail": {arm: r for arm, r in arms},
        "csi500_note": csi500_note,
        "verdicts": verdicts,
        "promote_to_formal": promote,
        "best_by_weighted_sharpe": best,
    }

    OUT_STEM.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(str(OUT_STEM) + ".json")
    md_path = Path(str(OUT_STEM) + ".md")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # markdown table
    lines = [
        "# 对照：快报/预告 ROS（代理）vs 正式报利润率扩张",
        "",
        f"- 宇宙：静态 HS300；行情：腾讯 qfq；BaoStock 禁用；切窗 `{CUT}`+",
        f"- 同出场：hold={EXIT_COMMON['hold_days']} stop={EXIT_COMMON['stop_loss']} "
        f"tp={EXIT_COMMON['take_profit']} max_pos={EXIT_COMMON['max_positions']}",
        f"- PIT：快报公告日 / 预告首次公告日 / 正式报字段公告日（merge_asof backward）",
        f"- Mongo：**未写入**",
        "",
        "## 覆盖率（HS300）",
        "",
        f"- 快报：{coverage['express']['codes_with_rows']}/{coverage['n_codes']} "
        f"（ROS股 {coverage['express']['codes_with_ros']}，ΔROS股 {coverage['express']['codes_with_dros']}）",
        f"- 预告：{coverage['forecast']['codes_with_rows']}/{coverage['n_codes']} "
        f"（有增速 {coverage['forecast']['codes_with_chg']}）；**无营收，无法算真 ROS**",
        "",
        "## 结果表",
        "",
        "| 臂 | 因子 | Sharpe | 总收益 | 近2年Sharpe | 近2年收益 | 腿(入账) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for t in table:
        lines.append(
            f"| {t['arm']} | {t['title']} | {_fmt_num(t.get('sharpe'))} | "
            f"{_fmt_num(t.get('total_return'))} | {_fmt_num(t.get('late_sharpe'))} | "
            f"{_fmt_num(t.get('late_return'))} | "
            f"{t.get('n_legs_accepted') if t.get('n_legs_accepted') is not None else '—'} |"
        )
    lines.extend(["", "## 结论", ""])
    for i, v in enumerate(verdicts, 1):
        lines.append(f"{i}. {v}")
    lines.extend(
        [
            "",
            f"- **是否值得继续挖成正式因子**：{'是（有条件）' if promote else '否（当前门槛）'}",
            "",
            "## CSI500 粗扫（有余力）",
            "",
        ]
    )
    if csi500_note and "summary" in csi500_note:
        s5 = csi500_note["summary"]
        l5 = csi500_note.get("late") or {}
        lines.append(
            f"- Arm A on CSI500：Sharpe={_fmt_num(s5.get('sharpe'))} "
            f"ret={_fmt_num(s5.get('total_return'))} "
            f"legs={s5.get('n_legs_accepted')}；"
            f"近2年 Sharpe={_fmt_num(l5.get('sharpe'))} ret={_fmt_num(l5.get('total_return'))}"
        )
    else:
        lines.append(f"- 未完成或失败：{csi500_note}")
    lines.extend(["", f"产物：`{json_path.name}` / `{md_path.name}`", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "\n".join(lines), flush=True)
    print(f"\n[ok] -> {json_path} ; {md_path}", flush=True)


if __name__ == "__main__":
    main()
