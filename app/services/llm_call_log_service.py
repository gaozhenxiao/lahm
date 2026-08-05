# -*- coding: utf-8 -*-
"""LLM API 调用输入/输出日志（用于调试与余额监控）。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("app.services.llm_call_log")

COLLECTION = "llm_api_call_logs"
MAX_TEXT = 12000
MAX_KEEP = 500  # 最多保留条数，防止无限膨胀
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    s = "" if text is None else str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} chars]"


def messages_to_text(messages: Any) -> str:
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    parts: List[str] = []
    try:
        for m in messages:
            role = getattr(m, "type", None) or getattr(m, "role", None) or m.__class__.__name__
            content = getattr(m, "content", m)
            if isinstance(content, list):
                chunks = []
                for c in content:
                    if isinstance(c, dict):
                        chunks.append(str(c.get("text") or c.get("content") or c))
                    else:
                        chunks.append(getattr(c, "text", None) or str(c))
                content = " ".join(chunks)
            parts.append(f"[{role}] {content}")
    except Exception:  # noqa: BLE001
        return _clip(messages)
    return "\n".join(parts)


def result_to_text(result: Any) -> str:
    try:
        gens = getattr(result, "generations", None)
        if gens:
            texts = []
            for g in gens:
                if isinstance(g, list) and g:
                    msg = getattr(g[0], "message", None)
                    texts.append(getattr(msg, "content", None) or str(g[0]))
                else:
                    texts.append(str(g))
            return "\n".join(texts)
        content = getattr(result, "content", None)
        if content is not None:
            if isinstance(content, list):
                return " ".join(str(x) for x in content)
            return str(content)
    except Exception:  # noqa: BLE001
        pass
    return str(result)


def extract_usage(result: Any) -> Dict[str, Optional[int]]:
    usage = None
    try:
        usage = getattr(result, "usage_metadata", None)
        if not usage and getattr(result, "llm_output", None):
            usage = (result.llm_output or {}).get("token_usage") or (result.llm_output or {}).get("usage")
        if not usage and getattr(result, "response_metadata", None):
            usage = (result.response_metadata or {}).get("token_usage") or (
                result.response_metadata or {}
            ).get("usage")
    except Exception:  # noqa: BLE001
        usage = None
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def log_llm_call(
    *,
    provider: str,
    model: str,
    input_text: str,
    output_text: str = "",
    error: Optional[str] = None,
    latency_ms: Optional[float] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """同步写入 Mongo（失败仅打日志，不影响主流程）。"""
    doc = {
        "timestamp": _now_iso(),
        "provider": provider or "unknown",
        "model": model or "unknown",
        "input": _clip(input_text),
        "output": _clip(output_text),
        "error": _clip(error, 4000) if error else None,
        "ok": error is None,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "meta": meta or {},
    }
    try:
        with _lock:
            from app.core.database import get_mongo_db_sync

            db = get_mongo_db_sync()
            col = db[COLLECTION]
            col.insert_one(doc)
            n = col.count_documents({})
            if n > MAX_KEEP:
                old = list(col.find({}, {"_id": 1}).sort("timestamp", 1).limit(n - MAX_KEEP))
                if old:
                    col.delete_many({"_id": {"$in": [x["_id"] for x in old]}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm call log write failed: %s", exc)


async def list_llm_call_logs(
    *,
    provider: Optional[str] = None,
    limit: int = 50,
    only_errors: bool = False,
) -> List[Dict[str, Any]]:
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    q: Dict[str, Any] = {}
    if provider:
        q["provider"] = provider
    if only_errors:
        q["ok"] = False
    cursor = db[COLLECTION].find(q, {"_id": 0}).sort("timestamp", -1).limit(max(1, min(limit, 200)))
    return [doc async for doc in cursor]
