"""等 wave2 完成后再跑 wave3 + 裁剪同步。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
W2 = ROOT / "data/factors/wave2_keep.json"


def run(cmd: list[str]) -> None:
    print("[cmd]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def main() -> None:
    print("[wait] wave2_keep.json ...", flush=True)
    while not W2.exists():
        time.sleep(30)
        print(f"[wait] still ... {time.strftime('%H:%M:%S')}", flush=True)
    print("[ok] wave2 done", flush=True)
    run([str(PY), "scripts/mine_wave3_driver.py"])
    run([str(PY), "scripts/sync_prune_and_mongo.py"])
    print("[done] wave2+wave3 mined, pruned, synced", flush=True)


if __name__ == "__main__":
    main()
