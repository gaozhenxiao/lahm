# -*- coding: utf-8 -*-
"""EmQuantAPI: historical K + permission check (realtime separately)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\GaoZX\Downloads\EMQuantAPI_Python\EMQuantAPI_Python\python3")
from EmQuantAPI import c  # noqa: E402


def flush(*a, **k):
    print(*a, **k)
    sys.stdout.flush()


def main() -> int:
    flush("===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "===")
    login = c.start("ForceLogin=1")
    flush("login", login.ErrorCode, login.ErrorMsg)
    if login.ErrorCode != 0:
        flush(c.geterrstring(login.ErrorCode, 0))
        return 1

    code = "600036.SH"
    today = datetime.now().strftime("%Y-%m-%d")

    # historical daily — last 15 calendar days
    start = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    flush("\n=== csd daily", code, start, "->", today, "===")
    d = c.csd(code, "OPEN,HIGH,LOW,CLOSE,VOLUME", start, today, "Period=1,Adjustflag=1,Ispandas=0")
    flush("csd", d.ErrorCode, d.ErrorMsg)
    if d.ErrorCode == 0:
        ok = 0
        for j, dt in enumerate(d.Dates):
            row = {d.Indicators[i]: d.Data[code][i][j] for i in range(len(d.Indicators))}
            if row.get("CLOSE") not in (None, ""):
                ok += 1
                flush(" ", dt, row)
        flush("non_null_bars", ok, "total_dates", len(d.Dates))

    # css snapshot-like cross section for yesterday-ish
    for td in ["2026-08-06", "2026-08-05", "2026-08-04"]:
        flush("\n=== css TradeDate=", td, "===")
        s = c.css(code, "OPEN,HIGH,LOW,CLOSE,VOLUME,AMOUNT", f"TradeDate={td},Ispandas=0")
        flush("css", s.ErrorCode, s.ErrorMsg)
        if s.ErrorCode == 0:
            flush(dict(zip(s.Indicators, s.Data[code])))
            if s.Data[code][0] not in (None, ""):
                break

    # historical minute K for a recent trading day (full day may be heavy — try 30 min window)
    day = "20260805"
    st, et = day + "100000", day + "103000"
    flush("\n=== cmc hist 1m", st, "->", et, "===")
    m = c.cmc(code, "OPEN,HIGH,LOW,CLOSE,VOLUME", st, et, "Period=1,Adjustflag=1,Ispandas=0")
    flush("cmc", m.ErrorCode, m.ErrorMsg)
    if m.ErrorCode == 0:
        flush("indicators", m.Indicators, "n_dates", len(m.Dates))
        n = len(m.Dates)
        for j in range(min(3, n)):
            row = {m.Indicators[i]: m.Data[i][j] for i in range(len(m.Indicators))}
            flush(" head", m.Dates[j], row)
        for j in range(max(0, n - 3), n):
            row = {m.Indicators[i]: m.Data[i][j] for i in range(len(m.Indicators))}
            flush(" tail", m.Dates[j], row)

    # realtime permission probe
    flush("\n=== realtime permission probe ===")
    snap = c.csqsnapshot(code, "NOW,VOLUME", "Ispandas=0")
    flush("csqsnapshot", snap.ErrorCode, snap.ErrorMsg)
    if snap.ErrorCode != 0:
        flush("cn=", c.geterrstring(snap.ErrorCode, 0))

    stop = c.stop()
    flush("\nstop", stop.ErrorCode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
