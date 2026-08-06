"""国家队因子回测：默认 episode 战役仓位（long_flat）。

用法:
  python scripts/backtest_national_team_factor.py
  python scripts/backtest_national_team_factor.py --logic threshold   # 旧日频对比
  python scripts/backtest_national_team_factor.py --logic both

口径: total_return=累计收益; annual_return=年化收益; buy_hold_return=基准累计

可选国诚标注 CSV: data/factors/guocheng_signals.csv
列: date,direction  (buy/sell/neutral)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors.national_team import (  # noqa: E402
    ERA_BASKETS,
    apply_position_logic,
    build_national_team_daily_factor,
    fetch_etf_hist,
)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def count_roundtrips(pos: pd.Series) -> dict:
    p = pos.fillna(0)
    prev = p.shift(1).fillna(0)
    buys = int(((prev <= 0.02) & (p > 0.02)).sum())
    sells = int(((prev > 0.02) & (p <= 0.02)).sum())
    holds = []
    in_pos = False
    start_i = 0
    for i, v in enumerate(p.tolist()):
        if not in_pos and v > 0.02:
            in_pos = True
            start_i = i
        elif in_pos and v <= 0.02:
            holds.append(i - start_i)
            in_pos = False
    return {
        "buy_trades": buys,
        "sell_trades": sells,
        "roundtrips": len(holds),
        "median_hold_bars": float(pd.Series(holds).median()) if holds else 0.0,
        "mean_hold_bars": float(pd.Series(holds).mean()) if holds else 0.0,
    }


def summarize(df: pd.DataFrame) -> dict:
    if df.empty or "strategy_ret" not in df.columns:
        return {"error": "empty"}
    eq = (1 + df["strategy_ret"].fillna(0)).cumprod()
    bh = (1 + df["bench_ret"].fillna(0)).cumprod()
    n = len(df)
    years = max(n / 252.0, 1e-9)
    total = float(eq.iloc[-1] - 1)
    ann = float(eq.iloc[-1] ** (1 / years) - 1)
    vol = float(df["strategy_ret"].std() * (252 ** 0.5))
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    active = df["strategy_ret"] != 0
    hit = float((df.loc[active, "strategy_ret"] > 0).mean()) if active.any() else 0.0
    pos = df["position_exec"]
    pos_nz = pos[pos > 0.02]
    out = {
        "bars": n,
        "start": str(df["date"].iloc[0].date()),
        "end": str(df["date"].iloc[-1].date()),
        "total_return": round(total, 4),
        "annual_return": round(ann, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown(eq), 4),
        "hit_ratio": round(hit, 4),
        "buy_hold_return": round(float(bh.iloc[-1] - 1), 4),
        "avg_position": round(float(pos.mean()), 4),
        "avg_position_when_active": round(float(pos_nz.mean()), 4) if len(pos_nz) else 0.0,
        "median_position_when_active": round(float(pos_nz.median()), 4) if len(pos_nz) else 0.0,
        "long_days": int((pos > 0.02).sum()),
        "flat_days": int((pos <= 0.02).sum()),
        "short_days": int((pos < 0).sum()),
        "long_pct": round(float((pos > 0.02).mean()), 4),
        "short_pct": round(float((pos < 0).mean()), 4),
        "factor_pos_days": int((df["factor"] > 0).sum()),
        "factor_neg_days": int((df["factor"] < 0).sum()),
    }
    out.update(count_roundtrips(pos))
    return out


def run_one(fac_base: pd.DataFrame, mode: str, params: dict) -> tuple[dict, pd.DataFrame]:
    fac = fac_base.copy()
    p = {**params, "position_mode": mode}
    spark = fac["news_spark"] if "news_spark" in fac.columns else (fac["gc_spark"] if "gc_spark" in fac.columns else None)
    share_z = fac["share_z"] if "share_z" in fac.columns else None
    pos, state = apply_position_logic(
        fac["factor"],
        fac["close"],
        params=p,
        spark=spark,
        share_z=share_z,
        huijin_confirm=fac["huijin_confirm"] if "huijin_confirm" in fac.columns else None,
        policy_risk=fac["policy_risk"] if "policy_risk" in fac.columns else None,
        policy_support=fac["policy_support"] if "policy_support" in fac.columns else None,
        dates=fac["date"] if "date" in fac.columns else None,
    )
    fac["position"] = pos
    fac["episode_state"] = state
    if "bench_ret" in fac.columns and fac["bench_ret"].notna().any():
        fac["bench_ret"] = fac["bench_ret"].fillna(fac["close"].pct_change())
    else:
        fac["bench_ret"] = fac["close"].pct_change()
    fac["position_exec"] = fac["position"].shift(1).fillna(0)
    fac["strategy_ret"] = fac["position_exec"] * fac["bench_ret"]
    stats = summarize(fac.dropna(subset=["bench_ret"]))
    stats["mode"] = mode
    stats["position_logic"] = str(p.get("position_logic") or "continuous")
    if "era" in fac.columns:
        stats["eras"] = sorted({str(x) for x in fac["era"].dropna().unique().tolist()})
    if "episode_state" in fac.columns:
        stats["state_counts"] = fac["episode_state"].value_counts().to_dict()
    return stats, fac


def plot_equity(fac: pd.DataFrame, out_png: Path, title: str) -> None:
    import matplotlib.pyplot as plt

    df = fac.dropna(subset=["bench_ret"]).copy()
    df["eq_strategy"] = (1 + df["strategy_ret"].fillna(0)).cumprod()
    df["eq_bh"] = (1 + df["bench_ret"].fillna(0)).cumprod()
    pos = df["position_exec"].fillna(0)
    prev = pos.shift(1).fillna(0)
    buys = df[(prev <= 0.02) & (pos > 0.02)]
    sells = df[(prev > 0.02) & (pos <= 0.02)]

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(
        2, 1, figsize=(13, 7.5), dpi=140, sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax = axes[0]
    ax.plot(df["date"], df["eq_bh"], color="#8a8a8a", lw=1.1, label="时代篮子买入持有", zorder=1)
    ax.plot(df["date"], df["eq_strategy"], color="#c0392b", lw=1.5, label="策略净值", zorder=2)
    ax.scatter(
        buys["date"],
        buys["eq_strategy"],
        marker="^",
        s=36,
        color="#1a7f37",
        edgecolors="white",
        linewidths=0.4,
        label=f"开仓 ({len(buys)})",
        zorder=4,
    )
    ax.scatter(
        sells["date"],
        sells["eq_strategy"],
        marker="v",
        s=36,
        color="#1f4e79",
        edgecolors="white",
        linewidths=0.4,
        label=f"清仓 ({len(sells)})",
        zorder=4,
    )
    ax.axhline(1.0, color="#bbbbbb", lw=0.8, ls="--", zorder=0)
    ax.set_title(title)
    ax.set_ylabel("累计净值")
    ax.legend(loc="upper left", frameon=False, ncol=2)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.fill_between(df["date"], 0, pos, color="#1f4e79", alpha=0.35, step=None)
    ax2.plot(df["date"], pos, color="#1f4e79", lw=0.9)
    ax2.set_ylabel("仓位")
    ax2.set_ylim(-0.05, 1.05)
    ax2.grid(True, alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    print(f"[backtest] wrote {out_png}")


def main() -> None:
    import os

    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2012-05-28")
    parser.add_argument("--end", default="2026-07-27")
    parser.add_argument("--etf", default="510300")
    parser.add_argument(
        "--mode",
        default="long_flat",
        choices=["long_short", "long_flat", "both"],
        help="long_flat=增仓做多/减仓空仓（推荐）",
    )
    parser.add_argument(
        "--logic",
        default="continuous",
        choices=["continuous", "episode", "threshold"],
        help="continuous=份额连续仓位（默认）; episode/threshold=旧逻辑对比",
    )
    parser.add_argument("--out", default=str(ROOT / "data" / "factors" / "national_team_backtest.json"))
    args = parser.parse_args()

    base_params = {
        "etf_code": args.etf,
        "use_era_universe": True,
        "share_lookback_days": 5,
        "skip_share_fetch": False,
        "share_fetch_days": 10,
        "position_mode": "long_flat",
        "position_logic": "continuous",
        # continuous：禁恐慌假开仓；2018 熊市窗口回撤止损
        "cooldown_bars": 5,
        "panic_spark_strength": 0.35,
        "panic_entry_share_z": 0.05,
        "allow_panic_entry": False,
        "episode_dd_exit_pre": -0.99,
        "episode_dd_exit_post": -0.99,
        "episode_dd_switch": "2023-10-01",
        "bear_window_dd_exit": -0.10,
        "bear_window_start": "2018-01-01",
        "bear_window_end": "2018-12-31",
        "extend_min_support": 1.5,
        "use_huijin_calendar": True,
        "huijin_calendar_mode": "buy_only",
        "huijin_extend_bars": 80,
        "use_policy_events": True,
        "policy_hard_exit": 1.2,
        "policy_soft_exit": 1.0,
        "policy_risk_cooldown": 10,
        "panic_ret": -0.02,
        "panic_dd": -0.08,
        "stress_lookback": 60,
        # continuous 仓位：底仓10%、响应快、允许份额信号反复进出
        "cont_z_lo": -0.15,
        "cont_z_hi": 0.20,
        "cont_smooth": 2,
        "cont_exit_z": -0.30,
        "cont_exit_confirm_days": 8,
        "cont_max_pos": 1.0,
        "cont_campaign_floor": 0.10,
        "cont_allow_signal_reentry": True,
        "cont_reentry_z": 0.03,
        "cont_cooldown_bars": 2,
        # legacy episode knobs (for --logic episode)
        "enter_threshold": 0.45,
        "exit_threshold": 0.0,
        "confirm_enter_days": 5,
        "confirm_exit_days": 15,
        "min_hold_bars": 45,
        "stress_dd": -0.12,
    }
    print(f"[backtest] building factor etf={args.etf} {args.start}..{args.end}")
    fac = build_national_team_daily_factor(start=args.start, end=args.end, params=base_params)
    if fac.empty:
        hist = fetch_etf_hist(args.etf, start=args.start.replace("-", ""), end=(args.end or "").replace("-", "") or None)
        if hist.empty:
            raise SystemExit("无法获取 510300 行情")
        fac = hist.copy()
        fac["factor"] = 0.0
        fac["position"] = 0.0
        fac["proxy"] = 0.0
        fac["gc_spark"] = 0.0

    logics = [args.logic]
    modes = ["long_short", "long_flat"] if args.mode == "both" else [args.mode]
    results = {}
    primary_fac = None
    fac_by_logic = {}
    for logic in logics:
        for m in modes:
            if logic in ("episode", "continuous") and m == "long_short":
                continue
            params = {
                **base_params,
                "position_logic": logic,
                "position_mode": m,
            }
            if logic == "threshold":
                params["enter_threshold"] = 0.35
                params["exit_threshold"] = 0.15
            stats, fac_m = run_one(fac, m, params)
            key = f"{logic}:{m}"
            results[key] = stats
            fac_by_logic[logic] = fac_m
            print(f"\n=== {key} ===")
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            if logic == "continuous" and m == "long_flat":
                primary_fac = fac_m
            elif primary_fac is None:
                primary_fac = fac_m

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if "continuous:long_flat" in results:
        primary_logic = "continuous"
        primary_fac = fac_by_logic.get("continuous", primary_fac)
    else:
        primary_logic = logics[0]

    payload = {
        "params": base_params,
        "results": results,
        "metric_defs": {
            "total_return": "累计收益（期末净值-1）",
            "annual_return": "年化收益",
            "buy_hold_return": "基准买入持有累计收益",
            "buy_trades": "买入次数",
            "median_hold_bars": "中位持仓交易日数",
            "avg_position": "平均仓位（含空仓日）",
        },
        "notes": [
            "信号=汇金300ETF份额(510300权重更高/510310/510330)；交易=早期宽基、近年银行+科创",
            "continuous：火花开战役，仓位随 share_z 线性映射到 [0,1]（含战役底仓）并 EMA 平滑",
            "2018 年窗口启用战役回撤止损（-10%）",
            "政策日历：维稳买入；汇金减持/清配资等可强制减仓",
            "汇金季报日历：按公告日确认/延长持仓，不单独开仓",
            "新闻源：national_team_news_events.csv + 国诚 + 弱恐慌代理 + 政策事件",
            "未计交易成本；仓位 T+1 生效",
            "total_return=累计；annual_return=年化",
        ],
        "era_baskets": [
            {
                "name": e["name"],
                "start": e["start"],
                "end": e["end"],
                "note": e.get("note"),
                "trade": e["trade"],
                "signal": e["signal"],
            }
            for e in ERA_BASKETS
        ],
        "tail": primary_fac.tail(12)[
            [
                c
                for c in ["date", "close", "factor", "support_score", "position", "episode_state", "strategy_ret"]
                if c in primary_fac.columns
            ]
        ]
        .assign(date=lambda d: pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"))
        .to_dict(orient="records"),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = out.with_suffix(".csv")
    primary_fac.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[backtest] wrote {out}")
    print(f"[backtest] wrote {csv_path}")

    png = out.parent / "national_team_equity_curve.png"
    plot_equity(primary_fac, png, title="国家队因子 continuous 净值曲线（份额连续仓位）")
    print(f"[backtest] wrote {png} (logic={primary_logic})")


if __name__ == "__main__":
    main()
