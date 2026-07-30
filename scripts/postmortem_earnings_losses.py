"""反思大亏腿：卖出后 N 日表现，看是止损过早还是买错方向。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEGS = ROOT / "data" / "factors" / "earnings_forecast" / "trade_legs.parquet"
DAILY = ROOT / "data" / "factors" / "earnings_forecast" / "daily"


def post_exit_ret(code: str, exit_date, horizons=(20, 60, 120, 252)) -> dict:
    path = DAILY / f"{code.replace('.', '_')}.parquet"
    if not path.exists():
        return {}
    px = pd.read_parquet(path)
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    idx = px.index[px["date"] == pd.Timestamp(exit_date)]
    if len(idx) == 0:
        # nearest
        idx = px.index[px["date"] >= pd.Timestamp(exit_date)]
        if len(idx) == 0:
            return {}
    i = int(idx[0])
    c0 = float(px.loc[i, "close"])
    out = {}
    for h in horizons:
        j = min(i + h, len(px) - 1)
        out[f"after_{h}d"] = float(px.loc[j, "close"]) / c0 - 1.0
        out[f"after_{h}d_date"] = str(pd.Timestamp(px.loc[j, "date"]).date())
    # max close after exit to end of sample
    out["after_max"] = float(px.loc[i:, "close"].max()) / c0 - 1.0
    out["end_ret"] = float(px.loc[len(px) - 1, "close"]) / c0 - 1.0
    return out


def main() -> None:
    legs = pd.read_parquet(LEGS)
    legs["entry_date"] = pd.to_datetime(legs["entry_date"])
    legs["exit_date"] = pd.to_datetime(legs["exit_date"])
    legs["ret"] = legs["exit_price"] / legs["entry_price"] - 1.0

    # accepted
    max_pos = 8
    acc = []
    active = []
    for _, row in legs.sort_values("entry_date").iterrows():
        active = [a for a in active if a["exit_date"] > row["entry_date"]]
        if len(active) >= max_pos:
            continue
        acc.append(row.to_dict())
        active.append(row.to_dict())
    acc = pd.DataFrame(acc).sort_values("ret")
    worst = acc.head(25).copy()

    rows = []
    for _, r in worst.iterrows():
        post = post_exit_ret(str(r["code"]), r["exit_date"])
        rows.append(
            {
                "code": r["code"],
                "entry": str(pd.Timestamp(r["entry_date"]).date()),
                "exit": str(pd.Timestamp(r["exit_date"]).date()),
                "mode": r.get("entry_mode"),
                "tier": r.get("surprise_tier"),
                "reason": r.get("reason"),
                "trade_ret": round(float(r["ret"]), 4),
                "lt_run": round(float(r.get("lt_run") or 0), 3),
                "after_20d": round(post.get("after_20d", float("nan")), 3),
                "after_60d": round(post.get("after_60d", float("nan")), 3),
                "after_120d": round(post.get("after_120d", float("nan")), 3),
                "after_252d": round(post.get("after_252d", float("nan")), 3),
                "after_max": round(post.get("after_max", float("nan")), 3),
                "to_end": round(post.get("end_ret", float("nan")), 3),
            }
        )
    out = pd.DataFrame(rows)
    path = ROOT / "data" / "factors" / "earnings_forecast_loss_postmortem.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))
    print("\nsummary of worst25:")
    print("  mean trade", out.trade_ret.mean())
    print("  mean after_60d", out.after_60d.mean())
    print("  mean after_max", out.after_max.mean())
    print("  pct rebound after_60d>0", (out.after_60d > 0).mean())
    print("  pct after_max>0.5", (out.after_max > 0.5).mean())
    print("  pct stop_loss", (out.reason == "stop_loss").mean())
    print("wrote", path)

    # 300476 special
    print("\n=== 300476 focus ===")
    print(out[out.code == "sz.300476"].to_string(index=False))


if __name__ == "__main__":
    main()
