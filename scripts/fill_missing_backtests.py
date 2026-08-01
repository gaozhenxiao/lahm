"""补跑列表中缺回测产物的因子（全量 HS300）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = ROOT / ".venv" / "Scripts" / "python.exe"

ONLY = [
    "volume_breakout",
    "narrow_range_breakout",
    "turn_surge_ma_reclaim",
    "boll_lower_reclaim",
    "new_high_pullback",
    "dual_ma_volume",
    "ret20_extreme_bounce",
    "amount_shrink_breakout",
]


def main() -> None:
    only = ",".join(ONLY)
    cmd = [
        str(PY),
        "scripts/run_new_factors.py",
        "--limit",
        "0",
        "--only",
        only,
        "--out",
        "data/factors/fill_missing_backtest_summary.json",
    ]
    print("[cmd]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(p.returncode)

    # 补净值图（若 matplotlib 可用）
    from pathlib import Path as P

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    factors = ROOT / "data" / "factors"
    for fid in ONLY:
        csv = factors / f"{fid}_backtest.csv"
        png = factors / f"{fid}_equity_curve.png"
        if not csv.exists():
            print(f"[skip plot] no csv {fid}", flush=True)
            continue
        df = pd.read_csv(csv, parse_dates=["date"])
        if "equity" not in df.columns:
            continue
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        axes[0].plot(df["date"], df["equity"], label=fid, color="#1f4e79")
        if "bench_ret" in df.columns:
            bh = (1 + df["bench_ret"].fillna(0)).cumprod()
            axes[0].plot(df["date"], bh, label="bench", color="#999999", alpha=0.85)
        axes[0].legend(loc="upper left")
        axes[0].set_title(fid)
        axes[0].grid(True, alpha=0.25)
        if "position" in df.columns:
            axes[1].fill_between(df["date"], 0, df["position"].fillna(0), color="#2a9d8f", alpha=0.55)
            axes[1].set_ylim(0, 1.05)
        axes[1].set_ylabel("exposure")
        axes[1].grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(png, dpi=120)
        plt.close(fig)
        print(f"[ok] plot {png.name}", flush=True)

    summary = json.loads((ROOT / "data/factors/fill_missing_backtest_summary.json").read_text(encoding="utf-8"))
    print("\n=== FILL RESULT ===", flush=True)
    for k, v in summary.items():
        if isinstance(v, dict) and "sharpe" in v:
            print(
                f"{k:28} ret={v.get('total_return')} sharpe={v.get('sharpe')} legs={v.get('n_legs_accepted')}",
                flush=True,
            )
        else:
            print(f"{k:28} {v}", flush=True)


if __name__ == "__main__":
    main()
