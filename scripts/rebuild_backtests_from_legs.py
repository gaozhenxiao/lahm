"""用已缓存 trade_legs 按「交易起点」重算净值与交易历史（不重跑信号）。

用法:
  python scripts/rebuild_backtests_from_legs.py
  python scripts/rebuild_backtests_from_legs.py --start 2018-01-02
  python scripts/rebuild_backtests_from_legs.py --only gross_expand_champ_tp35
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
from app.services.factors.runner import legs_to_trade_history, _trade_history_weight_mode  # noqa: E402


def _load_params(fid: str) -> dict:
    meta = FACTOR_IMPL.get(fid) or {}
    params = dict(meta.get("params") or {})
    # 产物里可能有更完整的 params（含 note 等）
    jp = kit.FACTORS_DATA / f"{fid}_backtest.json"
    if jp.exists():
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(payload.get("params"), dict):
                params = {**params, **payload["params"]}
        except Exception:  # noqa: BLE001
            pass
    # 注册表仓位开关优先，避免旧产物盖住新规则
    reg_p = meta.get("params") or {}
    for k in ("fixed_leg_weight", "position_display", "max_name_weight", "max_positions"):
        if k in reg_p:
            params[k] = reg_p[k]
    params["position_logic"] = fid
    return params


def rebuild_one(
    fid: str,
    *,
    start: str,
    end: str | None,
    bench: pd.DataFrame,
    cache_dir: Path,
    plot: bool = False,
) -> dict:
    legs_path = kit.factor_cache_dir(fid) / "trade_legs.parquet"
    if not legs_path.exists():
        return {"error": "no_trade_legs"}
    legs = pd.read_parquet(legs_path)
    if legs is None or legs.empty:
        return {"error": "empty_legs"}
    params = _load_params(fid)
    params["_cache_dir"] = str(cache_dir)
    title = str((FACTOR_IMPL.get(fid) or {}).get("title") or params.get("note") or fid)
    params["note"] = title
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=start, end=end
    )
    if daily.empty:
        return summary
    trades = legs_to_trade_history(
        accepted,
        max_positions=int(params.get("max_positions") or 8),
        weight_mode=_trade_history_weight_mode(params),
    )
    kit.write_factor_artifacts(
        fid, daily, summary, trades, params=params, title=title, plot=plot
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01", help="交易起点（含当日）")
    ap.add_argument("--end", default="", help="交易终点（含当日），默认至今")
    ap.add_argument("--only", default="", help="逗号分隔 factor_id；默认全部有 legs 的注册因子")
    ap.add_argument("--plot", action="store_true", help="同时重画净值图（默认跳过以加速）")
    args = ap.parse_args()
    end = args.end.strip() or None

    ids = list(FACTOR_IMPL.keys())
    if args.only.strip():
        ids = [x.strip() for x in args.only.split(",") if x.strip()]

    cache_dir = kit.shared_cache_dir()
    limiter = kit.RateLimiter(0.01)
    bench = kit.fetch_daily_valuation(
        "sh.000300",
        "2016-01-01",
        datetime.now().strftime("%Y-%m-%d"),
        limiter,
        cache_dir,
    )
    if bench is None or bench.empty:
        raise SystemExit("bench empty")

    results = {}
    ok = fail = skip = 0
    for i, fid in enumerate(ids, 1):
        try:
            summary = rebuild_one(
                fid,
                start=args.start,
                end=end,
                bench=bench,
                cache_dir=cache_dir,
                plot=bool(args.plot),
            )
            results[fid] = summary
            if summary.get("error"):
                skip += 1
                print(f"[{i}/{len(ids)}] skip {fid}: {summary.get('error')}", flush=True)
            else:
                ok += 1
                print(
                    f"[{i}/{len(ids)}] ok {fid}: ret={summary.get('total_return')} "
                    f"sharpe={summary.get('sharpe')} legs={summary.get('n_legs_accepted')}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            fail += 1
            results[fid] = {"error": str(exc)}
            print(f"[{i}/{len(ids)}] fail {fid}: {exc}", flush=True)

    out = kit.FACTORS_DATA / "rebuild_backtests_from_legs_summary.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] ok={ok} skip={skip} fail={fail} -> {out}", flush=True)


if __name__ == "__main__":
    main()
