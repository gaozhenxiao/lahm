"""串联 wave2 → wave3 → 按 Sharpe 裁剪弱因子并同步 Mongo。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def run(cmd: list[str]) -> None:
    print("[cmd]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def main() -> None:
    # wave2 may already be running separately; if keep file missing, run it
    w2_keep = ROOT / "data/factors/wave2_keep.json"
    if not w2_keep.exists():
        run([str(PY), "scripts/mine_wave2_driver.py"])
    else:
        print("[skip] wave2 already done", flush=True)

    run([str(PY), "scripts/mine_wave3_driver.py"])

    # prune weak factors from registry (wave2+wave3 sharpe<0.05)
    weak: list[str] = []
    good: list[str] = []
    for name in ("wave2_keep.json", "wave3_keep.json"):
        p = ROOT / "data/factors" / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        weak.extend(d.get("weak") or [])
        good.extend(d.get("good") or [])
    weak = sorted(set(weak) - set(good))
    print("GOOD:", good, flush=True)
    print("WEAK to retire:", weak, flush=True)
    (ROOT / "data/factors/wave23_prune.json").write_text(
        json.dumps({"good": sorted(set(good)), "weak": weak}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # sync builtins (weak still in FACTOR_IMPL until we edit registry; leave marker)
    run([str(PY), "scripts/sync_prune_and_mongo.py"])


if __name__ == "__main__":
    main()
