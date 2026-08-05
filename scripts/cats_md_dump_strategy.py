# encoding: UTF-8
"""CATS 客户端策略：只订阅行情并落盘（不下单）。

在 Wealth CATS 客户端「策略框架」中加载本文件（需已登录）。
输出：D:/cursor_space/lahm/data/cats/md_live.csv
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime

from strategy_platform.api import add_argument, register_realmd_cb, sub_realmd

universe = "600030.SH,000001.SZ,000300.SH"
out_path = r"D:\cursor_space\lahm\data\cats\md_live.csv"
max_rows = 200
start_time = "09:15:00"
end_time = "15:15:00"

add_argument("symbol", str, 0, universe)
add_argument("out_path", str, 0, out_path)
add_argument("max_rows", int, 0, max_rows)
add_argument("start_time", str, 0, start_time)
add_argument("end_time", str, 2, end_time)

_rows = 0
_fh = None
_writer = None


def _ensure_writer():
    global _fh, _writer
    if _writer is not None:
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    new_file = not os.path.exists(out_path)
    _fh = open(out_path, "a", newline="", encoding="utf-8")
    _writer = csv.writer(_fh)
    if new_file:
        _writer.writerow(
            [
                "ts_local",
                "symbol",
                "last",
                "pre_close",
                "open",
                "high",
                "low",
                "volume",
                "amount",
                "bid1",
                "ask1",
            ]
        )
        _fh.flush()


def _g(obj, *names, default=""):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None and v != "":
                return v
    return default


def on_realmd(md, cb_arg):
    global _rows
    try:
        _ensure_writer()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            _g(md, "symbol", "Symbol"),
            _g(md, "lastPrice", "last", "LastPrice"),
            _g(md, "preClose", "PreClose"),
            _g(md, "open", "Open"),
            _g(md, "high", "High"),
            _g(md, "low", "Low"),
            _g(md, "volume", "Volume"),
            _g(md, "amount", "turnover", "Amount"),
            _g(md, "bidPrice1", "bid1"),
            _g(md, "askPrice1", "ask1"),
        ]
        _writer.writerow(row)
        _fh.flush()
        _rows += 1
        if _rows <= 5 or _rows % 50 == 0:
            log.info("md dump row={} {}".format(_rows, row[:6]))
        if _rows >= max_rows:
            log.info("reached max_rows={}, stop writing".format(max_rows))
    except Exception as ex:
        log.info("on_realmd error: {}".format(ex))


def initialize(context):
    global universe, out_path, max_rows
    universe = context.symbol
    out_path = context.out_path
    max_rows = int(context.max_rows)
    syms = [s.strip() for s in str(universe).split(",") if s.strip()]
    register_realmd_cb(on_realmd)
    sub_realmd(",".join(syms) if len(syms) > 1 else syms[0])
    log.info("cats_md_dump start symbols={} out={}".format(syms, out_path))


def terminate(context):
    global _fh
    try:
        if _fh:
            _fh.close()
    except Exception:
        pass
    log.info("cats_md_dump terminate rows={}".format(_rows))
