"""打印若干大亏/对照案例过程。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEGS = ROOT / "data" / "factors" / "earnings_forecast" / "trade_legs.parquet"
EV = ROOT / "data" / "factors" / "earnings_forecast" / "positive_events.parquet"
DAILY = ROOT / "data" / "factors" / "earnings_forecast" / "daily"


def story(code: str, pub: str) -> None:
    legs = pd.read_parquet(LEGS)
    legs["event_pub"] = pd.to_datetime(legs["event_pub"])
    r = legs[(legs["code"] == code) & (legs["event_pub"] == pub)].iloc[0]
    ev = pd.read_parquet(EV)
    ev["profitForcastExpPubDate"] = pd.to_datetime(ev["profitForcastExpPubDate"])
    e = ev[(ev["code"] == code) & (ev["profitForcastExpPubDate"] == pub)].iloc[0]
    px = pd.read_parquet(DAILY / f"{code.replace('.', '_')}.parquet")
    px["date"] = pd.to_datetime(px["date"])

    peak = None
    if r["entry_mode"] == "pullback":
        ann = px[px["date"] >= pd.Timestamp(pub)].iloc[0]
        seg = px[(px["date"] >= ann["date"]) & (px["date"] <= r["entry_date"])]
        peak = float(seg["high"].max())
    ret = float(r["exit_price"]) / float(r["entry_price"]) - 1

    print(f"【{code}】")
    print(
        f"  预告: {e.get('profitForcastType')} "
        f"下限{e.get('profitForcastChgPctDwn')}% 上限{e.get('profitForcastChgPctUp')}%"
    )
    print(
        f"  公告日 {pub} | 档位 {r['surprise_tier']} | 路径 {r['entry_mode']}"
    )
    print(
        f"  短期涨幅 {float(r['pre_run'])*100:.1f}% | "
        f"两年涨幅 {float(r['lt_run'])*100:.0f}% | {r['chase_reason']}"
    )
    print(
        f"  买入 {pd.Timestamp(r['entry_date']).date()} "
        f"价{float(r['entry_price']):.2f}"
        + (f" | 公告后高点≈{peak:.2f} 回撤{float(r['pullback'])*100:.1f}%" if peak else "")
    )
    print(
        f"  卖出 {pd.Timestamp(r['exit_date']).date()} "
        f"价{float(r['exit_price']):.2f} ({r['reason']}) | 盈亏 {ret*100:.1f}%"
    )
    for d in [pub, str(pd.Timestamp(r["entry_date"]).date()), str(pd.Timestamp(r["exit_date"]).date())]:
        row = px[px["date"] == pd.Timestamp(d)]
        if len(row):
            rr = row.iloc[0]
            print(f"    · {d} 收盘{float(rr['close']):.2f} 涨跌{rr.get('pctChg')}%")
    print()


def main() -> None:
    cases = [
        ("sz.300476", "2025-03-10"),
        ("sz.002532", "2024-07-09"),
        ("sh.601689", "2023-01-13"),
        ("sz.002493", "2022-01-29"),
        ("sz.000977", "2026-07-08"),
        ("sh.600233", "2026-07-01"),
    ]
    for code, pub in cases:
        try:
            story(code, pub)
        except Exception as exc:  # noqa: BLE001
            print(f"fail {code} {pub}: {exc}\n")


if __name__ == "__main__":
    main()
