"""业绩预告回调因子回测。

用法:
  python scripts/backtest_earnings_forecast_factor.py
  python scripts/backtest_earnings_forecast_factor.py --start 2019-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "factors"

from app.services.factors.earnings_forecast import (  # noqa: E402
    DEFAULT_PARAMS,
    _data_dir,
    build_trade_legs,
    collect_positive_events,
    fetch_universe_codes,
    run_portfolio_backtest,
    _RateLimiter,
)


def _plot(daily: pd.DataFrame, path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(daily["date"], daily["equity"], label="earnings_forecast", color="#1f4e79")
    bh = (1 + daily["bench_ret"].fillna(0)).cumprod()
    axes[0].plot(daily["date"], bh, label="CSI300", color="#999999", alpha=0.85)
    axes[0].legend(loc="upper left")
    axes[0].set_title("Earnings forecast dual-path: announce buy or post pullback")
    axes[0].grid(True, alpha=0.25)
    axes[1].fill_between(daily["date"], 0, daily["position"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylabel("exposure")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def _trade_history(legs: pd.DataFrame) -> pd.DataFrame:
    if legs is None or legs.empty:
        return pd.DataFrame()
    rows = []
    for _, r in legs.iterrows():
        ret = float(r["exit_price"]) / float(r["entry_price"]) - 1.0
        mode = str(r.get("entry_mode") or "pullback")
        pre_run = float(r["pre_run"]) if "pre_run" in r and pd.notna(r.get("pre_run")) else 0.0
        lt_run = float(r["lt_run"]) if "lt_run" in r and pd.notna(r.get("lt_run")) else 0.0
        tier = str(r.get("surprise_tier") or "")
        reason = str(r.get("chase_reason") or "")
        note_open = reason or (
            f"路径={mode}; 超预期={tier}; 短期{pre_run*100:.1f}%; 两年{lt_run*100:.0f}%"
        )
        rows.append(
            {
                "date": pd.Timestamp(r["entry_date"]).strftime("%Y-%m-%d"),
                "action": "开仓",
                "code": r["code"],
                "entry_mode": mode,
                "surprise_tier": tier,
                "event_pub": pd.Timestamp(r["event_pub"]).strftime("%Y-%m-%d"),
                "days_after_announce": int(r["days_after"]),
                "pre_run": f"{pre_run * 100:.2f}%",
                "lt_run": f"{lt_run * 100:.2f}%",
                "pullback": f"{float(r['pullback']) * 100:.2f}%",
                "price": round(float(r["entry_price"]), 4),
                "note": note_open,
            }
        )
        # 行情末日未到期：不写伪造清仓
        if str(r.get("reason") or "") == "open":
            continue
        rows.append(
            {
                "date": pd.Timestamp(r["exit_date"]).strftime("%Y-%m-%d"),
                "action": "清仓",
                "code": r["code"],
                "entry_mode": mode,
                "surprise_tier": tier,
                "event_pub": pd.Timestamp(r["event_pub"]).strftime("%Y-%m-%d"),
                "days_after_announce": "",
                "pre_run": "",
                "lt_run": "",
                "pullback": "",
                "price": round(float(r["exit_price"]), 4),
                "day_ret": f"{ret * 100:.2f}%",
                "note": str(r.get("reason") or "hold_end"),
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def run_backtest(
    params: Optional[Dict[str, Any]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    params = {**DEFAULT_PARAMS, **(params or {})}
    ev_path = _data_dir() / "positive_events.parquet"
    legs_path = _data_dir() / "trade_legs.parquet"
    if not ev_path.exists():
        raise FileNotFoundError("缺少 positive_events.parquet，请先 refresh")
    events = pd.read_parquet(ev_path)
    need_rebuild = True
    if legs_path.exists():
        legs = pd.read_parquet(legs_path)
        need_rebuild = (
            "lt_run" not in legs.columns
            or "surprise_tier" not in legs.columns
            or "stop_used" in legs.columns  # A+C 残留字段 → 强制回到三维版
        )
        if need_rebuild:
            print("[rebuild] trade legs missing 3-factor fields, rebuilding...")
            legs = build_trade_legs(events, params, price_end=end)
    else:
        legs = build_trade_legs(events, params, price_end=end)

    # 组合层再筛一遍名额
    daily, summary, accepted = run_portfolio_backtest(legs, params, start=start, end=end)
    if daily.empty:
        print("[warn]", summary)
        return summary

    OUT.mkdir(parents=True, exist_ok=True)
    daily_path = OUT / "earnings_forecast_backtest.csv"
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    print(f"[ok] wrote {daily_path}")

    # 仅保留组合实际入账腿（已按 start 过滤）
    hist = _trade_history(accepted)
    hist_path = OUT / "earnings_forecast_trade_history.csv"
    hist.to_csv(hist_path, index=False, encoding="utf-8-sig")
    print(f"[ok] wrote {hist_path} n={len(hist)}")

    payload = {"params": params, "results": {"dual_path": summary}, "notes": [
        "对齐公告日 profitForcastExpPubDate",
        "追高三维：超预期档位(爆发≥100%/较强≥30%) + 两年涨幅位置 + 短期20日涨幅",
        "不满足直买条件 → 等公告后相对高点回撤8%再买；统一止损15%",
        "股票：佣金万一双向 + 卖出印花税千一",
    ]}
    json_path = OUT / "earnings_forecast_backtest.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    _plot(daily, OUT / "earnings_forecast_equity_curve.png")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--universe", default="hs300")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true", help="回测前先刷新事件与价格")
    parser.add_argument("--interval", type=float, default=0.4)
    args = parser.parse_args()

    params = {**DEFAULT_PARAMS, "universe": args.universe, "request_interval_sec": args.interval}
    if args.refresh:
        limiter = _RateLimiter(args.interval)
        codes = fetch_universe_codes(args.universe, limiter)
        if args.limit:
            codes = codes[: args.limit]
        collect_positive_events(codes, params, end_date=args.end, progress_every=10)
        events = pd.read_parquet(_data_dir() / "positive_events.parquet")
        build_trade_legs(events, params, price_end=args.end)

    run_backtest(params=params, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
