"""暴跌抄底因子回测。

用法:
  python scripts/backtest_dip_buy_factor.py
  python scripts/backtest_dip_buy_factor.py --compare
  python scripts/backtest_dip_buy_factor.py --start 2015-01-01
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

from app.services.factors.dip_buy import (  # noqa: E402
    BASELINE_PARAMS,
    DEFAULT_PARAMS,
    apply_dip_buy_positions,
    build_dip_buy_daily_factor,
    build_trade_return_series,
)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def count_roundtrips(pos: pd.Series) -> dict:
    p = pos.fillna(0)
    prev = p.shift(1).fillna(0)
    buys = int(((prev <= 0.05) & (p > 0.05)).sum())
    sells = int(((prev > 0.05) & (p <= 0.05)).sum())
    holds = []
    in_pos = False
    start_i = 0
    for i, v in enumerate(p.tolist()):
        if not in_pos and v > 0.05:
            in_pos = True
            start_i = i
        elif in_pos and v <= 0.05:
            holds.append(i - start_i)
            in_pos = False
    return {
        "buy_trades": buys,
        "sell_trades": sells,
        "roundtrips": len(holds),
        "median_hold_bars": float(pd.Series(holds).median()) if holds else 0.0,
        "mean_hold_bars": float(pd.Series(holds).mean()) if holds else 0.0,
    }


def summarize(df: pd.DataFrame, tag: str = "dip_buy") -> dict:
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
    # 收益归因用隔夜仓；曝光统计也用隔夜仓（真正承担当日涨跌的仓位）
    hold_col = "position_hold" if "position_hold" in df.columns else "position_exec"
    pos = df[hold_col].fillna(0.0) if hold_col in df.columns else df["position"].fillna(0.0)
    active = pos > 0.05
    hit = float((df.loc[active, "asset_ret"] > 0).mean()) if active.any() and "asset_ret" in df.columns else 0.0
    pos_nz = pos[pos > 0.05]
    cash_ann = float(df["cash_ret"].iloc[0] * 365) if "cash_ret" in df.columns and len(df) else 0.0
    total_cost = float(df["cost_ret"].fillna(0).sum()) if "cost_ret" in df.columns else 0.0
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
        "long_days": int((pos > 0.05).sum()),
        "flat_days": int((pos <= 0.05).sum()),
        "cash_annual": round(cash_ann, 4),
        "total_cost_drag": round(total_cost, 4),
        "position_logic": tag,
        "mode": "close_rebalance",
        "accounting": "eod_rebalance_hold_earns_day",
    }
    out.update(count_roundtrips(pos))
    uni_col = "universe_hold" if "universe_hold" in df.columns else "universe_exec"
    if uni_col in df.columns:
        vc = df.loc[pos > 0.05, uni_col].value_counts(normalize=True)
        out["universe_mix"] = {str(k): round(float(v), 3) for k, v in vc.items()}
    return out


def _trade_history(df: pd.DataFrame) -> pd.DataFrame:
    """按收盘调仓记账：比较隔夜仓 vs 收盘后仓；成交价=当日收盘；当日收益不含新增仓。"""
    rows = []
    eod = df["position"].fillna(0.0) if "position" in df.columns else df["position_exec"].fillna(0.0)
    hold = (
        df["position_hold"].fillna(0.0)
        if "position_hold" in df.columns
        else eod.shift(1).fillna(0.0)
    )
    if "strategy_ret" in df.columns:
        equity = (1.0 + df["strategy_ret"].fillna(0.0)).cumprod()
    else:
        equity = pd.Series(1.0, index=df.index)
    for i in range(len(df)):
        p0, p1 = float(hold.iloc[i]), float(eod.iloc[i])
        if p0 <= 0.05 and p1 > 0.05:
            action = "开仓"
        elif p0 > 0.05 and p1 <= 0.05:
            action = "清仓"
        elif abs(p1 - p0) >= 0.03 and max(p0, p1) > 0.05:
            action = "加仓" if p1 > p0 else "减仓"
        else:
            continue
        uni_eod = df["universe_eod"].iloc[i] if "universe_eod" in df.columns else (
            df["best_universe"].iloc[i] if "best_universe" in df.columns else ""
        )
        uni_hold = df["universe_hold"].iloc[i] if "universe_hold" in df.columns else (
            df["universe_exec"].iloc[i] if "universe_exec" in df.columns else ""
        )
        note = "收盘调仓；成交价=当日收盘；当日收益仅计隔夜仓，不含本笔新增"
        if action == "清仓":
            note = "收盘调仓清仓；当日涨跌仍按隔夜仓计入至收盘"
        elif action == "减仓":
            note = "收盘减仓；被减部分当日仍按隔夜仓计入收益"
        rows.append(
            {
                "date": pd.Timestamp(df["date"].iloc[i]).strftime("%Y-%m-%d"),
                "action": action,
                "position_before": round(p0, 4),
                "position_after": round(p1, 4),
                "delta": round(p1 - p0, 4),
                "equity": round(float(equity.iloc[i]), 4),
                "day_ret": (
                    f"{float(df['strategy_ret'].iloc[i]) * 100:.2f}%"
                    if "strategy_ret" in df.columns and pd.notna(df["strategy_ret"].iloc[i])
                    else None
                ),
                "close": float(df["trade_close"].iloc[i])
                if "trade_close" in df.columns and pd.notna(df["trade_close"].iloc[i])
                else (float(df["close"].iloc[i]) if pd.notna(df["close"].iloc[i]) else None),
                "factor": float(df["factor"].iloc[i]) if pd.notna(df["factor"].iloc[i]) else None,
                "best_universe": df["best_universe"].iloc[i] if "best_universe" in df.columns else "",
                "universe_exec": uni_eod,
                "universe_hold": uni_hold,
                "cost_ret": round(float(df["cost_ret"].iloc[i]), 6)
                if "cost_ret" in df.columns and pd.notna(df["cost_ret"].iloc[i])
                else 0.0,
                "note": note,
            }
        )

    # 样本末日状态：若末日已有调仓记录，只补 note，不再插第二条「持仓/空仓」
    if len(df):
        last = df.iloc[-1]
        last_date = pd.Timestamp(last["date"]).strftime("%Y-%m-%d")
        eod_pos = float(last.get("position") or 0.0)
        hold_pos = float(last.get("position_hold") or last.get("position_exec") or 0.0)
        end_note = (
            f"样本末日；隔夜仓={hold_pos:.4f}（计当日收益），"
            f"收盘后仓={eod_pos:.4f}（下一交易日起计收益）"
        )
        if rows and rows[-1]["date"] == last_date:
            rows[-1]["note"] = f"{rows[-1]['note']}；{end_note}"
        else:
            rows.append(
                {
                    "date": last_date,
                    "action": "持仓" if eod_pos > 0.05 else "空仓",
                    "position_before": round(hold_pos, 4),
                    "position_after": round(eod_pos, 4),
                    "delta": round(eod_pos - hold_pos, 4),
                    "equity": round(float(equity.iloc[-1]), 4),
                    "day_ret": (
                        f"{float(last['strategy_ret']) * 100:.2f}%"
                        if "strategy_ret" in df.columns and pd.notna(last.get("strategy_ret"))
                        else None
                    ),
                    "close": float(last["trade_close"])
                    if "trade_close" in df.columns and pd.notna(last.get("trade_close"))
                    else (float(last["close"]) if pd.notna(last.get("close")) else None),
                    "factor": float(last["factor"]) if pd.notna(last.get("factor")) else None,
                    "best_universe": last["best_universe"] if "best_universe" in df.columns else "",
                    "universe_exec": last["universe_eod"]
                    if "universe_eod" in df.columns
                    else (last["best_universe"] if "best_universe" in df.columns else ""),
                    "universe_hold": last["universe_hold"]
                    if "universe_hold" in df.columns
                    else (last.get("universe_exec") or ""),
                    "cost_ret": round(float(last["cost_ret"]), 6)
                    if "cost_ret" in df.columns and pd.notna(last.get("cost_ret"))
                    else 0.0,
                    "note": end_note,
                }
            )
    return pd.DataFrame(rows)


def _plot(df: pd.DataFrame, path: Path, label: str = "dip_buy") -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] plot skipped: {exc}")
        return
    eq = (1 + df["strategy_ret"].fillna(0)).cumprod()
    bh = (1 + df["bench_ret"].fillna(0)).cumprod()
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(df["date"], eq, label=label, color="#1f4e79")
    axes[0].plot(df["date"], bh, label="CSI300 buy&hold", color="#999999", alpha=0.8)
    axes[0].legend(loc="upper left")
    axes[0].set_title("Dip-buy factor equity")
    axes[0].grid(True, alpha=0.25)
    axes[1].fill_between(df["date"], 0, df["position"].fillna(0) if "position" in df.columns else df["position_exec"].fillna(0), color="#2a9d8f", alpha=0.55)
    axes[1].set_ylabel("position(eod)")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[ok] wrote {path}")


def _run_one(
    params: Dict[str, Any],
    start: Optional[str],
    end: Optional[str],
    tag: str,
) -> tuple[dict, pd.DataFrame]:
    fac = build_dip_buy_daily_factor(params=params, start=start, end=end, refresh_valuation=False)
    if fac.empty:
        return {"error": "empty", "position_logic": tag}, pd.DataFrame()
    fac = fac.dropna(subset=["date"]).copy()
    fac["position"] = apply_dip_buy_positions(fac["factor"], params)
    # 收盘调仓：不再把仓位整体 shift 当成次日开盘成交
    tr = build_trade_return_series(fac, params)
    fac = fac.merge(
        tr[
            [
                "date",
                "position_hold",
                "position_exec",
                "position_delta",
                "universe_hold",
                "universe_eod",
                "universe_exec",
                "asset_ret",
                "trade_close",
                "hold_close",
                "cash_ret",
                "buy_turnover",
                "sell_turnover",
                "cost_ret",
                "strategy_ret_gross",
                "strategy_ret",
            ]
        ],
        on="date",
        how="left",
        suffixes=("", "_tr"),
    )
    # merge 可能带上同名 position；以信号仓为准，hold/exec 来自 tr
    if "position_tr" in fac.columns:
        fac.drop(columns=["position_tr"], inplace=True)
    if "close_primary" in fac.columns:
        fac["bench_ret"] = pd.Series(fac["close_primary"]).pct_change().fillna(0.0)
    else:
        fac["bench_ret"] = fac["asset_ret"].fillna(0.0)
    fac["strategy_ret"] = fac["strategy_ret"].fillna(0.0)
    fac["asset_ret"] = fac["asset_ret"].fillna(0.0)
    fac["cost_ret"] = fac["cost_ret"].fillna(0.0)
    metrics = summarize(fac, tag=tag)
    metrics["trade_mode"] = params.get("trade_mode")
    metrics["aggression"] = params.get("aggression")
    metrics["commission_rate"] = params.get("commission_rate")
    metrics["stamp_tax_sell"] = params.get("stamp_tax_sell")
    return metrics, fac


COMPARE_CASES: Dict[str, Dict[str, Any]] = {
    "baseline": {**BASELINE_PARAMS},
    "cash_only": {**BASELINE_PARAMS, "cash_annual": 0.014},
    "best_etf": {**BASELINE_PARAMS, "trade_mode": "best_etf", "cash_annual": 0.0},
    "aggressive": {
        **BASELINE_PARAMS,
        "aggression": 1.35,
        "enter_threshold": 0.18,
        "buy_threshold": 0.18,
        "min_pos_keep": 0.08,
        "smooth": 2,
        "ret_short_soft": -0.03,
        "ret_short_hard": -0.07,
        "ret_mid_soft": -0.06,
        "ret_mid_hard": -0.13,
        "dd_soft": -0.06,
        "dd_hard": -0.15,
        "cheap_pct": 30.0,
        "expensive_pct": 75.0,
        "cash_annual": 0.0,
        "trade_mode": "csi300",
    },
    "optimized": {**DEFAULT_PARAMS},  # 空仓计息 + 对应ETF + 积极抄底
}


def run_backtest(
    start: str | None = None,
    end: str | None = None,
    compare: bool = False,
) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    # ETF/估值早期稀疏；默认从 2015 起，与对外披露口径一致（更早会拉低年化/夏普）
    if start is None:
        start = "2015-01-05"

    results: Dict[str, Any] = {}
    primary_df = pd.DataFrame()

    cases = COMPARE_CASES if compare else {"optimized": DEFAULT_PARAMS}
    for name, params in cases.items():
        metrics, fac = _run_one(params, start, end, tag=name)
        results[f"{name}:long_flat"] = metrics
        print(f"\n=== {name} ===")
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        if name == "optimized" or (not compare and name in cases):
            primary_df = fac

    if primary_df.empty and results:
        # fallback first non-empty
        for name, params in cases.items():
            metrics, fac = _run_one(params, start, end, tag=name)
            if not fac.empty:
                primary_df = fac
                break

    if primary_df.empty:
        print("[error] empty factor panel; run refresh_dip_buy_data.py first")
        return {"error": "empty"}

    csv_path = OUT / "dip_buy_backtest.csv"
    primary_df.to_csv(csv_path, index=False)
    print(f"[ok] wrote {csv_path}")

    trades = _trade_history(primary_df)
    trades_path = OUT / "dip_buy_trade_history.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    print(f"[ok] wrote {trades_path} n={len(trades)}")

    summary = {
        "params": DEFAULT_PARAMS,
        "results": results,
        "notes": [
            "optimized=空仓按年化1.4%计息 + 最强宇宙对应ETF(510300/159915/510500) + 更积极抄底",
            "记账：收盘调仓；成交价=当日收盘；当日收益只计隔夜仓，收盘新增仓位不计入当日涨跌",
            "成本：佣金万分之一（买卖）；ETF 免印花税；不计滑点；换宇宙按先卖后买",
            "净值 equity_t = equity_{t-1}×(1+strategy_ret_t)，strategy_ret=毛收益-成本",
            "ETF 缺失早期用指数代理",
            "compare 可看 baseline / cash_only / best_etf / aggressive / optimized",
        ],
    }
    json_path = OUT / "dip_buy_backtest.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[ok] wrote {json_path}")

    _plot(primary_df, OUT / "dip_buy_equity_curve.png", label="dip_buy optimized")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--compare", action="store_true", help="对比 baseline/计息/ETF/积极/综合")
    args = parser.parse_args()
    run_backtest(start=args.start, end=args.end, compare=args.compare)


if __name__ == "__main__":
    main()
