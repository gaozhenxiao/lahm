# -*- coding: utf-8 -*-
"""WCATS 行情桥：接收客户端策略推送的实时行情（内存 + 落盘快照）。"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "cats"
SNAPSHOT_PATH = DATA_DIR / "quotes_latest.json"
WATCHLIST_PATH = DATA_DIR / "watchlist.txt"

_lock = threading.Lock()
_quotes: Dict[str, Dict[str, Any]] = {}
_meta: Dict[str, Any] = {
    "last_push_ts": None,
    "push_count": 0,
    "bridge_alive_ts": None,
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.write_text(
            "600030.SH\n000001.SZ\n000300.SH\n", encoding="utf-8"
        )


def read_watchlist() -> List[str]:
    ensure_dirs()
    lines = WATCHLIST_PATH.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    for ln in lines:
        s = ln.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def upsert_quote(item: Dict[str, Any]) -> Dict[str, Any]:
    sym = str(item.get("symbol") or "").strip()
    if not sym:
        raise ValueError("symbol required")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    row = {
        "symbol": sym,
        "last": _num(item.get("last")),
        "open": _num(item.get("open")),
        "high": _num(item.get("high")),
        "low": _num(item.get("low")),
        "prev_close": _num(item.get("prev_close") or item.get("pre_close")),
        "volume": _num(item.get("volume")),
        "turnover": _num(item.get("turnover") or item.get("amount")),
        "bid1": _num(item.get("bid1")),
        "ask1": _num(item.get("ask1")),
        "md_time": item.get("time") or item.get("md_time") or "",
        "recv_ts": now,
    }
    with _lock:
        _quotes[sym] = row
        _meta["last_push_ts"] = now
        _meta["push_count"] = int(_meta.get("push_count") or 0) + 1
        _meta["bridge_alive_ts"] = now
        snap = {"meta": dict(_meta), "quotes": dict(_quotes)}
    _write_snapshot(snap)
    return row


def heartbeat(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with _lock:
        _meta["bridge_alive_ts"] = now
        if extra:
            _meta["bridge_extra"] = extra
        out = status_unlocked()
    return out


def get_quotes(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    with _lock:
        if not symbols:
            q = dict(_quotes)
        else:
            q = {s: _quotes[s] for s in symbols if s in _quotes}
        return {"meta": dict(_meta), "quotes": q, "watchlist": read_watchlist()}


def status() -> Dict[str, Any]:
    with _lock:
        return status_unlocked()


def status_unlocked() -> Dict[str, Any]:
    alive = _meta.get("bridge_alive_ts")
    age = None
    if alive:
        try:
            t0 = datetime.strptime(str(alive), "%Y-%m-%d %H:%M:%S.%f")
            age = (datetime.now() - t0).total_seconds()
        except Exception:
            age = None
    return {
        "ok": True,
        "symbol_count": len(_quotes),
        "push_count": _meta.get("push_count"),
        "last_push_ts": _meta.get("last_push_ts"),
        "bridge_alive_ts": alive,
        "bridge_age_sec": age,
        "bridge_fresh": age is not None and age < 30,
        "watchlist": read_watchlist(),
        "snapshot_path": str(SNAPSHOT_PATH),
    }


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _write_snapshot(snap: Dict[str, Any]) -> None:
    ensure_dirs()
    tmp = SNAPSHOT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
