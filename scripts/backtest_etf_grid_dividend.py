# -*- coding: utf-8 -*-
"""红利 ETF 网格回测。

用法:
  python scripts/backtest_etf_grid_dividend.py
  python scripts/backtest_etf_grid_dividend.py --v2
  python scripts/backtest_etf_grid_dividend.py --v2 --start 2019-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.strategies.etf_grid_backtest import (  # noqa: E402
    run_dividend_grid_batch,
    save_batch_outputs,
)


def _plot_compare(details: dict, out: Path, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    plotted = 0
    for code, blob in details.items():
        daily = blob.get("_daily")
        if daily is None or daily.empty:
            continue
        ax.plot(daily["date"], daily["equity"] / daily["equity"].iloc[0], label=f"{code} grid", linewidth=1.6)
        ax.plot(
            daily["date"],
            daily["bh_equity"] / daily["bh_equity"].iloc[0],
            label=f"{code} bh",
            linestyle="--",
            alpha=0.7,
            linewidth=1.1,
        )
        plotted += 1
        if plotted >= 3:
            break
    if plotted == 0:
        plt.close(fig)
        return
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--force-fetch", action="store_true")
    ap.add_argument("--no-compare", action="store_true")
    ap.add_argument("--v2", action="store_true", help="密网格+MA60 开关版")
    ap.add_argument("--v3", action="store_true", help="向上倾斜网格（中枢只上不下+底仓）")
    ap.add_argument("--n-grids", type=int, default=None)
    ap.add_argument("--step", type=float, default=None)
    ap.add_argument("--base-frac", type=float, default=None, help="v2 震荡段底仓比例")
    ap.add_argument("--min-layers", type=int, default=None, help="v3 最少保留档数")
    args = ap.parse_args()

    if args.v3:
        version = "v3"
    elif args.v2:
        version = "v2"
    else:
        version = "v1"
    params = {}
    if args.n_grids is not None:
        params["n_grids"] = args.n_grids
    if args.step is not None:
        params["step_pct"] = float(args.step)
    if args.base_frac is not None:
        params["base_frac"] = float(args.base_frac)
    if args.min_layers is not None:
        params["min_layers"] = int(args.min_layers)

    batch = run_dividend_grid_batch(
        include_compare=not args.no_compare,
        start=args.start,
        force_fetch=args.force_fetch,
        params=params or None,
        version=version,
    )
    path = save_batch_outputs(batch)
    print(f"\n[ok] summary -> {path}")
    table = batch["table"]
    if table is not None and not table.empty:
        print(f"\n=== {version} 网格 vs 买入持有 ===")
        cols = [
            c
            for c in [
                "group",
                "code",
                "name",
                "grid_cagr",
                "bh_cagr",
                "excess_cagr",
                "grid_sharpe",
                "bh_sharpe",
                "grid_max_dd",
                "n_trades",
                "regime_invested",
                "regime_cash",
                "regime_range",
                "regime_down",
            ]
            if c in table.columns
        ]
        print(table[cols].to_string(index=False))

    png = ROOT / "data" / "strategies" / f"etf_grid_dividend_nav_{version}.png"
    _plot_compare(batch["details"], png, title=f"ETF grid {version} vs buy&hold")
    slim = []
    for row in batch["payload"]["summary_table"]:
        slim.append(
            {
                k: row.get(k)
                for k in (
                    "code",
                    "name",
                    "group",
                    "grid_cagr",
                    "bh_cagr",
                    "excess_cagr",
                    "grid_sharpe",
                    "grid_max_dd",
                    "regime_invested",
                    "regime_cash",
                    "error",
                )
                if k in row or row.get("error")
            }
        )
    print("\n" + json.dumps(slim, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
