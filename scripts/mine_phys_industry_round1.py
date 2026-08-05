"""物理结构 × 行业样本挖掘 Round1。

在证监会行业池内复用固定出场的物理信号（收现/转固/应付/资本开支/CFO加速）。
行业池是样本设计（机制更干净处估预测力），核心排序仍是时间外推
（tw_score / recent2y），不是「从 A 标的拓展到 B 标的」。

- 行业来源：BaoStock `query_stock_industry`（缓存 `_shared/industry_map.parquet`）
- 宇宙文件：`_shared/universe_ind_<slug>.parquet`（可供 FACTOR_IMPL 复用）
- 出场冻结：hold40 / sl12 / tp30 / lag28 / brk60
- 产物：`data/factors/mine_phys_industry_round1/`

用法:
  .venv\\Scripts\\python.exe scripts/mine_phys_industry_round1.py
  .venv\\Scripts\\python.exe scripts/mine_phys_industry_round1.py --industries C39,C38,C36 --skip-build
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mine_phys_struct_round1 as phys  # noqa: E402
import mine_profit_causal_round1 as base  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.runner import prepare_shared_panel  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_phys_industry_round1"
base.OUT_ROOT = OUT_ROOT
base.TOP_N = 6
base.MIN_ACCEPTED_LEGS = 15

# 物理相关优先行业（证监会门类代码前缀 → 展示名）
DEFAULT_INDUSTRIES: List[Tuple[str, str]] = [
    ("C39", "计算机通信电子设备"),
    ("C38", "电气机械器材"),
    ("C35", "专用设备"),
    ("C34", "通用设备"),
    ("C36", "汽车制造"),
    ("C26", "化学原料制品"),
    ("C27", "医药制造"),
    ("C32", "有色金属冶炼"),
    ("I65", "软件和信息技术"),
    ("C37", "铁路船舶航空航天"),
]


def _slug(code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", code.lower())


def _universe_id(ind_code: str) -> str:
    return f"ind_{_slug(ind_code)}"


def _write_industry_universe(ind_code: str, codes: List[str], cache_dir: Path) -> Path:
    uid = _universe_id(ind_code)
    fp = cache_dir / f"universe_{uid}.parquet"
    pd.DataFrame({"code": codes}).to_parquet(fp, index=False)
    return fp


def load_industry_pools(
    *,
    force: bool = False,
    prefixes: Optional[List[str]] = None,
    min_n: int = 60,
) -> List[Dict[str, Any]]:
    cache = kit.shared_cache_dir()
    lim = kit.RateLimiter(0.05)
    ind = kit.fetch_industry_map(lim, cache, force=force)
    if ind is None or ind.empty or "industry" not in ind.columns:
        raise RuntimeError("industry_map empty")
    ind = ind.copy()
    ind["code"] = ind["code"].astype(str)
    ind["industry"] = ind["industry"].astype(str)
    # 提取门类代码：C39计算机… → C39
    ind["ind_code"] = ind["industry"].str.extract(r"^([A-Z]\d{2})", expand=False)
    ind["ind_name"] = ind["industry"].str.replace(r"^[A-Z]\d{2}", "", regex=True)

    want = {p.upper() for p in (prefixes or [a for a, _ in DEFAULT_INDUSTRIES])}
    pools: List[Dict[str, Any]] = []
    for code, g in ind.groupby("ind_code"):
        if not code or str(code) not in want:
            continue
        codes = kit.drop_st_codes(g["code"].astype(str).tolist())
        if len(codes) < min_n:
            print(f"[skip] {code} n={len(codes)} < {min_n}", flush=True)
            continue
        name = str(g["ind_name"].iloc[0] or code)
        uid = _universe_id(str(code))
        _write_industry_universe(str(code), codes, cache)
        pools.append(
            {
                "ind_code": str(code),
                "ind_name": name,
                "universe": uid,
                "n": len(codes),
                "codes": codes,
                "label": next((n for c, n in DEFAULT_INDUSTRIES if c == code), name),
            }
        )
        print(f"[pool] {code} {name}: n={len(codes)} universe={uid}", flush=True)
    pools.sort(key=lambda x: -int(x["n"]))
    return pools


def _phys_grid_for_universe(universe: str, bench: str) -> List[base.GridRow]:
    """复用 phys round1 网格，但改宇宙/基准。"""
    rows: List[base.GridRow] = []
    for cfg_id, family, fn, extra, np_, ng, nf, nb in phys._grid():
        e = dict(extra)
        e["universe"] = universe
        e["bench_code"] = bench
        # 行业池更小：略放宽最低腿数依赖，仍固定出场
        rows.append((cfg_id, family, fn, e, np_, ng, nf, nb))
    return rows


def mine_industry(pool: Dict[str, Any]) -> Dict[str, Any]:
    universe = pool["universe"]
    codes = pool["codes"]
    print(f"\n======== industry {pool['ind_code']} {pool['label']} n={pool['n']} ========", flush=True)
    base_params = {
        **base._base("hs300"),
        "universe": universe,
        "bench_code": "sh.000300",
        "_codes": codes,
    }
    grid = _phys_grid_for_universe(universe, "sh.000300")
    panel = prepare_shared_panel(
        base_params,
        need_profit=True,
        need_growth=False,
        need_fin_db=True,
        need_balance=False,
        limit=0,
        codes=codes,
    )
    print(f"[panel] {universe} n={len(panel)}", flush=True)

    cache = kit.shared_cache_dir()
    bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path) if bench_path.exists() else pd.DataFrame()
    if not bench.empty and "date" in bench.columns:
        bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    results: List[Dict[str, Any]] = []
    for i, (cfg_id, family, fn, extra, *_rest) in enumerate(grid, 1):
        # cfg 加上行业前缀，避免跨行业撞名
        full_id = f"{pool['ind_code'].lower()}__{cfg_id}"
        params = {**base_params, **extra, "_codes": codes, "universe": universe}
        print(f"  [{i}/{len(grid)}] {full_id}", flush=True)
        try:
            row = base._eval_one(full_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": full_id,
                "family": family,
                "universe": universe,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "rejected": True,
            }
        row["ind_code"] = pool["ind_code"]
        row["ind_name"] = pool["label"]
        results.append(row)
        print(
            f"    tw={row.get('tw_score')} sh={row.get('sharpe')} "
            f"r2y={row.get('recent2y_sharpe')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('overfit_flags')}",
            flush=True,
        )
        udir = OUT_ROOT / universe
        udir.mkdir(parents=True, exist_ok=True)
        (udir / "results_partial.json").write_text(
            json.dumps({"universe": universe, "pool": {k: pool[k] for k in ("ind_code", "ind_name", "n", "label")}, "all": results}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    ranked = sorted(results, key=base._rank_key, reverse=True)
    ok_clean = [
        r
        for r in ranked
        if r.get("ok")
        and not r.get("rejected")
        and not any(str(f).startswith("few_legs") or str(f).startswith("sus_") for f in (r.get("overfit_flags") or []))
    ]
    top = ok_clean[: base.TOP_N]
    payload = {
        "universe": universe,
        "ind_code": pool["ind_code"],
        "ind_name": pool["label"],
        "n_codes": pool["n"],
        "n_panel": len(panel),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "top": top,
        "all": results,
    }
    udir = OUT_ROOT / universe
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        f"# Industry Phys · {pool['ind_code']} {pool['label']}",
        "",
        f"- n_codes={pool['n']} panel={len(panel)}",
        "",
        "| cfg | tw | sh | r2y | legs |",
        "|-----|----|----|-----|------|",
    ]
    for r in top:
        lines.append(
            f"| `{r.get('cfg_id')}` | {base._fmt(r.get('tw_score'))} | "
            f"{base._fmt(r.get('sharpe'))} | {base._fmt(r.get('recent2y_sharpe'))} | "
            f"{r.get('n_legs_accepted')} |"
        )
    (udir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def write_round_summary(all_ind: Dict[str, Dict[str, Any]]) -> Path:
    lines = [
        "# 物理结构 × 行业范围挖掘 · Round1",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 原则：固定出场；换行业范围验证结构可迁移性",
        "",
    ]
    # 全局 top
    flat = []
    for p in all_ind.values():
        for r in p.get("all") or []:
            if r.get("ok") and not r.get("rejected"):
                flat.append(r)
    flat = sorted(flat, key=base._rank_key, reverse=True)
    lines += [
        "## 全局 Top15（跨行业）",
        "",
        "| cfg | industry | tw | sh | r2y | legs |",
        "|-----|----------|----|----|-----|------|",
    ]
    for r in flat[:15]:
        lines.append(
            f"| `{r.get('cfg_id')}` | {r.get('ind_code')} {r.get('ind_name')} | "
            f"{base._fmt(r.get('tw_score'))} | {base._fmt(r.get('sharpe'))} | "
            f"{base._fmt(r.get('recent2y_sharpe'))} | {r.get('n_legs_accepted')} |"
        )
    lines.append("")
    for uid, p in all_ind.items():
        lines.append(f"### {p.get('ind_code')} {p.get('ind_name')} (n={p.get('n_codes')})")
        lines.append("")
        for r in (p.get("top") or [])[:5]:
            lines.append(
                f"- `{r.get('cfg_id')}` tw={base._fmt(r.get('tw_score'))} "
                f"sh={base._fmt(r.get('sharpe'))} r2y={base._fmt(r.get('recent2y_sharpe'))} "
                f"legs={r.get('n_legs_accepted')}"
            )
        lines.append("")
    path = OUT_ROOT / "ROUND_SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "all_results.json").write_text(
        json.dumps({"built_at": datetime.now().isoformat(timespec="seconds"), "results": flat}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--industries", default="", help="逗号分隔门类代码，如 C39,C38；空=默认清单")
    ap.add_argument("--min-n", type=int, default=80)
    ap.add_argument("--force-industry", action="store_true")
    ap.add_argument("--limit-industries", type=int, default=0, help="只跑前 N 个行业（按规模）")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    prefixes = [x.strip().upper() for x in args.industries.split(",") if x.strip()] or None
    pools = load_industry_pools(force=args.force_industry, prefixes=prefixes, min_n=args.min_n)
    if args.limit_industries and args.limit_industries > 0:
        pools = pools[: args.limit_industries]
    print(f"[industries] n={len(pools)}", flush=True)

    all_ind: Dict[str, Dict[str, Any]] = {}
    for pool in pools:
        all_ind[pool["universe"]] = mine_industry(pool)

    summary = write_round_summary(all_ind)
    print(f"[done] {summary}", flush=True)


if __name__ == "__main__":
    main()
