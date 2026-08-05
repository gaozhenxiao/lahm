# -*- coding: utf-8 -*-
"""手动跑一轮公告监控。用法：
  .venv\\Scripts\\python.exe scripts/run_disclosure_poll.py
  .venv\\Scripts\\python.exe scripts/run_disclosure_poll.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略时段窗口")
    ap.add_argument("--lookback-days", type=int, default=1)
    ap.add_argument("--no-factors", action="store_true", help="本次不触发因子重算")
    args = ap.parse_args()

    from app.services.disclosure_monitor_service import run_disclosure_poll

    stats = run_disclosure_poll(
        force=args.force,
        lookback_days=args.lookback_days,
        trigger_factors=not args.no_factors,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
