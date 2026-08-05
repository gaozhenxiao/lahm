"""把结构大批量 Round1 Top 候选写入 lahm（仅 INSERT，≥#204）。

来源：data/factors/mine_struct_mass_round1/global_top.json + {univ}/results.json
自动按族正交选 12–20 条；近2年大亏剔除；宁可用略弱占位也不要只交三五个。
行情：腾讯 qfq；BaoStock 禁用。硬性：不 update；不填空洞；撞号 abort。

用法（挖掘完成后）:
  .venv\\Scripts\\python.exe scripts/fill_struct_mass_round1.py
  .venv\\Scripts\\python.exe scripts/fill_struct_mass_round1.py --dry-run
  .venv\\Scripts\\python.exe scripts/fill_struct_mass_round1.py --n 16
"""
from __future__ import annotations

import argparse
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

MINE_ROOT = ROOT / "data" / "factors" / "mine_struct_mass_round1"
MIN_UI = 204
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

# family -> (signal_fn, need_profit, need_growth, need_balance, need_fin_db, tag_cn)
FAMILY_META: Dict[str, Tuple[Any, bool, bool, bool, bool, str]] = {
    "cl_yoy_accel": (sig.signal_cl_yoy_accel_break, True, False, False, True, "合同负债YoY二阶"),
    "gp_rev_dual": (sig.signal_gp_rev_dual_hit_break, True, False, False, True, "毛利营收双击"),
    "opex_down_rev": (sig.signal_opex_down_rev_accel_break, True, False, False, True, "费用率下行"),
    "inv_delever_rev": (sig.signal_inv_delever_rev_break, True, False, False, True, "存货强度下行"),
    "ar_tighten_rev": (sig.signal_ar_tighten_rev_break, True, False, False, True, "应收强度下行"),
    "gp_opex_dual": (sig.signal_gp_opex_dual_break, True, False, False, True, "毛利费用双击"),
    "ar_inv_dual": (sig.signal_ar_inv_dual_break, True, False, False, True, "应收存货双改善"),
    "roe_struct": (sig.signal_roe_struct_improve_break, True, False, False, False, "ROE结构改善"),
    "roa_improve": (sig.signal_roa_improve_break, True, False, False, True, "ROA改善"),
    "roe_roa_sync": (sig.signal_roe_roa_sync_break, True, False, False, True, "ROE×ROA双击"),
    "lev_delever": (sig.signal_lev_delever_quality_break, True, False, False, True, "杠杆下行"),
    "cfo_quality": (sig.signal_cfo_quality_break, True, False, False, True, "现金流质量"),
    "asset_turn": (sig.signal_asset_turn_up_break, True, False, False, True, "资产周转"),
    "demand_pricing": (sig.signal_demand_pricing_break, True, False, True, False, "需求定价"),
    "cl_intensity": (sig.signal_cl_intensity_break, True, False, True, False, "合同负债强度"),
    "gross_net_catchup": (sig.signal_gross_net_catchup_break, True, False, False, False, "毛净追赶"),
    "gross_np_up": (sig.signal_gross_np_up_break, True, False, False, False, "毛净双升"),
    "gp_consec": (sig.signal_gp_consec_break, True, False, False, False, "连续毛利"),
    "np_regime": (sig.signal_np_regime_break, True, False, False, False, "净利regime"),
    "rev_roe_sync": (sig.signal_rev_roe_sync_break, True, True, False, False, "营收ROE同步"),
    "parent_lead": (sig.signal_parent_lead_break, True, True, False, False, "归属净利领先"),
    "roe_accel": (sig.signal_roe_accel_break, True, False, False, False, "ROE加速"),
}


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
    primary = settings.MONGO_DB
    targets = [primary]
    # 常见镜像库一并插入（若存在）
    for extra in ("lahm", "lahm_v0"):
        if extra != primary and extra in client.list_database_names():
            if "factors" in client[extra].list_collection_names():
                targets.append(extra)
    return targets, client


def _plan_db(dbn: str, client, new_ids: List[str]):
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    for fid in new_ids:
        if db.factors.find_one({"factor_id": fid}, {"_id": 1}):
            return False, [], f"ABORT {dbn}: factor_id already exists: {fid}"
    for pf in PROTECTED:
        if not db.factors.find_one({"factor_id": pf}, {"_id": 1}):
            # 部分保护项可能不在镜像库
            if dbn == settings.MONGO_DB:
                return False, [], f"ABORT {dbn}: protected missing: {pf}"

    start_ui = max(max_ui + 1, MIN_UI)
    next_physical = max_ui + 1
    if next_physical < MIN_UI and start_ui > next_physical:
        return (
            False,
            [],
            f"ABORT {dbn}: max_ui={max_ui} next_physical={next_physical} < MIN_UI={MIN_UI}",
        )

    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        base = datetime(2026, 8, 3, 22, 0, 0)
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
        f"-> UI#{start_ui}..#{start_ui + len(new_ids) - 1}"
    )
    return True, planned, msg


def _load_mine_row(univ: str, cfg_id: str) -> dict:
    path = MINE_ROOT / univ / "results.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for r in payload.get("all") or []:
        if r.get("cfg_id") == cfg_id:
            return r
    raise SystemExit(f"missing cfg {univ}/{cfg_id} in {path}")


def _short_cfg(cfg_id: str) -> str:
    # sm_clacc__clacc06_y08_brk55_h38 -> clacc06_y08
    body = cfg_id.split("__", 1)[-1]
    parts = body.split("_")
    return "_".join(parts[:3]) if len(parts) >= 3 else body[:24]


def _make_factor_id(univ: str, family: str, cfg_id: str) -> str:
    fam = family.replace("_", "")[:10]
    short = _short_cfg(cfg_id).replace("__", "_")[:28]
    return f"{fam}_{short}_{univ}_sm1"


def _pick_candidates(n: int, min_tw: float) -> List[Dict[str, Any]]:
    top_path = MINE_ROOT / "global_top.json"
    if not top_path.exists():
        raise SystemExit(f"missing {top_path}; run mine_struct_mass_round1.py first")
    rows = json.loads(top_path.read_text(encoding="utf-8"))
    # 过滤明显垃圾
    clean: List[dict] = []
    for r in rows:
        if r.get("tw_score") is None:
            continue
        if float(r.get("tw_score") or -999) < min_tw:
            continue
        r2 = r.get("recent2y_return")
        if r2 is not None and float(r2) < -0.20:
            continue
        r2s = r.get("recent2y_sharpe")
        if r2s is not None and float(r2s) < -0.35:
            continue
        nleg = int(r.get("n_legs_accepted") or 0)
        if nleg < 25:
            continue
        fam = r.get("family") or ""
        if fam not in FAMILY_META:
            continue
        clean.append(r)

    # 族优先正交：每族最多 2；宇宙尽量分散
    picked: List[dict] = []
    fam_count: Dict[str, int] = {}
    univ_count: Dict[str, int] = {}
    used_cfg: set = set()

    def _try_add(r: dict, fam_cap: int, univ_cap: int) -> bool:
        fam = r.get("family") or ""
        univ = r.get("universe") or "hs300"
        cfg = r.get("cfg_id") or ""
        key = f"{univ}|{cfg}"
        if key in used_cfg:
            return False
        if fam_count.get(fam, 0) >= fam_cap:
            return False
        if univ_count.get(univ, 0) >= univ_cap:
            return False
        picked.append(r)
        used_cfg.add(key)
        fam_count[fam] = fam_count.get(fam, 0) + 1
        univ_count[univ] = univ_count.get(univ, 0) + 1
        return True

    # pass1: 每族 1，每宇宙最多 n//2
    for r in clean:
        if len(picked) >= n:
            break
        _try_add(r, fam_cap=1, univ_cap=max(4, n // 2 + 2))
    # pass2: 放宽到每族 2
    for r in clean:
        if len(picked) >= n:
            break
        _try_add(r, fam_cap=2, univ_cap=max(6, n))
    # pass3: 再放宽（略弱占位）
    for r in clean:
        if len(picked) >= n:
            break
        _try_add(r, fam_cap=3, univ_cap=n)

    if len(picked) < 10:
        # 降低 tw 门槛再补
        for r in rows:
            if len(picked) >= 10:
                break
            if (r.get("family") or "") not in FAMILY_META:
                continue
            r2 = r.get("recent2y_return")
            if r2 is not None and float(r2) < -0.25:
                continue
            nleg = int(r.get("n_legs_accepted") or 0)
            if nleg < 20:
                continue
            _try_add(r, fam_cap=4, univ_cap=n)

    out: List[Dict[str, Any]] = []
    for r in picked[:n]:
        fam = r["family"]
        univ = r["universe"]
        cfg = r["cfg_id"]
        fn, np_, ng, nb, nf, tag_cn = FAMILY_META[fam]
        fid = _make_factor_id(univ, fam, cfg)
        # 碰撞时加后缀
        base_fid = fid
        k = 2
        while any(c["factor_id"] == fid for c in out):
            fid = f"{base_fid}_v{k}"
            k += 1
        out.append(
            {
                "factor_id": fid,
                "cfg_id": cfg,
                "univ": univ,
                "family": fam,
                "signal": fn,
                "signal_name": getattr(fn, "__name__", str(fn)),
                "need_profit": np_,
                "need_growth": ng,
                "need_balance": nb,
                "need_fin_db": nf,
                "name": f"{tag_cn}({univ.upper()}·{_short_cfg(cfg)}·结构大批量R1)",
                "title": f"{fam} {univ} sm1",
                "tags": [
                    "结构",
                    tag_cn,
                    "突破",
                    univ.upper(),
                    "qfq",
                    "mine_struct_mass",
                    "时间加权",
                ],
                "mine_row": r,
            }
        )
    return out


def _register(c: Dict[str, Any], params: Dict[str, Any]) -> None:
    fid = c["factor_id"]
    FACTOR_IMPL[fid] = {
        "name": c["name"],
        "category": "fundamental",
        "description": (
            f"mine_struct_mass_round1：{c['univ']} `{c['cfg_id']}` / {c['family']}。"
            f"结构信号+技术确认；腾讯 qfq；静态成分幸存者偏差。"
        ),
        "tags": c["tags"],
        "title": c["title"],
        "need_profit": c["need_profit"],
        "need_growth": c["need_growth"],
        "need_balance": c["need_balance"],
        "need_fin_db": c["need_fin_db"],
        "signal": c["signal"],
        "params": params,
    }


def _desc(c: Dict[str, Any], params: Dict[str, Any], mine: dict) -> str:
    return (
        f"{c['name']}；cfg=`{c['cfg_id']}`；signal=`{c['signal_name']}`；"
        f"tw_score={mine.get('tw_score')} full_sh={mine.get('sharpe')} "
        f"r2y_sh={mine.get('recent2y_sharpe')} r2y_ret={mine.get('recent2y_return')}；"
        f"universe={c['univ']}；hold={params.get('hold_days')} brk={params.get('break_days')} "
        f"lag={params.get('funda_lag')} entry={params.get('entry')}。"
        f"来源 mine_struct_mass_round1；静态成分幸存者偏差。"
    )


def _insert_mongo(candidates: List[dict], summaries: Dict[str, dict], params_map: Dict[str, dict], mine_map: Dict[str, dict]) -> None:
    targets, client = _mongo_targets()
    new_ids = [c["factor_id"] for c in candidates]
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

    cand_by_id = {c["factor_id"]: c for c in candidates}
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")

    for dbn, planned in plans.items():
        db = client[dbn]
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
                    "source": f"mine_struct_mass_round1/{c['univ']}",
                    "cfg_id": c["cfg_id"],
                    "family": c["family"],
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


def _verify_arts(factor_id: str) -> None:
    data = ROOT / "data" / "factors"
    legs = data / factor_id / "trade_legs.parquet"
    print(f"[art] {'YES' if legs.exists() else 'NO '} {factor_id}/trade_legs.parquet", flush=True)
    if not legs.exists():
        raise SystemExit(f"missing legs for {factor_id}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16, help="入库条数目标（10–20）")
    ap.add_argument("--min-tw", type=float, default=-0.15, help="最低 tw_score")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    n = max(10, min(20, int(args.n)))
    candidates = _pick_candidates(n, float(args.min_tw))
    print(f"[pick] n={len(candidates)} families={sorted({c['family'] for c in candidates})}", flush=True)
    for i, c in enumerate(candidates, 1):
        m = c["mine_row"]
        print(
            f"  {i:02d}. {c['univ']}/{c['cfg_id']} -> {c['factor_id']} "
            f"tw={m.get('tw_score')} r2y={m.get('recent2y_sharpe')} legs={m.get('n_legs_accepted')}",
            flush=True,
        )
    if len(candidates) < 10:
        raise SystemExit(f"ABORT: only picked {len(candidates)} < 10; mining quality too weak?")

    if args.dry_run:
        print("[dry-run] stop before backtest/insert", flush=True)
        return

    params_map: Dict[str, dict] = {}
    mine_map: Dict[str, dict] = {}
    for c in candidates:
        row = _load_mine_row(c["univ"], c["cfg_id"])
        params = deepcopy(row["params"])
        params["request_interval_sec"] = 0.35
        params["price_end"] = params.get("price_end") or "2026-07-30"
        params["exclude_st"] = True
        params["universe"] = c["univ"]
        params["bench_code"] = BENCH.get(c["univ"], "sh.000300")
        params_map[c["factor_id"]] = params
        mine_map[c["factor_id"]] = row
        _register(c, params)

    targets, client = _mongo_targets()
    new_ids = [c["factor_id"] for c in candidates]
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

    panels: Dict[str, Dict[str, Any]] = {}
    for univ in sorted({c["univ"] for c in candidates}):
        group = [c for c in candidates if c["univ"] == univ]
        base_params = dict(params_map[group[0]["factor_id"]])
        print(f"[panel] preparing {univ} ...", flush=True)
        panels[univ] = prepare_shared_panel(
            base_params,
            need_profit=any(c["need_profit"] for c in group),
            need_growth=any(c["need_growth"] for c in group),
            need_balance=any(c["need_balance"] for c in group),
            need_fin_db=any(c["need_fin_db"] for c in group),
            limit=0,
        )
        print(f"[panel] {univ} n={len(panels[univ])}", flush=True)

    summaries: Dict[str, dict] = {}
    for c in candidates:
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
        print(
            f"[bt] {fid} ret={summary.get('total_return')} sharpe={summary.get('sharpe')}",
            flush=True,
        )
        _verify_arts(fid)

    _insert_mongo(candidates, summaries, params_map, mine_map)

    report = []
    targets2, client2 = _mongo_targets()
    docs = _ui_docs(client2[settings.MONGO_DB])
    for c in candidates:
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
                "family": c["family"],
                "mine_tw": m.get("tw_score"),
                "mine_full_sh": m.get("sharpe"),
                "mine_r2y_sh": m.get("recent2y_sharpe"),
                "mine_r2y_ret": m.get("recent2y_return"),
                "bt_sharpe": s.get("sharpe"),
                "bt_total_return": s.get("total_return"),
                "bt_n_legs": s.get("n_legs_accepted"),
            }
        )
    out = ROOT / "data" / "factors" / "fill_struct_mass_round1.json"
    out.write_text(
        json.dumps(
            {"asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "report": report},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("======== REPORT ========", flush=True)
    for r in report:
        print(
            f"#{r['ui']} {r['factor_id']} | {r['univ']}/{r['cfg_id']} | "
            f"tw≈{r['mine_tw']} r2y_sh≈{r['mine_r2y_sh']} | bt_sh={r['bt_sharpe']}",
            flush=True,
        )
    print(f"[ok] -> {out}", flush=True)

    summary_md = MINE_ROOT / "SUMMARY.md"
    if summary_md.exists():
        extra = [
            "",
            f"## 本轮已入库（目标 ≥#{MIN_UI}；不覆盖 #166–#203）",
            "",
            "| UI | univ | family | cfg / factor_id | tw | r2y_sh | bt_sh |",
            "|----|------|--------|-----------------|----|--------|-------|",
        ]
        for r in report:
            tw = r["mine_tw"]
            r2 = r["mine_r2y_sh"]
            tw_s = f"{tw:.3f}" if isinstance(tw, (int, float)) else str(tw)
            r2_s = f"{r2:.3f}" if isinstance(r2, (int, float)) else str(r2)
            extra.append(
                f"| {r['ui']} | {r['univ']} | {r['family']} | `{r['cfg_id']}` → `{r['factor_id']}` | "
                f"{tw_s} | {r2_s} | {r['bt_sharpe']} |"
            )
        text = summary_md.read_text(encoding="utf-8")
        if "## 本轮已入库" not in text:
            summary_md.write_text(text.rstrip() + "\n" + "\n".join(extra) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
