# -*- coding: utf-8 -*-
"""监视 QMT 内置策略写出的行情文件。

用法:
  .venv\\Scripts\\python.exe scripts/watch_qmt_feed.py
  .venv\\Scripts\\python.exe scripts/watch_qmt_feed.py --once
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "data" / "qmt_feed"
LATEST = FEED / "latest.json"
HB = FEED / "heartbeat.txt"


def show_once() -> int:
    print("feed_dir:", FEED)
    if HB.exists():
        print("heartbeat:", HB.read_text(encoding="utf-8", errors="replace").strip())
    else:
        print("heartbeat: (missing) — QMT 模型尚未写出")
    if not LATEST.exists():
        print("latest.json: missing")
        return 1
    raw = LATEST.read_text(encoding="utf-8", errors="replace")
    data = json.loads(raw)
    print("ts:", data.get("ts"), "source:", data.get("source"), "codes:", data.get("codes"))
    ticks = data.get("ticks") or {}
    if isinstance(ticks, dict):
        for code, tick in list(ticks.items())[:8]:
            print(" ", code, tick)
    bars = data.get("bars_1m") or {}
    if isinstance(bars, dict):
        for code, rows in list(bars.items())[:3]:
            n = len(rows) if isinstance(rows, list) else "?"
            print("  1m", code, "rows=", n, "tail=", rows[-1] if isinstance(rows, list) and rows else rows)
    if data.get("error"):
        print("error:", data["error"])
    return 0


def watch(interval: float) -> int:
    print("watching", LATEST, "every", interval, "s  (Ctrl+C quit)")
    last_mtime = None
    while True:
        if LATEST.exists():
            mtime = LATEST.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                print("-" * 60)
                show_once()
        else:
            print("waiting for", LATEST, "…")
        time.sleep(interval)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()
    FEED.mkdir(parents=True, exist_ok=True)
    if args.once:
        return show_once()
    try:
        return watch(args.interval)
    except KeyboardInterrupt:
        print("\nbye")
        return 0


if __name__ == "__main__":
    sys.exit(main())
