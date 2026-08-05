"""#173 集中度上限 + 移动止盈 对照实验（应对 2026-07）。

规则（相对基线 #173 gross_expand_m16_lag28_hs300_r2）：
1. 单票上限 max_name_weight=0.25（持仓不足 4 只时不满仓）
2. 行业上限 max_industry_names=2（新浪行业；缺省用市场前缀近似）
3. 移动止盈：浮盈≥18% 后启用峰值回撤 9% 止盈；与原 tp=35% / sl=12% / hold=51 叠加

有改善则 INSERT 新因子 UI≥184；可选再挂「规则+空HS300」。
不 commit；BaoStock 禁用；腾讯 qfq 本地缓存。
"""
from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from pymongo import MongoClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    build_legs_from_entries,
    legs_to_trade_history,
)

BASE_FID = "gross_expand_m16_lag28_hs300_r2"
BASE_UI = 173
MIN_UI = 184
RECENT2Y_CUT = "2024-08-01"
JULY_START = "2026-07-01"
JULY_END = "2026-07-31"
TRADE_START = "2018-01-01"

FACTOR_ID = "gross_expand_m16_lag28_hs300_conc_trail"
NAME = "#173 + 集中度/移动止盈（单票≤25%·行业≤2·浮盈18%后回撤9%）"
TITLE = "毛利扩张#173 + 单票/行业上限 + 移动止盈"

FACTOR_ID_HEDGE = "gross_expand_m16_lag28_hs300_conc_trail_ls"
NAME_HEDGE = "#173 + 集中度/移动止盈 + 空HS300"
TITLE_HEDGE = "集中度/移动止盈多头 + 始终满仓空 HS300"

OUT_DIR = ROOT / "data" / "factors" / "expt_173_conc_trail"
FACTORS_DATA = ROOT / "data" / "factors"
INDUSTRY_CACHE = kit.shared_cache_dir() / "sina_industry_map.parquet"

# 叠加规则（与基线 tp=35% 并存；任一先触发）
RULE = {
    "max_name_weight": 0.25,
    "max_industry_names": 2,
    "trail_activate": 0.18,
    "trail_stop": 0.09,
}


def _bs_disabled(*_a, **_k):
    raise RuntimeError("BaoStock disabled (qfq local-cache only)")


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
    if len(r) < 2:
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


def _window_metrics(daily: pd.DataFrame, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    if start:
        d = d.loc[d["date"] >= pd.Timestamp(start)]
    if end:
        d = d.loc[d["date"] <= pd.Timestamp(end)]
    m = _metrics_from_rets(d["strategy_ret"])
    if not m.get("empty") and len(d):
        m["start"] = str(pd.Timestamp(d["date"].iloc[0]).date())
        m["end"] = str(pd.Timestamp(d["date"].iloc[-1]).date())
        m["avg_position"] = round(float(d["position"].mean()), 4) if "position" in d.columns else None
    return m


def _load_base_params() -> dict:
    p = FACTORS_DATA / f"{BASE_FID}_backtest.json"
    if p.exists():
        return deepcopy(json.loads(p.read_text(encoding="utf-8")).get("params") or {})
    targets, client = _mongo_targets()
    doc = client[settings.MONGO_DB].factors.find_one({"factor_id": BASE_FID}, {"params": 1})
    return deepcopy((doc or {}).get("params") or {})


def _fetch_sina_industry_map(*, force: bool = False) -> Dict[str, str]:
    """新浪「新浪行业」节点 → code(sh.600000) → 行业名。缓存 parquet。"""
    if INDUSTRY_CACHE.exists() and not force:
        df = pd.read_parquet(INDUSTRY_CACHE)
        out: Dict[str, str] = {}
        for _, r in df.iterrows():
            out[str(r["code"])] = str(r["industry"])
            if "code6" in df.columns:
                out[str(r["code6"])] = str(r["industry"])
            else:
                out[kit.code_to_symbol6(r["code"])] = str(r["industry"])
        print(f"[industry] cache n={len(df)} path={INDUSTRY_CACHE}", flush=True)
        return out

    headers = {"User-Agent": "Mozilla/5.0"}
    nodes_url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodes"
    )
    r = requests.get(nodes_url, timeout=30, headers=headers)
    r.raise_for_status()
    data = json.loads(r.text)

    def walk(node, path=None):
        path = path or []
        if not isinstance(node, list):
            return
        if len(node) >= 3 and isinstance(node[2], str) and str(node[2]).startswith("new_"):
            yield path + [node[0]], node[2]
        if len(node) >= 2 and isinstance(node[1], list):
            for ch in node[1]:
                yield from walk(ch, path + ([node[0]] if isinstance(node[0], str) else path))
        else:
            for ch in node:
                yield from walk(ch, path)

    inds = list(walk(data))
    print(f"[industry] sina nodes={len(inds)}", flush=True)
    rows = []
    for path, node_id in inds:
        ind_name = str(path[-1]) if path else node_id
        page = 1
        while page <= 40:
            u = (
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num=80&sort=symbol&asc=1&node={node_id}"
            )
            try:
                rr = requests.get(u, timeout=25, headers=headers)
                rr.raise_for_status()
                chunk = json.loads(rr.text) if rr.text else []
            except Exception as exc:  # noqa: BLE001
                print(f"[industry] fail {node_id} p{page}: {exc}", flush=True)
                break
            if not chunk:
                break
            for it in chunk:
                sym = str(it.get("symbol") or "")
                code6 = str(it.get("code") or "")
                if sym.startswith("sh") and len(sym) >= 8:
                    code = f"sh.{sym[2:]}"
                elif sym.startswith("sz") and len(sym) >= 8:
                    code = f"sz.{sym[2:]}"
                elif code6.isdigit():
                    code = ("sh." if code6.startswith(("6", "9")) else "sz.") + code6.zfill(6)
                else:
                    continue
                rows.append({"code": code, "code6": kit.code_to_symbol6(code), "industry": ind_name, "node": node_id})
            if len(chunk) < 80:
                break
            page += 1
            time.sleep(0.05)
        time.sleep(0.08)

    df = pd.DataFrame(rows).drop_duplicates("code", keep="first")
    INDUSTRY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(INDUSTRY_CACHE, index=False)
    out = {str(r["code"]): str(r["industry"]) for _, r in df.iterrows()}
    # 也挂 6 位
    for _, r in df.iterrows():
        out[str(r["code6"])] = str(r["industry"])
    print(f"[industry] built n={len(df)} unique industries={df['industry'].nunique()}", flush=True)
    return out


def _rebuild_legs_with_trail(
    base_legs: pd.DataFrame,
    price_map: Dict[str, pd.DataFrame],
    params: dict,
) -> pd.DataFrame:
    """用基线入场日重算出场（加 trail）；不重跑选股信号。"""
    hold = int(params.get("hold_days") or 51)
    stop = float(params.get("stop_loss") or 0.12)
    tp = params.get("take_profit")
    take_profit = float(tp) if tp is not None else None
    tr = params.get("trail_stop")
    trail_stop = float(tr) if tr is not None else None
    ta = params.get("trail_activate")
    trail_activate = float(ta) if ta is not None else None

    entries = base_legs[["code", "entry_date", "note"]].copy()
    entries = entries.rename(columns={"entry_date": "date"})
    entries["date"] = pd.to_datetime(entries["date"])
    all_legs: List[dict] = []
    for code, g in entries.groupby("code"):
        px = price_map.get(str(code))
        if px is None or px.empty:
            path = kit.shared_cache_dir() / "daily" / f"{str(code).replace('.', '_')}.parquet"
            if not path.exists():
                continue
            px = pd.read_parquet(path)
            px["date"] = pd.to_datetime(px["date"], errors="coerce")
        all_legs.extend(
            build_legs_from_entries(
                g,
                px,
                hold_days=hold,
                stop_loss=stop,
                take_profit=take_profit,
                trail_stop=trail_stop,
                trail_activate=trail_activate,
            )
        )
    if not all_legs:
        return pd.DataFrame()
    legs = pd.DataFrame(all_legs)
    legs = legs.sort_values(["code", "entry_date"]).drop_duplicates(["code", "entry_date"], keep="first")
    return legs.reset_index(drop=True)


def _run_bt(
    legs: pd.DataFrame,
    params: dict,
    *,
    label: str,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    cache_dir = kit.shared_cache_dir()
    p = dict(params)
    p["_cache_dir"] = str(cache_dir)
    p["position_logic"] = label
    limiter = kit.RateLimiter(0.35)
    bench = kit.fetch_daily_valuation(
        str(p.get("bench_code") or "sh.000300"),
        str(p.get("price_start") or "2016-01-01"),
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
    )
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=p, bench_daily=bench, start=TRADE_START
    )
    return daily, summary, accepted


def _pack(label: str, daily: pd.DataFrame, summary: Dict[str, Any], extra: Optional[dict] = None) -> dict:
    full = _window_metrics(daily)
    r2y = _window_metrics(daily, RECENT2Y_CUT)
    july = _window_metrics(daily, JULY_START, JULY_END)
    row = {
        "label": label,
        "full": full,
        "r2y": r2y,
        "july": july,
        "summary": {
            k: summary.get(k)
            for k in (
                "total_return",
                "sharpe",
                "max_drawdown",
                "n_legs_accepted",
                "avg_position",
                "max_name_weight",
                "max_industry_names",
            )
        },
    }
    if extra:
        row.update(extra)
    return row


def _fmt(m: Optional[dict]) -> str:
    if not m or m.get("empty"):
        return "n/a"
    return f"ret={m.get('total_return'):+.2%}  mdd={m.get('max_drawdown'):+.2%}  sh={m.get('sharpe')}"


def _hedge_daily(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    d["long_ret"] = d["strategy_ret"].fillna(0.0)
    d["strategy_ret"] = d["long_ret"] - d["bench_ret"].fillna(0.0)
    d["equity"] = (1.0 + d["strategy_ret"]).cumprod()
    return d


def _plot_compare(curves: Dict[str, pd.DataFrame], path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)
    ax0, ax1 = axes
    for label, d in curves.items():
        dd = d.copy()
        dd["date"] = pd.to_datetime(dd["date"])
        ax0.plot(dd["date"], dd["equity"], label=label, lw=1.2)
        j = dd[(dd["date"] >= JULY_START) & (dd["date"] <= JULY_END)].copy()
        if not j.empty:
            j_eq = (1.0 + j["strategy_ret"].fillna(0.0)).cumprod()
            ax1.plot(j["date"], j_eq, label=label, lw=1.4)
    ax0.set_title("Full-sample equity")
    ax0.legend(fontsize=8)
    ax0.grid(True, alpha=0.3)
    ax1.set_title("2026-07 equity (rebased)")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _write_factor_arts(
    factor_id: str,
    title: str,
    daily: pd.DataFrame,
    summary: dict,
    accepted: pd.DataFrame,
    params: dict,
) -> None:
    trades = legs_to_trade_history(accepted, max_positions=int(params.get("max_positions") or 8))
    kit.write_factor_artifacts(factor_id, daily, summary, trades, params=params, title=title)
    legs_dir = FACTORS_DATA / factor_id
    legs_dir.mkdir(parents=True, exist_ok=True)
    if not accepted.empty:
        accepted.to_parquet(legs_dir / "trade_legs.parquet", index=False)


def _plan_insert(dbn: str, client, factor_id: str) -> Tuple[bool, Optional[datetime], Optional[int], str]:
    db = client[dbn]
    docs = _ui_docs(db)
    max_ui = len(docs)
    next_ui = max_ui + 1
    if db.factors.find_one({"factor_id": factor_id}, {"_id": 1}):
        return False, None, None, f"ABORT {dbn}: factor_id already exists: {factor_id}"
    if next_ui < MIN_UI:
        return False, None, None, f"ABORT {dbn}: next_ui={next_ui} < MIN_UI={MIN_UI}"
    mx = _max_created_at(docs)
    if mx is None or not isinstance(mx, datetime):
        ca = datetime(2026, 8, 3, 16, 0, 0)
    else:
        ca = mx + timedelta(minutes=30)
    return True, ca, next_ui, f"[plan] {dbn} max_ui={max_ui} -> UI#{next_ui} created_at={ca} {factor_id}"


def _insert_one(
    factor_id: str,
    name: str,
    title: str,
    params: dict,
    summary: dict,
    *,
    tags: List[str],
    desc: str,
    meta: Optional[dict] = None,
) -> int:
    targets, client = _mongo_targets()
    plans: Dict[str, Tuple[datetime, int]] = {}
    for dbn in targets:
        ok, ca, ui, msg = _plan_insert(dbn, client, factor_id)
        print(msg, flush=True)
        if not ok:
            if dbn == settings.MONGO_DB:
                raise SystemExit(msg)
            continue
        assert ca is not None and ui is not None
        plans[dbn] = (ca, ui)
    if settings.MONGO_DB not in plans:
        raise SystemExit("ABORT: primary DB plan failed")

    now = datetime.now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    primary_ui = plans[settings.MONGO_DB][1]
    # 入库 params 不塞巨大 industry map
    clean_params = {k: v for k, v in params.items() if k != "industry_by_code"}
    clean_params["industry_source"] = "sina_new_zhhy"
    clean_params["industry_cache"] = str(INDUSTRY_CACHE.as_posix())

    for dbn, (ca, ui) in plans.items():
        db = client[dbn]
        n_before = len(_ui_docs(db))
        # 禁止覆盖 178–183
        for occupied in range(178, 184):
            if n_before >= occupied:
                pass
        clean_summary = {k: v for k, v in summary.items() if not str(k).startswith("_")}
        payload = {
            "factor_id": factor_id,
            "name": name,
            "category": "fundamental",
            "description": desc,
            "tags": tags,
            "status": "active",
            "builtin": True,
            "params": clean_params,
            "created_at": ca,
            "updated_at": now,
            "backtest_summary": {
                "available": True,
                "primary_logic": factor_id,
                "logics": {factor_id: clean_summary},
                "updated_at": now_s,
            },
            "last_backtest_error": None,
            "signal_name": "signal_gross_expand_break",
            "title": title,
        }
        if meta:
            payload["expt_meta"] = meta
        if db.factors.find_one({"factor_id": factor_id}, {"_id": 1}):
            raise SystemExit(f"ABORT race: {dbn}.{factor_id}")
        r = db.factors.insert_one(payload)
        docs = _ui_docs(db)
        seq = _ui_seq(docs, factor_id)
        print(
            f"[mongo] INSERT {dbn}.{factor_id} _id={r.inserted_id} "
            f"planned_UI#{ui} actual_UI#{seq}/{len(docs)}",
            flush=True,
        )
        if seq != ui:
            raise SystemExit(f"ABORT {dbn}: UI mismatch planned={ui} actual={seq}")
        if seq < MIN_UI:
            raise SystemExit(f"ABORT {dbn}: UI#{seq} < MIN_UI={MIN_UI}")
        if len(docs) != n_before + 1:
            raise SystemExit(f"ABORT {dbn}: count drift")
        # 确认 novel 178–183 未被动
        for check_fid in (
            "ge_mid_m12_mkv_cap5e10_hs300_r2n",
            "ge_novel_fmkv_b_edges_mbrk_hs300_r2n",
        ):
            if dbn == settings.MONGO_DB and not db.factors.find_one({"factor_id": check_fid}, {"_id": 1}):
                raise SystemExit(f"ABORT: protected novel missing: {check_fid}")
    return primary_ui


def main() -> None:
    kit.bs_login = _bs_disabled  # type: ignore[assignment]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base_params = _load_base_params()
    base_params.setdefault("universe", "hs300")
    base_params.setdefault("max_positions", 8)
    base_params.setdefault("hold_days", 51)
    base_params.setdefault("stop_loss", 0.12)
    base_params.setdefault("take_profit", 0.35)
    base_params.setdefault("bench_code", "sh.000300")
    print(f"[base] params keys={sorted(base_params.keys())}", flush=True)

    industry = _fetch_sina_industry_map(force=False)

    base_legs_path = FACTORS_DATA / BASE_FID / "trade_legs.parquet"
    if not base_legs_path.exists():
        raise SystemExit(f"missing base legs: {base_legs_path}")
    base_legs = pd.read_parquet(base_legs_path)
    print(f"[legs] base raw n={len(base_legs)}", flush=True)

    # 基线回测（复现）
    print("======== CFG baseline ========", flush=True)
    d0, s0, a0 = _run_bt(base_legs, base_params, label="baseline_173")
    if d0.empty:
        raise SystemExit(f"baseline empty: {s0}")
    rows = [_pack("#173 基线", d0, s0)]
    curves = {"#173 基线": d0}

    # A: 仅单票上限
    print("======== CFG name_cap ========", flush=True)
    p_a = {**base_params, "max_name_weight": RULE["max_name_weight"]}
    d_a, s_a, a_a = _run_bt(base_legs, p_a, label="name_cap")
    rows.append(_pack("A 单票≤25%", d_a, s_a))
    curves["A 单票≤25%"] = d_a

    # B: 单票 + 行业
    print("======== CFG name+industry ========", flush=True)
    p_b = {
        **base_params,
        "max_name_weight": RULE["max_name_weight"],
        "max_industry_names": RULE["max_industry_names"],
        "industry_by_code": industry,
    }
    d_b, s_b, a_b = _run_bt(base_legs, p_b, label="name_ind")
    rows.append(_pack("B 单票+行业≤2", d_b, s_b))
    curves["B 单票+行业"] = d_b

    # C: 仅移动止盈（浮盈18%后回撤9%，叠加 tp35）
    print("======== CFG trail ========", flush=True)
    p_c = {
        **base_params,
        "trail_activate": RULE["trail_activate"],
        "trail_stop": RULE["trail_stop"],
    }
    legs_c = _rebuild_legs_with_trail(base_legs, {}, p_c)
    print(f"[legs] trail n={len(legs_c)} reasons=\n{legs_c['reason'].value_counts()}", flush=True)
    d_c, s_c, a_c = _run_bt(legs_c, p_c, label="trail")
    rows.append(_pack("C 移动止盈(18%→回撤9%)", d_c, s_c))
    curves["C 移动止盈"] = d_c

    # D: 全套（主候选）
    print("======== CFG full package ========", flush=True)
    p_d = {
        **base_params,
        **RULE,
        "industry_by_code": industry,
        "position_logic": FACTOR_ID,
        "note": TITLE,
    }
    legs_d = _rebuild_legs_with_trail(base_legs, {}, p_d)
    print(f"[legs] full n={len(legs_d)} reasons=\n{legs_d['reason'].value_counts()}", flush=True)
    d_d, s_d, a_d = _run_bt(legs_d, p_d, label=FACTOR_ID)
    rows.append(_pack("D #173+集中度+移动止盈", d_d, s_d))
    curves["D 全套"] = d_d

    # E: 峰值回撤12%（无 activate）对照
    print("======== CFG trail12 ========", flush=True)
    p_e = {**base_params, "trail_stop": 0.12, "trail_activate": None}
    legs_e = _rebuild_legs_with_trail(base_legs, {}, p_e)
    d_e, s_e, a_e = _run_bt(legs_e, p_e, label="trail12")
    rows.append(_pack("E 峰值回撤12%(叠加tp35)", d_e, s_e))
    curves["E trail12"] = d_e

    # F: D + 空 HS300
    d_f = _hedge_daily(d_d)
    s_f = {
        **s_d,
        "total_return": _window_metrics(d_f)["total_return"],
        "sharpe": _window_metrics(d_f)["sharpe"],
        "max_drawdown": _window_metrics(d_f)["max_drawdown"],
        "position_logic": FACTOR_ID_HEDGE,
        "accounting": "post_hoc_long_minus_index_always_full",
        "hedge_mode": "always_full_short_index",
    }
    rows.append(_pack("F D+空HS300", d_f, s_f))
    curves["F D+空HS300"] = d_f

    print("\n======== COMPARE ========", flush=True)
    print(f"{'label':<28} {'JULY':<42} {'FULL':<42} {'R2Y'}", flush=True)
    for r in rows:
        print(
            f"{r['label']:<28} {_fmt(r['july']):<42} {_fmt(r['full']):<42} {_fmt(r['r2y'])}",
            flush=True,
        )

    _plot_compare(curves, OUT_DIR / "compare_equity.png")

    # 入库判定：7 月收益或 MDD 改善，或全样本 Sharpe 不明显变差
    base_july = rows[0]["july"]
    cand = next(r for r in rows if r["label"].startswith("D "))
    july_better = (cand["july"].get("total_return") or -9) > (base_july.get("total_return") or -9) + 0.02
    july_mdd_better = (cand["july"].get("max_drawdown") or -9) > (base_july.get("max_drawdown") or -9) + 0.02
    worth = july_better or july_mdd_better or (
        (cand["full"].get("sharpe") or 0) >= (rows[0]["full"].get("sharpe") or 0) * 0.85
        and july_better
    )
    # 用户：有改善或值得看曲线就入库 —— 7 月任一改善即挂
    insert_ok = july_better or july_mdd_better
    print(
        f"[gate] july_ret_better={july_better} july_mdd_better={july_mdd_better} insert={insert_ok}",
        flush=True,
    )

    report = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_ui": BASE_UI,
        "base_factor_id": BASE_FID,
        "rule": RULE,
        "rule_note": (
            "单票权重≤25%（不足4只留现金）；同新浪行业最多2只；"
            "浮盈达18%后启用峰值回撤9%止盈；与原 tp=35%/sl=12%/hold=51 叠加（任一先触发）。"
            "行业：新浪「新浪行业」节点映射，缓存 sina_industry_map.parquet。"
        ),
        "compare": [
            {
                "label": r["label"],
                "july": r["july"],
                "full": r["full"],
                "r2y": r["r2y"],
                "summary": r["summary"],
            }
            for r in rows
        ],
        "insert": None,
    }

    ui_main = None
    ui_hedge = None
    if insert_ok:
        # 写产物
        s_d_out = dict(s_d)
        s_d_out.update(
            {
                "july_2026": cand["july"],
                "recent2y": cand["r2y"],
                "recent2y_cut": RECENT2Y_CUT,
                "base_factor_id": BASE_FID,
                "rule": RULE,
            }
        )
        _write_factor_arts(FACTOR_ID, TITLE, d_d, s_d_out, a_d, p_d)
        desc = (
            f"在 UI#{BASE_UI} `{BASE_FID}` 上叠加：单票权重≤{RULE['max_name_weight']:.0%}；"
            f"同行业最多{RULE['max_industry_names']}只（新浪行业）；"
            f"浮盈≥{RULE['trail_activate']:.0%}后峰值回撤{RULE['trail_stop']:.0%}止盈；"
            f"与原 take_profit={base_params.get('take_profit')} 叠加。"
            f"2026-07 ret={cand['july'].get('total_return')} mdd={cand['july'].get('max_drawdown')}；"
            f"全样本 sharpe={cand['full'].get('sharpe')}；近2年 sharpe={cand['r2y'].get('sharpe')}。"
        )
        ui_main = _insert_one(
            FACTOR_ID,
            NAME,
            TITLE,
            p_d,
            s_d_out,
            tags=["基本面", "技术面", "毛利率", "HS300", "qfq", "集中度", "移动止盈", "应对7月"],
            desc=desc,
            meta={"base_ui": BASE_UI, "base_factor_id": BASE_FID, "rule": RULE, "compare": report["compare"]},
        )
        # 对冲版
        s_f_out = dict(s_f)
        s_f_out.update(
            {
                "july_2026": _window_metrics(d_f, JULY_START, JULY_END),
                "recent2y": _window_metrics(d_f, RECENT2Y_CUT),
                "base_factor_id": FACTOR_ID,
            }
        )
        # trades：沿用 D 的 accepted + 合成空指数不另写复杂腿，交易史用 D
        _write_factor_arts(FACTOR_ID_HEDGE, TITLE_HEDGE, d_f, s_f_out, a_d, {**p_d, "position_logic": FACTOR_ID_HEDGE})
        desc_h = (
            f"多头同 `{FACTOR_ID}`（#173+集中度/移动止盈）+ 始终满仓空 HS300；"
            f"r_hedged=r_port−r_index。2026-07 ret={s_f_out['july_2026'].get('total_return')}。"
        )
        ui_hedge = _insert_one(
            FACTOR_ID_HEDGE,
            NAME_HEDGE,
            TITLE_HEDGE,
            {**p_d, "hedge_mode": "always_full_short_index", "position_logic": FACTOR_ID_HEDGE},
            s_f_out,
            tags=["基本面", "毛利率", "HS300", "qfq", "集中度", "移动止盈", "多空对冲"],
            desc=desc_h,
            meta={"long_factor_id": FACTOR_ID, "hedge": "always_full_short_index"},
        )
        report["insert"] = {
            "ui": ui_main,
            "factor_id": FACTOR_ID,
            "name": NAME,
            "hedge_ui": ui_hedge,
            "hedge_factor_id": FACTOR_ID_HEDGE,
        }
    else:
        print("[skip insert] 7 月未明显改善", flush=True)
        # 仍落实验产物
        d_d.to_csv(OUT_DIR / "D_daily.csv", index=False)
        (OUT_DIR / "D_summary.json").write_text(
            json.dumps(s_d, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md = [
        f"# {NAME}",
        "",
        f"- 基线：#{BASE_UI} `{BASE_FID}`",
        f"- 规则：{report['rule_note']}",
        "",
        "## 对照（重点 2026-07）",
        "",
        "| 方案 | 7月收益 | 7月MDD | 全样本收益 | 全样本Sharpe | 全样本MDD | 近2年Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        j, f, y = r["july"], r["full"], r["r2y"]
        md.append(
            f"| {r['label']} | {j.get('total_return')} | {j.get('max_drawdown')} | "
            f"{f.get('total_return')} | {f.get('sharpe')} | {f.get('max_drawdown')} | {y.get('sharpe')} |"
        )
    if report["insert"]:
        md.extend(
            [
                "",
                f"- **已入库**：UI#{ui_main} `{FACTOR_ID}`；对冲 UI#{ui_hedge} `{FACTOR_ID_HEDGE}`",
            ]
        )
    (OUT_DIR / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("======== DONE ========", flush=True)
    print(json.dumps(report.get("insert"), ensure_ascii=False, indent=2), flush=True)
    print(f"report: {OUT_DIR / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
