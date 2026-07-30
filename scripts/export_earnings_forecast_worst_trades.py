"""导出业绩预告因子亏损最多的成交腿（组合已接受）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from app.services.factors.earnings_forecast import DEFAULT_PARAMS

LEGS = ROOT / "data" / "factors" / "earnings_forecast" / "trade_legs.parquet"
OUT = ROOT / "data" / "factors" / "earnings_forecast_worst_trades.csv"

MODE_MAP = {"announce_buy": "公告直买", "pullback": "回调买入"}
REASON_MAP = {"hold_end": "到期卖出", "stop_loss": "止损"}


def main() -> None:
    legs = pd.read_parquet(LEGS)
    legs["entry_date"] = pd.to_datetime(legs["entry_date"])
    legs["exit_date"] = pd.to_datetime(legs["exit_date"])
    legs["event_pub"] = pd.to_datetime(legs["event_pub"])
    legs["ret"] = legs["exit_price"] / legs["entry_price"] - 1.0

    max_pos = int(DEFAULT_PARAMS.get("max_positions") or 8)
    accepted = []
    active = []
    for _, row in legs.sort_values("entry_date").iterrows():
        active = [a for a in active if a["exit_date"] > row["entry_date"]]
        if len(active) >= max_pos:
            continue
        d = row.to_dict()
        d["n_pos_after_open"] = len(active) + 1
        d["weight"] = 1.0 / d["n_pos_after_open"]
        accepted.append(d)
        active.append(d)

    acc = pd.DataFrame(accepted).sort_values("ret")

    notes = []
    for _, r in acc.iterrows():
        if r["entry_mode"] == "announce_buy":
            base = "强业绩+公告前未大涨，公告收盘直买"
        else:
            base = "公告前已涨或非强业绩，等回调后买"
        notes.append(f"{base}；公告前涨幅{float(r['pre_run']) * 100:.1f}%")

    out = pd.DataFrame(
        {
            "亏损幅度": acc["ret"].map(lambda x: f"{x * 100:.2f}%"),
            "代码": acc["code"],
            "公告日": acc["event_pub"].dt.strftime("%Y-%m-%d"),
            "买入日": acc["entry_date"].dt.strftime("%Y-%m-%d"),
            "卖出日": acc["exit_date"].dt.strftime("%Y-%m-%d"),
            "买入仓位": acc["weight"].map(lambda x: f"{x * 100:.1f}%"),
            "同时持仓数": acc["n_pos_after_open"].astype(int),
            "公告前涨幅": acc["pre_run"].map(lambda x: f"{float(x) * 100:.2f}%"),
            "买入回撤": acc["pullback"].map(lambda x: f"{float(x) * 100:.2f}%"),
            "买入价": acc["entry_price"].map(lambda x: round(float(x), 4)),
            "卖出价": acc["exit_price"].map(lambda x: round(float(x), 4)),
            "入场路径": acc["entry_mode"].map(lambda x: MODE_MAP.get(x, x)),
            "公告后天数": acc["days_after"].astype(int),
            "卖出原因": acc["reason"].map(lambda x: REASON_MAP.get(x, x)),
            "备注": notes,
        }
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"wrote {OUT} n={len(out)}")
    print(out.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
