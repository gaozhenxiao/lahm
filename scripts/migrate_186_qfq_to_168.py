"""把误写到 #186 的 qfq·HS300 回测迁到因子 #168，并还原 #186（删文档/占位/本地产物）。"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402

SRC_ID = "gross_expand_m16_tp35_hs300_qfq"
DST_ID = "gross_expand_m16_tp35"
DATA = ROOT / "data" / "factors"

PARAMS = {
    "universe": "hs300",
    "price_start": "2016-01-01",
    "price_end": "2026-07-30",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.006,
    "margin_min": 0.16,
    "np_min": 0.10,
    "funda_lag": 29,
    "break_days": 60,
    "hold_days": 51,
    "stop_loss": 0.12,
    "take_profit": 0.35,
    "position_logic": DST_ID,
    "note": "新腾讯 qfq 日线 / 静态 HS300；wave84 gross_expand_m16 同参",
}

DESC = (
    "毛利率扩张突破（wave84 同参）：毛利≥16%；毛利环比升≥0.60%；净利率≥10%；"
    "财务热窗29日；入场=60日高+MA20；持有51日；止损12%；止盈35%。"
    "宇宙=静态沪深300；行情=腾讯前复权新 qfq 日线（_shared/daily，BaoStock 黑名单）。"
)

NAME = "毛利率扩张(新qfq·HS300·m16)"
TAGS = ["基本面", "技术面", "毛利率", "HS300", "qfq", "新日线", "wave84"]


def _load_summary() -> dict:
    fill = DATA / f"{SRC_ID}_fill186.json"
    bt = DATA / f"{SRC_ID}_backtest.json"
    if fill.exists():
        payload = json.loads(fill.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        if summary and "error" not in summary:
            return summary
    if bt.exists():
        payload = json.loads(bt.read_text(encoding="utf-8"))
        results = payload.get("results") or {}
        if SRC_ID in results:
            return results[SRC_ID]
        if results:
            return next(iter(results.values()))
    raise FileNotFoundError(f"no usable summary under {SRC_ID}")


def _migrate_local(summary: dict) -> None:
    dst_dir = DATA / DST_ID
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_legs = DATA / SRC_ID / "trade_legs.parquet"
    if src_legs.exists():
        shutil.copy2(src_legs, dst_dir / "trade_legs.parquet")
        print(f"[local] legs -> {dst_dir / 'trade_legs.parquet'}", flush=True)

    mapping = {
        f"{SRC_ID}_backtest.csv": f"{DST_ID}_backtest.csv",
        f"{SRC_ID}_trade_history.csv": f"{DST_ID}_trade_history.csv",
        f"{SRC_ID}_equity_curve.png": f"{DST_ID}_equity_curve.png",
    }
    for src_name, dst_name in mapping.items():
        src = DATA / src_name
        if src.exists():
            shutil.copy2(src, DATA / dst_name)
            print(f"[local] copy {src_name} -> {dst_name}", flush=True)

    summary_dst = dict(summary)
    summary_dst["position_logic"] = DST_ID
    bt_payload = {
        "params": dict(PARAMS),
        "results": {DST_ID: summary_dst},
        "notes": [
            "新腾讯 qfq 日线 / 静态 HS300；wave84 gross_expand_m16 同参（自误写 #186 迁移）"
        ],
    }
    bt_path = DATA / f"{DST_ID}_backtest.json"
    bt_path.write_text(json.dumps(bt_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[local] wrote {bt_path.name}", flush=True)

    meta_path = DATA / f"{DST_ID}_qfq_hs300_migrate.json"
    meta_path.write_text(
        json.dumps(
            {
                "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "from_factor_id": SRC_ID,
                "to_factor_id": DST_ID,
                "params": PARAMS,
                "summary": summary_dst,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _purge_186_local() -> None:
    # 仅删 #186 正式产物，保留 *_rerun* / restore 实验
    victims = [
        DATA / SRC_ID,
        DATA / f"{SRC_ID}_backtest.csv",
        DATA / f"{SRC_ID}_backtest.json",
        DATA / f"{SRC_ID}_trade_history.csv",
        DATA / f"{SRC_ID}_equity_curve.png",
        DATA / f"{SRC_ID}_fill186.json",
    ]
    for p in victims:
        if not p.exists():
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"[purge] {p}", flush=True)


def _mongo_targets() -> list[str]:
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


def _update_mongo_168(summary: dict) -> None:
    targets, client = _mongo_targets()
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    summary_dst = dict(summary)
    summary_dst["position_logic"] = DST_ID
    payload = {
        "name": NAME,
        "description": DESC,
        "tags": TAGS,
        "params": PARAMS,
        "updated_at": now,
        "backtest_summary": {
            "available": True,
            "primary_logic": DST_ID,
            "logics": {DST_ID: summary_dst},
            "updated_at": now_s,
        },
        "last_backtest_error": summary_dst.get("error"),
    }
    for dbn in targets:
        r = client[dbn].factors.update_one({"factor_id": DST_ID}, {"$set": payload}, upsert=False)
        print(f"[mongo] update {dbn}.{DST_ID} matched={r.matched_count} mod={r.modified_count}", flush=True)


def _delete_mongo_186() -> None:
    targets, client = _mongo_targets()
    delete_ids = [SRC_ID] + [f"_gen_pad_{i}" for i in range(171, 186)]
    for dbn in targets:
        r = client[dbn].factors.delete_many({"factor_id": {"$in": delete_ids}})
        print(f"[mongo] delete {dbn} count={r.deleted_count} ids={len(delete_ids)}", flush=True)


def _verify() -> None:
    targets, client = _mongo_targets()
    for dbn in targets:
        db = client[dbn]
        d168 = db.factors.find_one({"factor_id": DST_ID})
        d186 = db.factors.find_one({"factor_id": SRC_ID})
        pads = list(db.factors.find({"tags": "gen_seq_pad"}, {"factor_id": 1}))
        n = db.factors.count_documents({})
        logics = ((d168 or {}).get("backtest_summary") or {}).get("logics") or {}
        s = logics.get(DST_ID) or {}
        print(
            f"[verify] {dbn} count={n} "
            f"168_ret={s.get('total_return')} 168_sharpe={s.get('sharpe')} "
            f"186_exists={bool(d186)} pads={len(pads)}",
            flush=True,
        )
        # gen_seq of 168
        docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))

        def _key(d):
            ta = d.get("created_at") or ""
            if hasattr(ta, "isoformat"):
                ta = ta.isoformat(sep=" ")
            return (str(ta), str(d.get("factor_id") or ""))

        docs = sorted(docs, key=_key)
        for i, d in enumerate(docs, 1):
            if d.get("factor_id") == DST_ID:
                print(f"[verify] {dbn} {DST_ID} gen_seq=#{i}", flush=True)
                break
        else:
            print(f"[verify] {dbn} {DST_ID} NOT FOUND", flush=True)

    bt = DATA / f"{DST_ID}_backtest.json"
    print(f"[verify] local {bt.name} exists={bt.exists()}", flush=True)
    print(f"[verify] local {SRC_ID}_backtest.json exists={(DATA / f'{SRC_ID}_backtest.json').exists()}", flush=True)


def main() -> None:
    summary = _load_summary()
    print(f"[summary] ret={summary.get('total_return')} sharpe={summary.get('sharpe')}", flush=True)
    _migrate_local(summary)
    _update_mongo_168(summary)
    _delete_mongo_186()
    _purge_186_local()
    _verify()


if __name__ == "__main__":
    main()
