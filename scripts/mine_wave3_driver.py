"""第三波因子：冒烟 → 全量 → 写排名（结构同 wave2）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = ROOT / ".venv" / "Scripts" / "python.exe"

ONLY = [
    "garp_ma60",
    "roe_expand_breakout",
    "pb_below_growth",
    "quality_low_vol",
    "eps_yoy_reclaim",
    "triple_quality",
    "value_quality_mom",
    "growth_pullback_ma20",
    "cashcow_reclaim",
    "pe_pb_growth_triple",
]


def run(cmd: list[str]) -> None:
    print("[cmd]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def rank_rows(path: Path):
    from app.services.factors.factor_registry import FACTOR_IMPL

    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for k, v in data.items():
        if isinstance(v, dict) and "sharpe" in v:
            rows.append(
                (
                    k,
                    FACTOR_IMPL.get(k, {}).get("name", k),
                    v.get("total_return"),
                    v.get("annual_return"),
                    v.get("sharpe"),
                    v.get("max_drawdown"),
                    v.get("n_legs_accepted"),
                )
            )
    rows.sort(key=lambda x: -(x[4] if x[4] is not None else -999))
    return rows


def write_md(rows, path: Path, title: str) -> None:
    md = [
        title,
        "",
        "成本：佣金万一 + 印花税千一。",
        "",
        "| 排名 | 因子 | 名称 | 总收益 | 年化 | Sharpe | 最大回撤 | 腿数 |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]

    def pct(x):
        return f"{x:.1%}" if isinstance(x, (int, float)) else "—"

    for i, (fid, name, ret, ann, sh, mdd, legs) in enumerate(rows, 1):
        md.append(
            f"| {i} | `{fid}` | {name} | {pct(ret)} | {pct(ann)} | **{sh:.2f}** | {pct(mdd)} | {legs} |"
            if isinstance(sh, (int, float))
            else f"| {i} | `{fid}` | {name} | {pct(ret)} | {pct(ann)} | {sh} | {pct(mdd)} | {legs} |"
        )
    good = [r for r in rows if isinstance(r[4], (int, float)) and r[4] >= 0.15]
    weak = [r for r in rows if isinstance(r[4], (int, float)) and r[4] < 0.05]
    md += ["", "## 建议入库", ""]
    md += [f"- `{r[0]}` ({r[1]}) Sharpe={r[4]:.2f}" for r in good] or ["- （本批无 Sharpe≥0.15）"]
    md += ["", "## 暂不入库 / 观察", ""]
    md += [f"- `{r[0]}` Sharpe={r[4]:.2f}" for r in weak] or ["- （无）"]
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md), flush=True)


def main() -> None:
    only = ",".join(ONLY)
    run(
        [
            str(PY),
            "scripts/run_new_factors.py",
            "--limit",
            "40",
            "--only",
            only,
            "--out",
            "data/factors/wave3_smoke_summary.json",
        ]
    )
    smoke = rank_rows(ROOT / "data/factors/wave3_smoke_summary.json")
    print("\n=== SMOKE RANK ===", flush=True)
    for r in smoke:
        print(f"{r[0]:28} sharpe={r[4]} ret={r[2]} legs={r[6]}", flush=True)
    keep = [r[0] for r in smoke if r[4] is not None and r[4] >= 0.05]
    if len(keep) < 4:
        keep = [r[0] for r in smoke if r[4] is not None][:8]
    if not keep:
        keep = ONLY[:]
    print("FULL keep:", keep, flush=True)
    run(
        [
            str(PY),
            "scripts/run_new_factors.py",
            "--limit",
            "0",
            "--only",
            ",".join(keep),
            "--out",
            "data/factors/wave3_full_summary.json",
        ]
    )
    rows = rank_rows(ROOT / "data/factors/wave3_full_summary.json")
    write_md(rows, ROOT / "data/factors/wave3_rank.md", "# 第三波因子全量回测（沪深300，2018–2026）")
    good = [r[0] for r in rows if isinstance(r[4], (int, float)) and r[4] >= 0.15]
    weak = [r[0] for r in rows if isinstance(r[4], (int, float)) and r[4] < 0.05]
    (ROOT / "data/factors/wave3_keep.json").write_text(
        json.dumps({"good": good, "weak": weak, "all": [r[0] for r in rows]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
