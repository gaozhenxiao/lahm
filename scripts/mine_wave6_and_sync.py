"""wave6 完成后裁剪并同步 Mongo。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
MARK = ROOT / "data/factors/wave6_keep.json"


def run(cmd: list[str]) -> None:
    print("[cmd]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def main() -> None:
    if not MARK.exists():
        run([str(PY), "scripts/mine_wave6_driver.py"])
    else:
        print("[skip] wave6 already done", flush=True)
    run([str(PY), "scripts/sync_prune_and_mongo.py"])
    print("[done] wave6 mined + pruned + synced", flush=True)


if __name__ == "__main__":
    main()
