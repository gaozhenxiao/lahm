"""红利 ETF 向上倾斜网格因子回测。

用法:
  python scripts/backtest_dividend_etf_slope_grid.py
  python scripts/backtest_dividend_etf_slope_grid.py --etf 512890
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "factors"

from app.services.factors.dividend_etf_slope_grid import (  # noqa: E402
    DEFAULT_PARAMS,
    FACTOR_ID,
    run_backtest,
)


def _plot_equity(daily, trades, path: Path, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] equity plot skipped: {exc}")
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(daily["date"], daily["equity"], label="strategy", color="#1f4e79", lw=1.8)
    if "bh_equity" in daily.columns:
        axes[0].plot(daily["date"], daily["bh_equity"], label="ETF buy&hold", color="#999999", alpha=0.85)
    axes[0].legend(loc="upper left")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)

    # 净值上的买卖点
    if trades is not None and not trades.empty:
        eq_map = {
            pd_ts(d): float(e)
            for d, e in zip(daily["date"], daily["equity"])
        }
        buys_x, buys_y, sells_x, sells_y = [], [], [], []
        for _, t in trades.iterrows():
            d = pd_ts(t["date"])
            y = eq_map.get(d)
            if y is None:
                continue
            if str(t.get("action") or "").find("加") >= 0 or str(t.get("side") or "") == "buy":
                buys_x.append(d)
                buys_y.append(y)
            else:
                sells_x.append(d)
                sells_y.append(y)
        if buys_x:
            axes[0].scatter(buys_x, buys_y, marker="^", s=28, c="#c0392b", zorder=5, label="buy", alpha=0.85)
        if sells_x:
            axes[0].scatter(sells_x, sells_y, marker="v", s=28, c="#27ae60", zorder=5, label="sell", alpha=0.85)
        axes[0].legend(loc="upper left", fontsize=8)

    axes[1].fill_between(daily["date"], 0, daily["position"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("exposure")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def pd_ts(x):
    import pandas as pd

    return pd.Timestamp(x)


def _plot_signals(daily, trades, path: Path, title: str) -> None:
    """价格 + 中枢 + 买卖点（用户看图主入口）。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] signals plot skipped: {exc}")
        return

    fig, ax = plt.subplots(figsize=(13, 6.5))
    ax.plot(daily["date"], daily["close"], color="#1a1a1a", lw=1.2, label="close")
    if "center" in daily.columns:
        ax.plot(daily["date"], daily["center"], color="#e67e22", lw=1.4, ls="--", label="center (slope-up)")

    if trades is not None and not trades.empty:
        buy = trades[trades["action"].astype(str).str.contains("加") | (trades["side"].astype(str) == "buy")]
        sell = trades[trades["action"].astype(str).str.contains("减") | (trades["side"].astype(str) == "sell")]
        if not buy.empty:
            ax.scatter(
                pd.to_datetime(buy["date"]),
                buy["price"].astype(float),
                marker="^",
                s=36,
                c="#c0392b",
                zorder=6,
                label=f"buy ({len(buy)})",
            )
        if not sell.empty:
            ax.scatter(
                pd.to_datetime(sell["date"]),
                sell["price"].astype(float),
                marker="v",
                s=36,
                c="#27ae60",
                zorder=6,
                label=f"sell ({len(sell)})",
            )

    ax.set_title(title)
    ax.grid(True, alpha=0.28)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_ylabel("price")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--etf", default=DEFAULT_PARAMS["etf_code"])
    ap.add_argument("--start", default=DEFAULT_PARAMS["start"])
    ap.add_argument("--end", default=None)
    ap.add_argument("--force-fetch", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    params = {**DEFAULT_PARAMS, "etf_code": args.etf}
    daily, summary, trades = run_backtest(
        params, start=args.start, end=args.end, force_fetch=args.force_fetch
    )
    if summary.get("error") or daily is None or daily.empty:
        raise SystemExit(f"backtest failed: {summary}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    daily.to_csv(OUT / f"{FACTOR_ID}_backtest.csv", index=False, encoding="utf-8-sig")
    if trades is not None and not trades.empty:
        trades.to_csv(OUT / f"{FACTOR_ID}_trade_history.csv", index=False, encoding="utf-8-sig")

    payload = {
        "params": {**params, "start": args.start, "end": args.end},
        "results": {"slope_up_grid": summary},
        "notes": [
            "红利ETF向上倾斜网格：中枢=max(旧, MA90) 只升不降",
            f"默认 step={params['step_pct']*100:.1f}% / grids={params['n_grids']} / min_layers={params['min_layers']} / MA{params['ma_center']}",
            "相对中枢跌超步长加仓、涨超步长减仓；底仓不少于 min_layers",
            "不复权成交；除息日按持仓份额发现金分红并再投入网格；买入持有对照同步再投资",
            "ETF免印花税；佣金万一；与策略「红利倾斜网格」同源",
        ],
    }
    (OUT / f"{FACTOR_ID}_backtest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] wrote {OUT / f'{FACTOR_ID}_backtest.json'}")

    etf = summary.get("etf_code") or args.etf
    _plot_equity(
        daily,
        trades,
        OUT / f"{FACTOR_ID}_equity_curve.png",
        f"{FACTOR_ID} · {etf} · slope_up_grid",
    )
    _plot_signals(
        daily,
        trades,
        OUT / f"{FACTOR_ID}_signals.png",
        f"{FACTOR_ID} · {etf} · price / center / buy-sell",
    )


if __name__ == "__main__":
    main()
