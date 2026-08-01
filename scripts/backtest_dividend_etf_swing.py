"""红利 ETF 波段回测。

用法:
  python scripts/backtest_dividend_etf_swing.py
  python scripts/backtest_dividend_etf_swing.py --etf 512890 --compare
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "factors"

from app.services.factors.dividend_etf_swing import (  # noqa: E402
    DEFAULT_PARAMS,
    run_backtest,
)


def _plot(daily, path: Path, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(daily["date"], daily["equity"], label="strategy", color="#1f4e79")
    bh = (1 + daily["bench_ret"].fillna(0)).cumprod()
    axes[0].plot(daily["date"], bh, label="ETF buy&hold", color="#999999", alpha=0.85)
    axes[0].legend(loc="upper left")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[1].fill_between(daily["date"], 0, daily["position"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("exposure")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--etf", default=DEFAULT_PARAMS["etf_code"])
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--compare", action="store_true", help="同时跑 ma_pullback 与 trend_follow")
    ap.add_argument("--force-fetch", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    logics = ["ma_pullback", "trend_follow"] if args.compare else ["ma_pullback"]
    results = {}
    primary_daily = None
    primary_trades = None
    primary_logic = "ma_pullback"

    for logic in logics:
        params = {
            **DEFAULT_PARAMS,
            "etf_code": args.etf,
            "position_logic": logic,
        }
        daily, summary, trades = run_backtest(
            params, start=args.start, end=args.end, force_fetch=args.force_fetch
        )
        if summary.get("error"):
            print(f"[fail] {logic}: {summary}")
            results[logic] = summary
            continue
        results[logic] = summary
        print(f"\n=== {logic} / {summary.get('etf_code')} ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if logic == primary_logic or primary_daily is None:
            primary_daily = daily
            primary_trades = trades
            primary_logic = logic

    if primary_daily is None or primary_daily.empty:
        raise SystemExit("no successful backtest")

    etf = results.get(primary_logic, {}).get("etf_code") or args.etf
    primary_daily.to_csv(OUT / "dividend_etf_swing_backtest.csv", index=False, encoding="utf-8-sig")
    if primary_trades is not None:
        primary_trades.to_csv(OUT / "dividend_etf_swing_trade_history.csv", index=False, encoding="utf-8-sig")
    payload = {
        "params": {
            **DEFAULT_PARAMS,
            "etf_code": etf,
            "start": args.start,
            "compare": bool(args.compare),
        },
        "results": results,
        "notes": [
            "红利ETF波段：趋势过滤(MA60) + MA20回踩确认入场；跌破MA20/止损/到期离场",
            "ETF免印花税；佣金万一；收盘调仓，隔夜仓计次日收益",
            "基准对比为同一ETF买入持有",
            f"主逻辑={primary_logic}；可 --compare 对比 trend_follow",
        ],
    }
    (OUT / "dividend_etf_swing_backtest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] wrote {OUT / 'dividend_etf_swing_backtest.json'}")
    _plot(
        primary_daily,
        OUT / "dividend_etf_swing_equity_curve.png",
        f"dividend_etf_swing · {etf} · {primary_logic}",
    )


if __name__ == "__main__":
    main()
