"""新高 / 新低 × 买入 / 卖出：按股票类型看前瞻胜率。

事件（无前视）：
  - 新高：收盘价创 N 日新高，且昨日不是新高（波段首日）
  - 新低：对称

动作：
  - 买入：事件日收盘价入场，持有 H 日后看涨跌
  - 卖出：同一入场价做空持有 H 日（收益取反；胜率=做空赚钱比例）

股票类型（互斥）：大盘 HS300 / 中盘 CSI500 不含沪深300 / 小盘 CSI1000 不含前两者

防过拟合：IS < 2024-01-01；OOS ≥ 2024-01-01；只报告 OOS 仍同向的结论。

用法：
  python scripts/research_new_high_low_by_type.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

OUT = ROOT / "data" / "factors" / "research_new_high_low_by_type"
OOS_START = pd.Timestamp("2024-01-01")
START = pd.Timestamp("2018-01-01")
WINDOWS = (60, 120, 252)
HORIZONS = (5, 10, 20)
MIN_N = 80


def _load_type_map() -> Dict[str, str]:
    shared = kit.shared_cache_dir()
    hs = set(pd.read_parquet(shared / "universe_hs300.parquet")["code"].astype(str))
    c5 = set(pd.read_parquet(shared / "universe_csi500.parquet")["code"].astype(str))
    c1 = set(pd.read_parquet(shared / "universe_csi1000.parquet")["code"].astype(str))
    out: Dict[str, str] = {}
    for c in hs:
        out[c] = "大盘(HS300)"
    for c in c5:
        if c not in out:
            out[c] = "中盘(CSI500)"
    for c in c1:
        if c not in out:
            out[c] = "小盘(CSI1000)"
    return out


def _events_for_code(code: str, stock_type: str) -> List[Dict[str, Any]]:
    path = kit.daily_parquet_path(kit.shared_cache_dir(), code)
    if not path.exists():
        return []
    df = pd.read_parquet(path, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df = df[df["date"] >= START - pd.Timedelta(days=400)].reset_index(drop=True)
    if len(df) < 300:
        return []
    close = df["close"].astype(float).to_numpy()
    dates = df["date"]
    # 60d realized vol for subtype
    ret = pd.Series(close).pct_change()
    vol60 = ret.rolling(60).std() * np.sqrt(252)

    rows: List[Dict[str, Any]] = []
    for w in WINDOWS:
        roll_max = pd.Series(close).rolling(w, min_periods=w).max().to_numpy()
        roll_min = pd.Series(close).rolling(w, min_periods=w).min().to_numpy()
        # 今日创窗内新高：close == roll_max，且严格高于「昨日为止的窗高」
        # 用 close[t] > max(close[t-w:t]) 等价于 close[t] > roll_max.shift(1)
        prior_hi = pd.Series(close).shift(1).rolling(w, min_periods=w).max().to_numpy()
        prior_lo = pd.Series(close).shift(1).rolling(w, min_periods=w).min().to_numpy()
        is_nh = close > prior_hi
        is_nl = close < prior_lo
        # 波段首日：昨日不是同向事件
        nh_first = is_nh & ~np.r_[False, is_nh[:-1]]
        nl_first = is_nl & ~np.r_[False, is_nl[:-1]]

        for kind, mask in (("新高", nh_first), ("新低", nl_first)):
            idxs = np.where(mask)[0]
            for i in idxs:
                d = pd.Timestamp(dates.iloc[i])
                if d < START:
                    continue
                px0 = float(close[i])
                if not np.isfinite(px0) or px0 <= 0:
                    continue
                v = float(vol60.iloc[i]) if i < len(vol60) and pd.notna(vol60.iloc[i]) else np.nan
                feat: Dict[str, Any] = {
                    "code": code,
                    "stock_type": stock_type,
                    "event": kind,
                    "window": w,
                    "entry_date": d,
                    "entry_price": px0,
                    "vol60": v,
                }
                for h in HORIZONS:
                    j = i + h
                    if j >= len(close):
                        feat[f"fwd_{h}d"] = np.nan
                    else:
                        feat[f"fwd_{h}d"] = float(close[j] / px0 - 1.0)
                rows.append(feat)
    return rows


def _stats(s: pd.Series) -> Dict[str, Any]:
    s = s.dropna()
    if s.empty:
        return {"n": 0, "win_rate": None, "med": None, "avg": None}
    return {
        "n": int(len(s)),
        "win_rate": float((s > 0).mean()),
        "med": float(s.median()),
        "avg": float(s.mean()),
    }


def _pct(x: Optional[float], d: int = 1) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{100.0 * float(x):.{d}f}%"


def summarize(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """对每个 (类型, 事件, 窗口, 动作) 算 IS/OOS 20日主指标 + 5/10日。"""
    rows: List[Dict[str, Any]] = []
    is_m = df["entry_date"] < OOS_START
    oos_m = df["entry_date"] >= OOS_START

    actions = (
        ("买入", 1.0),
        ("卖出", -1.0),  # 做空：收益取反
    )
    types = sorted(df["stock_type"].unique())
    for st in ["全部"] + types:
        base = df if st == "全部" else df[df["stock_type"] == st]
        for event in ("新高", "新低"):
            for w in WINDOWS:
                sub = base[(base["event"] == event) & (base["window"] == w)]
                if sub.empty:
                    continue
                for act_name, sign in actions:
                    # 主看 20d
                    def pack(mask: pd.Series) -> Dict[str, Any]:
                        part = sub.loc[mask]
                        out = {"n": int(len(part))}
                        for h in HORIZONS:
                            col = f"fwd_{h}d"
                            stt = _stats(part[col] * sign)
                            out[f"h{h}"] = stt
                        return out

                    is_s = pack(is_m.reindex(sub.index).fillna(False))
                    oos_s = pack(oos_m.reindex(sub.index).fillna(False))
                    all_s = pack(pd.Series(True, index=sub.index))

                    wr_is = (is_s.get("h20") or {}).get("win_rate")
                    wr_oos = (oos_s.get("h20") or {}).get("win_rate")
                    # 相对 50% 的优势；OOS 同向才算有用
                    edge_is = None if wr_is is None else wr_is - 0.5
                    edge_oos = None if wr_oos is None else wr_oos - 0.5
                    verdict = "reject"
                    note = ""
                    if (is_s["n"] < MIN_N) or (oos_s["n"] < MIN_N):
                        verdict = "thin"
                        note = f"样本不足 IS={is_s['n']} OOS={oos_s['n']}"
                    elif edge_is is None or edge_oos is None:
                        verdict = "reject"
                        note = "无有效收益"
                    elif edge_is * edge_oos < 0:
                        verdict = "regime_flip"
                        note = f"IS边{edge_is:+.3f} 与 OOS边{edge_oos:+.3f} 反向"
                    elif abs(edge_oos) >= 0.03 and abs(edge_is) >= 0.01:
                        verdict = "pass"
                        note = f"OOS胜率{_pct(wr_oos)}（相对50% {edge_oos:+.1%}）"
                    elif abs(edge_oos) >= 0.015:
                        verdict = "weak"
                        note = f"OOS略偏 {_pct(wr_oos)}"
                    else:
                        verdict = "reject"
                        note = f"OOS接近掷硬币 {_pct(wr_oos)}"

                    rows.append(
                        {
                            "stock_type": st,
                            "event": event,
                            "window": w,
                            "action": act_name,
                            "verdict": verdict,
                            "note": note,
                            "is": is_s,
                            "oos": oos_s,
                            "all": all_s,
                            "edge_is_20d": edge_is,
                            "edge_oos_20d": edge_oos,
                        }
                    )

    meta = {
        "n_events": int(len(df)),
        "n_is": int(is_m.sum()),
        "n_oos": int(oos_m.sum()),
        "by_type": df.groupby("stock_type").size().to_dict(),
        "by_event": df.groupby("event").size().to_dict(),
    }
    return rows, meta


def write_report(df: pd.DataFrame, rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "events.parquet", index=False)
    (OUT / "results.json").write_text(
        json.dumps(
            {"asof": pd.Timestamp.now().isoformat(timespec="seconds"), "meta": meta, "rows": rows},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    def cell(block: Dict[str, Any], h: int = 20) -> str:
        st = block.get(f"h{h}") or {}
        return f"{_pct(st.get('win_rate'))} / {_pct(st.get('med'))} (n={st.get('n') or block.get('n')})"

    md: List[str] = [
        "# 新高 / 新低 × 买入 / 卖出 · 分股票类型",
        "",
        "## 怎么读",
        "",
        "- **新高买入**：股价刚创 N 日新高当天收盘买入，看后面赚不赚钱",
        "- **新高卖出**：同一天做空（赌回调）",
        "- **新低买入 / 新低卖出**：对称",
        "- 胜率相对 **50%**；只有 IS、OOS（2024+）同向且 OOS 明显偏离，才标 **pass**",
        "",
        f"- 事件数：{meta['n_events']}（IS {meta['n_is']} / OOS {meta['n_oos']}）",
        f"- 类型分布：{meta['by_type']}",
        "",
        "## 主表（20 日前瞻：胜率 / 中位收益）",
        "",
        "| 类型 | 事件 | 窗口 | 动作 | 裁决 | IS 20d | OOS 20d | 说明 |",
        "|------|------|------|------|------|--------|---------|------|",
    ]
    # 先输出 pass/weak，再 flip，再其它里挑 20d 窗口全部类型
    order = {"pass": 0, "weak": 1, "regime_flip": 2, "thin": 3, "reject": 4}
    show = sorted(rows, key=lambda r: (order.get(r["verdict"], 9), r["stock_type"], r["event"], r["window"], r["action"]))
    for r in show:
        if r["window"] not in (60, 120, 252):
            continue
        # 表格太大：默认只列 pass/weak/flip；reject 里只保留「全部」+120窗作对照
        if r["verdict"] == "reject" and not (r["stock_type"] == "全部" and r["window"] == 120):
            continue
        md.append(
            f"| {r['stock_type']} | {r['event']} | {r['window']}d | {r['action']} | **{r['verdict']}** | "
            f"{cell(r['is'])} | {cell(r['oos'])} | {r['note']} |"
        )

    passed = [r for r in rows if r["verdict"] == "pass"]
    weak = [r for r in rows if r["verdict"] == "weak"]
    flips = [r for r in rows if r["verdict"] == "regime_flip"]

    md.extend(["", "## 人话结论", ""])
    if not passed:
        md.append("本轮 **没有** 经得起 2024+ 外样本的强规则（pass=0）。")
    else:
        md.append("### 相对靠谱（OOS 通过）")
        md.append("")
        for r in passed:
            o20 = r["oos"]["h20"]
            md.append(
                f"- **{r['stock_type']}** · {r['event']}{r['window']}d · **{r['action']}**："
                f"OOS胜率 {_pct(o20['win_rate'])}，中位 {_pct(o20['med'])}，n={o20['n']}"
            )
        md.append("")

    if weak:
        md.append("### 弱信号（可观察）")
        md.append("")
        for r in weak:
            md.append(f"- {r['stock_type']} · {r['event']}{r['window']}d · {r['action']}：{r['note']}")
        md.append("")

    if flips:
        md.append("### 体制翻转（过去对、2024后反了，别用）")
        md.append("")
        # 只列「全部」或有代表性的
        for r in flips:
            if r["stock_type"] != "全部" and r["window"] != 120:
                continue
            md.append(
                f"- {r['stock_type']} · {r['event']}{r['window']}d · {r['action']}：{r['note']}"
            )
        md.append("")

    # 分类型对照：120日新高买入
    md.extend(
        [
            "## 快速对照：120 日新高 / 新低（OOS 20 日胜率）",
            "",
            "| 类型 | 新高→买入 | 新高→卖出 | 新低→买入 | 新低→卖出 |",
            "|------|-----------|-----------|-----------|-----------|",
        ]
    )
    for st in ["全部", "大盘(HS300)", "中盘(CSI500)", "小盘(CSI1000)"]:
        cells = []
        for event, action in (("新高", "买入"), ("新高", "卖出"), ("新低", "买入"), ("新低", "卖出")):
            hit = next(
                (
                    r
                    for r in rows
                    if r["stock_type"] == st and r["event"] == event and r["window"] == 120 and r["action"] == action
                ),
                None,
            )
            if not hit:
                cells.append("-")
            else:
                wr = (hit["oos"].get("h20") or {}).get("win_rate")
                cells.append(f"{_pct(wr)} [{hit['verdict']}]")
        md.append(f"| {st} | " + " | ".join(cells) + " |")

    md.extend(
        [
            "",
            "## 说明",
            "",
            "- 静态成分有幸存者偏差；未计涨跌停/交易成本。",
            "- 「卖出」按做空近似，实盘 T+1/融券成本会更差。",
            f"- 产物：`{OUT.as_posix()}`",
            "",
        ]
    )
    (OUT / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[ok] -> {OUT / 'SUMMARY.md'}", flush=True)


def main() -> None:
    type_map = _load_type_map()
    print(f"[universe] typed={len(type_map)}", flush=True)
    all_rows: List[Dict[str, Any]] = []
    codes = sorted(type_map.keys())
    for i, code in enumerate(codes, 1):
        if i % 200 == 0 or i == len(codes):
            print(f"[scan] {i}/{len(codes)} events_so_far={len(all_rows)}", flush=True)
        all_rows.extend(_events_for_code(code, type_map[code]))
    df = pd.DataFrame(all_rows)
    if df.empty:
        raise SystemExit("no events")
    print(
        f"[events] n={len(df)} types={df['stock_type'].value_counts().to_dict()} "
        f"events={df['event'].value_counts().to_dict()}",
        flush=True,
    )
    rows, meta = summarize(df)
    write_report(df, rows, meta)

    print("======== PASS / WEAK ========", flush=True)
    for r in rows:
        if r["verdict"] in ("pass", "weak"):
            o20 = r["oos"]["h20"]
            print(
                f"[{r['verdict']}] {r['stock_type']} {r['event']}{r['window']}d {r['action']} "
                f"OOS wr={_pct(o20['win_rate'])} med={_pct(o20['med'])} n={o20['n']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
