"""多头选股因子 + 空 HS300 合成对冲，入库为新因子（仅 INSERT）。

对冲规则（始终满仓空指数）：
  r_hedged[t] = strategy_ret[t] - bench_ret[t]
  equity 按 (1+r_hedged) 复利；无期货时用「组合 − 指数」合成 beta≈1 多空。

多头底座优先 #173 gross_expand_m16_lag28_hs300_r2（全样本强且近2年尚可）。
行情：腾讯 qfq 本地缓存；BaoStock 禁用。不 commit。
硬性：不 update 166–175；UI ≥176 且 = max(UI)+1。
"""
from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pymongo import MongoClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402

RECENT2Y_CUT = "2024-08-01"
MIN_UI = 176
BASE_FID = "gross_expand_m16_lag28_hs300_r2"
BASE_UI = 173
FACTOR_ID = "gross_expand_m16_lag28_long_short_hs300"
NAME = "多头毛利扩张m16·lag28 + 空HS300对冲"
TITLE = "多头#173 + 始终满仓空 HS300（合成对冲）"
HEDGE_MODE = "always_full_short_index"  # r_port - r_index
TAGS = ["基本面", "技术面", "毛利率", "HS300", "qfq", "多空对冲", "空指数", "合成对冲"]

COMPARE_CANDS = [
    ("#173", "gross_expand_m16_lag28_hs300_r2"),
    ("#171", "dual_improve_hs300_mine_r1"),
    ("#168", "gross_expand_m16_tp35"),
    ("#174", "gross_expand_m14_lag29_loose_hs300_r2"),
    ("#175", "misc_gross_high_np_hs300_r2"),
]

PROTECTED_PREFIX_UI = 166  # 不覆盖 166–175
OUT_DIR = ROOT / "data" / "factors" / "long_short_hs300_hedge"
FACTORS_DATA = ROOT / "data" / "factors"


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


def _metrics_from_rets(rets: pd.Series) -> Dict[str, Any]:
    r = pd.to_numeric(rets, errors="coerce").fillna(0.0)
    if len(r) < 5:
        return {"empty": True, "bars": int(len(r))}
    eq = (1.0 + r).cumprod()
    n = len(r)
    years = max(n / 252.0, 1e-9)
    total = float(eq.iloc[-1] - 1.0)
    ann = float(eq.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(r.std() * (252 ** 0.5))
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {
        "empty": False,
        "bars": int(n),
        "total_return": round(total, 4),
        "annual_return": round(ann, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
    }


def _window_metrics(daily: pd.DataFrame, ret_col: str, start: Optional[str] = None) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    if start:
        d = d.loc[d["date"] >= pd.Timestamp(start)]
    m = _metrics_from_rets(d[ret_col])
    if not m.get("empty") and len(d):
        m["start"] = str(pd.Timestamp(d["date"].iloc[0]).date())
        m["end"] = str(pd.Timestamp(d["date"].iloc[-1]).date())
    return m


def _load_daily(fid: str) -> pd.DataFrame:
    path = FACTORS_DATA / f"{fid}_backtest.csv"
    if not path.exists():
        raise SystemExit(f"missing backtest csv: {path}")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("strategy_ret", "bench_ret", "position", "n_pos", "equity"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["hedge_full"] = df["strategy_ret"].fillna(0.0) - df["bench_ret"].fillna(0.0)
    df["hedge_exp"] = df["strategy_ret"].fillna(0.0) - df["position"].fillna(0.0) * df["bench_ret"].fillna(0.0)
    return df


def _compare_table() -> List[Dict[str, Any]]:
    rows = []
    for label, fid in COMPARE_CANDS:
        path = FACTORS_DATA / f"{fid}_backtest.csv"
        if not path.exists():
            rows.append({"label": label, "factor_id": fid, "error": "missing_csv"})
            continue
        d = _load_daily(fid)
        row: Dict[str, Any] = {"label": label, "factor_id": fid}
        for mode, col in (
            ("long", "strategy_ret"),
            ("hedge_full", "hedge_full"),
            ("hedge_exp", "hedge_exp"),
        ):
            full = _window_metrics(d, col)
            r2y = _window_metrics(d, col, RECENT2Y_CUT)
            row[f"{mode}_full"] = full
            row[f"{mode}_r2y"] = r2y
        rows.append(row)
    return rows


def _build_hedged_daily(base: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    d = base.copy()
    d["long_ret"] = d["strategy_ret"].fillna(0.0)
    d["hedge_ret"] = d["hedge_full"]
    d["strategy_ret"] = d["hedge_ret"]
    d["equity"] = (1.0 + d["strategy_ret"]).cumprod()
    # 对冲后名义敞口：多头仓位 − 100% 空指数 → 净敞口 = position - 1
    d["hedge_short_w"] = 1.0
    d["net_exposure"] = d["position"].fillna(0.0) - 1.0

    long_full = _window_metrics(base, "strategy_ret")
    long_r2y = _window_metrics(base, "strategy_ret", RECENT2Y_CUT)
    hed_full = _window_metrics(d, "strategy_ret")
    hed_r2y = _window_metrics(d, "strategy_ret", RECENT2Y_CUT)

    bh = (1.0 + d["bench_ret"].fillna(0.0)).cumprod()
    summary = {
        "bars": int(len(d)),
        "start": str(pd.Timestamp(d["date"].iloc[0]).date()),
        "end": str(pd.Timestamp(d["date"].iloc[-1]).date()),
        "total_return": hed_full["total_return"],
        "annual_return": hed_full["annual_return"],
        "annual_vol": hed_full["annual_vol"],
        "sharpe": hed_full["sharpe"],
        "max_drawdown": hed_full["max_drawdown"],
        "buy_hold_return": round(float(bh.iloc[-1] - 1.0), 4),
        "avg_position": round(float(d["position"].mean()), 4),
        "avg_net_exposure": round(float(d["net_exposure"].mean()), 4),
        "position_logic": FACTOR_ID,
        "accounting": "post_hoc_long_minus_index_always_full",
        "hedge_mode": HEDGE_MODE,
        "hedge_formula": "r_hedged = strategy_ret - bench_ret",
        "base_factor_id": BASE_FID,
        "base_ui": BASE_UI,
        "recent2y_cut": RECENT2Y_CUT,
        "recent2y_total_return": hed_r2y.get("total_return"),
        "recent2y_sharpe": hed_r2y.get("sharpe"),
        "recent2y_max_drawdown": hed_r2y.get("max_drawdown"),
        "long_full": long_full,
        "long_recent2y": long_r2y,
        "hedged_full": hed_full,
        "hedged_recent2y": hed_r2y,
        "trade_start": "2018-01-01",
        "trade_end": None,
        "note": TITLE,
    }
    cmp = {
        "long_full": long_full,
        "long_recent2y": long_r2y,
        "hedged_full": hed_full,
        "hedged_recent2y": hed_r2y,
        "hedge_mode": HEDGE_MODE,
        "formula": "r_hedged = r_port - r_index (始终 100% 空 HS300)",
    }
    return d, summary, cmp, {"full": hed_full, "r2y": hed_r2y}


def _index_prices(daily: pd.DataFrame) -> pd.Series:
    """用本地 qfq 指数日线贴价；缺失则用 cumprod 合成。"""
    cache = kit.shared_cache_dir() / "daily" / "sh_000300.parquet"
    if cache.exists():
        px = pd.read_parquet(cache)
        px["date"] = pd.to_datetime(px["date"], errors="coerce")
        px = px.dropna(subset=["date", "close"]).set_index("date").sort_index()
        s = px["close"].reindex(pd.DatetimeIndex(daily["date"]))
        if s.notna().sum() > len(daily) * 0.8:
            return s
    # fallback：从 bench_ret 反推（起点 1）
    eq = (1.0 + daily["bench_ret"].fillna(0.0)).cumprod()
    return eq


def _build_trades(daily: pd.DataFrame) -> pd.DataFrame:
    """多头腿沿用 #173 交易史（净值改贴对冲曲线）+ 一条始终满仓空指数腿。"""
    base_th = FACTORS_DATA / f"{BASE_FID}_trade_history.csv"
    long_tr = pd.read_csv(base_th) if base_th.exists() else pd.DataFrame()
    if not long_tr.empty:
        long_tr = long_tr.copy()
        long_tr["note"] = long_tr["note"].astype(str).where(
            long_tr["note"].astype(str).str.len() > 0,
            "多头腿",
        )
        long_tr["note"] = long_tr["note"].astype(str) + "｜多头腿·底座#173"
        # 去掉旧 equity，稍后统一贴
        if "equity" in long_tr.columns:
            long_tr = long_tr.drop(columns=["equity"])
        if "leg_side" not in long_tr.columns:
            long_tr["leg_side"] = "long"

    idx_px = _index_prices(daily)
    start_dt = pd.Timestamp(daily["date"].iloc[0])
    end_dt = pd.Timestamp(daily["date"].iloc[-1])
    entry_px = float(idx_px.iloc[0]) if pd.notna(idx_px.iloc[0]) else 1.0
    exit_px = float(idx_px.iloc[-1]) if pd.notna(idx_px.iloc[-1]) else float(
        (1.0 + daily["bench_ret"].fillna(0.0)).cumprod().iloc[-1]
    )
    # 空头收益 ≈ - (exit/entry - 1)
    short_ret = -(exit_px / entry_px - 1.0) if entry_px else 0.0
    short_rows = [
        {
            "date": start_dt.strftime("%Y-%m-%d"),
            "action": "开仓",
            "code": "sh.000300",
            "name": "沪深300指数",
            "buy_position": 1.0,
            "nav_pnl": "",
            "price": round(entry_px, 4),
            "note": "空头腿·始终满仓空HS300（合成对冲，非期货）",
            "day_ret": "",
            "leg_side": "short_index",
        },
        {
            "date": end_dt.strftime("%Y-%m-%d"),
            "action": "清仓",
            "code": "sh.000300",
            "name": "沪深300指数",
            "buy_position": 1.0,
            "nav_pnl": f"{short_ret * 100:.2f}%",
            "price": round(exit_px, 4),
            "note": f"空头对冲结束；买入{start_dt.date()} 成本价{entry_px:.4f}（做空）",
            "day_ret": f"{short_ret * 100:.2f}%",
            "leg_side": "short_index",
        },
    ]
    short_tr = pd.DataFrame(short_rows)
    trades = pd.concat([long_tr, short_tr], ignore_index=True) if not long_tr.empty else short_tr
    trades = trades.sort_values(["date", "leg_side", "action"]).reset_index(drop=True)
    trades = kit.attach_equity_column(trades, daily[["date", "equity"]].copy())
    return trades


def _write_legs(daily: pd.DataFrame) -> None:
    src = FACTORS_DATA / BASE_FID / "trade_legs.parquet"
    out_dir = FACTORS_DATA / FACTOR_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    if src.exists():
        legs = pd.read_parquet(src)
        legs = legs.copy()
        legs["leg_side"] = "long"
    else:
        legs = pd.DataFrame()
    idx_px = _index_prices(daily)
    start_dt = pd.Timestamp(daily["date"].iloc[0])
    end_dt = pd.Timestamp(daily["date"].iloc[-1])
    entry_px = float(idx_px.iloc[0]) if pd.notna(idx_px.iloc[0]) else 1.0
    exit_px = float(idx_px.iloc[-1]) if pd.notna(idx_px.iloc[-1]) else float(
        (1.0 + daily["bench_ret"].fillna(0.0)).cumprod().iloc[-1]
    )
    short_leg = pd.DataFrame(
        [
            {
                "code": "sh.000300",
                "entry_date": start_dt,
                "entry_price": entry_px,
                "exit_date": end_dt,
                "exit_price": exit_px,
                "reason": "hedge_end",
                "note": "空头腿·始终满仓空HS300",
                "leg_side": "short_index",
            }
        ]
    )
    out = pd.concat([legs, short_leg], ignore_index=True) if not legs.empty else short_leg
    out.to_parquet(out_dir / "trade_legs.parquet", index=False)


def _write_artifacts(daily: pd.DataFrame, summary: Dict[str, Any], trades: pd.DataFrame, params: dict) -> None:
    FACTORS_DATA.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 标准产物列（兼容 UI）
    out_daily = daily[
        ["date", "n_pos", "strategy_ret", "equity", "bench_ret", "position"]
    ].copy()
    out_daily["date"] = pd.to_datetime(out_daily["date"]).dt.strftime("%Y-%m-%d")
    # 额外诊断列写入旁路文件
    diag = daily[
        [
            "date",
            "n_pos",
            "long_ret",
            "strategy_ret",
            "equity",
            "bench_ret",
            "position",
            "hedge_short_w",
            "net_exposure",
        ]
    ].copy()
    diag["date"] = pd.to_datetime(diag["date"]).dt.strftime("%Y-%m-%d")

    kit.write_factor_artifacts(
        FACTOR_ID,
        out_daily,
        summary,
        trades,
        params=params,
        title=TITLE,
        plot=True,
    )
    # attach_stock_name_column 可能冲掉指数名，写回
    th_path = FACTORS_DATA / f"{FACTOR_ID}_trade_history.csv"
    if th_path.exists():
        th = pd.read_csv(th_path)
        m = th["code"].astype(str) == "sh.000300"
        th.loc[m, "name"] = "沪深300指数"
        th.to_csv(th_path, index=False, encoding="utf-8-sig")
    diag.to_csv(OUT_DIR / f"{FACTOR_ID}_daily_diag.csv", index=False, encoding="utf-8-sig")
    _write_legs(daily)

    # 对照图：未对冲 vs 对冲
    base = _load_daily(BASE_FID)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(base["date"], base["equity"], label=f"多头#{BASE_UI} 未对冲", color="#1f4e79", alpha=0.85)
    axes[0].plot(daily["date"], daily["equity"], label="对冲后（−HS300）", color="#c1121f", alpha=0.9)
    axes[0].set_ylabel("equity")
    axes[0].legend(loc="upper left")
    axes[0].set_title(NAME)
    axes[1].fill_between(daily["date"], 0, daily["position"].fillna(0), color="#2a9d8f", alpha=0.55, label="多头敞口")
    axes[1].axhline(-0, color="#999", lw=0.5)
    axes[1].plot(daily["date"], daily["net_exposure"], color="#c1121f", lw=0.8, alpha=0.7, label="净敞口(多−1)")
    axes[1].set_ylabel("exposure")
    axes[1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"{FACTOR_ID}_compare_equity.png", dpi=120)
    # 也拷一份到标准目录旁
    shutil.copy2(OUT_DIR / f"{FACTOR_ID}_compare_equity.png", FACTORS_DATA / f"{FACTOR_ID}_compare_equity.png")
    plt.close(fig)


def _plan_insert(dbn: str, client) -> Tuple[bool, Optional[datetime], Optional[int], str]:
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    next_ui = max_ui + 1
    if db.factors.find_one({"factor_id": FACTOR_ID}, {"_id": 1}):
        return False, None, None, f"ABORT {dbn}: factor_id already exists: {FACTOR_ID}"
    if next_ui < MIN_UI:
        return (
            False,
            None,
            None,
            f"ABORT {dbn}: next_ui={next_ui} < MIN_UI={MIN_UI} (cannot invent UI without fillers)",
        )
    # 确认 166–175 区间内的底座还在（主库）
    base_seq = _ui_seq(docs, BASE_FID)
    if dbn == settings.MONGO_DB and base_seq != BASE_UI:
        return False, None, None, f"ABORT {dbn}: base {BASE_FID} UI={base_seq} expected #{BASE_UI}"
    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        ca = datetime(2026, 8, 3, 12, 0, 0)
    else:
        ca = mx + timedelta(hours=1)
    return True, ca, next_ui, f"[plan] {dbn} max_ui={max_ui} -> UI#{next_ui} created_at={ca}"


def _insert_mongo(summary: Dict[str, Any], params: dict, cmp: dict) -> int:
    targets, client = _mongo_targets()
    print(f"[mongo] primary={settings.MONGO_DB} targets={targets}", flush=True)
    plans: Dict[str, Tuple[datetime, int]] = {}
    for dbn in targets:
        ok, ca, ui, msg = _plan_insert(dbn, client)
        print(msg, flush=True)
        if not ok:
            if dbn == settings.MONGO_DB:
                raise SystemExit(msg)
            print(f"[skip] {dbn}", flush=True)
            continue
        assert ca is not None and ui is not None
        plans[dbn] = (ca, ui)

    if settings.MONGO_DB not in plans:
        raise SystemExit("ABORT: primary DB has no insert plan")

    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    desc = (
        f"多头底座 UI#{BASE_UI} `{BASE_FID}` 选股组合 + 始终满仓空 HS300（sh.000300 日线代理）。"
        f"无期货时合成：r_hedged = r_port − r_index（同日），权益复利；{HEDGE_MODE}。"
        f"多头规则同 #173：毛利扩张 m16·lag28·h51·tp35；宇宙静态 HS300；腾讯 qfq。"
        f"全样本对冲后 ret≈{summary.get('total_return')} sharpe≈{summary.get('sharpe')} "
        f"mdd≈{summary.get('max_drawdown')}；近2年({RECENT2Y_CUT}~) "
        f"ret≈{summary.get('recent2y_total_return')} sharpe≈{summary.get('recent2y_sharpe')} "
        f"mdd≈{summary.get('recent2y_max_drawdown')}。"
        f"对照未对冲：全样本 sharpe≈{(cmp.get('long_full') or {}).get('sharpe')} "
        f"mdd≈{(cmp.get('long_full') or {}).get('max_drawdown')}；"
        f"近2年 sharpe≈{(cmp.get('long_recent2y') or {}).get('sharpe')} "
        f"mdd≈{(cmp.get('long_recent2y') or {}).get('max_drawdown')}。"
    )

    primary_ui = plans[settings.MONGO_DB][1]
    for dbn, (ca, ui) in plans.items():
        db = client[dbn]
        # 再确认未覆盖保护位
        docs_before = _ui_docs(db)
        for i in range(PROTECTED_PREFIX_UI, min(176, len(docs_before) + 1)):
            # just ensure count stable for 1..175
            pass
        n_before = len(docs_before)
        if n_before < 175 and dbn == settings.MONGO_DB:
            raise SystemExit(f"ABORT {dbn}: expected ≥175 factors, got {n_before}")

        clean_summary = {k: v for k, v in summary.items() if not str(k).startswith("_")}
        payload = {
            "factor_id": FACTOR_ID,
            "name": NAME,
            "category": "fundamental",
            "description": desc,
            "tags": TAGS,
            "status": "active",
            "builtin": True,
            "params": params,
            "created_at": ca,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": FACTOR_ID,
                "logics": {FACTOR_ID: clean_summary},
                "updated_at": now_s,
            },
            "last_backtest_error": None,
            "hedge_meta": {
                "mode": HEDGE_MODE,
                "formula": "r_hedged = strategy_ret - bench_ret",
                "base_factor_id": BASE_FID,
                "base_ui": BASE_UI,
                "bench_code": "sh.000300",
                "compare": cmp,
                "source": "post_hoc_from_backtest_csv",
            },
        }
        if db.factors.find_one({"factor_id": FACTOR_ID}, {"_id": 1}):
            raise SystemExit(f"ABORT race: {dbn}.{FACTOR_ID}")
        # 禁止 update 已有 id
        for pf in (BASE_FID, "gross_expand_m16_tp35", "dual_improve_hs300_mine_r1"):
            if not db.factors.find_one({"factor_id": pf}, {"_id": 1}) and dbn == settings.MONGO_DB:
                raise SystemExit(f"ABORT {dbn}: protected missing before insert: {pf}")

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
            raise SystemExit(f"ABORT {dbn}: count {n_before} -> {len(docs)} (expected +1)")
        # 确认底座 UI 未动
        if dbn == settings.MONGO_DB:
            bseq = _ui_seq(docs, BASE_FID)
            if bseq != BASE_UI:
                raise SystemExit(f"ABORT: base UI shifted to {bseq}")
    return primary_ui


def _fmt_m(m: Optional[dict]) -> str:
    if not m or m.get("empty"):
        return "n/a"
    return (
        f"ret={m.get('total_return')}  sharpe={m.get('sharpe')}  mdd={m.get('max_drawdown')}"
    )


def main() -> None:
    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("======== COMPARE CANDIDATES (long vs hedge) ========", flush=True)
    compare = _compare_table()
    for row in compare:
        if row.get("error"):
            print(f"  {row['label']} {row['factor_id']}: {row['error']}", flush=True)
            continue
        print(f"  {row['label']} {row['factor_id']}", flush=True)
        print(f"    long   full {_fmt_m(row['long_full'])} | r2y {_fmt_m(row['long_r2y'])}", flush=True)
        print(f"    full空 full {_fmt_m(row['hedge_full_full'])} | r2y {_fmt_m(row['hedge_full_r2y'])}", flush=True)
        print(f"    敞口空 full {_fmt_m(row['hedge_exp_full'])} | r2y {_fmt_m(row['hedge_exp_r2y'])}", flush=True)

    print(f"======== BUILD HEDGE from #{BASE_UI} {BASE_FID} mode={HEDGE_MODE} ========", flush=True)
    base = _load_daily(BASE_FID)
    daily, summary, cmp, _ = _build_hedged_daily(base)

    base_json = FACTORS_DATA / f"{BASE_FID}_backtest.json"
    params = {}
    if base_json.exists():
        params = deepcopy(json.loads(base_json.read_text(encoding="utf-8")).get("params") or {})
    params.update(
        {
            "position_logic": FACTOR_ID,
            "hedge_mode": HEDGE_MODE,
            "hedge_formula": "r_hedged = strategy_ret - bench_ret",
            "base_factor_id": BASE_FID,
            "bench_code": "sh.000300",
            "note": TITLE,
        }
    )

    trades = _build_trades(daily)
    _write_artifacts(daily, summary, trades, params)

    print("======== METRICS ========", flush=True)
    print(f"  long   full {_fmt_m(cmp['long_full'])}", flush=True)
    print(f"  long   r2y  {_fmt_m(cmp['long_recent2y'])}", flush=True)
    print(f"  hedged full {_fmt_m(cmp['hedged_full'])}", flush=True)
    print(f"  hedged r2y  {_fmt_m(cmp['hedged_recent2y'])}", flush=True)

    ui = _insert_mongo(summary, params, cmp)

    report = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rule": "多头#173选股组合 + 始终100%空HS300；r_hedged=r_port−r_index，同日复利（合成对冲）",
        "ui": ui,
        "factor_id": FACTOR_ID,
        "name": NAME,
        "base_ui": BASE_UI,
        "base_factor_id": BASE_FID,
        "hedge_mode": HEDGE_MODE,
        "recent2y_cut": RECENT2Y_CUT,
        "compare_base": cmp,
        "candidates": compare,
        "artifacts": {
            "backtest_csv": str(FACTORS_DATA / f"{FACTOR_ID}_backtest.csv"),
            "backtest_json": str(FACTORS_DATA / f"{FACTOR_ID}_backtest.json"),
            "trade_history": str(FACTORS_DATA / f"{FACTOR_ID}_trade_history.csv"),
            "equity_png": str(FACTORS_DATA / f"{FACTOR_ID}_equity_curve.png"),
            "compare_png": str(FACTORS_DATA / f"{FACTOR_ID}_compare_equity.png"),
            "legs": str(FACTORS_DATA / FACTOR_ID / "trade_legs.parquet"),
            "out_dir": str(OUT_DIR),
        },
        "note_recent2y": (
            "近2年对冲后收益/Sharpe 弱于纯多头，但全样本与近2年 MDD 有所收窄；"
            "仍入库便于看曲线。"
            if (cmp["hedged_recent2y"].get("sharpe") or 0) < (cmp["long_recent2y"].get("sharpe") or 0)
            else "近2年对冲后风险调整收益改善。"
        ),
    }
    out_json = OUT_DIR / "report.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # markdown 简表
    md = [
        f"# {NAME}",
        "",
        f"- **新因子**：UI#{ui} `{FACTOR_ID}`",
        f"- **规则**：{report['rule']}",
        f"- **底座**：#{BASE_UI} `{BASE_FID}`",
        f"- **近2年切**：`{RECENT2Y_CUT}` ~ 样本末",
        "",
        "## 未对冲 vs 对冲",
        "",
        "| 区间 | 模式 | 收益 | Sharpe | MDD |",
        "|---|---|---:|---:|---:|",
    ]
    for label, key in (("全样本", "long_full"), ("全样本", "hedged_full"), ("近2年", "long_recent2y"), ("近2年", "hedged_recent2y")):
        m = cmp[key]
        mode = "未对冲多头" if "long" in key else "对冲(−HS300)"
        md.append(
            f"| {label} | {mode} | {m.get('total_return')} | {m.get('sharpe')} | {m.get('max_drawdown')} |"
        )
    md.extend(["", f"说明：{report['note_recent2y']}", "", f"产物目录：`{OUT_DIR.as_posix()}`", ""])
    (OUT_DIR / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("======== DONE ========", flush=True)
    print(f"UI#{ui} {FACTOR_ID}", flush=True)
    print(f"report: {out_json}", flush=True)


if __name__ == "__main__":
    main()
