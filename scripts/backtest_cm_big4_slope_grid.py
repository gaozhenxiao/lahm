# -*- coding: utf-8 -*-
"""中国移动 + 中国核电 + 四大行等权倾斜网格回测。

用法:
  python scripts/backtest_cm_big4_slope_grid.py
  python scripts/backtest_cm_big4_slope_grid.py --start 2022-01-05
  python scripts/backtest_cm_big4_slope_grid.py --also-factor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.strategies.cm_big4_grid import (  # noqa: E402
    DEFAULT_PARAMS,
    DEFAULT_START,
    run_basket,
    save_batch_outputs,
)

OUT = ROOT / "data" / "strategies"
FACTORS = ROOT / "data" / "factors"


def _plot(combined, path: Path, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(combined["date"], combined["equity"], label="grid basket", color="#1f4e79", lw=1.8)
    axes[0].plot(combined["date"], combined["bh_equity"], label="buy&hold basket", color="#999", alpha=0.9)
    axes[0].legend(loc="upper left")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[1].fill_between(combined["date"], 0, combined["exposure"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("avg exposure")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def _write_factor_artifacts(batch: dict) -> None:
    from app.services.factors.cm_big4_slope_grid import FACTOR_ID, run_backtest

    FACTORS.mkdir(parents=True, exist_ok=True)
    daily, summary, trades = run_backtest(force_fetch=False)
    if summary.get("error") or daily.empty:
        print(f"[warn] factor artifacts skipped: {summary}")
        return
    daily.to_csv(FACTORS / f"{FACTOR_ID}_backtest.csv", index=False, encoding="utf-8-sig")
    if trades is not None and not trades.empty:
        trades.to_csv(FACTORS / f"{FACTOR_ID}_trade_history.csv", index=False, encoding="utf-8-sig")
    else:
        # 占位空操作历史，避免产物缺失
        (FACTORS / f"{FACTOR_ID}_trade_history.csv").write_text(
            "date,action,note\n", encoding="utf-8-sig"
        )
    payload = {
        "params": batch["payload"].get("params"),
        "results": {"cm_big4_slope_grid": summary},
        "notes": batch["payload"].get("notes") or [],
    }
    (FACTORS / f"{FACTOR_ID}_backtest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _plot(
        daily,
        FACTORS / f"{FACTOR_ID}_equity_curve.png",
        f"{FACTOR_ID} · CM+Big4 equal sleeves",
    )
    print(f"[ok] factor artifacts -> {FACTORS / FACTOR_ID}_*")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--force-fetch", action="store_true")
    ap.add_argument("--also-factor", action="store_true", help="同步写入 data/factors 产物")
    args = ap.parse_args()

    params = dict(DEFAULT_PARAMS)
    batch = run_basket(
        start=args.start,
        end=args.end,
        force=args.force_fetch,
        params=params,
        quiet=False,
    )
    if batch.get("error"):
        raise SystemExit(batch)

    OUT.mkdir(parents=True, exist_ok=True)
    path = save_batch_outputs(batch)
    print(f"\n[ok] summary -> {path}")
    _plot(
        batch["combined"],
        OUT / "cm_big4_slope_grid_equity.png",
        "CM + Big4 equal sleeves · slope-up grid vs buy&hold",
    )

    port = batch["payload"]["portfolio"]
    g, b = port["grid"], port["buy_hold"]
    print(
        json.dumps(
            {
                "start": port["start"],
                "end": port["end"],
                "grid_cagr": g.get("cagr"),
                "bh_cagr": b.get("cagr"),
                "excess_cagr": port["excess_cagr"],
                "grid_sharpe": g.get("sharpe"),
                "grid_max_dd": g.get("max_dd"),
                "bh_max_dd": b.get("max_dd"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.also_factor:
        _write_factor_artifacts(batch)


if __name__ == "__main__":
    main()
