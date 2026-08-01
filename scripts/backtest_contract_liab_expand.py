"""回测合同负债扩张因子并同步 Mongo。

用法:
  python scripts/backtest_contract_liab_expand.py
  python scripts/backtest_contract_liab_expand.py --limit 40
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=沪深300全量")
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()

    cmd = [
        str(PY),
        "scripts/run_new_factors.py",
        "--only",
        "contract_liab_expand",
        "--limit",
        str(args.limit),
        "--out",
        "data/factors/contract_liab_expand_summary.json",
    ]
    print("[cmd]", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
    if rc != 0:
        raise SystemExit(rc)

    # plot if csv exists
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        csv = ROOT / "data/factors/contract_liab_expand_backtest.csv"
        png = ROOT / "data/factors/contract_liab_expand_equity_curve.png"
        if csv.exists():
            df = pd.read_csv(csv, parse_dates=["date"])
            fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
            axes[0].plot(df["date"], df["equity"], color="#1f4e79", label="contract_liab_expand")
            if "bench_ret" in df.columns:
                bh = (1 + df["bench_ret"].fillna(0)).cumprod()
                axes[0].plot(df["date"], bh, color="#999999", alpha=0.85, label="bench")
            axes[0].legend(loc="upper left")
            axes[0].set_title("contract liability expand")
            axes[0].grid(True, alpha=0.25)
            if "position" in df.columns:
                axes[1].fill_between(df["date"], 0, df["position"].fillna(0), color="#2a9d8f", alpha=0.55)
                axes[1].set_ylim(0, 1.05)
            axes[1].grid(True, alpha=0.25)
            fig.tight_layout()
            fig.savefig(png, dpi=120)
            plt.close(fig)
            print(f"[ok] plot {png}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot: {exc}", flush=True)

    summary = ROOT / "data/factors/contract_liab_expand_summary.json"
    if summary.exists():
        print(summary.read_text(encoding="utf-8"), flush=True)

    if not args.no_sync:
        # upsert builtins including new factor
        rc2 = subprocess.run([str(PY), "scripts/sync_prune_and_mongo.py", "--sync-only"], cwd=str(ROOT)).returncode
        if rc2 != 0:
            raise SystemExit(rc2)
    print("[done] contract_liab_expand", flush=True)


if __name__ == "__main__":
    main()
