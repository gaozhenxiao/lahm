"""批量生成/补强因子说明 Markdown（选股步骤 + 真实案例 + 回测摘要）。

用法:
  python scripts/generate_factor_guides.py
  python scripts/generate_factor_guides.py --only growth_breakout,demand_pricing_break
  python scripts/generate_factor_guides.py --top 40
  python scripts/generate_factor_guides.py --all-short   # 只覆盖过简 guides
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.guide_builder import render_guide_markdown  # noqa: E402

GUIDES = ROOT / "docs" / "features" / "guides"
DATA = ROOT / "data" / "factors"
KEEP = ["new_factors_batch.md", "gross_expand_champ_tp35.md"]  # 手写精品不覆盖


def _is_short(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    substantive = text
    for marker in ("## 怎么跑", "## 产物", "```"):
        if marker in substantive:
            substantive = substantive.split(marker)[0]
    return len(substantive.strip()) < 280


def _sharpe(fid: str) -> float:
    for name in (f"{fid}_summary.json", f"{fid}_backtest.json"):
        p = DATA / name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and isinstance(d.get("sharpe"), (int, float)):
            return float(d["sharpe"])
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, dict) and isinstance(v.get("sharpe"), (int, float)):
                    return float(v["sharpe"])
    return -999.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔 factor_id")
    ap.add_argument("--top", type=int, default=0, help="按 Sharpe 取前 N 个有产物的因子")
    ap.add_argument("--all-short", action="store_true", help="覆盖所有过简 guide 文件")
    ap.add_argument("--force", action="store_true", help="覆盖已有长文档（除 KEEP）")
    args = ap.parse_args()

    targets: list[str] = []
    if args.only:
        targets = [x.strip() for x in args.only.split(",") if x.strip()]
    elif args.all_short:
        for p in sorted(GUIDES.glob("*.md")):
            if p.name in KEEP:
                continue
            if _is_short(p):
                targets.append(p.stem)
    elif args.top > 0:
        ranked = sorted(
            (( _sharpe(fid), fid) for fid in FACTOR_IMPL if (DATA / f"{fid}_trade_history.csv").exists()),
            reverse=True,
        )
        targets = [fid for sh, fid in ranked[: args.top] if sh > -900]
    else:
        # 默认：凡有成交记录的因子都生成（保证说明里有真实案例）
        for fid in FACTOR_IMPL:
            if (DATA / f"{fid}_trade_history.csv").exists():
                targets.append(fid)
        for p in sorted(GUIDES.glob("*.md")):
            if p.name not in KEEP and _is_short(p) and p.stem in FACTOR_IMPL:
                targets.append(p.stem)

    # 去重保序
    seen = set()
    uniq = []
    for t in targets:
        if t in seen or t not in FACTOR_IMPL:
            continue
        seen.add(t)
        uniq.append(t)

    GUIDES.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    for fid in uniq:
        out = GUIDES / f"{fid}.md"
        if out.name in KEEP:
            skipped += 1
            continue
        if out.exists() and not args.force and not _is_short(out) and args.only == "" and not args.all_short:
            # 默认模式：已有长文不覆盖
            if "怎么选股" in out.read_text(encoding="utf-8"):
                skipped += 1
                continue
        body = render_guide_markdown(fid, FACTOR_IMPL[fid], data_dir=DATA)
        out.write_text(body, encoding="utf-8")
        written += 1
        print(f"[ok] {fid} -> {out.relative_to(ROOT)} ({len(body)} chars)")

    print(f"done written={written} skipped={skipped} candidates={len(uniq)}")


if __name__ == "__main__":
    main()
