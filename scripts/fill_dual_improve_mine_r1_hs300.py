"""把 mine round1 HS300 Top dual_improve 写入 lahm 为新因子（永远 max(UI)+1，不填空洞）。

信号：signal_dual_improve_breakout（FACTOR_IMPL 已有 dual_improve_breakout 可跑）
宇宙：静态 hs300；行情：腾讯 qfq（_shared/daily，BaoStock 禁用）
不碰 168/186。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import run_factor_pipeline  # noqa: E402

FACTOR_ID = "dual_improve_hs300_mine_r1"
TITLE = "双改善突破(HS300·mine R1)"
NAME = "双改善突破(毛利+净利·HS300·新qfq·mine R1)"
DESC = (
    "毛利+净利双改善突破（mine_csi300_500_1000_round1 / hs300 Top："
    "dual_improve__base_lag28_h50_tp35）。"
    "参数：margin_improve=0.005，margin_min=0.15，np_improve=0.004，"
    "财务热窗28日；入场=60日高+MA20；持有50日；止损12%；止盈35%；最多8仓。"
    "宇宙=静态沪深300；行情=腾讯前复权新 qfq（_shared/daily）。"
    "信号实现：signal_dual_improve_breakout。"
)
TAGS = ["基本面", "技术面", "双改善", "HS300", "qfq", "新日线", "mine_round1"]

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
    "margin_improve": 0.005,
    "margin_min": 0.15,
    "np_improve": 0.004,
    "funda_lag": 28,
    "break_days": 60,
    "hold_days": 50,
    "stop_loss": 0.12,
    "take_profit": 0.35,
    "position_logic": FACTOR_ID,
    "note": "mine round1 hs300 Top dual_improve__base_lag28_h50_tp35 / 新腾讯 qfq",
}

# 写入时按目标库当前 max(created_at)+1h 挂到末尾；禁止写死旧号（会在 RETIRED 漂移后占到 #166）
CREATED_AT = None  # 运行时按库计算
MINE_TARGET = {"sharpe": 0.9322, "total_return": 10.8255}


def _max_created_at(db, exclude=None):
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
    return mx


def _next_created_at(db, exclude=None):
    """永远 max(existing created_at)+1h，不填空洞。"""
    from datetime import timedelta

    mx = _max_created_at(db, exclude=exclude)
    if mx is None:
        return datetime(2026, 6, 23, 11, 0, 0)
    if not isinstance(mx, datetime):
        return datetime.now()
    return mx + timedelta(hours=1)


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


def _assert_safe(client, targets: list[str]) -> None:
    for dbn in targets:
        for forbidden in ("gross_expand_m16_tp35", "gross_expand_m16_tp35_hs300_qfq"):
            # 仅确认存在性打印；本脚本绝不 update/delete 它们
            exists = client[dbn].factors.find_one({"factor_id": forbidden}, {"factor_id": 1})
            print(f"[safe] {dbn} keep {forbidden} exists={bool(exists)}", flush=True)


def _write_mongo(summary: dict) -> None:
    targets, client = _mongo_targets()
    _assert_safe(client, targets)
    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    summary_dst = dict(summary)
    summary_dst["position_logic"] = FACTOR_ID
    for dbn in targets:
        # 每个库独立：max(现有序号时间)+1h，绝不填空洞/占旧号
        created_at = _next_created_at(client[dbn], exclude={FACTOR_ID})
        payload = {
            "factor_id": FACTOR_ID,
            "name": NAME,
            "category": "fundamental",
            "description": DESC,
            "tags": TAGS,
            "status": "active",
            "builtin": True,
            "params": dict(PARAMS),
            "created_at": created_at,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": FACTOR_ID,
                "logics": {FACTOR_ID: summary_dst},
                "updated_at": now_s,
            },
            "last_backtest_error": summary_dst.get("error"),
        }
        # 禁止误写 168/186
        r = client[dbn].factors.update_one(
            {"factor_id": FACTOR_ID},
            {"$set": payload},
            upsert=True,
        )
        docs = list(client[dbn].factors.find({}, {"factor_id": 1, "created_at": 1}))

        def _key(x):
            ta = x.get("created_at") or ""
            if hasattr(ta, "isoformat"):
                ta = ta.isoformat(sep=" ")
            return (str(ta), str(x.get("factor_id") or ""))

        docs = sorted(docs, key=_key)
        seq = next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == FACTOR_ID), None)
        print(
            f"[mongo] upsert {dbn}.{FACTOR_ID} matched={r.matched_count} "
            f"mod={r.modified_count} upserted={r.upserted_id} "
            f"created_at={created_at} UI#{seq}/{len(docs)}",
            flush=True,
        )


def _verify() -> None:
    targets, client = _mongo_targets()
    data = ROOT / "data" / "factors"
    arts = [
        f"{FACTOR_ID}_backtest.csv",
        f"{FACTOR_ID}_backtest.json",
        f"{FACTOR_ID}_trade_history.csv",
        f"{FACTOR_ID}_equity_curve.png",
    ]
    legs = data / FACTOR_ID / "trade_legs.parquet"
    for a in arts:
        p = data / a
        print(f"[art] {'YES' if p.exists() else 'NO '} {a} {p.stat().st_size if p.exists() else 0}", flush=True)
    print(f"[art] {'YES' if legs.exists() else 'NO '} trade_legs.parquet", flush=True)

    for dbn in targets:
        db = client[dbn]
        d = db.factors.find_one({"factor_id": FACTOR_ID})
        d168 = db.factors.find_one({"factor_id": "gross_expand_m16_tp35"}, {"factor_id": 1, "name": 1})
        d186 = db.factors.find_one({"factor_id": "gross_expand_m16_tp35_hs300_qfq"}, {"factor_id": 1})
        docs = list(db.factors.find({}, {"factor_id": 1, "created_at": 1}))

        def _key(x):
            ta = x.get("created_at") or ""
            if hasattr(ta, "isoformat"):
                ta = ta.isoformat(sep=" ")
            return (str(ta), str(x.get("factor_id") or ""))

        docs = sorted(docs, key=_key)
        seq = next((i for i, x in enumerate(docs, 1) if x.get("factor_id") == FACTOR_ID), None)
        logics = ((d or {}).get("backtest_summary") or {}).get("logics") or {}
        s = logics.get(FACTOR_ID) or {}
        print(
            f"[verify] {dbn} n={len(docs)} UI#{seq} "
            f"ret={s.get('total_return')} sharpe={s.get('sharpe')} "
            f"168_ok={bool(d168)} 186_exists={bool(d186)}",
            flush=True,
        )


def main() -> None:
    # 确认信号可导入
    assert callable(sig.signal_dual_improve_breakout)
    from app.services.factors.factor_registry import FACTOR_IMPL

    assert "dual_improve_breakout" in FACTOR_IMPL
    print(
        f"[signal] dual_improve_breakout in FACTOR_IMPL; "
        f"fn={sig.signal_dual_improve_breakout.__name__}",
        flush=True,
    )

    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    cache = kit.shared_cache_dir()
    codes = kit.fetch_universe_codes("hs300", kit.RateLimiter(0.01), cache, force=False)
    print(f"[universe] hs300 codes={len(codes)}", flush=True)
    print(f"[params] {json.dumps(PARAMS, ensure_ascii=False)}", flush=True)

    summary = run_factor_pipeline(
        FACTOR_ID,
        TITLE,
        sig.signal_dual_improve_breakout,
        PARAMS,
        need_profit=True,
        need_growth=False,
        limit=0,
        start="2018-01-01",
    )

    ret = summary.get("total_return")
    sharpe = summary.get("sharpe")
    close = (
        isinstance(ret, (int, float))
        and isinstance(sharpe, (int, float))
        and abs(float(ret) - MINE_TARGET["total_return"]) < 0.05
        and abs(float(sharpe) - MINE_TARGET["sharpe"]) < 0.02
    )
    meta = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "mine_csi300_500_1000_round1/hs300 dual_improve__base_lag28_h50_tp35",
        "factor_id": FACTOR_ID,
        "ui_target": "max+1",
        "signal": "signal_dual_improve_breakout",
        "mine_target": MINE_TARGET,
        "reproduced_mine": close,
        "params": PARAMS,
        "summary": summary,
    }
    out = ROOT / "data" / "factors" / f"{FACTOR_ID}_fill171.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)

    if summary.get("error"):
        raise SystemExit(f"backtest error: {summary.get('error')}")

    _write_mongo(summary if isinstance(summary, dict) else {"error": str(summary)})
    _verify()
    print(f"[ok] fill -> {out}", flush=True)


if __name__ == "__main__":
    main()
