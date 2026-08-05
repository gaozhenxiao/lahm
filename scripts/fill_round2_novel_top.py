"""把 Round2 novel Top 候选写入 lahm（仅 INSERT，序号从 178 起）。

来源：data/factors/mine_csi300_500_1000_round2/{univ,_novel}/results.json
行情：腾讯 qfq（_shared/daily）；BaoStock 禁用。
硬性：不 update 已有 factor_id；不填空洞；UI 不得小于 178；撞号 abort。
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

MINE_ROOT = ROOT / "data" / "factors" / "mine_csi300_500_1000_round2"
MIN_UI = 178
PROTECTED = (
    "gross_expand_m16_tp35",
    "gross_expand_lag28_tp35",
    "dual_improve_hs300_mine_r1",
    "gross_expand_m16_lag28_hs300_r2",
    "gross_expand_m16_lag28_long_short_hs300",
    "expr_ros_improve_break",
)

# 按用户指定顺序；第 6 取 HS300 fmkv（全局 Top 更高，且不与前五重复）
CANDIDATES: List[Dict[str, Any]] = [
    {
        "factor_id": "ge_mid_m12_mkv_cap5e10_hs300_r2n",
        "cfg_id": "ge_mid__m12_mkv_cap5e10",
        "univ": "hs300",
        "results_sub": "hs300_novel",
        "signal": sig.signal_gross_expand_break,
        "signal_name": "signal_gross_expand_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": False,
        "name": "中小市值毛利扩张(HS300·ge_mid__m12_mkv_cap5e10·mine R2 novel 时间加权)",
        "title": "GE midcap m12 mkv HS300 R2 novel",
        "tags": ["基本面", "技术面", "毛利率", "中小市值", "HS300", "qfq", "mine_round2", "novel", "时间加权"],
    },
    {
        "factor_id": "struct_catchup_lag28_h45_hs300_r2n",
        "cfg_id": "struct__catchup_lag28_h45",
        "univ": "hs300",
        "results_sub": "hs300_novel",
        "signal": sig.signal_gross_net_catchup_break,
        "signal_name": "signal_gross_net_catchup_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": False,
        "name": "毛净追赶结构(HS300·struct__catchup_lag28_h45·mine R2 novel 时间加权)",
        "title": "Catchup lag28 h45 HS300 R2 novel",
        "tags": ["基本面", "技术面", "毛利率", "净利率", "catchup", "HS300", "qfq", "mine_round2", "novel", "时间加权"],
    },
    {
        "factor_id": "q_np_gap_exp120_h35_tp30_csi1000_r2n",
        "cfg_id": "q_np_gap__exp120_h35_tp30",
        "univ": "csi1000",
        "results_sub": "csi1000_novel",
        "signal": sig.signal_q_np_gap,
        "signal_name": "signal_q_np_gap",
        "need_profit": False,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": True,
        "name": "单季利润断层(CSI1000·q_np_gap__exp120_h35_tp30·mine R2 novel 时间加权)",
        "title": "Q NP gap exp120 CSI1000 R2 novel",
        "tags": ["正式季报", "单季净利", "利润断层", "CSI1000", "qfq", "mine_round2", "novel", "时间加权"],
    },
    {
        "factor_id": "struct_demand_m18_lag30_csi1000_r2n",
        "cfg_id": "struct__demand_m18_lag30",
        "univ": "csi1000",
        "results_sub": "csi1000_novel",
        "signal": sig.signal_demand_pricing_break,
        "signal_name": "signal_demand_pricing_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": True,
        "need_fin_db": False,
        "name": "需求定价结构(CSI1000·struct__demand_m18_lag30·mine R2 novel 时间加权)",
        "title": "Demand m18 lag30 CSI1000 R2 novel",
        "tags": ["基本面", "技术面", "合同负债", "毛利率", "CSI1000", "qfq", "mine_round2", "novel", "时间加权"],
    },
    {
        "factor_id": "struct_catchup_lag28_h45_csi500_r2n",
        "cfg_id": "struct__catchup_lag28_h45",
        "univ": "csi500",
        "results_sub": "csi500_novel",
        "signal": sig.signal_gross_net_catchup_break,
        "signal_name": "signal_gross_net_catchup_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": False,
        "name": "毛净追赶结构(CSI500·struct__catchup_lag28_h45·mine R2 novel 时间加权)",
        "title": "Catchup lag28 h45 CSI500 R2 novel",
        "tags": ["基本面", "技术面", "毛利率", "净利率", "catchup", "CSI500", "qfq", "mine_round2", "novel", "时间加权"],
    },
    {
        "factor_id": "ge_novel_fmkv_b_edges_mbrk_hs300_r2n",
        "cfg_id": "ge_novel__fmkv_b_edges_mbrk",
        "univ": "hs300",
        "results_sub": "hs300_novel",
        "signal": sig.signal_gross_expand_break,
        "signal_name": "signal_gross_expand_break",
        "need_profit": True,
        "need_growth": False,
        "need_balance": False,
        "need_fin_db": False,
        "name": "毛利扩张f(mkv)(HS300·ge_novel__fmkv_b_edges_mbrk·mine R2 novel 时间加权)",
        "title": "GE novel fmkv edges mbrk HS300 R2 novel",
        "tags": ["基本面", "技术面", "毛利率", "f(mkv)", "HS300", "qfq", "mine_round2", "novel", "时间加权"],
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


def _load_mine_row(sub: str, cfg_id: str) -> dict:
    path = MINE_ROOT / sub / "results.json"
    if not path.exists():
        # 回退到非 _novel 目录
        alt = MINE_ROOT / sub.replace("_novel", "") / "results.json"
        path = alt if alt.exists() else path
    data = json.loads(path.read_text(encoding="utf-8"))
    for r in data.get("all") or []:
        if r.get("cfg_id") == cfg_id:
            return r
    raise SystemExit(f"cfg_id not found in {path}: {cfg_id}")


def _desc(c: dict, params: dict, mine: dict) -> str:
    return (
        f"mine_csi300_500_1000_round2 / {c['results_sub']} `{c['cfg_id']}`"
        f"（时间加权 tw≈{mine.get('tw_score'):.3f}；mine R2 novel 时间加权）。"
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
        base = datetime(2026, 6, 23, 19, 0, 0)
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
        if not ok:
            if dbn == settings.MONGO_DB:
                raise SystemExit(msg)
            print(f"[skip] {dbn} (non-primary)", flush=True)
            continue
        plans[dbn] = planned

    if settings.MONGO_DB not in plans:
        raise SystemExit(f"ABORT: primary DB {settings.MONGO_DB} has no insert plan")

    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    cand_by_id = {c["factor_id"]: c for c in CANDIDATES}

    for dbn, planned in plans.items():
        db = client[dbn]
        docs_before = _ui_docs(db)
        # 保护 #166–#177 映射
        protect_map = {
            "gross_expand_lag28_tp35": 166,
            "gross_expand_m16_tp35": 168,
            "dual_improve_hs300_mine_r1": 171,
            "expr_ros_improve_break": 177,
        }
        for pf, expect in protect_map.items():
            got = _ui_seq(docs_before, pf)
            if got is not None and got != expect:
                raise SystemExit(f"ABORT {dbn}: before insert {pf} UI={got} expect={expect}")

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
                    "source": f"mine_csi300_500_1000_round2/{c['results_sub']}",
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
            for pf, expect in protect_map.items():
                got = _ui_seq(docs, pf)
                if got != expect:
                    raise SystemExit(f"ABORT {dbn}: {pf} UI shifted {expect}->{got}")


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

    # 信号必须可解析
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
        row = _load_mine_row(c["results_sub"], c["cfg_id"])
        params = deepcopy(row["params"])
        params["request_interval_sec"] = 0.35
        params["price_end"] = params.get("price_end") or "2026-07-30"
        params["exclude_st"] = True
        # 对齐 registry 宇宙
        params["universe"] = c["univ"]
        if c["univ"] == "hs300":
            params["bench_code"] = "sh.000300"
        elif c["univ"] == "csi500":
            params["bench_code"] = "sh.000905"
        elif c["univ"] == "csi1000":
            params["bench_code"] = "sh.000852"
        params_map[c["factor_id"]] = params
        mine_map[c["factor_id"]] = row
        print(
            f"[mine] {c['univ']}/{c['cfg_id']} -> {c['factor_id']} "
            f"tw={row.get('tw_score'):.3f} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe'):.3f}",
            flush=True,
        )

    # 按宇宙准备共享 panel（flags 取该宇宙候选的并集）
    panels: Dict[str, Dict[str, Any]] = {}
    for univ in sorted({c["univ"] for c in CANDIDATES}):
        group = [c for c in CANDIDATES if c["univ"] == univ]
        need_profit = any(c["need_profit"] for c in group)
        need_growth = any(c["need_growth"] for c in group)
        need_balance = any(c["need_balance"] for c in group)
        need_fin_db = any(c["need_fin_db"] for c in group)
        base_params = dict(params_map[group[0]["factor_id"]])
        print(
            f"[panel] preparing {univ} profit={need_profit} balance={need_balance} fin_db={need_fin_db}...",
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
    docs = _ui_docs(client2[primary].factors)
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
    out = ROOT / "data" / "factors" / "fill_round2_novel_top.json"
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


if __name__ == "__main__":
    main()
