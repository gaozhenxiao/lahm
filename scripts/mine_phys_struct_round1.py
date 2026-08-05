"""物理世界结构因子 Round1：固定出场，少参数，换结构故事。

物理信息（本地财务库）：
- 销售收现比 = 销售商品收现 / 营收
- 在建工程转固 = CIP↓ & 固定资产↑
- 应付授信 = 应付账款/营收↑ × 营收增长
- 资本开支周期 = 购建固资等现金/营收↑ × 营收
- 经营现金流 YoY 二阶加速

出场冻结：hold=40, stop=0.12, take_profit=0.30, funda_lag=28, break_days=60
每个故事最多 2 个结构刻度 × hs300/csi500/csi1000，禁止拧出场。

用法:
  .venv\\Scripts\\python.exe scripts/mine_phys_struct_round1.py --universes hs300 --skip-build
  .venv\\Scripts\\python.exe scripts/mine_phys_struct_round1.py --skip-build
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mine_profit_causal_round1 as base  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from mine_factor_dedup import DedupIndex, build_inventory, write_inventory_markdown  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_phys_struct_round1"
base.OUT_ROOT = OUT_ROOT
base.TOP_N = 8
base.MIN_ACCEPTED_LEGS = 20


def _fixed(**more: Any) -> Dict[str, Any]:
    """统一出场；只允许改入场结构阈值。"""
    return base._exit_pack(40, sl=0.12, tp=0.30, lag=28, brk=60, entry="break", **more)


def _grid() -> List[base.GridRow]:
    rows: List[base.GridRow] = []

    # 1) 销售收现比上行（客户真金白银付款）
    for tag, extra in [
        ("cc03_ry00", _fixed(collect_improve=0.03, growth_min=0.0)),
        ("cc04_ry05_np03", _fixed(collect_improve=0.04, growth_min=0.05, np_min=0.03, collect_min=0.90)),
    ]:
        rows.append(
            (f"phys_cashcollect__{tag}", "cash_collect", sig.signal_cash_collect_up_break, extra, True, False, True, False)
        )

    # 2) 在建工程转固（产能落地）
    for tag, extra in [
        ("cip_fa_basic", _fixed(growth_min=0.0)),
        ("cip_fa_ry05", _fixed(growth_min=0.05, np_min=0.03)),
    ]:
        rows.append(
            (f"phys_cipconvert__{tag}", "cip_convert", sig.signal_cip_convert_break, extra, True, False, True, False)
        )

    # 3) 应付授信扩张（供应链融资支撑需求）
    for tag, extra in [
        ("ap015_ry06", _fixed(ap_improve=0.015, growth_min=0.06, ap_max=0.75)),
        ("ap02_ry08_np03", _fixed(ap_improve=0.02, growth_min=0.08, ap_max=0.65, np_min=0.03)),
    ]:
        rows.append(
            (f"phys_apcredit__{tag}", "ap_credit", sig.signal_ap_credit_rev_break, extra, True, False, True, False)
        )

    # 4) 资本开支扩张周期
    for tag, extra in [
        ("cx02_ry05", _fixed(capex_improve=0.02, growth_min=0.05)),
        ("cx03_ry06_acc03", _fixed(capex_improve=0.03, growth_min=0.06, growth_accel=0.03, np_min=0.03)),
    ]:
        rows.append(
            (f"phys_capex__{tag}", "capex_cycle", sig.signal_capex_cycle_break, extra, True, False, True, False)
        )

    # 5) 经营现金流 YoY 再加速
    for tag, extra in [
        ("cfoacc08_y05", _fixed(cfo_accel=0.08, cfo_yoy_min=0.05)),
        ("cfoacc10_y08_np03", _fixed(cfo_accel=0.10, cfo_yoy_min=0.08, np_min=0.03)),
    ]:
        rows.append(
            (f"phys_cfoaccel__{tag}", "cfo_yoy_accel", sig.signal_cfo_yoy_accel_break, extra, True, False, True, False)
        )

    return rows


base._grid = _grid  # type: ignore[assignment]


def write_phys_summary(all_univ: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# 物理世界结构挖掘 · Round1",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 原则：**换结构故事，不拧出场**（hold40 / sl12 / tp30 / lag28 / brk60）",
        "- 物理字段：`fin_cash_collect` / `fin_cip*` / `fin_ap_to_rev` / `fin_capex_to_rev` / `fin_cfo_yoy`",
        "",
        "| family | 物理含义 | signal |",
        "|--------|----------|--------|",
        "| cash_collect | 销售收现比上行 | `signal_cash_collect_up_break` |",
        "| cip_convert | 在建工程转固 | `signal_cip_convert_break` |",
        "| ap_credit | 应付/营收↑×营收增长 | `signal_ap_credit_rev_break` |",
        "| capex_cycle | 资本开支强度↑ | `signal_capex_cycle_break` |",
        "| cfo_yoy_accel | 经营现金流 YoY 二阶 | `signal_cfo_yoy_accel_break` |",
        "",
        "## 各宇宙 Top",
        "",
    ]
    for u, payload in all_univ.items():
        lines.append(f"### {u}")
        lines.append("")
        lines.append("| cfg | tw_score | sharpe | ret | r2y_sh | legs | flags |")
        lines.append("|-----|----------|--------|-----|--------|------|-------|")
        for r in (payload.get("top") or [])[:8]:
            lines.append(
                f"| `{r.get('cfg_id')}` | {base._fmt(r.get('tw_score'))} | "
                f"{base._fmt(r.get('sharpe'))} | {base._fmt(r.get('total_return'))} | "
                f"{base._fmt(r.get('recent2y_sharpe'))} | {r.get('n_legs_accepted')} | "
                f"{r.get('overfit_flags') or []} |"
            )
        lines.append("")
    path = OUT_ROOT / "ROUND_SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default="hs300,csi500,csi1000")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--force-universe", action="store_true")
    ap.add_argument("--no-dedup", action="store_true")
    args = ap.parse_args()

    univs = [u.strip() for u in args.universes.split(",") if u.strip()]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "CAUSAL_TREE.md").write_text(
        "\n".join(
            [
                "# 物理结构因果树",
                "",
                "```",
                "真实世界现金流/产能",
                " ├─ 客户付款 → 销售收现比",
                " ├─ 产能落地 → CIP↓ + FA↑",
                " ├─ 供应链授信 → AP/营收↑ + 营收增长",
                " ├─ 扩张投资 → Capex/营收↑",
                " └─ 现金利润加速 → CFO YoY 二阶",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if not args.skip_build:
        base.build_universes(force=args.force_universe)

    dedup = None
    if not args.no_dedup:
        inv = build_inventory()
        write_inventory_markdown(inv, OUT_ROOT / "dedup_inventory.md")
        dedup = DedupIndex(inv)

    grid = _grid()
    print(f"[grid] n={len(grid)} × universes={univs}", flush=True)
    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in univs:
        if u not in base.UNIVERSES:
            print(f"skip unknown universe {u}", flush=True)
            continue
        all_univ[u] = base.mine_universe(u, grid, dedup=dedup)

    summary = write_phys_summary(all_univ)
    flat = []
    for u, p in all_univ.items():
        for r in p.get("all") or []:
            flat.append(r)
    (OUT_ROOT / "all_results.json").write_text(
        json.dumps(
            {
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "n": len(flat),
                "results": flat,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[done] summary={summary}", flush=True)


if __name__ == "__main__":
    main()
