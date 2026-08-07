"""把二阶挖掘 Round2 Top 候选写入 lahm（仅 INSERT）。

来源：data/factors/mine_second_order_round2/{univ}/results.json
行情：腾讯 qfq（_shared/daily）；BaoStock 禁用。
硬性：不 update 已有 factor_id；不填空洞；撞号 abort。
MIN_UI=255（主库已至 #254；不覆盖 #198–#203）。
宁少勿滥：3 条正交二阶族（AR×CL 交叉 / 应收二阶 / CFO质量二阶）。
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

MINE_ROOT = ROOT / "data" / "factors" / "mine_second_order_round2"
MIN_UI = 255
BENCH = {"hs300": "sh.000300", "csi500": "sh.000905", "csi1000": "sh.000852"}
PROTECTED = (
    "gross_expand_m16_tp35",
    "gross_expand_lag28_tp35",
    "dual_improve_hs300_mine_r1",
    "gross_expand_m16_lag28_hs300_r2",
    "gross_expand_m16_lag28_long_short_hs300",
    "expr_ros_improve_break",
    "ipo_2y5_earn_break",
    "dual_rev_np_yoy_dual04_hs300_yoy",
    "rev_yoy_acc_racc05_hs300_yoy",
    "q_np_yoy_acc_qacc15_hs300_yoy",
    "ar_tighten_ar015_hs300_causal",
    "cl_yoy_acc_clacc12_csi500_causal",
    "opex_rev_ox05_hs300_causal",
)

CANDIDATES: List[Dict[str, Any]] = [
    {
        "factor_id": "ar_cl_dual_ar015_csi500_so2",
        "cfg_id": "ar_cl_dual__arcl_ar015_cl10_brk70_h42_np04",
        "univ": "csi500",
        "signal": sig.signal_ar_cl_dual_accel_break,
        "signal_name": "signal_ar_cl_dual_accel_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": True,
        "need_fin_db": True,
        "name": "应收收紧×合同负债加速(CSI500·ar015_cl10_brk70·二阶R2)",
        "title": "AR tighten x CL accel CSI500",
        "tags": ["应收", "合同负债", "YoY加速", "交叉验证", "突破", "CSI500", "qfq", "mine_second_order_r2", "时间加权"],
    },
    {
        "factor_id": "ar_acc_ar012_hs300_so2",
        "cfg_id": "ar_acc__aracc012_ry05_brk60_h40",
        "univ": "hs300",
        "signal": sig.signal_ar_improve_accel_break,
        "signal_name": "signal_ar_improve_accel_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": True,
        "name": "应收强度改善二阶(HS300·aracc012_ry05_brk60·二阶R2)",
        "title": "AR improve accel HS300",
        "tags": ["应收", "二阶", "回款质量", "突破", "HS300", "qfq", "mine_second_order_r2", "时间加权"],
    },
    {
        "factor_id": "cfo_np_acc_cfoq08_csi500_so2",
        "cfg_id": "cfo_np_acc__cfoq08_m06_g00_brk60_h40",
        "univ": "csi500",
        "signal": sig.signal_cfo_np_quality_accel_break,
        "signal_name": "signal_cfo_np_quality_accel_break",
        "need_profit": True,
        "need_growth": True,
        "need_balance": False,
        "need_fin_db": True,
        "name": "CFO净利质量二阶(CSI500·cfoq08_m06_brk60·二阶R2)",
        "title": "CFO/NP quality accel CSI500",
        "tags": ["现金流", "利润质量", "二阶", "突破", "CSI500", "qfq", "mine_second_order_r2", "时间加权"],
    },
]


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


def _load_mine_row(univ: str, cfg_id: str) -> dict:
    path = MINE_ROOT / univ / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for r in data.get("all") or []:
        if r.get("cfg_id") == cfg_id:
            return r
    raise SystemExit(f"cfg_id not found in {path}: {cfg_id}")


def _desc(c: dict, params: dict, mine: dict) -> str:
    return (
        f"mine_second_order_round2 / {c['univ']} `{c['cfg_id']}`"
        f"（时间加权 tw≈{mine.get('tw_score'):.3f}；二阶挖掘 R2）。"
        f"宇宙={c['univ']}；信号={c['signal_name']}；"
        f"行情=腾讯前复权 qfq（_shared/daily）；BaoStock 禁用。"
        f"mine 指标：full_sh≈{mine.get('sharpe')}，full_ret≈{mine.get('total_return')}，"
        f"r2y_sh≈{mine.get('recent2y_sharpe')}，r2y_ret≈{mine.get('recent2y_return')}，"
        f"legs≈{mine.get('n_legs_accepted')}。"
        f"核心 params={json.dumps({k: params[k] for k in params if k not in ('request_interval_sec',)}, ensure_ascii=False)}"
    )


def _plan_db(dbn: str, client, new_ids: List[str]) -> Tuple[bool, List[Tuple[str, datetime, int]], str]:
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    start_ui = max(MIN_UI, max_ui + 1)
    next_physical = max_ui + 1

    for fid in new_ids:
        if db.factors.find_one({"factor_id": fid}, {"_id": 1}):
            return False, [], f"ABORT {dbn}: factor_id already exists: {fid}"

    for fid in PROTECTED:
        if not db.factors.find_one({"factor_id": fid}, {"_id": 1}):
            if fid in (
                "gross_expand_m16_tp35",
                "gross_expand_lag28_tp35",
                "dual_improve_hs300_mine_r1",
                "expr_ros_improve_break",
                "ipo_2y5_earn_break",
            ):
                return False, [], f"ABORT {dbn}: protected factor missing: {fid}"

    if start_ui != next_physical:
        return (
            False,
            [],
            f"ABORT {dbn}: max_ui={max_ui} next_physical={next_physical} < MIN_UI={MIN_UI} "
            f"(cannot invent UI#{start_ui} without filler docs)",
        )

    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        base = datetime(2026, 8, 7, 8, 0, 0)
    else:
        base = mx + timedelta(hours=1)

    planned: List[Tuple[str, datetime, int]] = []
    for i, fid in enumerate(new_ids):
        ca = base + timedelta(hours=i)
        ui = start_ui + i
        if ui <= max_ui:
            occ = docs[ui - 1].get("factor_id")
            return False, [], f"ABORT {dbn}: UI#{ui} already occupied by {occ}"
        planned.append((fid, ca, ui))

    msg = (
        f"[plan] {dbn} max_ui={max_ui} max_created_at={mx} "
        f"-> UI#{start_ui}..#{start_ui + len(new_ids) - 1} "
        f"created_at={[str(c) for _, c, _ in planned]}"
    )
    return True, planned, msg


def _insert_mongo(summaries: Dict[str, dict], params_map: Dict[str, dict], mine_map: Dict[str, dict]) -> None:
    targets, client = _mongo_targets()
    new_ids = [c["factor_id"] for c in CANDIDATES]
    print(f"[mongo] primary={settings.MONGO_DB} targets={targets}", flush=True)

    plans = {}
    for dbn in targets:
        ok, planned, msg = _plan_db(dbn, client, new_ids)
        print(msg, flush=True)
        if not ok and dbn == settings.MONGO_DB:
            raise SystemExit(msg)
        if ok:
            plans[dbn] = planned

    if settings.MONGO_DB not in plans:
        raise SystemExit("ABORT: primary DB not planned")

    cand_by_id = {c["factor_id"]: c for c in CANDIDATES}
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")

    for dbn, planned in plans.items():
        db = client[dbn]
        for pf in ("gross_expand_lag28_tp35", "gross_expand_m16_tp35", "dual_improve_hs300_mine_r1", "ipo_2y5_earn_break"):
            got = _ui_seq(_ui_docs(db), pf)
            print(f"[protect] {dbn} {pf} UI#{got}", flush=True)

        for fid, created_at, ui in planned:
            c = cand_by_id[fid]
            params = dict(params_map[fid])
            params["position_logic"] = fid
            summary = dict(summaries[fid])
            summary["position_logic"] = fid
            mine = mine_map[fid]
            payload = {
                "factor_id": fid,
                "name": c["name"],
                "category": "fundamental",
                "description": _desc(c, params, mine),
                "tags": c["tags"],
                "status": "active",
                "builtin": True,
                "params": params,
                "created_at": created_at,
                "updated_at": now,
                "backtest_summary": {
                    "available": True,
                    "primary_logic": fid,
                    "logics": {fid: summary},
                    "updated_at": now_s,
                },
                "last_backtest_error": summary.get("error"),
                "mine_meta": {
                    "source": f"mine_second_order_round2/{c['univ']}",
                    "cfg_id": c["cfg_id"],
                    "signal": c["signal_name"],
                    "tw_score": mine.get("tw_score"),
                    "full_sharpe": mine.get("sharpe"),
                    "full_return": mine.get("total_return"),
                    "recent2y_sharpe": mine.get("recent2y_sharpe"),
                    "recent2y_return": mine.get("recent2y_return"),
                    "n_legs_accepted": mine.get("n_legs_accepted"),
                },
            }
            if db.factors.find_one({"factor_id": fid}, {"_id": 1}):
                raise SystemExit(f"ABORT race: {dbn}.{fid} appeared before insert")
            r = db.factors.insert_one(payload)
            docs = _ui_docs(db)
            seq = _ui_seq(docs, fid)
            print(
                f"[mongo] INSERT {dbn}.{fid} _id={r.inserted_id} "
                f"created_at={created_at} planned_UI#{ui} actual_UI#{seq}/{len(docs)}",
                flush=True,
            )
            if seq != ui:
                raise SystemExit(f"ABORT {dbn}.{fid}: UI mismatch planned={ui} actual={seq}")
            for pf in (
                "gross_expand_lag28_tp35",
                "gross_expand_m16_tp35",
                "dual_improve_hs300_mine_r1",
                "ipo_2y5_earn_break",
            ):
                if _ui_seq(docs, pf) is None:
                    raise SystemExit(f"ABORT {dbn}: {pf} disappeared after insert")


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
        print(f"[art] {'YES' if p.exists() else 'NO '} {a} {p.stat().st_size if p.exists() else 0}", flush=True)
    print(f"[art] {'YES' if legs.exists() else 'NO '} {factor_id}/trade_legs.parquet", flush=True)
    if not legs.exists():
        raise SystemExit(f"missing legs for {factor_id}")


def main() -> None:
    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    for c in CANDIDATES:
        fid = c["factor_id"]
        if fid not in FACTOR_IMPL:
            raise SystemExit(f"ABORT: {fid} not in FACTOR_IMPL")
        meta = FACTOR_IMPL[fid]
        if meta.get("signal") is None:
            raise SystemExit(f"ABORT: {fid} has no signal in FACTOR_IMPL")
        print(f"[registry] OK {fid} signal={c['signal_name']}", flush=True)

    targets, client = _mongo_targets()
    new_ids = [c["factor_id"] for c in CANDIDATES]
    print("======== PRECHECK ========", flush=True)
    primary_ok = False
    for dbn in targets:
        ok, planned, msg = _plan_db(dbn, client, new_ids)
        print(msg, flush=True)
        if dbn == settings.MONGO_DB:
            primary_ok = ok
            if ok:
                for fid, ca, ui in planned:
                    print(f"  will CREATE UI#{ui} factor_id={fid} created_at={ca}", flush=True)
    if not primary_ok:
        raise SystemExit("ABORT: primary DB plan failed")

    params_map: Dict[str, dict] = {}
    mine_map: Dict[str, dict] = {}
    for c in CANDIDATES:
        row = _load_mine_row(c["univ"], c["cfg_id"])
        params = deepcopy(row["params"])
        params["request_interval_sec"] = 0.35
        params["price_end"] = "2026-08-05"
        params["exclude_st"] = True
        params["universe"] = c["univ"]
        params["bench_code"] = BENCH.get(c["univ"], "sh.000300")
        params_map[c["factor_id"]] = params
        mine_map[c["factor_id"]] = row
        print(
            f"[mine] {c['univ']}/{c['cfg_id']} -> {c['factor_id']} "
            f"tw={row.get('tw_score'):.3f} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe'):.3f}",
            flush=True,
        )

    panels: Dict[str, Dict[str, Any]] = {}
    for univ in sorted({c["univ"] for c in CANDIDATES}):
        group = [c for c in CANDIDATES if c["univ"] == univ]
        need_profit = any(c["need_profit"] for c in group)
        need_growth = any(c["need_growth"] for c in group)
        need_balance = any(c["need_balance"] for c in group)
        need_fin_db = any(c["need_fin_db"] for c in group)
        base_params = dict(params_map[group[0]["factor_id"]])
        print(
            f"[panel] preparing {univ} profit={need_profit} growth={need_growth} "
            f"balance={need_balance} fin_db={need_fin_db}...",
            flush=True,
        )
        panels[univ] = prepare_shared_panel(
            base_params,
            need_profit=need_profit,
            need_growth=need_growth,
            need_balance=need_balance,
            need_fin_db=need_fin_db,
            limit=0,
        )
        print(f"[panel] {univ} n={len(panels[univ])}", flush=True)

    summaries: Dict[str, dict] = {}
    for c in CANDIDATES:
        fid = c["factor_id"]
        print(f"======== BACKTEST {fid} ========", flush=True)
        summary = run_factor_pipeline(
            fid,
            c["title"],
            c["signal"],
            params_map[fid],
            need_profit=c["need_profit"],
            need_growth=c["need_growth"],
            need_balance=c["need_balance"],
            need_fin_db=c["need_fin_db"],
            limit=0,
            start="2018-01-01",
            price_map=panels[c["univ"]],
            shared=True,
        )
        if summary.get("error"):
            raise SystemExit(f"backtest error {fid}: {summary.get('error')}")
        summaries[fid] = summary
        mine = mine_map[fid]
        print(
            f"[bt] {fid} ret={summary.get('total_return')} sharpe={summary.get('sharpe')} "
            f"(mine ret={mine.get('total_return')} sh={mine.get('sharpe')})",
            flush=True,
        )
        _verify_arts(fid)

    _insert_mongo(summaries, params_map, mine_map)

    report = []
    targets2, client2 = _mongo_targets()
    primary = settings.MONGO_DB
    docs = _ui_docs(client2[primary])
    for c in CANDIDATES:
        fid = c["factor_id"]
        s = summaries[fid]
        m = mine_map[fid]
        seq = _ui_seq(docs, fid)
        report.append(
            {
                "ui": seq,
                "factor_id": fid,
                "name": c["name"],
                "cfg_id": c["cfg_id"],
                "univ": c["univ"],
                "mine_tw": m.get("tw_score"),
                "mine_full_sh": m.get("sharpe"),
                "mine_r2y_sh": m.get("recent2y_sharpe"),
                "mine_r2y_ret": m.get("recent2y_return"),
                "bt_sharpe": s.get("sharpe"),
                "bt_total_return": s.get("total_return"),
                "bt_n_legs": s.get("n_legs_accepted"),
            }
        )
    out = ROOT / "data" / "factors" / "fill_second_order_round2.json"
    payload = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "primary_db": primary,
        "report": report,
        "summaries": {k: v for k, v in summaries.items()},
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("======== REPORT ========", flush=True)
    for r in report:
        print(
            f"#{r['ui']} {r['factor_id']} | {r['univ']}/{r['cfg_id']} | "
            f"full_sh≈{r['mine_full_sh']} r2y_sh≈{r['mine_r2y_sh']:.3f} | "
            f"bt_sh={r['bt_sharpe']} bt_ret={r['bt_total_return']}",
            flush=True,
        )
    print(f"[ok] -> {out}", flush=True)

    summary_md = MINE_ROOT / "SUMMARY.md"
    if summary_md.exists():
        extra = [
            "",
            "## 本轮已入库（#255–#257；不覆盖 #198–#203）",
            "",
            "| UI | univ | cfg / factor_id | tw | r2y_sh | bt_sh |",
            "|----|------|-----------------|----|--------|-------|",
        ]
        for r in report:
            extra.append(
                f"| {r['ui']} | {r['univ']} | `{r['cfg_id']}` → `{r['factor_id']}` | "
                f"{r['mine_tw']:.3f} | {r['mine_r2y_sh']:.3f} | {r['bt_sharpe']} |"
            )
        extra.extend(
            [
                "",
                "未挂：同族第二档 ar_cl_dual；gp_margin_accel / inv_improve_accel（全样本偏弱或与上列重叠）。",
                "",
            ]
        )
        text = summary_md.read_text(encoding="utf-8")
        if "## 本轮已入库" not in text:
            summary_md.write_text(text.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


if __name__ == "__main__":
    main()
