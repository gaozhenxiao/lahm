"""挂机链式回测：先技术面全量，再基本面全量。

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
    tech = [
        "volume_breakout",
        "narrow_range_breakout",
        "turn_surge_ma_reclaim",
        "boll_lower_reclaim",
        "new_high_pullback",
        "dual_ma_volume",
        "ret20_extreme_bounce",
        "amount_shrink_breakout",
        "pb_low_ma_reclaim",
        "double_cheap_reclaim",
        "pb_below_one_reclaim",
    ]
    funda = [
        "growth_breakout",
        "oversold_roe_bounce",
        "pead_roe_drift",
        "pe_quality_cross",
    ]
    run(["--only", ",".join(tech), "--limit", "0"])
    run(["--only", ",".join(funda), "--limit", "0"])
    print("[ok] chain done", flush=True)


if __name__ == "__main__":
    main()
