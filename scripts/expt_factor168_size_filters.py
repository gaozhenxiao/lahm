"""因子168在 csi_core 上试：加市值 / 绝对净利门槛。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import prepare_shared_panel, run_factor_pipeline  # noqa: E402

BASE = {
    "universe": "csi_core",
    "exclude_st": True,
    "price_start": "2016-01-01",
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.006,
    "margin_min": 0.16,
    "np_min": 0.1,
    "funda_lag": 29,
    "break_days": 60,
    "hold_days": 51,
    "stop_loss": 0.12,
    "take_profit": 0.35,
}

# 市值：100亿 / 200亿 / 500亿；净利：1亿 / 5亿 / 10亿（报告期累计）
VARIANTS = [
    ("baseline", {}),
    ("np_1e8", {"net_profit_min": 1e8}),
    ("np_5e8", {"net_profit_min": 5e8}),
    ("np_1e9", {"net_profit_min": 1e9}),
    ("mv_1e10", {"mktcap_min": 1e10}),
    ("mv_2e10", {"mktcap_min": 2e10}),
    ("mv_5e10", {"mktcap_min": 5e10}),
    ("mv2e10_np5e8", {"mktcap_min": 2e10, "net_profit_min": 5e8}),
    ("mv5e10_np1e9", {"mktcap_min": 5e10, "net_profit_min": 1e9}),
]


def main() -> None:
    cache = kit.shared_cache_dir()
    codes = kit.fetch_universe_codes("csi_core", kit.RateLimiter(0.01), cache)
    print(f"[universe] csi_core={len(codes)}", flush=True)
    fill = fin_db.fill_total_share_in_profit_cache(cache / "profit", codes=codes)
    print(f"[fill-share] {fill}", flush=True)

    panel = prepare_shared_panel(BASE, need_profit=True, need_growth=False, limit=0)
    print(f"[panel] n={len(panel)}", flush=True)

    results = {}
    for tag, extra in VARIANTS:
        params = {**BASE, **extra}
        fid = f"gross_expand_m16_tp35__{tag}"
        print(f"\n======== {tag} {extra} ========", flush=True)
        summary = run_factor_pipeline(
            fid,
            f"m16 size filter {tag}",
            sig.signal_gross_expand_break,
            params,
            need_profit=True,
            limit=0,
            start="2018-01-01",
            price_map=panel,
        )
        results[tag] = {
            "params_extra": extra,
            "sharpe": summary.get("sharpe"),
            "total_return": summary.get("total_return"),
            "max_drawdown": summary.get("max_drawdown"),
            "n_legs_raw": summary.get("n_legs_raw"),
            "n_legs_accepted": summary.get("n_legs_accepted"),
            "annual_return": summary.get("annual_return"),
        }
        print(results[tag], flush=True)

    out = ROOT / "data" / "factors" / "gross_expand_m16_tp35_size_filter_expt.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] {out}", flush=True)
    # rank by sharpe
    ranked = sorted(
        results.items(),
        key=lambda kv: (kv[1].get("sharpe") is not None, kv[1].get("sharpe") or -999),
        reverse=True,
    )
    print("\n[rank by sharpe]", flush=True)
    for tag, r in ranked:
        print(
            f"  {tag}: sharpe={r.get('sharpe')} ret={r.get('total_return')} "
            f"dd={r.get('max_drawdown')} legs={r.get('n_legs_accepted')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
