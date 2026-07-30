"""构建汇金季报持仓日历（按公告日对齐，避免报告期截止日前视）。

数据源: akshare.stock_main_stock_holder（十大股东）
默认标的: 四大行 + 光大（汇金持股较稳定、变动可观测）

用法:
  python scripts/build_huijin_quarterly_calendar.py
  python scripts/build_huijin_quarterly_calendar.py --refresh
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors.national_team import (  # noqa: E402
    build_huijin_quarterly_calendar,
    fetch_huijin_bank_holdings_raw,
)

OUT_RAW = ROOT / "data" / "factors" / "huijin_holdings_raw.csv"
OUT_CAL = ROOT / "data" / "factors" / "huijin_quarterly_calendar.csv"


def main() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="重新拉取十大股东原始表")
    args = parser.parse_args()

    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    if args.refresh or not OUT_RAW.exists():
        print("[huijin] fetching bank top holders …")
        raw = fetch_huijin_bank_holdings_raw()
        if raw.empty:
            raise SystemExit("拉取失败：无数据")
        raw.to_csv(OUT_RAW, index=False, encoding="utf-8-sig")
        print(f"[huijin] wrote {OUT_RAW} rows={len(raw)}")
    else:
        raw = pd.read_csv(OUT_RAW)
        print(f"[huijin] reuse {OUT_RAW} rows={len(raw)}")

    cal, detail = build_huijin_quarterly_calendar(raw)
    cal.to_csv(OUT_CAL, index=False, encoding="utf-8-sig")
    detail_path = ROOT / "data" / "factors" / "huijin_quarterly_detail.csv"
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    print(f"[huijin] calendar events={len(cal)} -> {OUT_CAL}")
    if not cal.empty:
        print(cal.tail(12).to_string(index=False))
        lag = (pd.to_datetime(cal["announce_date"]) - pd.to_datetime(cal["period_end"])).dt.days
        print(f"[huijin] announce lag days: mean={lag.mean():.1f} median={lag.median():.1f}")


if __name__ == "__main__":
    main()
