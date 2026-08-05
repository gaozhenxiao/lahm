# encoding: UTF-8
"""
WCATS 行情桥（客户端策略，只读，不下单）

在已登录的 Wealth CATS「策略框架」里加载本文件，启动一次即可：
- 订阅 data/cats/watchlist.txt 中的标的（每 30 秒热加载）
- 把实时行情 POST 到本机 lahm：http://127.0.0.1:8000/api/cats/bridge/quote
- 同时写本地快照兜底：data/cats/bridge_raw.jsonl

lahm 侧查询：
  GET /api/cats/bridge/status
  GET /api/cats/bridge/quotes
"""

from strategy_platform.api import (
    add_argument,
    register_realmd_cb,
    second_timer,
    sub_realmd,
    unsub_realmd,
)

watchlist_path = r"D:\cursor_space\lahm\data\cats\watchlist.txt"
bridge_url = "http://127.0.0.1:8000/api/cats/bridge"
bridge_token = "lahm-local"
raw_path = r"D:\cursor_space\lahm\data\cats\bridge_raw.jsonl"
start_time = "09:00:00"
end_time = "23:59:59"

add_argument("watchlist_path", str, 0, watchlist_path)
add_argument("bridge_url", str, 0, bridge_url)
add_argument("bridge_token", str, 0, bridge_token)
add_argument("raw_path", str, 0, raw_path)
add_argument("start_time", str, 0, start_time)
add_argument("end_time", str, 2, end_time)

_subscribed = set()
_push_ok = 0
_push_fail = 0


def _read_watchlist():
    import os

    if not os.path.isfile(watchlist_path):
        return ["600030.SH", "000001.SZ"]
    out = []
    with open(watchlist_path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.split("#", 1)[0].strip()
            if s:
                out.append(s)
    return out or ["600030.SH", "000001.SZ"]


def _http_json(method, path, payload):
    import json
    import urllib.request

    url = bridge_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Cats-Bridge-Token": bridge_token,
        },
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.read()


def _append_raw(obj):
    import json
    import os

    d = os.path.dirname(raw_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(raw_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _g(md, *names):
    for n in names:
        if hasattr(md, n):
            v = getattr(md, n)
            if v is not None and v != "":
                return v
    return None


def on_realmd(md, cb_arg):
    global _push_ok, _push_fail
    item = {
        "symbol": _g(md, "symbol", "Symbol"),
        "last": _g(md, "lastPrice", "last", "LastPrice"),
        "open": _g(md, "openPrice", "open", "Open"),
        "high": _g(md, "highPrice", "high", "High"),
        "low": _g(md, "lowPrice", "low", "Low"),
        "prev_close": _g(md, "prevClosePrice", "preClosePrice", "preClose"),
        "volume": _g(md, "volume", "Volume"),
        "turnover": _g(md, "turnover", "amount", "Amount"),
        "bid1": _g(md, "bidPrice1", "bid1"),
        "ask1": _g(md, "askPrice1", "ask1"),
        "time": _g(md, "time", "dataTime", "updateTime"),
    }
    try:
        _append_raw(item)
    except Exception:
        pass
    try:
        _http_json("POST", "/quote", item)
        _push_ok += 1
    except Exception as ex:
        _push_fail += 1
        if _push_fail <= 3 or _push_fail % 50 == 0:
            log.info("bridge push fail: {}".format(ex))


def _sync_subs():
    global _subscribed
    want = set(_read_watchlist())
    add = sorted(want - _subscribed)
    rem = sorted(_subscribed - want)
    if rem:
        try:
            unsub_realmd(rem)
        except Exception as ex:
            log.info("unsub fail: {}".format(ex))
    if add:
        try:
            sub_realmd(add)
            log.info("sub {}".format(add))
        except Exception as ex:
            log.info("sub fail: {}".format(ex))
    _subscribed = want


def on_timer(arg):
    _sync_subs()
    try:
        _http_json(
            "POST",
            "/heartbeat",
            {
                "rows": _push_ok,
                "symbols": sorted(_subscribed),
                "note": "fail={}".format(_push_fail),
            },
        )
    except Exception as ex:
        log.info("heartbeat fail: {}".format(ex))
    log.info(
        "bridge alive ok={} fail={} nsym={}".format(
            _push_ok, _push_fail, len(_subscribed)
        )
    )


def initialize(params):
    global watchlist_path, bridge_url, bridge_token, raw_path
    watchlist_path = params["watchlist_path"]
    bridge_url = params["bridge_url"]
    bridge_token = params["bridge_token"]
    raw_path = params["raw_path"]
    register_realmd_cb(on_realmd)
    _sync_subs()
    second_timer(30, on_timer, None)
    log.info("wcats bridge started -> {}".format(bridge_url))


def finalize(params):
    log.info("wcats bridge finalize ok={} fail={}".format(_push_ok, _push_fail))
