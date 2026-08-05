"""把 Round2 HS300 Top3 候选写入 lahm（仅 INSERT，序号从 173 起）。

来源：data/factors/mine_csi300_500_1000_round2/hs300/results.json
宇宙：静态 hs300；行情：腾讯 qfq（_shared/daily）；BaoStock 禁用。
硬性：不 update 任何已有 factor_id；不填空洞；UI 不得小于 173。
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
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

RESULTS = ROOT / "data" / "factors" / "mine_csi300_500_1000_round2" / "hs300" / "results.json"
MIN_UI = 173
PROTECTED = {
    "gross_expand_m16_tp35",
    "gross_expand_lag28_tp35",
    "dual_improve_hs300_mine_r1",
    "gross_expand_m16_tp35_hs300_qfq",
}

# (factor_id, cfg_id, name, title, signal_fn, mine_metrics_keys)
CANDIDATES: List[Dict[str, Any]] = [
    {
        "factor_id": "gross_expand_m16_lag28_hs300_r2",
        "cfg_id": "gross_expand__m16_lag28_h51_tp35",
        "name": "毛利扩张(m16·lag28·h51·tp35·HS300·mine R2时间加权)",
        "title": "毛利扩张 m16 lag28 h51 tp35 HS300 mine R2",
        "signal": sig.signal_gross_expand_break,
        "signal_name": "signal_gross_expand_break",
        "tags": ["基本面", "技术面", "毛利率", "HS300", "qfq", "mine_round2", "时间加权"],
    },
    {
        "factor_id": "gross_expand_m14_lag29_loose_hs300_r2",
        "cfg_id": "gross_expand__m14_lag29_loose",
        "name": "毛利扩张(m14·lag29·loose·HS300·mine R2时间加权)",
        "title": "毛利扩张 m14 lag29 loose HS300 mine R2",
        "signal": sig.signal_gross_expand_break,
        "signal_name": "signal_gross_expand_break",
        "tags": ["基本面", "技术面", "毛利率", "HS300", "qfq", "mine_round2", "时间加权"],
    },
    {
        "factor_id": "misc_gross_high_np_hs300_r2",
        "cfg_id": "misc__gross_high_np",
        "name": "高净利毛利扩张(misc·HS300·mine R2时间加权)",
        "title": "高净利毛利扩张 misc HS300 mine R2",
        "signal": sig.signal_gross_high_np_break,
        "signal_name": "signal_gross_high_np_break",
        "tags": ["基本面", "技术面", "毛利率", "净利率", "HS300", "qfq", "mine_round2", "时间加权"],
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


def _load_mine_row(cfg_id: str) -> dict:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    for r in data.get("all") or []:
        if r.get("cfg_id") == cfg_id:
            return r
    raise SystemExit(f"cfg_id not found in results.json: {cfg_id}")


def _desc(cfg_id: str, params: dict, mine: dict) -> str:
    return (
        f"mine_csi300_500_1000_round2 / hs300 `{cfg_id}`（时间加权 tw≈{mine.get('tw_score'):.3f}）。"
        f"参数：margin_improve={params.get('margin_improve')}，margin_min={params.get('margin_min')}，"
        f"np_min={params.get('np_min')}，财务热窗{params.get('funda_lag')}日；"
        f"入场={params.get('break_days')}日高+MA20；持有{params.get('hold_days')}日；"
        f"止损{float(params.get('stop_loss') or 0)*100:.0f}%；止盈{float(params.get('take_profit') or 0)*100:.0f}%；最多8仓。"
        f"宇宙=静态沪深300；行情=腾讯前复权 qfq（_shared/daily）。"
        f"mine 指标：full_sh≈{mine.get('sharpe')}，full_ret≈{mine.get('total_return')}，"
        f"r2y_sh≈{mine.get('recent2y_sharpe')}，r2y_ret≈{mine.get('recent2y_return')}，"
        f"legs≈{mine.get('n_legs_accepted')}。"
    )


def _plan_db(dbn: str, client, new_ids: List[str]) -> Tuple[bool, List[Tuple[str, datetime, int]], str]:
    """返回 (ok, [(factor_id, created_at, planned_ui), ...], message)。"""
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
            # 168 的 qfq 别名可能不在所有库；主保护项必须在
            if fid in ("gross_expand_m16_tp35", "gross_expand_lag28_tp35", "dual_improve_hs300_mine_r1"):
                return False, [], f"ABORT {dbn}: protected factor missing: {fid}"

    if start_ui != next_physical:
        # 想要的序号 > 物理下一号（库里因子偏少）→ 无法在不插空洞文档时达到 ≥173
        return (
            False,
            [],
            f"ABORT {dbn}: max_ui={max_ui} next_physical={next_physical} < MIN_UI={MIN_UI} "
            f"(cannot invent UI#{start_ui} without filler docs)",
        )

    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        base = datetime(2026, 6, 23, 14, 0, 0)
    else:
        base = mx + timedelta(hours=1)

    planned: List[Tuple[str, datetime, int]] = []
    for i, fid in enumerate(new_ids):
        ca = base + timedelta(hours=i)
        ui = start_ui + i
        # 撞号：该 UI 位已有别的 factor
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
            # 非主库可跳过；主库失败则整体 abort
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
                "description": _desc(c["cfg_id"], params, mine),
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
                    "source": "mine_csi300_500_1000_round2/hs300",
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
            # 只 INSERT；已存在则 abort（上面已检查，这里再防竞态）
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
            # 确认未动保护项
            for pf in ("gross_expand_m16_tp35", "gross_expand_lag28_tp35", "dual_improve_hs300_mine_r1"):
                if not db.factors.find_one({"factor_id": pf}, {"_id": 1}):
                    raise SystemExit(f"ABORT {dbn}: protected {pf} vanished after insert")


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


def main() -> None:
    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    # 写入前：打印序号计划
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

    # 加载 mine 参数
    params_map: Dict[str, dict] = {}
    mine_map: Dict[str, dict] = {}
    for c in CANDIDATES:
        row = _load_mine_row(c["cfg_id"])
        params = deepcopy(row["params"])
        params["request_interval_sec"] = 0.35
        params["price_end"] = params.get("price_end") or "2026-07-30"
        params_map[c["factor_id"]] = params
        mine_map[c["factor_id"]] = row
        print(
            f"[mine] {c['cfg_id']} -> {c['factor_id']} "
            f"tw={row.get('tw_score'):.3f} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe'):.3f} "
            f"params={json.dumps(params, ensure_ascii=False)}",
            flush=True,
        )

    # 共享 panel 跑三个回测
    base_params = dict(params_map[CANDIDATES[0]["factor_id"]])
    print("[panel] preparing shared hs300 panel...", flush=True)
    price_map = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=False,
        need_balance=False,
        need_fin_db=False,
        limit=0,
    )
    print(f"[panel] n={len(price_map)}", flush=True)

    summaries: Dict[str, dict] = {}
    for c in CANDIDATES:
        fid = c["factor_id"]
        print(f"======== BACKTEST {fid} ========", flush=True)
        summary = run_factor_pipeline(
            fid,
            c["title"],
            c["signal"],
            params_map[fid],
            need_profit=True,
            need_growth=False,
            limit=0,
            start="2018-01-01",
            price_map=price_map,
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

    # 汇总回报
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
                "mine_tw": m.get("tw_score"),
                "mine_full_sh": m.get("sharpe"),
                "mine_r2y_sh": m.get("recent2y_sharpe"),
                "bt_sharpe": s.get("sharpe"),
                "bt_total_return": s.get("total_return"),
            }
        )
    out = ROOT / "data" / "factors" / "fill_hs300_round2_top3.json"
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
            f"#{r['ui']} {r['factor_id']} | {r['name']} | "
            f"tw≈{r['mine_tw']:.3f} full_sh≈{r['mine_full_sh']} r2y_sh≈{r['mine_r2y_sh']:.3f} | "
            f"bt_sh={r['bt_sharpe']} bt_ret={r['bt_total_return']}",
            flush=True,
        )
    print(f"[ok] -> {out}", flush=True)


if __name__ == "__main__":
    main()
