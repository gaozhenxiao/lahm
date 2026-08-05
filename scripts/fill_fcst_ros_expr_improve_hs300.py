"""把对照实验 Arm A（快报 ROS 改善+突破）升级为正式因子（仅 INSERT）。

来源：data/factors/expt_fcst_ros_vs_formal.{json,md}
信号：signal_expr_ros_improve_break（快报可算 ROS/ΔROS + 披露后突破）
宇宙：静态 hs300；行情：腾讯 qfq；BaoStock 禁用。
硬性：不 update 任何已有 factor_id；UI ≥177 且 = max+1；不填空洞。
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

FACTOR_ID = "expr_ros_improve_break"
EXPT_ID = "expt_arm_a_expr_ros"
EXPT_JSON = ROOT / "data" / "factors" / "expt_fcst_ros_vs_formal.json"
MIN_UI = 177
CUT = "2024-08-01"
START = "2018-01-01"
PROTECTED = (
    "gross_expand_m16_tp35",
    "gross_expand_lag28_tp35",
    "dual_improve_hs300_mine_r1",
    "gross_expand_m16_lag28_hs300_r2",
    "gross_expand_m16_lag28_long_short_hs300",
)

NAME = "业绩快报ROS改善+突破(HS300·近窗强全样本弱)"
TITLE = "快报ROS改善+突破 HS300 expt_fcst_ros ArmA"
TAGS = [
    "业绩快报",
    "ROS",
    "ΔROS",
    "突破",
    "基本面",
    "技术面",
    "HS300",
    "qfq",
    "expt_fcst_ros",
    "近窗强全样本弱",
]

PARAMS = {
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
    "ros_improve": 0.005,
    "ros_min": 0.0,
    "position_logic": FACTOR_ID,
    "note": TITLE,
}

# 实验目标（允许极小浮点差）
EXPT_TARGET = {"sharpe": 0.0488, "total_return": 0.1352, "late_sharpe": 1.524}


def _ui_docs(db) -> List[dict]:
    docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1, "name": 1}))

    def _key(x):
        ta = x.get("created_at") or ""
        if hasattr(ta, "isoformat"):
            ta = ta.isoformat(sep=" ")
        return (str(ta), str(x.get("factor_id") or ""))

    return sorted(docs, key=_key)


def _ui_seq(docs: List[dict], factor_id: str) -> Optional[int]:
    return next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == factor_id), None)


def _max_created_at(docs: List[dict]) -> Optional[datetime]:
    mx = None
    for d in docs:
        ca = d.get("created_at")
        if ca is None:
            continue
        if mx is None or ca > mx:
            mx = ca
    return mx


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


def _desc(summary: dict, late: dict) -> str:
    return (
        "来自对照实验 expt_fcst_ros_vs_formal Arm A（业绩快报ROS改善+突破）。"
        "信号=快报可算 ROS/ΔROS（净利/营收）同比改善≥0.005 且 ROS≥0，"
        "披露后热窗28日内突破60日高并站上MA20；PIT=快报 ACTUAL_ANN_DT/ANN_DT。"
        "出场：持有50日、止损12%、止盈35%、最多8仓；宇宙=静态沪深300；行情=腾讯前复权 qfq。"
        f"全样本 sharpe≈{summary.get('sharpe')} ret≈{summary.get('total_return')} "
        f"mdd≈{summary.get('max_drawdown')} legs≈{summary.get('n_legs_accepted')}；"
        f"近2年({CUT}+) sharpe≈{late.get('sharpe')} ret≈{late.get('total_return')} "
        f"mdd≈{late.get('max_drawdown')}。"
        "特征：近窗强、全样本弱，作研究/跟踪臂入库，非全样本冠军。"
    )


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


def _plan_db(dbn: str, client) -> Tuple[bool, Optional[datetime], Optional[int], str]:
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    next_ui = max_ui + 1
    if db.factors.find_one({"factor_id": FACTOR_ID}, {"_id": 1}):
        return False, None, None, f"ABORT {dbn}: factor_id already exists: {FACTOR_ID}"
    for pf in PROTECTED:
        if dbn == settings.MONGO_DB and not db.factors.find_one({"factor_id": pf}, {"_id": 1}):
            # 部分保护项可能仅主库有；底座三项必须在
            if pf in (
                "gross_expand_m16_tp35",
                "gross_expand_lag28_tp35",
                "dual_improve_hs300_mine_r1",
            ):
                return False, None, None, f"ABORT {dbn}: protected missing: {pf}"
    if next_ui < MIN_UI:
        return (
            False,
            None,
            None,
            f"ABORT {dbn}: next_ui={next_ui} < MIN_UI={MIN_UI} (cannot invent UI without fillers)",
        )
    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        ca = datetime(2026, 8, 3, 12, 0, 0)
    else:
        ca = mx + timedelta(hours=1)
    return True, ca, next_ui, f"[plan] {dbn} max_ui={max_ui} -> UI#{next_ui} created_at={ca}"


def _verify_arts(factor_id: str) -> None:
    data = ROOT / "data" / "factors"
    arts = [
        f"{factor_id}_backtest.csv",
        f"{factor_id}_backtest.json",
        f"{factor_id}_trade_history.csv",
        f"{factor_id}_equity_curve.png",
    ]
    legs = data / factor_id / "trade_legs.parquet"
    for a in arts:
        p = data / a
        ok = p.exists() and p.stat().st_size > 0
        print(f"[art] {'YES' if ok else 'NO '} {a} {p.stat().st_size if p.exists() else 0}", flush=True)
        if not ok:
            raise SystemExit(f"ABORT missing artifact: {a}")
    if not legs.exists() or legs.stat().st_size <= 0:
        raise SystemExit(f"ABORT missing legs: {legs}")
    print(f"[art] YES {factor_id}/trade_legs.parquet {legs.stat().st_size}", flush=True)


def _reuse_expt_artifacts() -> Tuple[dict, dict]:
    """把实验 Arm A 产物复制为正式 factor_id（参数一致时）。"""
    data = ROOT / "data" / "factors"
    src_csv = data / f"{EXPT_ID}_backtest.csv"
    src_json = data / f"{EXPT_ID}_backtest.json"
    src_tr = data / f"{EXPT_ID}_trade_history.csv"
    src_png = data / f"{EXPT_ID}_equity_curve.png"
    src_legs = data / EXPT_ID / "trade_legs.parquet"
    for p in (src_csv, src_json, src_tr, src_png, src_legs):
        if not p.exists():
            raise SystemExit(f"ABORT reuse: missing {p}")

    daily = pd.read_csv(src_csv)
    # equity csv 一般无 position_logic 列；trade_history 可能有
    shutil.copy2(src_csv, data / f"{FACTOR_ID}_backtest.csv")
    shutil.copy2(src_png, data / f"{FACTOR_ID}_equity_curve.png")

    tr = pd.read_csv(src_tr)
    if "position_logic" in tr.columns:
        tr["position_logic"] = FACTOR_ID
    if "note" in tr.columns:
        tr["note"] = tr["note"].astype(str).str.replace(EXPT_ID, FACTOR_ID, regex=False)
    tr.to_csv(data / f"{FACTOR_ID}_trade_history.csv", index=False)

    dst_legs_dir = data / FACTOR_ID
    dst_legs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_legs, dst_legs_dir / "trade_legs.parquet")

    meta = json.loads(src_json.read_text(encoding="utf-8"))
    summary = dict((meta.get("results") or {}).get(EXPT_ID) or {})
    summary["position_logic"] = FACTOR_ID
    params = dict(PARAMS)
    out_json = {
        "params": params,
        "results": {FACTOR_ID: summary},
        "notes": [TITLE, "promoted from expt_fcst_ros_vs_formal Arm A / reuse artifacts"],
    }
    (data / f"{FACTOR_ID}_backtest.json").write_text(
        json.dumps(out_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    late = _slice_metrics(daily, CUT)
    return summary, late


def _run_backtest() -> Tuple[dict, dict]:
    assert fin_db.db_available(), "本地 ashare_fin_db 不可用"
    print("[panel] prepare HS300 fin_db …", flush=True)
    panel = prepare_shared_panel(
        PARAMS,
        need_profit=False,
        need_growth=False,
        need_fin_db=True,
        limit=0,
    )
    sample = next(iter(panel.values()), pd.DataFrame())
    cols = list(sample.columns) if sample is not None else []
    if "expr_dros" not in cols and "expr_ros" not in cols:
        raise SystemExit(f"ABORT panel missing expr_ros/dros; cols sample={cols[:30]}")
    print(f"[panel] n={len(panel)} expr_ok", flush=True)

    summary = run_factor_pipeline(
        FACTOR_ID,
        TITLE,
        sig.signal_expr_ros_improve_break,
        dict(PARAMS),
        need_profit=False,
        need_growth=False,
        need_fin_db=True,
        limit=0,
        start=START,
        price_map=panel,
    )
    if not isinstance(summary, dict) or summary.get("error"):
        raise SystemExit(f"backtest error: {summary}")
    daily = pd.read_csv(ROOT / "data" / "factors" / f"{FACTOR_ID}_backtest.csv")
    late = _slice_metrics(daily, CUT)
    return summary, late


def _insert_mongo(summary: dict, late: dict) -> int:
    targets, client = _mongo_targets()
    print(f"[mongo] primary={settings.MONGO_DB} targets={targets}", flush=True)
    plans: Dict[str, Tuple[datetime, int]] = {}
    for dbn in targets:
        ok, ca, ui, msg = _plan_db(dbn, client)
        print(msg, flush=True)
        if not ok:
            if dbn == settings.MONGO_DB:
                raise SystemExit(msg)
            print(f"[skip] {dbn} (non-primary)", flush=True)
            continue
        assert ca is not None and ui is not None
        plans[dbn] = (ca, ui)

    if settings.MONGO_DB not in plans:
        raise SystemExit("ABORT: primary DB has no insert plan")

    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    desc = _desc(summary, late)
    primary_ui = plans[settings.MONGO_DB][1]
    summary_dst = dict(summary)
    summary_dst["position_logic"] = FACTOR_ID
    summary_dst["recent2y_sharpe"] = late.get("sharpe")
    summary_dst["recent2y_total_return"] = late.get("total_return")
    summary_dst["recent2y_max_drawdown"] = late.get("max_drawdown")

    for dbn, (ca, ui) in plans.items():
        db = client[dbn]
        n_before = len(_ui_docs(db))
        # 禁止已存在（含 ensure_builtins 竞态）
        if db.factors.find_one({"factor_id": FACTOR_ID}, {"_id": 1}):
            raise SystemExit(f"ABORT race: {dbn}.{FACTOR_ID} already exists")
        for pf in ("gross_expand_m16_tp35", "dual_improve_hs300_mine_r1"):
            if dbn == settings.MONGO_DB and not db.factors.find_one({"factor_id": pf}, {"_id": 1}):
                raise SystemExit(f"ABORT {dbn}: protected missing before insert: {pf}")

        payload = {
            "factor_id": FACTOR_ID,
            "name": NAME,
            "category": "fundamental",
            "description": desc,
            "tags": TAGS,
            "status": "active",
            "builtin": True,
            "params": dict(PARAMS),
            "created_at": ca,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": FACTOR_ID,
                "logics": {FACTOR_ID: summary_dst},
                "updated_at": now_s,
            },
            "last_backtest_error": summary_dst.get("error"),
            "expt_meta": {
                "source": "expt_fcst_ros_vs_formal",
                "arm": "A",
                "expt_factor_id": EXPT_ID,
                "signal": "signal_expr_ros_improve_break",
                "cut": CUT,
                "full_sharpe": summary.get("sharpe"),
                "full_return": summary.get("total_return"),
                "recent2y_sharpe": late.get("sharpe"),
                "recent2y_return": late.get("total_return"),
                "n_legs_accepted": summary.get("n_legs_accepted"),
            },
        }
        r = db.factors.insert_one(payload)
        docs = _ui_docs(db)
        seq = _ui_seq(docs, FACTOR_ID)
        print(
            f"[mongo] INSERT {dbn}.{FACTOR_ID} _id={r.inserted_id} "
            f"created_at={ca} planned_UI#{ui} actual_UI#{seq}/{len(docs)}",
            flush=True,
        )
        if seq != ui:
            raise SystemExit(f"ABORT {dbn}: UI mismatch planned={ui} actual={seq}")
        if len(docs) != n_before + 1:
            raise SystemExit(f"ABORT {dbn}: count {n_before} -> {len(docs)}")
        # 确认未动保护 UI
        if dbn == settings.MONGO_DB:
            for pf, expect in (
                ("gross_expand_m16_tp35", 168),
                ("dual_improve_hs300_mine_r1", 171),
            ):
                got = _ui_seq(docs, pf)
                if got != expect:
                    raise SystemExit(f"ABORT {dbn}: {pf} UI shifted {expect}->{got}")
    return primary_ui


def main() -> None:
    reuse = "--reuse-expt" in sys.argv or "--reuse" in sys.argv
    force_rerun = "--rerun" in sys.argv

    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]
    assert callable(sig.signal_expr_ros_improve_break)

    # 确认实验源
    if EXPT_JSON.exists():
        ex = json.loads(EXPT_JSON.read_text(encoding="utf-8"))
        a = next((t for t in (ex.get("table") or []) if t.get("arm") == "A"), {})
        print(
            f"[expt] ArmA sharpe={a.get('sharpe')} late_sh={a.get('late_sharpe')} "
            f"ret={a.get('total_return')} late_ret={a.get('late_return')}",
            flush=True,
        )

    targets, client = _mongo_targets()
    print("======== PRECHECK ========", flush=True)
    primary_ok = False
    for dbn in targets:
        ok, ca, ui, msg = _plan_db(dbn, client)
        print(msg, flush=True)
        if dbn == settings.MONGO_DB:
            primary_ok = ok
            if ok:
                print(f"  will CREATE UI#{ui} factor_id={FACTOR_ID} created_at={ca}", flush=True)
    if not primary_ok:
        raise SystemExit("ABORT: primary DB plan failed")

    # 默认：有实验产物则复用（与实验完全一致）；--rerun 强制重跑
    expt_csv = ROOT / "data" / "factors" / f"{EXPT_ID}_backtest.csv"
    if force_rerun:
        reuse = False
    elif expt_csv.exists() and not reuse:
        reuse = True
        print("[mode] auto --reuse-expt (pass --rerun to force pipeline)", flush=True)

    if reuse:
        print("======== REUSE EXPT ARTIFACTS ========", flush=True)
        summary, late = _reuse_expt_artifacts()
    else:
        print("======== BACKTEST ========", flush=True)
        summary, late = _run_backtest()

    _verify_arts(FACTOR_ID)
    print(
        f"[bt] full sh={summary.get('sharpe')} ret={summary.get('total_return')} "
        f"mdd={summary.get('max_drawdown')} legs={summary.get('n_legs_accepted')}",
        flush=True,
    )
    print(
        f"[bt] late sh={late.get('sharpe')} ret={late.get('total_return')} "
        f"mdd={late.get('max_drawdown')}",
        flush=True,
    )

    # 与实验对齐抽检
    try:
        if abs(float(summary.get("sharpe")) - EXPT_TARGET["sharpe"]) > 0.02:
            print(
                f"[warn] sharpe drift vs expt: {summary.get('sharpe')} vs {EXPT_TARGET['sharpe']}",
                flush=True,
            )
        if not late.get("empty") and abs(float(late.get("sharpe")) - EXPT_TARGET["late_sharpe"]) > 0.05:
            print(
                f"[warn] late_sharpe drift vs expt: {late.get('sharpe')} vs {EXPT_TARGET['late_sharpe']}",
                flush=True,
            )
    except Exception:
        pass

    ui = _insert_mongo(summary, late)

    report = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ui": ui,
        "factor_id": FACTOR_ID,
        "name": NAME,
        "source": "expt_fcst_ros_vs_formal Arm A",
        "reuse_expt": reuse,
        "full": {
            "sharpe": summary.get("sharpe"),
            "total_return": summary.get("total_return"),
            "max_drawdown": summary.get("max_drawdown"),
            "n_legs_accepted": summary.get("n_legs_accepted"),
            "annual_return": summary.get("annual_return"),
            "annual_vol": summary.get("annual_vol"),
        },
        "recent2y": late,
        "params": PARAMS,
        "primary_db": settings.MONGO_DB,
    }
    out = ROOT / "data" / "factors" / "fill_fcst_ros_expr_improve_hs300.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("======== REPORT ========", flush=True)
    print(
        f"#{ui} {FACTOR_ID} | {NAME}\n"
        f"  full  sharpe={summary.get('sharpe')} ret={summary.get('total_return')} "
        f"mdd={summary.get('max_drawdown')} legs={summary.get('n_legs_accepted')}\n"
        f"  r2y   sharpe={late.get('sharpe')} ret={late.get('total_return')} "
        f"mdd={late.get('max_drawdown')}",
        flush=True,
    )
    print(f"[ok] -> {out}", flush=True)


if __name__ == "__main__":
    main()
