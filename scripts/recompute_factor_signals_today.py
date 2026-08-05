"""全量活跃因子：按各宇宙缓存重算今日入场信号，汇总机会列表。

不走 BaoStock；日线/财务优先本地 cache。
不重跑全历史回测（不做 run_factor_pipeline），只扫今日/近几日信号。

用法:
  .venv\\Scripts\\python.exe scripts/recompute_factor_signals_today.py
  .venv\\Scripts\\python.exe scripts/recompute_factor_signals_today.py --asof 2026-08-03
  .venv\\Scripts\\python.exe scripts/recompute_factor_signals_today.py --write-mongo
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import (  # noqa: E402
    enrich_with_ashare_fin,
    enrich_with_balance,
    enrich_with_growth,
    enrich_with_profit,
    prepare_price_panel,
)


SPECIAL_COMPUTE = {
    "national_team": "app.services.factors.national_team:compute_national_team_signal",
    "dip_buy": "app.services.factors.dip_buy:compute_dip_buy_signal",
    "earnings_forecast": "app.services.factors.earnings_forecast:compute_earnings_forecast_signal",
    "dividend_etf_swing": "app.services.factors.dividend_etf_swing:compute_dividend_etf_swing_signal",
    "dividend_etf_slope_grid": "app.services.factors.dividend_etf_slope_grid:compute_dividend_etf_slope_grid_signal",
    "cm_big4_slope_grid": "app.services.factors.cm_big4_slope_grid:compute_cm_big4_slope_grid_signal",
}


def _import_dotted(path: str):
    mod_name, _, attr = path.rpartition(":")
    mod = __import__(mod_name, fromlist=[attr])
    return getattr(mod, attr)


def _load_names(cache: Path) -> Dict[str, str]:
    p = cache / "stock_names.parquet"
    if not p.exists():
        return {}
    try:
        df = pd.read_parquet(p)
        if "code" not in df.columns:
            return {}
        name_col = "name" if "name" in df.columns else ("code_name" if "code_name" in df.columns else None)
        if not name_col:
            return {}
        return {
            str(r["code"]): str(r[name_col])
            for _, r in df[["code", name_col]].dropna().iterrows()
        }
    except Exception:  # noqa: BLE001
        return {}


def _force_cache_only_params(params: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    p["request_interval_sec"] = 0.01
    return p


def _build_panel(
    universe: str,
    *,
    need_profit: bool,
    need_growth: bool,
    need_balance: bool,
    need_fin_db: bool,
    base_params: Dict[str, Any],
) -> Dict[str, pd.DataFrame]:
    cache = kit.shared_cache_dir()
    kit.clear_proxy()
    params = _force_cache_only_params({**base_params, "universe": universe})
    limiter = kit.RateLimiter(0.01)
    codes = kit.fetch_universe_codes(universe, limiter, cache)
    print(f"[panel] universe={universe} codes={len(codes)} "
          f"profit={need_profit} growth={need_growth} balance={need_balance} fin={need_fin_db}",
          flush=True)
    # 强制 cache_only：不登录 BaoStock
    price_map: Dict[str, pd.DataFrame] = {}
    daily_dir = cache / "daily"
    for i, code in enumerate(codes, 1):
        fp = daily_dir / f"{code.replace('.', '_')}.parquet"
        if not fp.exists():
            continue
        try:
            raw = pd.read_parquet(fp)
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
            raw = prepare_price_panel(raw, params)
            raw["code"] = code
            if not raw.empty:
                price_map[code] = raw
        except Exception as exc:  # noqa: BLE001
            print(f"[panel] skip {code}: {exc}", flush=True)
        if i % 200 == 0:
            print(f"[panel] {universe} daily {i}/{len(codes)} loaded={len(price_map)}", flush=True)
    print(f"[panel] {universe} loaded={len(price_map)}", flush=True)
    if need_profit:
        price_map = enrich_with_profit(price_map, params, cache)
    if need_growth:
        price_map = enrich_with_growth(price_map, params, cache)
    if need_fin_db:
        price_map = enrich_with_ashare_fin(price_map, params, cache)
    if need_balance:
        sample = next(iter(price_map.values()), pd.DataFrame())
        if sample is None or "contract_liab" not in getattr(sample, "columns", []):
            price_map = enrich_with_balance(price_map, params, cache)
    return price_map


def _hits_for_factor(
    signal_fn,
    price_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    asof_dt: pd.Timestamp,
    *,
    grace_days: int = 3,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    lo = asof_dt - pd.Timedelta(days=grace_days)
    for code, px in price_map.items():
        try:
            entries = signal_fn(px, params)
        except Exception:  # noqa: BLE001
            continue
        if entries is None or getattr(entries, "empty", True):
            continue
        entries = entries.copy()
        entries["date"] = pd.to_datetime(entries["date"], errors="coerce")
        exact = entries[entries["date"] == asof_dt]
        if exact.empty:
            exact = entries[(entries["date"] >= lo) & (entries["date"] <= asof_dt)]
            if exact.empty:
                continue
            # 取最近一根
            exact = exact.sort_values("date").tail(1)
        for _, r in exact.iterrows():
            hits.append(
                {
                    "code": code,
                    "entry": str(pd.Timestamp(r["date"]).date()),
                    "note": str(r.get("note") or ""),
                }
            )
    return hits


def _extract_special_hits(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    comps = result.get("components") or {}
    if isinstance(comps, dict):
        for key in ("candidates", "hits", "signals", "picks", "matches"):
            rows = comps.get(key)
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    code = r.get("code") or r.get("symbol") or r.get("ts_code")
                    if not code:
                        continue
                    hits.append(
                        {
                            "code": str(code),
                            "entry": str(r.get("entry") or r.get("date") or result.get("asof") or ""),
                            "note": str(r.get("note") or r.get("reason") or ""),
                        }
                    )
                if hits:
                    return hits
    # 顶层列表兜底
    for key in ("candidates", "hits"):
        rows = result.get(key)
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and (r.get("code") or r.get("symbol")):
                    hits.append(
                        {
                            "code": str(r.get("code") or r.get("symbol")),
                            "entry": str(r.get("entry") or r.get("date") or ""),
                            "note": str(r.get("note") or ""),
                        }
                    )
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--grace-days", type=int, default=0, help="无精确当日信号时向前容差天数；默认 0=只要今日")
    ap.add_argument("--write-mongo", action="store_true", help="写入 factor_signals / factors.latest_*")
    ap.add_argument("--only", default="", help="逗号分隔 factor_id")
    ap.add_argument(
        "--out",
        default="data/factors/opportunity_signals_today.json",
        help="机会列表 JSON 输出路径",
    )
    ap.add_argument("--skip-special", action="store_true")
    args = ap.parse_args()

    asof = args.asof.strip() or datetime.now().strftime("%Y-%m-%d")
    asof_dt = pd.Timestamp(asof)
    cache = kit.shared_cache_dir()
    names = _load_names(cache)

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        only = [x.strip() for x in args.only.split(",") if x.strip()]
        ids = [x for x in only if x in FACTOR_IMPL]
        special_ids = [x for x in only if x in SPECIAL_COMPUTE]
    else:
        special_ids = list(SPECIAL_COMPUTE.keys()) if not args.skip_special else []

    # 按宇宙聚合最大 enrich 需求
    by_uni: Dict[str, Dict[str, bool]] = defaultdict(
        lambda: {"need_profit": False, "need_growth": False, "need_balance": False, "need_fin_db": False}
    )
    for fid in ids:
        meta = FACTOR_IMPL[fid]
        u = str((meta.get("params") or {}).get("universe") or "hs300")
        by_uni[u]["need_profit"] |= bool(meta.get("need_profit"))
        by_uni[u]["need_growth"] |= bool(meta.get("need_growth"))
        by_uni[u]["need_balance"] |= bool(meta.get("need_balance"))
        by_uni[u]["need_fin_db"] |= bool(meta.get("need_fin_db"))

    base_params = dict(next(iter(FACTOR_IMPL.values()))["params"])
    panels: Dict[str, Dict[str, pd.DataFrame]] = {}
    t0 = time.time()
    for u, needs in sorted(by_uni.items()):
        panels[u] = _build_panel(u, base_params=base_params, **needs)

    results: Dict[str, Any] = {}
    opportunity: Dict[str, List[Dict[str, Any]]] = {}
    ok = err = hits_factors = 0
    log_path = cache / "recompute_factor_signals_today_progress.jsonl"
    if log_path.exists():
        log_path.unlink()

    def _log(rec: Dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    for i, fid in enumerate(ids, 1):
        meta = FACTOR_IMPL[fid]
        params = dict(meta["params"])
        u = str(params.get("universe") or "hs300")
        panel = panels.get(u) or {}
        try:
            hits = _hits_for_factor(
                meta["signal"],
                panel,
                params,
                asof_dt,
                grace_days=int(args.grace_days),
            )
            for h in hits:
                h["name"] = names.get(h["code"], "")
            payload = {
                "factor_id": fid,
                "name": meta.get("name") or fid,
                "asof": asof,
                "signal": "buy" if hits else "neutral",
                "value": float(len(hits)),
                "components": {"candidates": hits[:50]},
                "note": f"{fid} universe={u} scanned={len(panel)} hits={len(hits)}",
                "universe": u,
                "scanned": len(panel),
                "n_hits": len(hits),
            }
            results[fid] = payload
            if hits:
                opportunity[fid] = hits
                hits_factors += 1
            ok += 1
            print(
                f"[{i}/{len(ids)}] {fid} hits={len(hits)} universe={u}",
                flush=True,
            )
            _log({"i": i, "n": len(ids), "factor_id": fid, "n_hits": len(hits), "ok": True})
        except Exception as exc:  # noqa: BLE001
            err += 1
            results[fid] = {"factor_id": fid, "error": str(exc)}
            print(f"[{i}/{len(ids)}] FAIL {fid}: {exc}", flush=True)
            _log({"i": i, "n": len(ids), "factor_id": fid, "ok": False, "err": str(exc)})

    # 特殊因子：走各自 compute_*
    for fid in special_ids:
        try:
            fn = _import_dotted(SPECIAL_COMPUTE[fid])
            # params from FACTOR_IMPL if any else empty; builtins may live only in service
            params = {}
            if fid in FACTOR_IMPL:
                params = dict(FACTOR_IMPL[fid].get("params") or {})
            else:
                try:
                    from app.services.factors_service import BUILTIN_FACTORS

                    for f in BUILTIN_FACTORS:
                        if f.get("factor_id") == fid:
                            params = dict(f.get("params") or {})
                            break
                except Exception:  # noqa: BLE001
                    params = {}
            raw = fn(params, asof)
            hits = _extract_special_hits(raw if isinstance(raw, dict) else {})
            for h in hits:
                h["name"] = names.get(str(h["code"]).replace("_", "."), h.get("name") or "")
            payload = dict(raw) if isinstance(raw, dict) else {"raw": raw}
            payload["factor_id"] = fid
            payload["n_hits"] = len(hits)
            payload["components"] = {**(payload.get("components") or {}), "candidates": hits[:50]}
            results[fid] = payload
            if hits:
                opportunity[fid] = hits
                hits_factors += 1
            ok += 1
            print(f"[special] {fid} hits={len(hits)} signal={payload.get('signal')}", flush=True)
            _log({"factor_id": fid, "n_hits": len(hits), "ok": True, "special": True})
        except Exception as exc:  # noqa: BLE001
            err += 1
            results[fid] = {"factor_id": fid, "error": str(exc), "trace": traceback.format_exc()[-500:]}
            print(f"[special] FAIL {fid}: {exc}", flush=True)
            _log({"factor_id": fid, "ok": False, "err": str(exc), "special": True})

    if args.write_mongo:
        try:
            from app.core.database import get_mongo_db
            from app.utils.timezone import now_tz
            import asyncio

            async def _write() -> None:
                db = get_mongo_db()
                for fid, payload in results.items():
                    if "error" in payload:
                        continue
                    doc = {
                        "factor_id": fid,
                        "asof": payload.get("asof") or asof,
                        "signal": payload.get("signal"),
                        "value": payload.get("value"),
                        "components": payload.get("components"),
                        "note": payload.get("note"),
                        "created_at": now_tz(),
                    }
                    await db["factor_signals"].insert_one(doc)
                    await db["factors"].update_one(
                        {"factor_id": fid},
                        {
                            "$set": {
                                "latest_signal": payload.get("signal"),
                                "latest_value": payload.get("value"),
                                "latest_asof": payload.get("asof"),
                                "updated_at": now_tz(),
                            }
                        },
                    )

            asyncio.run(_write())
            print("[mongo] wrote factor_signals + factors.latest_*", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[mongo] skip/fail: {exc}", flush=True)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "asof": asof,
        "started_elapsed_min": round((time.time() - t0) / 60, 2),
        "n_factors": len(ids) + len(special_ids),
        "ok": ok,
        "errors": err,
        "factors_with_hits": hits_factors,
        "total_hit_rows": sum(len(v) for v in opportunity.values()),
        "universes": {u: len(p) for u, p in panels.items()},
        "opportunity": {
            fid: [
                {"code": h["code"], "name": h.get("name") or "", "entry": h.get("entry"), "note": h.get("note")}
                for h in rows
            ]
            for fid, rows in opportunity.items()
        },
        "results": results,
    }
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    status = {
        "asof": asof,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_min": summary["started_elapsed_min"],
        "ok": ok,
        "errors": err,
        "factors_with_hits": hits_factors,
        "total_hit_rows": summary["total_hit_rows"],
        "out": str(out),
    }
    (cache / "recompute_factor_signals_today_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n======== 机会列表摘要 ========", flush=True)
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    for fid, rows in sorted(opportunity.items(), key=lambda x: (-len(x[1]), x[0])):
        name = (results.get(fid) or {}).get("name") or fid
        codes = ", ".join(
            f"{h['code']}{('('+h['name']+')') if h.get('name') else ''}" for h in rows[:12]
        )
        more = f" …+{len(rows)-12}" if len(rows) > 12 else ""
        print(f"  [{len(rows):3d}] {fid} | {name}: {codes}{more}", flush=True)
    print(f"\n[ok] -> {out}", flush=True)


if __name__ == "__main__":
    main()
