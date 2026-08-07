"""场景挖掘：在已入库因子族的 trade_legs 上找高胜率条件（非新挖参数）。

方法（防过拟合）：
1. 母体固定：毛利扩张冠军线 7 因子（不改信号/参数）
2. 条件族预注册：入场前动量 / 拥挤度 / 组合规则（禁止扫分位挑最优）
3. 目标：入场后 10/20/40 日胜率、中位收益、中位最大回撤
4. 时间切分：IS = entry < OOS_START；OOS 只做确认
5. 产出：过滤器规则，不是新因子

用法：
  python scripts/mine_scenarios_gross_expand.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

OUT_DIR_ROOT = ROOT / "data" / "factors"
OOS_START = pd.Timestamp("2024-01-01")
TRADE_START = pd.Timestamp("2018-01-01")
MIN_IS_N = 80
MIN_OOS_N = 30
# OOS 胜率相对 IS 最多掉这么多个百分点仍算「站得住」
MAX_WR_DECAY_PP = 0.05

FAMILIES: Dict[str, Dict[str, Any]] = {
    "gross_expand": {
        "title": "毛利扩张族",
        "factor_ids": [
            "gross_expand_m16_tp35",
            "gross_expand_lag28_tp35",
            "gross_expand_m16_lag28_hs300_r2",
            "gross_expand_imp005_tp35",
            "gross_expand_champ_tp33",
            "gross_expand_lag30_tp35",
            "gross_expand_m18_lag29_tp35",
        ],
    },
    "ar_cl_causal": {
        "title": "应收/合同负债因果族",
        "factor_ids": [
            "ar_tighten_ar015_hs300_causal",
            "cl_yoy_acc_clacc12_csi500_causal",
            "opex_rev_ox05_hs300_causal",
            "ar_cl_dual_ar015_csi500_so2",
            "ar_acc_ar012_hs300_so2",
            "cfo_np_acc_cfoq08_csi500_so2",
        ],
    },
}

HORIZONS = (10, 20, 40)
PRIOR_WINDOWS = {"prior_1m": 21, "prior_3m": 63, "prior_6m": 126}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    label: str
    kind: str  # baseline | prefer | avoid
    pred: Callable[[pd.DataFrame], pd.Series]


def _load_family_legs(factor_ids: List[str]) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for fid in factor_ids:
        path = kit.factor_cache_dir(fid) / "trade_legs.parquet"
        if not path.exists():
            print(f"[warn] missing legs {fid}", flush=True)
            continue
        df = pd.read_parquet(path)
        df["factor_id"] = fid
        rows.append(df)
    if not rows:
        raise SystemExit("no family legs found")
    all_ = pd.concat(rows, ignore_index=True)
    all_["code"] = all_["code"].astype(str)
    all_["entry_date"] = pd.to_datetime(all_["entry_date"])
    all_["exit_date"] = pd.to_datetime(all_["exit_date"])
    all_ = all_[all_["entry_date"] >= TRADE_START].copy()
    return all_


def _crowd_by_entry(raw: pd.DataFrame) -> pd.DataFrame:
    """每个 (code, entry_date) 的同族拥挤度 = 当日触发的家族因子数。"""
    g = (
        raw.groupby(["code", "entry_date"], as_index=False)
        .agg(
            crowd=("factor_id", "nunique"),
            factors=("factor_id", lambda s: ",".join(sorted(set(map(str, s))))),
            n_legs=("factor_id", "size"),
            entry_price=("entry_price", "first"),
        )
        .sort_values(["entry_date", "code"])
        .reset_index(drop=True)
    )
    return g


class PriceCache:
    def __init__(self) -> None:
        self._cache: Dict[str, pd.DataFrame] = {}
        self.shared = kit.shared_cache_dir()

    def get(self, code: str) -> Optional[pd.DataFrame]:
        if code in self._cache:
            return self._cache[code]
        path = kit.daily_parquet_path(self.shared, code)
        if not path.exists():
            self._cache[code] = None  # type: ignore[assignment]
            return None
        df = pd.read_parquet(path)
        keep = [c for c in ["date", "close", "high", "low", "peTTM", "pbMRQ"] if c in df.columns]
        df = df[keep]
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        df["close"] = df["close"].astype(float)
        self._cache[code] = df
        return df


def _idx_on_or_after(dates: pd.Series, ts: pd.Timestamp) -> Optional[int]:
    # dates sorted
    pos = int(dates.searchsorted(ts, side="left"))
    if pos >= len(dates):
        return None
    return pos


def _idx_on_or_before(dates: pd.Series, ts: pd.Timestamp) -> Optional[int]:
    pos = int(dates.searchsorted(ts, side="right")) - 1
    if pos < 0:
        return None
    return pos


def enrich_features(events: pd.DataFrame, prices: PriceCache) -> pd.DataFrame:
    bench = prices.get("sh.000300")
    if bench is None or bench.empty:
        raise SystemExit("missing HS300 daily for relative momentum")
    bench = bench.rename(columns={"close": "bench_close"})[["date", "bench_close"]]

    recs: List[Dict[str, Any]] = []
    miss = 0
    for row in events.itertuples(index=False):
        code = str(row.code)
        entry = pd.Timestamp(row.entry_date)
        px = prices.get(code)
        if px is None or px.empty:
            miss += 1
            continue
        dates = px["date"]
        i0 = _idx_on_or_after(dates, entry)
        if i0 is None:
            miss += 1
            continue
        c0 = float(px.loc[i0, "close"])
        entry_px = float(row.entry_price) if pd.notna(row.entry_price) and row.entry_price > 0 else c0

        feat: Dict[str, Any] = {
            "code": code,
            "entry_date": entry,
            "entry_price": entry_px,
            "crowd": int(row.crowd),
            "factors": row.factors,
            "n_legs": int(row.n_legs),
        }

        for name, w in PRIOR_WINDOWS.items():
            j = i0 - w
            if j < 0:
                feat[name] = np.nan
            else:
                c_prev = float(px.loc[j, "close"])
                feat[name] = (c0 / c_prev - 1.0) if c_prev > 0 else np.nan

        # 相对沪深300的 3 月超额
        if i0 >= 63:
            d0 = pd.Timestamp(px.loc[i0, "date"])
            d_prev = pd.Timestamp(px.loc[i0 - 63, "date"])
            b0 = bench.loc[bench["date"] <= d0, "bench_close"]
            b1 = bench.loc[bench["date"] <= d_prev, "bench_close"]
            if len(b0) and len(b1) and float(b1.iloc[-1]) > 0 and float(b0.iloc[-1]) > 0:
                stock_r = c0 / float(px.loc[i0 - 63, "close"]) - 1.0
                bench_r = float(b0.iloc[-1]) / float(b1.iloc[-1]) - 1.0
                feat["prior_3m_ex300"] = stock_r - bench_r
            else:
                feat["prior_3m_ex300"] = np.nan
        else:
            feat["prior_3m_ex300"] = np.nan

        # PE（若有）
        if "peTTM" in px.columns:
            pe = px.loc[i0, "peTTM"] if "peTTM" in px.columns else np.nan
            try:
                feat["pe_ttm"] = float(pe) if pd.notna(pe) else np.nan
            except Exception:
                feat["pe_ttm"] = np.nan
        else:
            feat["pe_ttm"] = np.nan

        closes = px["close"].to_numpy(dtype=float)
        for h in HORIZONS:
            i1 = i0 + h
            if i1 >= len(closes):
                feat[f"fwd_{h}d"] = np.nan
                feat[f"mdd_{h}d"] = np.nan
                continue
            path = closes[i0 : i1 + 1] / entry_px
            feat[f"fwd_{h}d"] = float(path[-1] - 1.0)
            peak = np.maximum.accumulate(path)
            dd = path / peak - 1.0
            feat[f"mdd_{h}d"] = float(dd.min()) if len(dd) else np.nan

        if i0 > 0:
            feat["entry_day_ret"] = c0 / float(px.loc[i0 - 1, "close"]) - 1.0
        else:
            feat["entry_day_ret"] = np.nan

        recs.append(feat)

    out = pd.DataFrame.from_records(recs)
    print(f"[enrich] events={len(events)} ok={len(out)} miss_px={miss}", flush=True)
    return out


def _stats(df: pd.DataFrame, horizon: int = 20) -> Dict[str, Any]:
    r = df[f"fwd_{horizon}d"].dropna()
    mdd = df[f"mdd_{horizon}d"].dropna()
    r40 = df["fwd_40d"].dropna() if "fwd_40d" in df.columns else pd.Series(dtype=float)
    if r.empty:
        return {
            "n": 0,
            "win_rate": None,
            "med_ret": None,
            "med_mdd": None,
            "med_ret_40d": None,
            "p10_mdd": None,
        }
    return {
        "n": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "med_ret": float(r.median()),
        "med_mdd": float(mdd.median()) if len(mdd) else None,
        "med_ret_40d": float(r40.median()) if len(r40) else None,
        "p10_mdd": float(mdd.quantile(0.10)) if len(mdd) else None,
    }


def build_scenarios() -> List[Scenario]:
    """预注册条件族：只评这些，不搜索最优阈值。"""

    def col_lt(c: str, thr: float) -> Callable[[pd.DataFrame], pd.Series]:
        return lambda d: d[c].notna() & (d[c] < thr)

    def col_ge(c: str, thr: float) -> Callable[[pd.DataFrame], pd.Series]:
        return lambda d: d[c].notna() & (d[c] >= thr)

    def col_between(c: str, a: float, b: float) -> Callable[[pd.DataFrame], pd.Series]:
        return lambda d: d[c].notna() & (d[c] >= a) & (d[c] < b)

    return [
        Scenario("baseline_all", "全样本", "baseline", lambda d: pd.Series(True, index=d.index)),
        # --- prior 3m（主轴，与药明/海康报告同构）---
        Scenario("p3m_lt10", "入场前3月涨幅 <10%（偏海康）", "prefer", col_lt("prior_3m", 0.10)),
        Scenario("p3m_10_30", "入场前3月涨幅 10%–30%", "baseline", col_between("prior_3m", 0.10, 0.30)),
        Scenario("p3m_ge30", "入场前3月涨幅 ≥30%（偏药明）", "avoid", col_ge("prior_3m", 0.30)),
        Scenario("p3m_ge50", "入场前3月涨幅 ≥50%", "avoid", col_ge("prior_3m", 0.50)),
        # --- prior 1m / 6m ---
        Scenario("p1m_lt05", "入场前1月涨幅 <5%", "prefer", col_lt("prior_1m", 0.05)),
        Scenario("p1m_ge15", "入场前1月涨幅 ≥15%（短线追高）", "avoid", col_ge("prior_1m", 0.15)),
        Scenario("p6m_lt20", "入场前6月涨幅 <20%", "prefer", col_lt("prior_6m", 0.20)),
        Scenario("p6m_ge50", "入场前6月涨幅 ≥50%", "avoid", col_ge("prior_6m", 0.50)),
        # --- 拥挤度 ---
        Scenario("crowd_le3", "同族拥挤度 ≤3", "prefer", lambda d: d["crowd"] <= 3),
        Scenario("crowd_ge5", "同族拥挤度 ≥5", "avoid", lambda d: d["crowd"] >= 5),
        Scenario("crowd_ge7", "同族拥挤度 ≥7", "avoid", lambda d: d["crowd"] >= 7),
        # --- 入场日大阳 ---
        Scenario("eday_lt03", "入场日涨幅 <3%", "prefer", col_lt("entry_day_ret", 0.03)),
        Scenario("eday_ge07", "入场日涨幅 ≥7%（大阳后追）", "avoid", col_ge("entry_day_ret", 0.07)),
        # --- 相对沪深300超额 ---
        Scenario("ex300_lt0", "3月相对沪深300超额 <0", "prefer", col_lt("prior_3m_ex300", 0.0)),
        Scenario("ex300_lt10", "3月相对沪深300超额 <10%", "prefer", col_lt("prior_3m_ex300", 0.10)),
        Scenario("ex300_ge20", "3月相对沪深300超额 ≥20%", "avoid", col_ge("prior_3m_ex300", 0.20)),
        Scenario("ex300_ge40", "3月相对沪深300超额 ≥40%", "avoid", col_ge("prior_3m_ex300", 0.40)),
        # --- 组合（少量预注册交叉，不网格搜索）---
        Scenario(
            "prefer_calm",
            "冷静入场：3月<10% 且 拥挤≤3",
            "prefer",
            lambda d: (d["prior_3m"].notna() & (d["prior_3m"] < 0.10) & (d["crowd"] <= 3)),
        ),
        Scenario(
            "prefer_calm_eday",
            "冷静+非大阳：3月<10% 且 拥挤≤3 且 当日<3%",
            "prefer",
            lambda d: (
                d["prior_3m"].notna()
                & (d["prior_3m"] < 0.10)
                & (d["crowd"] <= 3)
                & d["entry_day_ret"].notna()
                & (d["entry_day_ret"] < 0.03)
            ),
        ),
        Scenario(
            "avoid_hot",
            "过热：3月≥30% 且 拥挤≥5",
            "avoid",
            lambda d: (d["prior_3m"].notna() & (d["prior_3m"] >= 0.30) & (d["crowd"] >= 5)),
        ),
        Scenario(
            "avoid_climax",
            "高潮追入：3月≥30% 且 当日≥7%",
            "avoid",
            lambda d: (
                d["prior_3m"].notna()
                & (d["prior_3m"] >= 0.30)
                & d["entry_day_ret"].notna()
                & (d["entry_day_ret"] >= 0.07)
            ),
        ),
    ]


def evaluate(df: pd.DataFrame, scenarios: List[Scenario]) -> List[Dict[str, Any]]:
    is_mask = df["entry_date"] < OOS_START
    oos_mask = df["entry_date"] >= OOS_START
    base_is = _stats(df.loc[is_mask])
    base_oos = _stats(df.loc[oos_mask])
    base_all = _stats(df)

    rows: List[Dict[str, Any]] = []
    for sc in scenarios:
        m = sc.pred(df).fillna(False)
        m_is = m & is_mask
        m_oos = m & oos_mask
        st_all = _stats(df.loc[m])
        st_is = _stats(df.loc[m_is])
        st_oos = _stats(df.loc[m_oos])

        def lift(wr, base_wr):
            if wr is None or base_wr is None:
                return None
            return float(wr - base_wr)

        # 验收：prefer 要在 OOS 上相对 baseline 仍有优势；avoid 则 OOS 仍更差
        verdict = "reject"
        note = ""
        is_lift = lift(st_is["win_rate"], base_is["win_rate"])
        oos_lift = lift(st_oos["win_rate"], base_oos["win_rate"])
        regime_flip = False
        if sc.kind in ("prefer", "avoid") and is_lift is not None and oos_lift is not None:
            # IS 与 OOS 相对 baseline 的方向相反 → 体制翻转，绝不能当规则上线
            if sc.kind == "prefer":
                regime_flip = (is_lift >= 0.01 and oos_lift <= -0.01) or (is_lift <= -0.01 and oos_lift >= 0.01)
            else:
                regime_flip = (is_lift <= -0.01 and oos_lift >= 0.01) or (is_lift >= 0.01 and oos_lift <= -0.01)

        if sc.kind == "baseline":
            verdict = "baseline"
        elif regime_flip:
            verdict = "regime_flip"
            note = f"IS lift={is_lift:+.3f} 与 OOS lift={oos_lift:+.3f} 方向相反（不可上线）"
        elif st_is["n"] < MIN_IS_N:
            verdict = "reject"
            note = f"IS n={st_is['n']} < {MIN_IS_N}"
        elif st_oos["n"] < MIN_OOS_N:
            verdict = "weak"
            note = f"OOS n={st_oos['n']} < {MIN_OOS_N}"
        else:
            is_wr, oos_wr = st_is["win_rate"], st_oos["win_rate"]
            decay = (is_wr - oos_wr) if is_wr is not None and oos_wr is not None else 1.0
            if sc.kind == "prefer":
                oos_ret_lift = None
                if st_oos["med_ret"] is not None and base_oos["med_ret"] is not None:
                    oos_ret_lift = st_oos["med_ret"] - base_oos["med_ret"]
                if decay > MAX_WR_DECAY_PP and (oos_lift or 0) < 0.02:
                    verdict = "reject"
                    note = f"OOS衰减过大 decay={decay:.3f}"
                elif (oos_lift or 0) >= 0.02 and (oos_ret_lift or 0) >= -0.005:
                    verdict = "pass"
                    note = f"OOS胜率+{oos_lift:.3f} vs baseline"
                elif (oos_lift or 0) >= 0.01:
                    verdict = "weak"
                    note = f"OOS胜率略优 +{oos_lift:.3f}"
                else:
                    verdict = "reject"
                    note = f"OOS未优于baseline lift={oos_lift}"
            elif sc.kind == "avoid":
                if (oos_lift or 0) <= -0.02:
                    verdict = "pass"
                    note = f"OOS胜率{oos_lift:.3f} vs baseline（确认应避开）"
                elif (oos_lift or 0) <= -0.01:
                    verdict = "weak"
                    note = f"OOS略差 {oos_lift:.3f}"
                else:
                    verdict = "reject"
                    note = f"OOS未显著更差 lift={oos_lift}"

        rows.append(
            {
                "scenario_id": sc.scenario_id,
                "label": sc.label,
                "kind": sc.kind,
                "verdict": verdict,
                "note": note,
                "regime_flip": regime_flip,
                "all": st_all,
                "is": st_is,
                "oos": st_oos,
                "lift_is_wr": is_lift,
                "lift_oos_wr": oos_lift,
                "lift_oos_med_ret": (
                    None
                    if st_oos["med_ret"] is None or base_oos["med_ret"] is None
                    else st_oos["med_ret"] - base_oos["med_ret"]
                ),
            }
        )

    # attach baselines for report
    meta = {
        "base_all": base_all,
        "base_is": base_is,
        "base_oos": base_oos,
    }
    return rows, meta  # type: ignore[return-value]


def _pct(x: Optional[float], digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{100.0 * float(x):.{digits}f}%"


def _pp(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{100.0 * float(x):+.1f}pt"


def write_report(
    rows: List[Dict[str, Any]],
    meta: Dict[str, Any],
    df: pd.DataFrame,
    *,
    family_key: str,
    family_title: str,
    factor_ids: List[str],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "family_key": family_key,
        "family_title": family_title,
        "family": factor_ids,
        "oos_start": str(OOS_START.date()),
        "n_events": int(len(df)),
        "n_is": int((df["entry_date"] < OOS_START).sum()),
        "n_oos": int((df["entry_date"] >= OOS_START).sum()),
        "meta": meta,
        "scenarios": rows,
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    df.to_parquet(out_dir / "events_enriched.parquet", index=False)

    def line(st: Dict[str, Any]) -> str:
        return (
            f"n={st['n']} | 20d胜率 {_pct(st['win_rate'])} | "
            f"20d中位 {_pct(st['med_ret'])} | 20d中位MDD {_pct(st['med_mdd'])} | "
            f"40d中位 {_pct(st['med_ret_40d'])}"
        )

    md: List[str] = [
        f"# {family_title} · 高胜率场景挖掘",
        "",
        "## 设定（防过拟合）",
        "",
        f"- 母体因子（{len(factor_ids)}）：`" + "` / `".join(factor_ids) + "`",
        f"- 分析单元：去重 `(code, entry_date)`，拥挤度=当日同族触发因子数",
        f"- 样本：entry≥{TRADE_START.date()}；IS < {OOS_START.date()}；OOS ≥ {OOS_START.date()}",
        f"- 事件数：全样本 **{len(df)}**（IS {(df['entry_date'] < OOS_START).sum()} / OOS {(df['entry_date'] >= OOS_START).sum()}）",
        "- 条件族：**预注册**，不搜索最优分位",
        f"- 门槛：IS n≥{MIN_IS_N}，OOS n≥{MIN_OOS_N}；prefer 需 OOS 胜率仍优于 baseline",
        "",
        "## Baseline（20 日前瞻）",
        "",
        f"- 全样本：{line(meta['base_all'])}",
        f"- IS：{line(meta['base_is'])}",
        f"- OOS：{line(meta['base_oos'])}",
        "",
        "## 场景对照表",
        "",
        "| 场景 | 类型 | 裁决 | IS n | IS胜率(提升) | OOS n | OOS胜率(提升) | OOS 20d中位 | 说明 |",
        "|------|------|------|------|--------------|-------|---------------|-------------|------|",
    ]
    for r in rows:
        md.append(
            f"| {r['label']} | {r['kind']} | **{r['verdict']}** | "
            f"{r['is']['n']} | {_pct(r['is']['win_rate'])} ({_pp(r.get('lift_is_wr'))}) | "
            f"{r['oos']['n']} | {_pct(r['oos']['win_rate'])} ({_pp(r.get('lift_oos_wr'))}) | "
            f"{_pct(r['oos']['med_ret'])} | {r['note']} |"
        )

    passed_prefer = [r for r in rows if r["kind"] == "prefer" and r["verdict"] == "pass"]
    passed_avoid = [r for r in rows if r["kind"] == "avoid" and r["verdict"] == "pass"]
    weak = [r for r in rows if r["verdict"] == "weak"]
    flips = [r for r in rows if r["verdict"] == "regime_flip"]

    md.extend(
        [
            "",
            "## 关键结论：IS 复现 ≠ 可上线",
            "",
            "训练窗里「看起来更高胜率」的条件，必须在 OOS 同向确认；"
            "若 IS/OOS 相对 baseline 的方向相反（regime_flip），一律不能当实盘过滤器。",
            "",
        ]
    )
    if flips:
        md.append("### 体制翻转（regime_flip）")
        md.append("")
        for r in flips:
            md.append(
                f"- **{r['label']}**：IS {_pp(r.get('lift_is_wr'))} → OOS {_pp(r.get('lift_oos_wr'))}；{r['note']}"
            )
        md.append("")

    md.extend(["", "## 可执行过滤规则（OOS 通过）", ""])
    if not passed_prefer and not passed_avoid:
        md.append("本轮无严格 **pass** 的规则。见下方 weak / regime_flip，勿直接当实盘开关。")
        md.append("")
    else:
        if passed_prefer:
            md.append("### 优先做（prefer）")
            md.append("")
            for r in passed_prefer:
                md.append(
                    f"- **{r['label']}**（`{r['scenario_id']}`）："
                    f"OOS 20d胜率 {_pct(r['oos']['win_rate'])}（{_pp(r.get('lift_oos_wr'))}），"
                    f"中位 {_pct(r['oos']['med_ret'])}；{r['note']}"
                )
            md.append("")
        if passed_avoid:
            md.append("### 避开 / 降权（avoid）")
            md.append("")
            for r in passed_avoid:
                md.append(
                    f"- **{r['label']}**（`{r['scenario_id']}`）："
                    f"OOS 20d胜率 {_pct(r['oos']['win_rate'])}（{_pp(r.get('lift_oos_wr'))}）；{r['note']}"
                )
            md.append("")

    if weak:
        md.extend(["### 弱确认（样本或提升不够，仅观察）", ""])
        for r in weak:
            md.append(f"- {r['label']}：{r['note']}")
        md.append("")

    md.extend(
        [
            "## 建议用法",
            "",
            "1. 信号仍用原母体因子，**不新挖参数**。",
            "2. 任何「高胜率场景」必须过 OOS；出现 regime_flip 一律不作实盘过滤。",
            "3. 换母体用同一套框架复验，只保留跨体制仍稳的条件。",
            "4. 规则需定期用新 OOS 窗复验；衰减超阈值则降级。",
            "",
            f"产物：`{out_dir.as_posix()}/results.json` ，`events_enriched.parquet`",
            "",
        ]
    )
    (out_dir / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[ok] -> {out_dir / 'SUMMARY.md'}", flush=True)


def run_family(family_key: str) -> None:
    cfg = FAMILIES[family_key]
    factor_ids: List[str] = list(cfg["factor_ids"])
    title = str(cfg["title"])
    out_dir = OUT_DIR_ROOT / f"mine_scenarios_{family_key}"
    print(f"======== FAMILY {family_key} / {title} ========", flush=True)
    raw = _load_family_legs(factor_ids)
    print(f"[legs] raw={len(raw)} factors={raw['factor_id'].nunique()}", flush=True)
    events = _crowd_by_entry(raw)
    print(f"[events] unique (code,entry)={len(events)} crowd_med={events['crowd'].median()}", flush=True)

    print("======== ENRICH PRICES ========", flush=True)
    df = enrich_features(events, PriceCache())
    if df.empty:
        raise SystemExit("no enriched events")

    scenarios = build_scenarios()
    print(f"[scenarios] n={len(scenarios)} (prespecified)", flush=True)
    rows, meta = evaluate(df, scenarios)  # type: ignore[misc]
    write_report(
        rows,
        meta,
        df,
        family_key=family_key,
        family_title=title,
        factor_ids=factor_ids,
        out_dir=out_dir,
    )

    print("======== PASS / AVOID / FLIP ========", flush=True)
    for r in rows:
        if r["verdict"] in ("pass", "weak", "regime_flip") or r["kind"] == "baseline":
            print(
                f"[{r['verdict']}] {r['kind']:7s} {r['scenario_id']:20s} "
                f"IS lift={_pp(r.get('lift_is_wr'))} OOS lift={_pp(r.get('lift_oos_wr'))} | {r['label']}",
                flush=True,
            )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Scenario mining on hung factor families")
    ap.add_argument(
        "--family",
        default="all",
        choices=["all", *FAMILIES.keys()],
        help="which mother family to mine",
    )
    args = ap.parse_args()
    keys = list(FAMILIES.keys()) if args.family == "all" else [args.family]
    for k in keys:
        run_family(k)


if __name__ == "__main__":
    main()
