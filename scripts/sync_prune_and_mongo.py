"""根据 wave2/wave3 keep 结果：弱因子移出 FACTOR_IMPL、加入 RETIRED，并同步 Mongo。"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

from app.core.config import settings
from app.services.factors_service import BUILTIN_FACTORS, RETIRED_FACTOR_IDS


def _remove_factor_blocks(text: str, ids: list[str]) -> str:
    for fid in ids:
        # match "fid": { ... },  with nested braces
        pattern = rf'    "{re.escape(fid)}": \{{'
        m = re.search(pattern, text)
        if not m:
            print(f"[skip] not in registry text: {fid}")
            continue
        start = m.start()
        i = m.end() - 1  # at '{'
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    # swallow trailing comma + newline
                    while end < len(text) and text[end] in " \t":
                        end += 1
                    if end < len(text) and text[end] == ",":
                        end += 1
                    if end < len(text) and text[end] == "\n":
                        end += 1
                    text = text[:start] + text[end:]
                    print(f"[rm] {fid}")
                    break
            i += 1
    return text


def _ensure_retired(text: str, ids: list[str]) -> str:
    # RETIRED_FACTOR_IDS = ( ... )
    m = re.search(r"RETIRED_FACTOR_IDS = \((.*?)\)", text, flags=re.S)
    if not m:
        print("[warn] RETIRED_FACTOR_IDS not found")
        return text
    body = m.group(1)
    existing = set(re.findall(r'"([^"]+)"', body))
    add = [i for i in ids if i not in existing]
    if not add:
        return text
    insert = "".join(f'    "{i}",\n' for i in add)
    # insert before closing
    new_body = body.rstrip() + "\n" + insert
    return text[: m.start(1)] + new_body + text[m.end(1) :]


def main() -> None:
    prune_path = ROOT / "data/factors/wave23_prune.json"
    weak: list[str] = []
    good: list[str] = []
    for name in (
        "wave2_keep.json",
        "wave3_keep.json",
        "wave4_keep.json",
        "wave5_keep.json",
        "wave6_keep.json",
        "wave7_hybrid_core_keep.json",
        "wave8_hybrid_more_keep.json",
        "wave9_contract_keep.json",
        "wave10_funda_more_keep.json",
        "wave11_winner_variants_keep.json",
        "wave12_top_neighbors_keep.json",
        "wave13_w12_variants_keep.json",
        "wave14_combo_keep.json",
        "wave15_param_tilt_keep.json",
        "wave16_winner_tilt_keep.json",
        "overnight_keep.json",
    ):
        p = ROOT / "data/factors" / name
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            weak.extend(d.get("weak") or [])
            good.extend(d.get("good") or [])
    # 冒烟阶段已淘汰 / 无腿的也退役
    for name in (
        "wave2_smoke_summary.json",
        "wave3_smoke_summary.json",
        "wave4_smoke_summary.json",
        "wave5_smoke_summary.json",
        "wave6_smoke_summary.json",
    ):
        p = ROOT / "data/factors" / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for k, v in d.items():
            if not isinstance(v, dict):
                continue
            if "error" in v:
                weak.append(k)
            elif "sharpe" in v and v["sharpe"] is not None and v["sharpe"] < 0.05:
                # 若全量又救回来则保留
                if k not in good:
                    weak.append(k)
    weak = sorted(set(weak) - set(good))
    prune_path.write_text(
        json.dumps({"good": sorted(set(good)), "weak": weak}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prune = json.loads(prune_path.read_text(encoding="utf-8"))
    weak = list(prune.get("weak") or [])
    good = list(prune.get("good") or [])
    print("good", good)
    print("weak", weak)

    if weak:
        reg = ROOT / "app/services/factors/factor_registry.py"
        reg.write_text(_remove_factor_blocks(reg.read_text(encoding="utf-8"), weak), encoding="utf-8")
        svc = ROOT / "app/services/factors_service.py"
        svc.write_text(_ensure_retired(svc.read_text(encoding="utf-8"), weak), encoding="utf-8")

    # re-import after edits
    import importlib

    import app.services.factors.factor_registry as fr
    import app.services.factors_service as fs

    importlib.reload(fr)
    importlib.reload(fs)

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    now = datetime.now()
    targets = list(dict.fromkeys([settings.MONGO_DB, "lahm"]))
    retired = list(fs.RETIRED_FACTOR_IDS)
    for name in targets:
        db = client[name]
        if retired:
            r = db["factors"].delete_many({"factor_id": {"$in": retired}})
            db["factor_signals"].delete_many({"factor_id": {"$in": retired}})
            print(f"{name}: deleted retired={r.deleted_count}")
        for f in fs.BUILTIN_FACTORS:
            payload = {**f, "status": "active", "builtin": True, "updated_at": now}
            if f.get("created_at") is None:
                payload["created_at"] = now
            db["factors"].update_one({"factor_id": f["factor_id"]}, {"$set": payload}, upsert=True)
        print(f"{name}: builtins={len(fs.BUILTIN_FACTORS)} good_present={all(g in fr.FACTOR_IMPL for g in good)}")


def sync_mongo_only() -> None:
    """只把当前内置因子 upsert 到 Mongo，不裁剪 registry。"""
    from datetime import datetime

    from pymongo import MongoClient

    from app.core.config import settings
    import app.services.factors.factor_registry as fr
    import app.services.factors_service as fs

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    now = datetime.now()
    targets = list(dict.fromkeys([settings.MONGO_DB, "lahm"]))
    for name in targets:
        db = client[name]
        for f in fs.BUILTIN_FACTORS:
            payload = {**f, "status": "active", "builtin": True, "updated_at": now}
            if f.get("created_at") is None:
                payload["created_at"] = now
            db["factors"].update_one({"factor_id": f["factor_id"]}, {"$set": payload}, upsert=True)
        print(f"{name}: synced builtins={len(fs.BUILTIN_FACTORS)} registry={len(fr.FACTOR_IMPL)}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--sync-only", action="store_true", help="只同步 Mongo，不退役弱因子")
    args = ap.parse_args()
    if args.sync_only:
        sync_mongo_only()
    else:
        main()
