"""挂机链式回测：先较大样本，再全量技术面，再全量基本面。

用法:
  python scripts/chain_factor_backtests.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(args: list[str]) -> None:
    cmd = [PY, str(ROOT / "scripts" / "run_new_factors.py"), *args]
    print(">>", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> None:
    # 1) 已有 limit100 时可由外部先跑；这里默认从技术面全量开始
    tech = [
        "low_vol_reclaim",
        "momentum_ma_pullback",
        "volume_breakout",
        "ma120_pullback",
        "turnover_dryup_bounce",
        "narrow_range_breakout",
        "gap_down_recover",
        "consecutive_down_bounce",
        "turn_surge_ma_reclaim",
        "boll_lower_reclaim",
        "new_high_pullback",
        "dual_ma_volume",
        "ret20_extreme_bounce",
        "amount_shrink_breakout",
        "pb_low_ma_reclaim",
        "pe_low_ma_reclaim",
        "double_cheap_reclaim",
        "pb_below_one_reclaim",
    ]
    funda = [
        "cheap_roe_bounce",
        "growth_breakout",
        "eps_growth_reclaim",
        "ma_trend_quality",
        "high_margin_pullback",
        "oversold_roe_bounce",
        "pead_roe_drift",
        "pe_quality_cross",
    ]
    run(["--only", ",".join(tech), "--limit", "0"])
    run(["--only", ",".join(funda), "--limit", "0"])
    print("[ok] chain done", flush=True)


if __name__ == "__main__":
    main()
