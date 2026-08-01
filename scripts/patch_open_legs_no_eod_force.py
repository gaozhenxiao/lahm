"""把已有 trade_legs 中「持有期被行情末日截断」的 hold_end 改为 open，并重算产物。

用法:
  python scripts/patch_open_legs_no_eod_force.py
  python scripts/patch_open_legs_no_eod_force.py --only gross_high_np_np10_m18
  python scripts/patch_open_legs_no_eod_force.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors.factor_registry import FACTOR_IMPL  # noqa: E402
from app.services.factors.runner import legs_to_trade_history  # noqa: E402

_PX_CACHE: dict[str, pd.DataFrame] = {}


def _hold_days(fid: str) -> int:
    meta = FACTOR_IMPL.get(fid) or {}
    params = dict(meta.get("params") or {})
    jp = kit.FACTORS_DATA / f"{fid}_backtest.json"
    if jp.exists():
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(payload.get("params"), dict):
                params = {**params, **payload["params"]}
        except Exception:  # noqa: BLE001
            pass
    return int(params.get("hold_days") or 20)


def _load_px(code: str, cache: Path) -> pd.DataFrame | None:
    if code in _PX_CACHE:
        return _PX_CACHE[code]
    fp = cache / f"{code.replace('.', '_')}.parquet"
    if not fp.exists():
        _PX_CACHE[code] = None  # type: ignore[assignment]
        return None
    px = pd.read_parquet(fp, columns=["date", "close"])
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    _PX_CACHE[code] = px
    return px


def patch_legs(fid: str, *, dry_run: bool = False) -> dict:
    legs_path = kit.factor_cache_dir(fid) / "trade_legs.parquet"
    if not legs_path.exists():
        return {"error": "no_trade_legs"}
    legs = pd.read_parquet(legs_path)
    if legs is None or legs.empty:
        return {"error": "empty_legs"}
    hold = _hold_days(fid)
    cache = kit.shared_cache_dir() / "daily"
    n_patch = 0
    # 只检查可能被截断的腿：hold_end 且持有交易日跨度 < hold_days
    reasons = legs["reason"].astype(str) if "reason" in legs.columns else pd.Series([""] * len(legs))
    cand_mask = reasons.isin(["hold_end", "open"])
    if not cand_mask.any():
        return {"patched_legs": 0, "hold_days": hold, "n_legs": len(legs)}

    out = legs.copy()
    for code, idx in out.loc[cand_mask].groupby(out.loc[cand_mask, "code"].astype(str)).groups.items():
        px = _load_px(str(code), cache)
        if px is None or px.empty:
            continue
        last_i = len(px) - 1
        last_dt = pd.Timestamp(px.loc[last_i, "date"])
        date_to_i = {pd.Timestamp(d): i for i, d in enumerate(px["date"])}
        for i in idx:
            reason = str(out.at[i, "reason"] or "")
            if reason not in ("hold_end", "open"):
                continue
            entry = pd.Timestamp(out.at[i, "entry_date"])
            ei = date_to_i.get(entry)
            if ei is None:
                # 找 >= entry 的首个交易日
                later = [j for d, j in date_to_i.items() if d >= entry]
                if not later:
                    continue
                ei = min(later)
            if (ei + hold) <= last_i:
                continue
            new_exit = last_dt + pd.Timedelta(days=1)
            # 已是 open 且退出日落在末日之后：跳过，避免重复重算
            if reason == "open" and pd.Timestamp(out.at[i, "exit_date"]) > last_dt:
                continue
            out.at[i, "reason"] = "open"
            out.at[i, "exit_price"] = float(px.loc[last_i, "close"])
            out.at[i, "exit_date"] = new_exit
            n_patch += 1

    if n_patch and not dry_run:
        out.to_parquet(legs_path, index=False)
    return {"patched_legs": n_patch, "hold_days": hold, "n_legs": len(legs)}


def rebuild_one(fid: str, *, start: str, bench: pd.DataFrame, cache_dir: Path) -> dict:
    legs_path = kit.factor_cache_dir(fid) / "trade_legs.parquet"
    if not legs_path.exists():
        return {"error": "no_trade_legs"}
    legs = pd.read_parquet(legs_path)
    meta = FACTOR_IMPL.get(fid) or {}
    params = dict(meta.get("params") or {})
    jp = kit.FACTORS_DATA / f"{fid}_backtest.json"
    if jp.exists():
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(payload.get("params"), dict):
                params = {**params, **payload["params"]}
        except Exception:  # noqa: BLE001
            pass
    params["position_logic"] = fid
    params["_cache_dir"] = str(cache_dir)
    title = str(meta.get("title") or params.get("note") or fid)
    params["note"] = title
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=start
    )
    if daily.empty:
        return summary
    trades = legs_to_trade_history(accepted, max_positions=int(params.get("max_positions") or 8))
    kit.write_factor_artifacts(fid, daily, summary, trades, params=params, title=title, plot=False)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔 factor_id")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true", help="只改 legs，不重算净值产物")
    args = ap.parse_args()

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]

    cache_dir = kit.shared_cache_dir()
    bench = None
    if not args.no_rebuild and not args.dry_run:
        bench = kit.fetch_daily_valuation(
            "sh.000300",
            "2016-01-01",
            datetime.now().strftime("%Y-%m-%d"),
            kit.RateLimiter(0.01),
            cache_dir,
        )

    total_patch = 0
    rebuilt = 0
    touched = 0
    for i, fid in enumerate(ids, 1):
        if i % 15 == 0:
            _PX_CACHE.clear()
        info = patch_legs(fid, dry_run=args.dry_run)
        if info.get("error"):
            continue
        n = int(info.get("patched_legs") or 0)
        if not n:
            if i % 50 == 0:
                print(f"[{i}/{len(ids)}] ...", flush=True)
            continue
        touched += 1
        total_patch += n
        print(f"[{i}/{len(ids)}] {fid}: patched={n}/{info.get('n_legs')}", flush=True)
        if not args.dry_run and not args.no_rebuild and bench is not None:
            summary = rebuild_one(fid, start=args.start, bench=bench, cache_dir=cache_dir)
            if not summary.get("error"):
                rebuilt += 1
                print(
                    f"  rebuilt sharpe={summary.get('sharpe')} ret={summary.get('total_return')}",
                    flush=True,
                )
            else:
                print(f"  rebuild skip: {summary}", flush=True)

    _PX_CACHE.clear()
    print(
        f"[done] factors_touched={touched} patched_legs={total_patch} "
        f"rebuilt={rebuilt} dry_run={args.dry_run}",
        flush=True,
    )


if __name__ == "__main__":
    main()
