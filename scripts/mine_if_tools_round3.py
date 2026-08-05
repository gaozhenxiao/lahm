"""Round3 工具型原型：股票多头 + IF 期货对冲 / 贴水信号 / QVIX 保护代理。

底座优先已挂 #173（gross_expand_m16_lag28_hs300_r2）的日收益；
对冲腿用真实 IF0 日收益（非指数代理）。

原型：
  A. always_short_if     : r = r_long - r_IF
  B. basis_cond_hedge    : 深度贴水时减弱空头；升水/浅贴水满空
  C. qvix_protect_proxy  : QVIX 偏高时削减多头敞口（保护性看跌的简化代理；非真实期权）

对比：always_short_index（旧合成）vs always_short_if。

规则：近年加权 tw_score；不写 Mongo（先挖）；产物 mine_if_tools_round3/
BaoStock 禁用；股票侧腾讯 qfq 已在底座因子中。

用法:
  .venv\\Scripts\\python.exe scripts/download_if_io_shared.py
  .venv\\Scripts\\python.exe scripts/mine_if_tools_round3.py
  .venv\\Scripts\\python.exe scripts/mine_if_tools_round3.py --insert   # 选择性入库 max+1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from pymongo import MongoClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_if_tools_round3"
FACTORS_DATA = ROOT / "data" / "factors"
SHARED = kit.shared_cache_dir()
START = "2018-01-01"
RECENT2Y_CUT = "2024-08-01"
MIN_UI = 186

SEGMENTS: List[Tuple[str, str, Optional[str], float]] = [
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_now", "2024-01-01", None, 0.50),
]

# 多头底座（已入库 / 本地有 backtest csv）
BASE_CANDS = [
    ("#173", "gross_expand_m16_lag28_hs300_r2"),
    ("#178", "ge_mid_m12_mkv_cap5e10_hs300_r2n"),
    ("#179", "struct_catchup_lag28_h45_hs300_r2n"),
    ("#168", "gross_expand_m16_tp35"),
]


def _sharpe(rets: pd.Series) -> Optional[float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5 or float(r.std(ddof=0)) == 0:
        return None
    return float(r.mean() / r.std(ddof=0) * math.sqrt(252))


def _max_dd(eq: pd.Series) -> Optional[float]:
    e = pd.to_numeric(eq, errors="coerce").dropna()
    if e.empty:
        return None
    return float((e / e.cummax() - 1.0).min())


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


def _slice_metrics(daily: pd.DataFrame, ret_col: str, start: str, end: Optional[str]) -> Dict[str, Any]:
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    mask = d["date"] >= pd.Timestamp(start)
    if end:
        mask &= d["date"] <= pd.Timestamp(end)
    part = d.loc[mask]
    if len(part) < 5:
        return {"empty": True, "bars": int(len(part))}
    m = _metrics_from_rets(part[ret_col])
    m["start"] = str(pd.Timestamp(part["date"].iloc[0]).date())
    m["end"] = str(pd.Timestamp(part["date"].iloc[-1]).date())
    return m


def _tw_score(daily: pd.DataFrame, ret_col: str) -> Dict[str, Any]:
    segs: Dict[str, Any] = {}
    score_num = 0.0
    score_den = 0.0
    for label, s, e, w in SEGMENTS:
        m = _slice_metrics(daily, ret_col, s, e)
        segs[label] = {**m, "weight": w}
        sh = m.get("sharpe")
        if sh is not None and not m.get("empty"):
            score_num += w * float(sh)
            score_den += w
    tw_sharpe = score_num / score_den if score_den > 0 else None
    recent2y = _slice_metrics(daily, ret_col, RECENT2Y_CUT, None)
    early = segs.get("y2018_2021") or {}
    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    early_sh = early.get("sharpe")
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")
    penalty = 0.0
    if "early_inflated_recent_poor" in flags:
        penalty += 0.50
    elif "recent2y_big_loss" in flags:
        penalty += 0.35
    elif "recent2y_neg_sharpe" in flags:
        penalty += 0.20
    tw_adj = (tw_sharpe - penalty) if tw_sharpe is not None else None
    return {
        "segments": segs,
        "tw_sharpe": tw_sharpe,
        "tw_score": tw_adj,
        "tw_penalty": penalty,
        "recent2y": recent2y,
        "tw_flags": flags,
        "late_sharpe": (segs.get("y2024_now") or {}).get("sharpe"),
        "early_sharpe": early.get("sharpe"),
        "mid_sharpe": (segs.get("y2022_2023") or {}).get("sharpe"),
    }


def _load_long_daily(fid: str) -> Optional[pd.DataFrame]:
    path = FACTORS_DATA / f"{fid}_backtest.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("strategy_ret", "bench_ret", "position", "equity"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    df = df.loc[df["date"] >= pd.Timestamp(START)].copy()
    return df


def _load_if_tools() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if0_path = SHARED / "futures" / "IF0_daily.parquet"
    basis_path = SHARED / "futures" / "IF0_basis.parquet"
    qvix_path = SHARED / "options" / "qvix_300etf.parquet"
    if not if0_path.exists() or not basis_path.exists():
        raise SystemExit("missing IF cache; run scripts/download_if_io_shared.py first")
    if0 = pd.read_parquet(if0_path)
    basis = pd.read_parquet(basis_path)
    qvix = pd.read_parquet(qvix_path) if qvix_path.exists() else pd.DataFrame()
    if0["date"] = pd.to_datetime(if0["date"])
    basis["date"] = pd.to_datetime(basis["date"])
    if not qvix.empty:
        qvix["date"] = pd.to_datetime(qvix["date"])
    return if0, basis, qvix


def _merge_tools(long_df: pd.DataFrame, basis: pd.DataFrame, qvix: pd.DataFrame) -> pd.DataFrame:
    d = long_df.copy()
    b = basis[["date", "if_close", "if_ret", "spot_close", "spot_ret", "basis_pct", "basis_pct_z60"]].copy()
    m = d.merge(b, on="date", how="inner")
    if not qvix.empty:
        q = qvix[["date", "close", "qvix_z60"]].rename(columns={"close": "qvix"})
        m = m.merge(q, on="date", how="left")
        m["qvix"] = m["qvix"].ffill()
        m["qvix_z60"] = m["qvix_z60"].ffill()
    else:
        m["qvix"] = float("nan")
        m["qvix_z60"] = float("nan")
    m["long_ret"] = m["strategy_ret"].fillna(0.0)
    m["bench_ret"] = m["bench_ret"].fillna(0.0)
    m["if_ret"] = m["if_ret"].fillna(0.0)
    m["position"] = m["position"].fillna(0.0) if "position" in m.columns else 1.0
    return m


def _proto_A_always_short_if(m: pd.DataFrame) -> pd.DataFrame:
    """始终满仓空 IF0。"""
    out = m.copy()
    out["hedge_w"] = 1.0
    out["net_ret"] = out["long_ret"] - out["if_ret"]
    return out


def _proto_A2_always_short_index(m: pd.DataFrame) -> pd.DataFrame:
    out = m.copy()
    out["hedge_w"] = 1.0
    out["net_ret"] = out["long_ret"] - out["bench_ret"]
    return out


def _proto_B_basis_cond(m: pd.DataFrame, deep_z: float = -1.0, shallow_w: float = 0.35) -> pd.DataFrame:
    """贴水条件对冲：basis_pct_z60 <= deep_z（深度贴水）→ 空头权重 shallow_w；否则满空。

    直觉：深度贴水时空 IF 不利（贴水收敛常伴随 IF 相对走强/回补），减弱空头。
    """
    out = m.copy()
    z = out["basis_pct_z60"]
    # 信号用前一日，避免当日偷看
    z_lag = z.shift(1)
    w = pd.Series(1.0, index=out.index)
    deep = z_lag <= deep_z
    w = w.where(~deep.fillna(False), shallow_w)
    out["hedge_w"] = w.fillna(1.0)
    out["net_ret"] = out["long_ret"] - out["hedge_w"] * out["if_ret"]
    out["basis_rule"] = f"z60_lag<={deep_z} -> hedge_w={shallow_w}; else 1.0"
    return out


def _proto_C_qvix_protect(m: pd.DataFrame, z_cut: float = 1.0, long_scale: float = 0.55) -> pd.DataFrame:
    """QVIX 偏高时削减多头（保护性看跌代理）+ 满空 IF。

    局限：非真实买 put；用「降仓」近似保护，无权利金成本（偏乐观）。
    """
    out = m.copy()
    z = out["qvix_z60"].shift(1)
    scale = pd.Series(1.0, index=out.index)
    hot = z >= z_cut
    scale = scale.where(~hot.fillna(False), long_scale)
    out["long_scale"] = scale.fillna(1.0)
    out["hedge_w"] = 1.0
    out["net_ret"] = out["long_scale"] * out["long_ret"] - out["hedge_w"] * out["if_ret"]
    out["opt_proxy_note"] = f"qvix_z60_lag>={z_cut} -> long*{long_scale}; no premium cost"
    return out


def _pack_result(
    cfg_id: str,
    family: str,
    base_label: str,
    base_fid: str,
    daily: pd.DataFrame,
    note: str,
) -> Dict[str, Any]:
    d = daily.copy()
    d["strategy_ret"] = d["net_ret"].fillna(0.0)
    d["equity"] = (1.0 + d["strategy_ret"]).cumprod()
    tw = _tw_score(d, "strategy_ret")
    full = _metrics_from_rets(d["strategy_ret"])
    long_full = _metrics_from_rets(d["long_ret"])
    row = {
        "cfg_id": cfg_id,
        "family": family,
        "base_label": base_label,
        "base_factor_id": base_fid,
        "universe": "hs300",
        "note": note,
        "ok": True,
        "rejected": "early_inflated_recent_poor" in (tw.get("tw_flags") or []),
        "tw_score": tw.get("tw_score"),
        "tw_sharpe": tw.get("tw_sharpe"),
        "tw_penalty": tw.get("tw_penalty"),
        "tw_flags": tw.get("tw_flags") or [],
        "sharpe": full.get("sharpe"),
        "total_return": full.get("total_return"),
        "annual_return": full.get("annual_return"),
        "max_drawdown": full.get("max_drawdown"),
        "recent2y_sharpe": (tw.get("recent2y") or {}).get("sharpe"),
        "recent2y_return": (tw.get("recent2y") or {}).get("total_return"),
        "late_sharpe": tw.get("late_sharpe"),
        "early_sharpe": tw.get("early_sharpe"),
        "mid_sharpe": tw.get("mid_sharpe"),
        "long_full_sharpe": long_full.get("sharpe"),
        "long_full_ret": long_full.get("total_return"),
        "avg_hedge_w": float(d["hedge_w"].mean()) if "hedge_w" in d.columns else None,
        "bars": int(len(d)),
        "start": str(pd.Timestamp(d["date"].iloc[0]).date()),
        "end": str(pd.Timestamp(d["date"].iloc[-1]).date()),
    }
    # attach daily for artifact
    row["_daily"] = d
    return row


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "-"
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _plot(curves: Dict[str, pd.DataFrame], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for label, d in curves.items():
        ax.plot(pd.to_datetime(d["date"]), d["equity"], label=label, lw=1.1)
    ax.set_title("IF tools prototypes (equity)")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_mine() -> Dict[str, Any]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _, basis, qvix = _load_if_tools()
    results: List[Dict[str, Any]] = []
    curves: Dict[str, pd.DataFrame] = {}

    for base_label, base_fid in BASE_CANDS:
        long_df = _load_long_daily(base_fid)
        if long_df is None:
            print(f"[skip base] missing csv {base_fid}", flush=True)
            continue
        m = _merge_tools(long_df, basis, qvix)
        if len(m) < 100:
            print(f"[skip base] too few overlap days {base_fid} n={len(m)}", flush=True)
            continue
        print(f"[base] {base_label} {base_fid} overlap={len(m)}", flush=True)

        specs = [
            (
                f"{base_fid}__short_if",
                "always_short_if",
                _proto_A_always_short_if(m),
                "多头 + 始终满仓空 IF0（真实期货日收益）",
            ),
            (
                f"{base_fid}__short_index",
                "always_short_index_proxy",
                _proto_A2_always_short_index(m),
                "对照：多头 + 始终空指数（旧合成代理）",
            ),
            (
                f"{base_fid}__basis_cond_if",
                "basis_cond_hedge",
                _proto_B_basis_cond(m, deep_z=-1.0, shallow_w=0.35),
                "贴水条件对冲：z60<=-1 时空头 35%，否则满空 IF",
            ),
            (
                f"{base_fid}__basis_cond_if_z15",
                "basis_cond_hedge",
                _proto_B_basis_cond(m, deep_z=-1.5, shallow_w=0.25),
                "贴水条件对冲：z60<=-1.5 时空头 25%",
            ),
            (
                f"{base_fid}__qvix_protect_if",
                "qvix_protect_proxy",
                _proto_C_qvix_protect(m, z_cut=1.0, long_scale=0.55),
                "QVIX 保护代理：波动偏高削减多头 + 满空 IF（无权利金）",
            ),
        ]
        for cfg_id, family, daily, note in specs:
            row = _pack_result(cfg_id, family, base_label, base_fid, daily, note)
            print(
                f"  {cfg_id}: tw={row['tw_score']} full_sh={row['sharpe']} "
                f"r2y_sh={row['recent2y_sharpe']} r2y_ret={row['recent2y_return']} "
                f"flags={row['tw_flags']}",
                flush=True,
            )
            curves[cfg_id] = row["_daily"]
            # persist daily per cfg
            cfg_dir = OUT_ROOT / "dailies"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            row["_daily"].to_csv(cfg_dir / f"{cfg_id}.csv", index=False)
            slim = {k: v for k, v in row.items() if k != "_daily"}
            results.append(slim)

    results_sorted = sorted(
        [r for r in results if not r.get("rejected")],
        key=lambda r: (
            float(r.get("tw_score") if r.get("tw_score") is not None else -999),
            float(r.get("recent2y_sharpe") if r.get("recent2y_sharpe") is not None else -999),
        ),
        reverse=True,
    )
    # prefer IF-based families for lahm list
    lahm_list = [
        r
        for r in results_sorted
        if r.get("family") in ("always_short_if", "basis_cond_hedge", "qvix_protect_proxy")
        and (r.get("recent2y_sharpe") is None or float(r.get("recent2y_sharpe") or -9) > -0.1)
        and float(r.get("tw_score") or -9) > 0.3
    ][:8]

    _plot({k: curves[k] for k in list(curves)[:8]}, OUT_ROOT / "equity_compare.png")

    payload = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "survivor_bias_note": "多头底座沿用静态成分因子；IF/QVIX 为公开日频缓存",
        "data": {
            "if0": str((SHARED / "futures" / "IF0_daily.parquet").relative_to(ROOT)),
            "basis": str((SHARED / "futures" / "IF0_basis.parquet").relative_to(ROOT)),
            "qvix": str((SHARED / "options" / "qvix_300etf.parquet").relative_to(ROOT)),
            "io_note": "无单合约 IO 链；用 300ETF QVIX 作波动代理；非真实期权盈亏",
        },
        "n_cfgs": len(results),
        "top": results_sorted[:12],
        "lahm_candidates": lahm_list,
        "all": results,
    }
    (OUT_ROOT / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _write_summary(payload)
    return payload


def _write_summary(payload: Dict[str, Any]) -> Path:
    lines = [
        "# IF/IO 工具型因子原型 · Round3",
        "",
        f"- 时间：{payload.get('built_at')}",
        "- 股票：腾讯 qfq（底座因子）；**BaoStock 禁用**",
        "- 期货：akshare 新浪 `IF0` 主力连续 → `_shared/futures/IF0_daily.parquet`",
        "- 基差：IF0 vs `sh.000300` spot → `_shared/futures/IF0_basis.parquet`",
        "- 期权：无可用 IO 单合约日链；`index_option_300index_qvix` 全 NaN；改用 **300ETF QVIX** 作波动代理",
        "- Mongo：默认不写；`--insert` 才 INSERT max+1（≥186）",
        "- 成分幸存者偏差：沿用股票底座因子说明",
        "",
        "## 原型说明",
        "",
        "| family | 规则 | 局限 |",
        "|--------|------|------|",
        "| always_short_if | r=r_long−r_IF0 | 换月跳空未修正；无保证金/展期成本 |",
        "| always_short_index_proxy | r=r_long−r_index | 旧合成对照，非真实期货 |",
        "| basis_cond_hedge | 深度贴水减弱空 IF | 规则启发式；非最优对冲比 |",
        "| qvix_protect_proxy | 高波动削减多头+空 IF | **非真实买 put**；无权利金（偏乐观） |",
        "",
        "## Top（按 tw_score）",
        "",
        "| cfg | tw | full_sh | full_ret | r2y_sh | r2y_ret | family | base |",
        "|-----|----|---------|----------|--------|--------|--------|------|",
    ]
    for r in payload.get("top") or []:
        lines.append(
            f"| `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | {_fmt(r.get('sharpe'))} | "
            f"{_fmt(r.get('total_return'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('family')} | {r.get('base_label')} |"
        )
    lines.extend(
        [
            "",
            "## 可挂 lahm 候选（IF 相关 + 近2年不崩 + tw>0.3，未入库）",
            "",
            "| cfg | tw | r2y_sh | r2y_ret | family | note |",
            "|-----|----|--------|--------|--------|------|",
        ]
    )
    for r in payload.get("lahm_candidates") or []:
        lines.append(
            f"| `{r.get('cfg_id')}` | {_fmt(r.get('tw_score'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('family')} | {r.get('note')} |"
        )
    if not payload.get("lahm_candidates"):
        lines.append("| （暂无） | | | | | |")
    lines.extend(
        [
            "",
            "## 下一步",
            "- round3 股票 novel 继续跑 csi500/csi1000",
            "- IF 原型若扎实：选 1 个 always_short_if 或 basis_cond 以 max+1 INSERT",
            "- 期权真链若后续可下：替换 QVIX 代理为保护性看跌/备兑真实结算",
            "",
        ]
    )
    path = OUT_ROOT / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- optional insert ----------

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


def insert_best(payload: Dict[str, Any], max_n: int = 1) -> None:
    """选择性入库：优先 basis_cond / always_short_if；与同底座空指数对照接近亦可（真实 IF 工具链）。"""
    cands = payload.get("lahm_candidates") or []
    if not cands:
        print("[insert] no candidates", flush=True)
        return
    all_by_id = {r["cfg_id"]: r for r in payload.get("all") or []}
    picks: List[Dict[str, Any]] = []
    prefer = ("basis_cond_hedge", "always_short_if")
    for fam in prefer:
        for r in cands:
            if r.get("family") != fam:
                continue
            # 避免同底座重复挂多个几乎一样的；每个 family 至多 1
            if any(p.get("family") == fam and p.get("base_factor_id") == r.get("base_factor_id") for p in picks):
                continue
            twin = all_by_id.get(f"{r['base_factor_id']}__short_index")
            if twin and float(r.get("tw_score") or -9) < float(twin.get("tw_score") or -9) - 0.15:
                print(f"[insert skip] {r['cfg_id']} tw much worse than short_index twin", flush=True)
                continue
            picks.append(r)
            if len(picks) >= max_n:
                break
        if len(picks) >= max_n:
            break
    if not picks:
        print("[insert] nothing solid enough", flush=True)
        return

    # stable short factor_ids
    id_map = {
        "ge_mid_m12_mkv_cap5e10_hs300_r2n__basis_cond_if_z15": "ge_mid_hs300_r2n_basis_if_z15",
        "ge_mid_m12_mkv_cap5e10_hs300_r2n__short_if": "ge_mid_hs300_r2n_short_if",
        "gross_expand_m16_lag28_hs300_r2__basis_cond_if_z15": "ge173_hs300_basis_if_z15",
        "gross_expand_m16_lag28_hs300_r2__short_if": "ge173_hs300_short_if",
    }

    dbs, client = _mongo_targets()
    for r in picks:
        factor_id = id_map.get(r["cfg_id"]) or r["cfg_id"].replace("__", "_")[:72]
        daily_path = OUT_ROOT / "dailies" / f"{r['cfg_id']}.csv"
        daily = pd.read_csv(daily_path)
        daily["date"] = pd.to_datetime(daily["date"])
        if "strategy_ret" not in daily.columns and "net_ret" in daily.columns:
            daily["strategy_ret"] = daily["net_ret"]
        if "equity" not in daily.columns:
            daily["equity"] = (1.0 + daily["strategy_ret"].fillna(0.0)).cumprod()
        if "position" not in daily.columns:
            daily["position"] = daily["long_scale"] if "long_scale" in daily.columns else 1.0
        if "bench_ret" not in daily.columns:
            daily["bench_ret"] = 0.0
        summary = {
            "bars": int(r["bars"]),
            "start": r["start"],
            "end": r["end"],
            "total_return": r["total_return"],
            "annual_return": r["annual_return"],
            "sharpe": r["sharpe"],
            "max_drawdown": r["max_drawdown"],
            "tw_score": r["tw_score"],
            "recent2y_sharpe": r["recent2y_sharpe"],
            "recent2y_return": r["recent2y_return"],
            "position_logic": factor_id,
            "hedge_mode": r["family"],
            "base_factor_id": r["base_factor_id"],
            "note": r["note"],
            "accounting": "post_hoc_long_minus_IF0",
            "limitations": "IF0连续换月跳空未修正；无保证金/展期成本；贴水规则启发式",
        }
        params = {
            "universe": "hs300",
            "hedge_instrument": "IF0",
            "hedge_source": "akshare:futures_zh_daily_sina",
            "hedge_mode": r["family"],
            "base_factor_id": r["base_factor_id"],
            "exclude_st": True,
            "price_start": "2016-01-01",
            "max_positions": 8,
            "commission_rate": 0.0001,
            "stamp_tax_sell": 0.001,
            "bench_code": "sh.000300",
        }
        name = f"多头{r['base_label']}+{r['family']}(IF0·mine IF tools R3 时间加权)"
        title = f"{r['base_label']} + {r['family']} IF0"
        trades = pd.DataFrame(columns=["date", "code", "side", "reason"])
        kit.write_factor_artifacts(factor_id, daily, summary, trades, params=params, title=title)

        for dbn in dbs:
            db = client[dbn]
            docs = _ui_docs(db)
            max_ui = len(docs)
            next_ui = max_ui + 1
            if db.factors.find_one({"factor_id": factor_id}, {"_id": 1}):
                print(f"[ABORT] {dbn} exists {factor_id}", flush=True)
                continue
            if next_ui < MIN_UI:
                print(f"[ABORT] {dbn} next_ui={next_ui}<{MIN_UI}", flush=True)
                continue
            mx = None
            for d in docs:
                ca = d.get("created_at")
                if ca is not None and (mx is None or ca > mx):
                    mx = ca
            ca = (mx + timedelta(minutes=30)) if isinstance(mx, datetime) else datetime(2026, 8, 3, 16, 30, 0)
            doc = {
                "factor_id": factor_id,
                "name": name,
                "title": title,
                "builtin": False,
                "category": "mine",
                "status": "active",
                "tags": ["基本面", "技术面", "HS300", "qfq", "IF0", "期货对冲", "贴水", "mine_if_tools", "时间加权"],
                "description": r["note"] + "；换月跳空未修正；无保证金成本",
                "params": params,
                "signal": "overlay_if_hedge",
                "created_at": ca,
                "updated_at": datetime.now(),
                "meta": {
                    "tw_score": r.get("tw_score"),
                    "sharpe": r.get("sharpe"),
                    "recent2y_sharpe": r.get("recent2y_sharpe"),
                    "recent2y_return": r.get("recent2y_return"),
                    "family": r.get("family"),
                    "base_factor_id": r.get("base_factor_id"),
                    "cfg_id": r.get("cfg_id"),
                    "ui_planned": next_ui,
                },
            }
            # latest metrics for UI
            doc["latest_asof"] = r.get("end")
            doc["latest_value"] = r.get("total_return")
            ins = db.factors.insert_one(doc)
            docs2 = _ui_docs(db)
            seq = next((i for i, x in enumerate(docs2, 1) if x.get("factor_id") == factor_id), None)
            print(f"[mongo] INSERT {dbn}.{factor_id} UI#{seq} (planned {next_ui}) _id={ins.inserted_id}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--insert", action="store_true", help="选择性入库 1 个扎实 IF 原型")
    ap.add_argument("--insert-n", type=int, default=1)
    args = ap.parse_args()
    payload = run_mine()
    print((OUT_ROOT / "SUMMARY.md").read_text(encoding="utf-8"), flush=True)
    if args.insert:
        insert_best(payload, max_n=args.insert_n)


if __name__ == "__main__":
    main()
