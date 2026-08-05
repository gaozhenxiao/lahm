# -*- coding: utf-8 -*-
"""Sweep improvements on slope-up dividend grid (v3)."""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.strategies.etf_grid_backtest import (  # noqa: E402
    DEFAULT_PARAMS_V3,
    backtest_symbol,
)
from app.services.factors.dividend_etf_swing import load_or_fetch_etf as load_etf  # noqa: E402
import pandas as pd


def run_one(code: str, **kw):
    params = {**DEFAULT_PARAMS_V3, **{k: v for k, v in kw.items() if k != "tag"}}
    hit = backtest_symbol(
        code,
        name=code,
        step_pct=kw.get("step_pct"),
        start="2018-01-01",
        version="v3",
        params=params,
    )
    if hit.get("error"):
        return {"code": code, "error": hit["error"], **kw}
    r = hit["result"]
    g, b = r["grid"], r["buy_hold"]
    return {
        "code": code,
        **{k: kw[k] for k in kw},
        "cagr": g["cagr"],
        "bh_cagr": b["cagr"],
        "excess": r["excess_cagr"],
        "sharpe": g["sharpe"],
        "bh_sharpe": b["sharpe"],
        "max_dd": g["max_dd"],
        "bh_dd": b.get("max_dd"),
        "n_trades": r["n_trades"],
        "score": g["sharpe"] + 0.5 * r["excess_cagr"] * 10 - 0.3 * abs(g["max_dd"]),
    }


def main():
    codes = ["515080", "515180", "512890", "510880"]
    rows = []

    # baseline
    for code in codes:
        rows.append(run_one(code, step_pct=0.006, min_layers=3, n_grids=8, ma_center=60, tag="baseline"))

    # param grid on 515080 first, then apply top configs to all
    grid = {
        "step_pct": [0.004, 0.005, 0.006, 0.008, 0.010],
        "min_layers": [2, 3, 4, 5],
        "n_grids": [6, 8, 10],
        "ma_center": [40, 60, 90, 120],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"sweep combos on 515080: {len(combos)}", flush=True)
    for vals in combos:
        kw = dict(zip(keys, vals))
        kw["tag"] = "sweep"
        rows.append(run_one("515080", **kw))

    df = pd.DataFrame(rows)
    out = ROOT / "data" / "strategies" / "etf_grid_v3_improve_sweep.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    base = df[(df["code"] == "515080") & (df["tag"] == "baseline")].iloc[0]
    sweep = df[(df["code"] == "515080") & (df["tag"] == "sweep")].copy()
    sweep = sweep.sort_values(["score", "sharpe", "excess"], ascending=False)
    print("\n=== baseline 515080 ===", flush=True)
    print(base[["cagr", "excess", "sharpe", "max_dd", "n_trades", "score"]].to_string(), flush=True)
    print("\n=== top 10 by score (515080) ===", flush=True)
    print(
        sweep.head(10)[
            ["step_pct", "min_layers", "n_grids", "ma_center", "cagr", "excess", "sharpe", "max_dd", "n_trades", "score"]
        ].to_string(index=False),
        flush=True,
    )

    # validate top-3 configs across dividend ETFs
    top3 = sweep.head(3)
    val_rows = []
    for _, cfg in top3.iterrows():
        kw = {
            "step_pct": float(cfg["step_pct"]),
            "min_layers": int(cfg["min_layers"]),
            "n_grids": int(cfg["n_grids"]),
            "ma_center": int(cfg["ma_center"]),
            "tag": f"top",
        }
        for code in codes:
            val_rows.append(run_one(code, **kw))
    # also asymmetric candidates via direct engine (buy_step != sell_step) — implement inline
    from datetime import datetime
    from app.services.strategies import etf_grid_backtest as m

    def asym_backtest(code, buy_step, sell_step, min_layers=3, n_grids=8, ma_center=60):
        dfx = load_etf(code, start="20180101")
        if dfx is None or dfx.empty:
            return {"code": code, "error": "no_data"}
        dfx = dfx.copy()
        dfx["date"] = pd.to_datetime(dfx["date"])
        dfx = dfx[dfx["date"] >= pd.Timestamp("2018-01-01")].reset_index(drop=True)
        # monkey: temporarily use mean step in summary but custom loop
        # reuse slope_up with buy/sell asymmetry by patching locally
        px = dfx
        n_grids = max(int(n_grids), 2)
        min_layers = int(min_layers)
        unit = 1.0 / n_grids
        ma = px["close"].astype(float).rolling(int(ma_center)).mean()
        cash = 1.0
        lots = []
        center = None
        commission = 0.0001
        rows_eq = []
        for i in range(len(px)):
            d = px.at[i, "date"]
            price = float(px.at[i, "close"])
            ma_i = float(ma.at[i]) if pd.notna(ma.at[i]) else price
            if center is None:
                center = price
                for _ in range(max(min_layers, n_grids // 2)):
                    if len(lots) >= n_grids or cash < unit * 0.5:
                        break
                    spend = min(cash, unit)
                    fee = spend * commission
                    shares = (spend - fee) / price
                    cash -= spend
                    lots.append(shares)
            else:
                center = max(center, ma_i)
                guard = 0
                while len(lots) < n_grids and price <= center * (1.0 - buy_step) and guard < n_grids:
                    spend = min(cash, unit)
                    if spend < unit * 0.5:
                        break
                    fee = spend * commission
                    shares = (spend - fee) / price
                    cash -= spend
                    lots.append(shares)
                    guard += 1
                guard = 0
                while len(lots) > min_layers and price >= center * (1.0 + sell_step) and guard < n_grids:
                    shares = lots.pop(0)
                    gross = shares * price
                    fee = gross * commission
                    cash += gross - fee
                    guard += 1
            pos = sum(s * price for s in lots)
            rows_eq.append({"date": d, "equity": cash + pos, "close": price})
        daily = pd.DataFrame(rows_eq)
        bh0 = float(daily.iloc[0]["close"])
        daily["bh_equity"] = (1.0 * (1 - commission) / bh0) * daily["close"]
        daily = daily.set_index("date")
        gm = m._metrics(daily["equity"], ann_cash=0.014)
        bm = m._metrics(daily["bh_equity"], ann_cash=0.014)
        return {
            "code": code,
            "tag": "asym",
            "buy_step": buy_step,
            "sell_step": sell_step,
            "cagr": gm["cagr"],
            "bh_cagr": bm["cagr"],
            "excess": round(gm["cagr"] - bm["cagr"], 4),
            "sharpe": gm["sharpe"],
            "max_dd": gm["max_dd"],
            "score": gm["sharpe"] + 0.5 * (gm["cagr"] - bm["cagr"]) * 10 - 0.3 * abs(gm["max_dd"]),
        }

    asym_cfgs = [
        (0.004, 0.008),
        (0.005, 0.010),
        (0.006, 0.010),
        (0.005, 0.006),
        (0.004, 0.006),
    ]
    for bs, ss in asym_cfgs:
        for code in codes:
            val_rows.append(asym_backtest(code, bs, ss))

    val = pd.DataFrame(val_rows)
    val_path = ROOT / "data" / "strategies" / "etf_grid_v3_improve_validate.csv"
    val.to_csv(val_path, index=False, encoding="utf-8-sig")

    print("\n=== cross-ETF: top sweep configs ===", flush=True)
    for tag_cols in ["step_pct", "min_layers", "n_grids", "ma_center"]:
        pass
    show = val[val["tag"] == "top"].copy()
    if not show.empty:
        print(
            show.groupby(["step_pct", "min_layers", "n_grids", "ma_center"])
            .agg(avg_excess=("excess", "mean"), avg_sharpe=("sharpe", "mean"), avg_score=("score", "mean"))
            .sort_values("avg_score", ascending=False)
            .head(5)
            .to_string(),
            flush=True,
        )
    print("\n=== cross-ETF: asymmetric buy/sell ===", flush=True)
    asym = val[val["tag"] == "asym"].copy()
    if not asym.empty:
        print(
            asym.groupby(["buy_step", "sell_step"])
            .agg(avg_excess=("excess", "mean"), avg_sharpe=("sharpe", "mean"), avg_score=("score", "mean"))
            .sort_values("avg_score", ascending=False)
            .to_string(),
            flush=True,
        )
        print("\nper-name best asym:", flush=True)
        for code in codes:
            sub = asym[asym["code"] == code].sort_values("score", ascending=False).head(1)
            print(sub[["code", "buy_step", "sell_step", "cagr", "excess", "sharpe", "max_dd"]].to_string(index=False), flush=True)

    # pick best overall: max avg_score across dividend codes
    candidates = []
    # from top configs
    for _, cfg in top3.iterrows():
        sub = show[
            (show["step_pct"] == cfg["step_pct"])
            & (show["min_layers"] == cfg["min_layers"])
            & (show["n_grids"] == cfg["n_grids"])
            & (show["ma_center"] == cfg["ma_center"])
        ]
        if sub.empty:
            continue
        candidates.append(
            {
                "kind": "symmetric",
                "cfg": {
                    "step_pct": float(cfg["step_pct"]),
                    "min_layers": int(cfg["min_layers"]),
                    "n_grids": int(cfg["n_grids"]),
                    "ma_center": int(cfg["ma_center"]),
                },
                "avg_score": float(sub["score"].mean()),
                "avg_excess": float(sub["excess"].mean()),
                "avg_sharpe": float(sub["sharpe"].mean()),
            }
        )
    for (bs, ss), g in asym.groupby(["buy_step", "sell_step"]):
        candidates.append(
            {
                "kind": "asymmetric",
                "cfg": {"buy_step": float(bs), "sell_step": float(ss), "min_layers": 3, "n_grids": 8, "ma_center": 60},
                "avg_score": float(g["score"].mean()),
                "avg_excess": float(g["excess"].mean()),
                "avg_sharpe": float(g["sharpe"].mean()),
            }
        )
    # baseline avg
    base_all = df[(df["tag"] == "baseline") & (df["code"].isin(codes))]
    candidates.append(
        {
            "kind": "baseline",
            "cfg": {"step_pct": 0.006, "min_layers": 3, "n_grids": 8, "ma_center": 60},
            "avg_score": float(base_all["score"].mean()),
            "avg_excess": float(base_all["excess"].mean()),
            "avg_sharpe": float(base_all["sharpe"].mean()),
        }
    )
    cand_df = pd.DataFrame(candidates).sort_values("avg_score", ascending=False)
    print("\n=== candidate ranking ===", flush=True)
    print(cand_df.to_string(index=False), flush=True)
    best = cand_df.iloc[0].to_dict()
    summary = {
        "baseline_515080": {
            "cagr": float(base["cagr"]),
            "excess": float(base["excess"]),
            "sharpe": float(base["sharpe"]),
            "max_dd": float(base["max_dd"]),
        },
        "best": best,
        "top_symmetric_515080": sweep.head(3).to_dict(orient="records"),
    }
    (ROOT / "data" / "strategies" / "etf_grid_v3_improve_best.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("\n[ok] wrote", out, val_path, flush=True)


if __name__ == "__main__":
    main()
