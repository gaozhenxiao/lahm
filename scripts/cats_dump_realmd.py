# encoding: UTF-8
"""
CATS 客户端策略框架：只读订阅实时行情并落盘（不下单）。

用法（在已登录的 Wealth CATS 中）：
1. 策略 / 脚本管理里加载本文件
2. 参数 symbols 默认 600030.SH,000001.SZ；out_path 默认写到本机 lahm 目录
3. 启动后查看 out_path 是否持续追加行情行

注意：必须在 CATS 客户端策略框架内运行，独立 Python 进程无法调用 sub_realmd。
"""

from strategy_platform.api import (
    sub_realmd,
    register_realmd_cb,
    add_argument,
    second_timer,
)

symbols = "600030.SH,000001.SZ"
out_path = r"D:\cursor_space\lahm\data\cats\realmd_live.txt"
max_rows = 200
start_time = "09:00:00"
end_time = "23:59:59"

add_argument("symbols", str, 0, symbols)
add_argument("out_path", str, 0, out_path)
add_argument("max_rows", int, 0, max_rows)
add_argument("start_time", str, 0, start_time)
add_argument("end_time", str, 2, end_time)

_rows = 0


def _append(line):
    global _rows
    import os
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    _rows += 1


def on_realmd(md, cb_arg):
    line = (
        "symbol={0} last={1} open={2} high={3} low={4} prevClose={5} "
        "volume={6} turnover={7} time={8}".format(
            getattr(md, "symbol", ""),
            getattr(md, "lastPrice", ""),
            getattr(md, "openPrice", ""),
            getattr(md, "highPrice", ""),
            getattr(md, "lowPrice", ""),
            getattr(md, "prevClosePrice", getattr(md, "preClosePrice", "")),
            getattr(md, "volume", ""),
            getattr(md, "turnover", ""),
            getattr(md, "time", getattr(md, "dataTime", "")),
        )
    )
    log.info(line)
    _append(line)
    if _rows >= max_rows:
        log.info("reached max_rows={}, stop timer keep process".format(max_rows))


def on_timer(arg):
    log.info("dump_realmd alive rows={0} out={1}".format(_rows, out_path))


def initialize(params):
    global symbols, out_path, max_rows
    symbols = params["symbols"]
    out_path = params["out_path"]
    max_rows = int(params["max_rows"])
    register_realmd_cb(on_realmd)
    universe = [s.strip() for s in symbols.split(",") if s.strip()]
    sub_realmd(universe)
    second_timer(10, on_timer, None)
    _append("# start symbols={0}".format(",".join(universe)))
    log.info("dump_realmd started -> {0}".format(out_path))


def finalize(params):
    log.info("dump_realmd finalize rows={0}".format(_rows))
