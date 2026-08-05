# -*- coding: utf-8 -*-
"""财联社电报抓取（v1/roll + 签名）。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("webapi.cls_telegraph")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cls.cn/telegraph",
    "Accept": "application/json, text/plain, */*",
}


def _sign(params: Dict[str, Any]) -> str:
    items = sorted(
        (k, "" if v is None else str(v))
        for k, v in params.items()
        if k != "sign"
    )
    raw = "&".join(f"{k}={v}" for k, v in items)
    return hashlib.md5(hashlib.sha1(raw.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()


def fetch_telegraph(limit: int = 40) -> List[Dict[str, Any]]:
    """返回标准化快讯列表：title/content/time/url/id。"""
    params: Dict[str, Any] = {
        "app": "CailianpressWeb",
        "os": "web",
        "sv": "8.4.6",
        "category": "",
        "last_time": "",
        "refresh_type": 1,
        "rn": min(int(limit), 50),
    }
    params["sign"] = _sign(params)
    url = "https://www.cls.cn/v1/roll/get_roll_list"
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cls roll failed: %s", exc)
        return _fallback_akshare(limit)

    if not isinstance(data, dict) or data.get("errno") not in (0, "0", None):
        logger.warning("cls roll bad payload: %s", str(data)[:200])
        return _fallback_akshare(limit)

    rows = ((data.get("data") or {}).get("roll_data")) or []
    out: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        title = (row.get("title") or "").strip()
        content = (row.get("content") or row.get("brief") or title or "").strip()
        if not content and not title:
            continue
        nid = str(row.get("id") or row.get("article_id") or "")
        ctime = row.get("ctime") or row.get("time") or row.get("modified_time")
        ts = None
        if ctime:
            try:
                ts = datetime.fromtimestamp(int(ctime)).isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001
                ts = str(ctime)
        out.append(
            {
                "id": nid or hashlib.md5(content.encode("utf-8")).hexdigest()[:12],
                "title": title or content[:40],
                "content": content,
                "time": ts,
                "url": f"https://www.cls.cn/detail/{nid}" if nid else "https://www.cls.cn/telegraph",
                "source": "财联社",
                "subjects": row.get("subjects") or row.get("stock_list") or [],
            }
        )
    return out or _fallback_akshare(limit)


def _fallback_akshare(limit: int) -> List[Dict[str, Any]]:
    try:
        import akshare as ak

        df = ak.stock_info_global_cls(symbol="全部")
        if df is None or df.empty:
            df = ak.stock_info_global_em()
        items: List[Dict[str, Any]] = []
        for _, r in df.head(limit).iterrows():
            title = str(r.get("标题") or "")
            content = str(r.get("内容") or r.get("摘要") or title)
            items.append(
                {
                    "id": hashlib.md5((title + content).encode("utf-8")).hexdigest()[:12],
                    "title": title or content[:40],
                    "content": content,
                    "time": str(r.get("发布时间") or ""),
                    "url": str(r.get("链接") or "https://www.cls.cn/telegraph"),
                    "source": "akshare",
                    "subjects": [],
                }
            )
        return items
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare news fallback failed: %s", exc)
        return []


# ensure hashlib used in primary path too (already imported)
