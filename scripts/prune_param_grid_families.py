"""同信号结构、不同参数网格：每族最多保留 CAGR / Sharpe / 回撤 三维优胜（去重后 ≤3），其余退役。

不删 data/factors 下回测 CSV/JSON；只从 FACTOR_IMPL 移除并加入 RETIRED_FACTOR_IDS，再同步 Mongo。

用法:
  .\\.venv\\Scripts\\python.exe scripts/prune_param_grid_families.py --dry-run
  .\\.venv\\Scripts\\python.exe scripts/prune_param_grid_families.py
  .\\.venv\\Scripts\\python.exe scripts/prune_param_grid_families.py --apply --sync-mongo
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sync_prune_and_mongo import _ensure_retired, _remove_factor_blocks  # noqa: E402

DATA = ROOT / "data" / "factors"
LOG_PATH = DATA / "param_grid_family_prune.json"
CHAMPION_PATH = DATA / "overnight_champion.json"
LEADS_CACHE = DATA / "_leads_factor_book_cache.json"


def _load_metrics(fid: str) -> Optional[Dict[str, float]]:
    path = DATA / f"{fid}_backtest.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    results = raw.get("results") or {}
    if not isinstance(results, dict) or not results:
        return None
    # 优先取与 fid 同名的逻辑块，否则取第一个
    row = results.get(fid) or results.get("main")
    if row is None:
        row = next(iter(results.values()), None)
    if not isinstance(row, dict):
        return None
    ar = row.get("annual_return")
    sh = row.get("sharpe")
    dd = row.get("max_drawdown")
    if ar is None and sh is None and dd is None:
        return None
    out: Dict[str, float] = {}
    if ar is not None:
        out["annual_return"] = float(ar)
    if sh is not None:
        out["sharpe"] = float(sh)
    if dd is not None:
        out["max_drawdown"] = float(dd)
    if "total_return" in row and row["total_return"] is not None:
        out["total_return"] = float(row["total_return"])
    return out if out else None


def _pick_best(
    candidates: List[Tuple[str, Dict[str, float]]],
    key: str,
    *,
    higher_better: bool,
    tie_keys: List[Tuple[str, bool]],
) -> Optional[str]:
    usable = [(fid, m) for fid, m in candidates if key in m]
    if not usable:
        return None

    def sort_key(item: Tuple[str, Dict[str, float]]):
        fid, m = item
        primary = m[key]
        # higher_better → negate for ascending sort of "rank" so we take last? Use reverse.
        parts: List[Any] = [primary if higher_better else -primary]
        for tk, th in tie_keys:
            v = m.get(tk)
            if v is None:
                parts.append(float("-inf") if th else float("inf"))
            else:
                parts.append(v if th else -v)
        parts.append(fid)  # stable
        return tuple(parts)

    usable.sort(key=sort_key, reverse=True)
    return usable[0][0]


def select_family_winners(
    members: List[str],
    metrics: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """返回 keep / retire / winners_by_dim / no_data。"""
    with_data = [(fid, metrics[fid]) for fid in members if fid in metrics]
    no_data = sorted(fid for fid in members if fid not in metrics)

    # 单成员族：有数据或无数据都保留（非网格炮灰）
    if len(members) == 1:
        return {
            "keep": list(members),
            "retire": [],
            "winners_by_dim": {
                "annual_return": members[0] if members[0] in metrics else None,
                "sharpe": members[0] if members[0] in metrics else None,
                "max_drawdown": members[0] if members[0] in metrics else None,
            },
            "no_data": no_data,
            "singleton": True,
        }

    # 多成员：无数据一律不进优胜；从有数据里按三维各取 1，去重
    best_ar = _pick_best(
        with_data,
        "annual_return",
        higher_better=True,
        tie_keys=[("sharpe", True), ("max_drawdown", True)],
    )
    best_sh = _pick_best(
        with_data,
        "sharpe",
        higher_better=True,
        tie_keys=[("annual_return", True), ("max_drawdown", True)],
    )
    # max_drawdown 多为负：代数最大 = 回撤最浅
    best_dd = _pick_best(
        with_data,
        "max_drawdown",
        higher_better=True,
        tie_keys=[("sharpe", True), ("annual_return", True)],
    )

    winners_by_dim = {
        "annual_return": best_ar,
        "sharpe": best_sh,
        "max_drawdown": best_dd,
    }
    keep_set = {x for x in (best_ar, best_sh, best_dd) if x}
    # 全族无回测：全部退休（网格炮灰）
    if not keep_set:
        return {
            "keep": [],
            "retire": sorted(members),
            "winners_by_dim": winners_by_dim,
            "no_data": no_data,
            "singleton": False,
            "note": "no_backtest_in_family",
        }

    keep = sorted(keep_set)
    retire = sorted(set(members) - keep_set)
    return {
        "keep": keep,
        "retire": retire,
        "winners_by_dim": winners_by_dim,
        "no_data": no_data,
        "singleton": False,
    }


def build_plan() -> Dict[str, Any]:
    from app.services.factors.factor_registry import FACTOR_IMPL

    families: Dict[str, List[str]] = defaultdict(list)
    meta_snap: Dict[str, Dict[str, Any]] = {}
    for fid, meta in FACTOR_IMPL.items():
        sig = meta.get("signal")
        sig_name = getattr(sig, "__name__", None) or f"__unknown__:{fid}"
        families[sig_name].append(fid)
        meta_snap[fid] = {
            "name": meta.get("name"),
            "title": meta.get("title"),
            "tags": meta.get("tags") or [],
            "signal": sig_name,
        }

    metrics: Dict[str, Dict[str, float]] = {}
    for fid in FACTOR_IMPL:
        m = _load_metrics(fid)
        if m:
            metrics[fid] = m

    family_reports: List[Dict[str, Any]] = []
    keep_all: List[str] = []
    retire_all: List[str] = []

    for sig_name in sorted(families):
        members = sorted(families[sig_name])
        sel = select_family_winners(members, metrics)
        keep_all.extend(sel["keep"])
        retire_all.extend(sel["retire"])
        report = {
            "signal": sig_name,
            "size": len(members),
            "members": members,
            "keep": sel["keep"],
            "retire": sel["retire"],
            "winners_by_dim": sel["winners_by_dim"],
            "no_data": sel["no_data"],
            "singleton": sel.get("singleton", False),
            "keep_metrics": {k: metrics.get(k) for k in sel["keep"]},
        }
        if sel.get("note"):
            report["note"] = sel["note"]
        family_reports.append(report)

    # 只对「多成员族」产生的退休做裁剪；单成员 keep 已计入
    multi = [f for f in family_reports if not f["singleton"]]
    multi_retire = sorted({fid for f in multi for fid in f["retire"]})
    multi_keep = sorted({fid for f in multi for fid in f["keep"]})

    return {
        "asof": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "rule": {
            "group_by": "FACTOR_IMPL[fid]['signal'].__name__",
            "dims": ["annual_return(max)", "sharpe(max)", "max_drawdown(max=浅)", "dedupe"],
            "no_data": "不得入选优胜；多成员族中无数据成员退役",
            "singleton": "唯一信号结构保留（无论有无回测）",
            "tie_break": "主指标相等时依次用次维 + factor_id",
        },
        "summary": {
            "active_before": len(FACTOR_IMPL),
            "families_total": len(family_reports),
            "families_multi": len(multi),
            "families_singleton": len(family_reports) - len(multi),
            "keep_total": len(set(keep_all)),
            "retire_total": len(multi_retire),
            "active_after": len(FACTOR_IMPL) - len(multi_retire),
            "multi_keep": len(multi_keep),
            "with_metrics": len(metrics),
            "without_metrics": len(FACTOR_IMPL) - len(metrics),
        },
        "keep": sorted(set(keep_all)),
        "retire": multi_retire,
        "families": family_reports,
        "meta": meta_snap,
    }


def _update_champion_if_retired(retire: List[str], keep: List[str]) -> Optional[Dict[str, Any]]:
    if not CHAMPION_PATH.exists():
        return None
    raw = json.loads(CHAMPION_PATH.read_text(encoding="utf-8"))
    champ = raw.get("champion") or {}
    cid = str(champ.get("id") or "")
    if not cid or cid not in retire:
        return {"action": "unchanged", "champion_id": cid}

    # 在仍活跃（keep）且有回测的因子里按 sharpe 重选
    best_id = None
    best_sh = float("-inf")
    best_m: Dict[str, float] = {}
    for fid in keep:
        m = _load_metrics(fid)
        if not m or "sharpe" not in m:
            continue
        if m["sharpe"] > best_sh or (m["sharpe"] == best_sh and (best_id is None or fid < best_id)):
            best_sh = m["sharpe"]
            best_id = fid
            best_m = m

    if not best_id:
        return {"action": "champion_retired_no_replacement", "old": cid}

    from app.services.factors.factor_registry import FACTOR_IMPL

    meta = FACTOR_IMPL.get(best_id) or {}
    sig = meta.get("signal")
    new_champ = {
        "id": best_id,
        "name": meta.get("name"),
        "signal": getattr(sig, "__name__", None),
        "sharpe": best_m.get("sharpe"),
        "total_return": best_m.get("total_return"),
        "annual_return": best_m.get("annual_return"),
        "max_drawdown": best_m.get("max_drawdown"),
        "params": {
            k: v
            for k, v in (meta.get("params") or {}).items()
            if k
            not in {
                "universe",
                "price_start",
                "max_positions",
                "commission_rate",
                "stamp_tax_sell",
                "request_interval_sec",
                "bench_code",
            }
        },
        "artifacts": {
            "backtest_json": f"data/factors/{best_id}_backtest.json",
            "equity_curve": f"data/factors/{best_id}_equity_curve.png",
            "trade_history": f"data/factors/{best_id}_trade_history.csv",
        },
        "note": f"原冠军 {cid} 因参数网格族裁剪退役，按活跃因子最高 Sharpe 重选",
    }
    raw["previous_champion"] = {
        "id": cid,
        "name": champ.get("name"),
        "sharpe": champ.get("sharpe"),
        "note": "retired by param_grid_family_prune",
    }
    raw["champion"] = new_champ
    raw["asof"] = datetime.now().date().isoformat()
    findings = list(raw.get("findings") or [])
    findings.insert(
        0,
        f"参数网格族裁剪：原冠军 {cid} 退役，新冠军 {best_id}（sharpe={best_m.get('sharpe')}）",
    )
    raw["findings"] = findings[:12]
    CHAMPION_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"action": "repointed", "old": cid, "new": best_id, "sharpe": best_m.get("sharpe")}


def apply_plan(plan: Dict[str, Any], *, sync_mongo: bool) -> None:
    weak = list(plan["retire"])
    if not weak:
        print("[apply] nothing to retire")
    else:
        reg = ROOT / "app/services/factors/factor_registry.py"
        reg.write_text(_remove_factor_blocks(reg.read_text(encoding="utf-8"), weak), encoding="utf-8")
        svc = ROOT / "app/services/factors_service.py"
        svc.write_text(_ensure_retired(svc.read_text(encoding="utf-8"), weak), encoding="utf-8")
        print(f"[apply] removed {len(weak)} from registry + RETIRED_FACTOR_IDS")

    import app.services.factors.factor_registry as fr
    import app.services.factors_service as fs

    importlib.reload(fr)
    importlib.reload(fs)

    champ_info = _update_champion_if_retired(weak, list(fr.FACTOR_IMPL.keys()))
    plan["champion_update"] = champ_info
    print("[champion]", champ_info)

    if LEADS_CACHE.exists():
        LEADS_CACHE.unlink()
        print(f"[cache] deleted {LEADS_CACHE.name}")

    LOG_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[log] {LOG_PATH}")

    if sync_mongo:
        from pymongo import MongoClient

        from app.core.config import settings

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
            print(f"{name}: builtins={len(fs.BUILTIN_FACTORS)} registry={len(fr.FACTOR_IMPL)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只写日志与打印，不改 registry")
    ap.add_argument("--apply", action="store_true", help="执行退役")
    ap.add_argument("--sync-mongo", action="store_true", help="apply 后同步 Mongo")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True  # 默认安全

    plan = build_plan()
    s = plan["summary"]
    print(
        f"families={s['families_total']} (multi={s['families_multi']}, singleton={s['families_singleton']}) "
        f"active {s['active_before']} -> {s['active_after']} retire={s['retire_total']}"
    )

    # 打印多成员族摘要
    for fam in plan["families"]:
        if fam["singleton"]:
            continue
        w = fam["winners_by_dim"]
        print(
            f"  [{fam['signal']}] n={fam['size']} keep={fam['keep']} "
            f"ar={w['annual_return']} sh={w['sharpe']} dd={w['max_drawdown']} "
            f"retire={len(fam['retire'])}"
        )

    LOG_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[log] wrote {LOG_PATH}")

    if args.apply:
        apply_plan(plan, sync_mongo=args.sync_mongo)
    else:
        print("[dry-run] no registry changes; re-run with --apply [--sync-mongo]")


if __name__ == "__main__":
    main()
