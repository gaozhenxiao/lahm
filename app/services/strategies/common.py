# -*- coding: utf-8 -*-
"""策略扫描公共工具：缓存 / 序列化。"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("webapi.strategies")

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "strategies"
DEFAULT_TTL_SEC = 300


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def cache_path(strategy_id: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{strategy_id}_latest.json"


def read_cache(strategy_id: str) -> Optional[Dict[str, Any]]:
    fp = cache_path(strategy_id)
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("read cache %s failed: %s", strategy_id, exc)
        return None


def write_cache(strategy_id: str, payload: Dict[str, Any]) -> None:
    fp = cache_path(strategy_id)
    fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_age_sec(payload: Dict[str, Any]) -> Optional[float]:
    asof = payload.get("asof")
    if not asof:
        return None
    try:
        ts = datetime.fromisoformat(str(asof))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return (datetime.now(ts.tzinfo) - ts).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def cached_scan(
    strategy_id: str,
    scan_fn: Callable[[], Dict[str, Any]],
    *,
    refresh: bool = False,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> Dict[str, Any]:
    if not refresh:
        cached = read_cache(strategy_id)
        if cached:
            age = cache_age_sec(cached)
            if age is not None and age <= ttl_sec:
                out = dict(cached)
                out["cached"] = True
                out["cache_age_sec"] = int(age)
                return out
    payload = scan_fn()
    payload.setdefault("strategy_id", strategy_id)
    payload.setdefault("asof", now_iso())
    payload["cached"] = False
    payload["cache_age_sec"] = 0
    write_cache(strategy_id, payload)
    return payload
