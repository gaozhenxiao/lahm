#coding:utf-8
"""lahm 行情导出（QMT 内置 Python 模型）

用法（完整 QMT 客户端内）：
1. 打开任意股票分时/K线图（建议 1 分钟周期）
2. 模型管理 / 公式 → 找到本文件 lahm_quote_export
3. 应用到主图或副图，切换到「实时」运行
4. 行情会写入：D:\\cursor_space\\lahm\\data\\qmt_feed\\

外部读取：
  python scripts/watch_qmt_feed.py
"""
from __future__ import print_function

import json
import os
import time
import traceback
from datetime import datetime

# 输出目录（lahm 项目）
OUT_DIR = r"D:\cursor_space\lahm\data\qmt_feed"

# 默认关注标的；也可在图上换主图股票，脚本会一并导出主图代码
DEFAULT_CODES = [
    "600036.SH",  # 招商银行
    "300059.SZ",  # 东方财富
    "000001.SZ",  # 平安银行
    "000300.SH",  # 沪深300
]

# 写盘节流（秒），避免 tick 过密把磁盘打满
MIN_WRITE_INTERVAL = 0.5


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dir():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)


def _to_plain(obj):
    """把 QMT/pandas 对象尽量转成 JSON 可序列化结构。"""
    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            # index 可能是时间字符串
            rec = obj.tail(20).reset_index()
            return json.loads(rec.to_json(orient="records", force_ascii=False))
        if isinstance(obj, pd.Series):
            return json.loads(obj.to_json(force_ascii=False))
    except Exception:
        pass
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[str(k)] = _to_plain(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    try:
        if hasattr(obj, "item"):
            return obj.item()
    except Exception:
        pass
    return str(obj)


def _write_payload(payload):
    _ensure_dir()
    latest = os.path.join(OUT_DIR, "latest.json")
    tmp = latest + ".tmp"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    with open(tmp, "w") as f:
        f.write(text)
    try:
        if os.path.exists(latest):
            os.remove(latest)
    except Exception:
        pass
    os.rename(tmp, latest)

    day = datetime.now().strftime("%Y%m%d")
    ndjson = os.path.join(OUT_DIR, "ticks_%s.ndjson" % day)
    line = json.dumps(payload, ensure_ascii=False)
    with open(ndjson, "a") as f:
        f.write(line + "\n")

    # 心跳
    hb = os.path.join(OUT_DIR, "heartbeat.txt")
    with open(hb, "w") as f:
        f.write(_now_str() + "\n")


def _collect_codes(ContextInfo):
    codes = list(DEFAULT_CODES)
    try:
        main = ContextInfo.stockcode + "." + ContextInfo.market
        if main and main not in codes:
            codes.insert(0, main)
    except Exception:
        pass
    try:
        uni = ContextInfo.get_universe() or []
        for c in uni:
            if c and c not in codes:
                codes.append(c)
    except Exception:
        pass
    return codes


def _export_once(ContextInfo, source):
    last = getattr(ContextInfo, "_lahm_last_write", 0)
    now = time.time()
    if now - last < MIN_WRITE_INTERVAL:
        return
    ContextInfo._lahm_last_write = now

    codes = _collect_codes(ContextInfo)
    payload = {
        "ts": _now_str(),
        "source": source,
        "codes": codes,
        "period": getattr(ContextInfo, "period", ""),
        "ticks": {},
        "bars_1m": {},
        "error": None,
    }
    try:
        ticks = ContextInfo.get_full_tick(codes)
        payload["ticks"] = _to_plain(ticks)
    except Exception as e:
        payload["error"] = "get_full_tick: %s" % e

    try:
        md = ContextInfo.get_market_data_ex(
            ["open", "high", "low", "close", "volume", "amount"],
            stock_code=codes,
            period="1m",
            count=5,
            dividend_type="none",
            fill_data=True,
            subscribe=True,
        )
        plain = {}
        if isinstance(md, dict):
            for code, df in md.items():
                plain[code] = _to_plain(df)
        else:
            plain["_raw"] = _to_plain(md)
        payload["bars_1m"] = plain
    except Exception as e:
        err = payload.get("error")
        msg = "get_market_data_ex: %s" % e
        payload["error"] = (err + " | " + msg) if err else msg

    try:
        _write_payload(payload)
        ContextInfo._lahm_write_count = getattr(ContextInfo, "_lahm_write_count", 0) + 1
        if ContextInfo._lahm_write_count % 20 == 1:
            print("[lahm_export]", payload["ts"], "codes=", len(codes), "ok")
    except Exception:
        print("[lahm_export] write fail")
        traceback.print_exc()


def _on_quote(ContextInfo):
    def callback(datas):
        try:
            # 订阅回调里也落一版（节流）
            last = getattr(ContextInfo, "_lahm_last_write", 0)
            if time.time() - last < MIN_WRITE_INTERVAL:
                return
            ContextInfo._lahm_last_write = time.time()
            payload = {
                "ts": _now_str(),
                "source": "subscribe_whole_quote",
                "codes": list(datas.keys()) if isinstance(datas, dict) else [],
                "ticks": _to_plain(datas),
                "bars_1m": {},
                "error": None,
            }
            _write_payload(payload)
        except Exception:
            traceback.print_exc()

    return callback


def init(ContextInfo):
    _ensure_dir()
    ContextInfo._lahm_last_write = 0
    ContextInfo._lahm_write_count = 0
    codes = _collect_codes(ContextInfo)
    try:
        ContextInfo.set_universe(codes)
    except Exception:
        pass

    # 全推行情订阅（有权限时更及时）
    try:
        ContextInfo.subscribe_whole_quote(codes, _on_quote(ContextInfo))
        print("[lahm_export] subscribe_whole_quote ok", codes)
    except Exception as e:
        print("[lahm_export] subscribe fail:", e)

    # 定时兜底：每 3 秒导出一次（部分版本支持 schedule_run）
    try:
        ContextInfo.schedule_run(
            lambda: _export_once(ContextInfo, "schedule"),
            -1,
            int(time.time() * 1000),
            -1,
            3000,
            "lahm_quote_export",
        )
        print("[lahm_export] schedule_run 3s ok")
    except Exception as e:
        print("[lahm_export] schedule_run unavailable:", e)

    print("[lahm_export] init ->", OUT_DIR)
    _export_once(ContextInfo, "init")


def handlebar(ContextInfo):
    # 只在最新 K 线实时刷新时导出
    try:
        if not ContextInfo.is_last_bar():
            return
    except Exception:
        pass
    _export_once(ContextInfo, "handlebar")
