# -*- coding: utf-8 -*-
"""Stepwise EmQuantAPI realtime/minute-K probe with per-call timeouts."""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\GaoZX\Downloads\EMQuantAPI_Python\EMQuantAPI_Python\python3")
from EmQuantAPI import c  # noqa: E402


def flush(*a, **k):
    print(*a, **k)
    sys.stdout.flush()


def call_timeout(fn, timeout_s: float, label: str):
    flush(f"\n>>> {label} (timeout={timeout_s}s)")
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout:
            flush(f"!!! TIMEOUT {label}")
            return None


def main() -> int:
    flush("===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "===")
    login = call_timeout(lambda: c.start("ForceLogin=1"), 30, "start")
    if login is None:
        return 2
    flush("start", login.ErrorCode, getattr(login, "ErrorMsg", None))
    if login.ErrorCode != 0:
        flush(c.geterrstring(login.ErrorCode, 0))
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    code = "600036.SH"

    # A) daily K (should be fast)
    def do_csd():
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        return c.csd(code, "OPEN,HIGH,LOW,CLOSE,VOLUME", start, today, "Period=1,Adjustflag=1,Ispandas=0")

    d = call_timeout(do_csd, 20, "csd daily")
    if d is not None:
        flush("csd", d.ErrorCode, d.ErrorMsg)
        if d.ErrorCode == 0 and d.Dates:
            j = len(d.Dates) - 1
            row = {d.Indicators[i]: d.Data[code][i][j] for i in range(len(d.Indicators))}
            flush(" last", d.Dates[j], row)

    # B) snapshot
    def do_snap():
        return c.csqsnapshot(code, "TIME,PRECLOSE,OPEN,HIGH,LOW,NOW,VOLUME,AMOUNT", "Ispandas=0")

    snap = call_timeout(do_snap, 15, "csqsnapshot")
    if snap is not None:
        flush("snap", snap.ErrorCode, snap.ErrorMsg)
        if snap.ErrorCode == 0:
            for cd in snap.Codes:
                flush(cd, dict(zip(snap.Indicators, snap.Data[cd])))

    # C) minute K — narrow morning window, single stock
    def do_cmc():
        # 14-digit datetime range for today morning session
        st = datetime.now().strftime("%Y%m%d") + "093000"
        et = datetime.now().strftime("%Y%m%d%H%M%S")
        return c.cmc(code, "OPEN,HIGH,LOW,CLOSE,VOLUME", st, et, "Period=1,Adjustflag=1,Ispandas=0")

    m = call_timeout(do_cmc, 25, "cmc 1m morning~now")
    if m is not None:
        flush("cmc", m.ErrorCode, m.ErrorMsg)
        if m.ErrorCode == 0:
            flush("indicators", m.Indicators, "dates", len(m.Dates))
            # single-code cmc uses rank-2 layout in Data[i][j]
            n = len(m.Dates)
            flush("head dates", m.Dates[:2], "tail", m.Dates[-3:])
            for j in range(max(0, n - 3), n):
                try:
                    row = {m.Indicators[i]: m.Data[i][j] for i in range(len(m.Indicators))}
                except Exception:
                    row = {m.Indicators[i]: m.Data[code][i][j] for i in range(len(m.Indicators))}
                flush(" ", m.Dates[j], row)

    # D) short realtime subscribe
    pushes = []

    def on_csq(qd):
        pushes.append(str(qd))
        flush("PUSH", str(qd)[:200])

    def do_sub():
        return c.csq(code, "TIME,NOW,OPEN,HIGH,LOW,VOLUME", "Pushtype=2", on_csq)

    sub = call_timeout(do_sub, 10, "csq subscribe")
    if sub is not None:
        flush("sub", sub.SerialID, sub.ErrorCode, sub.ErrorMsg)
        if sub.ErrorCode == 0:
            time.sleep(5)
            c.csqcancel(sub.SerialID)
            flush("pushes", len(pushes))

    stop = call_timeout(lambda: c.stop(), 10, "stop")
    flush("stop", getattr(stop, "ErrorCode", stop))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
