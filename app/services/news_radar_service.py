# -*- coding: utf-8 -*-
"""新闻雷达：财联社快讯 → DeepSeek 重要性/标的影响 → 推荐。"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services import cls_telegraph

logger = logging.getLogger("webapi.news_radar")

ROOT = Path(__file__).resolve().parents[2]
CACHE_FP = ROOT / "data" / "reports" / "news_radar_latest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _deepseek_chat(prompt: str, *, max_tokens: int = 3500) -> str:
    from openai import OpenAI

    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key or key.startswith("your_"):
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    client = OpenAI(api_key=key, base_url=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com")
    kwargs: Dict[str, Any] = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是A股投研助手。只输出合法 JSON 对象，不要 markdown 代码块，不要注释。"
                    "关注对股价有短期或明确基本面影响的事件。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    try:
        kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
    except Exception:  # noqa: BLE001
        kwargs.pop("response_format", None)
        resp = client.chat.completions.create(**kwargs)
    text = (resp.choices[0].message.content or "").strip()
    try:
        from app.services.llm_call_log_service import log_llm_call

        usage = getattr(resp, "usage", None)
        log_llm_call(
            provider="deepseek",
            model="deepseek-chat",
            input_text=prompt[:4000],
            output_text=text[:4000],
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            meta={"adapter": "news_radar"},
        )
    except Exception:  # noqa: BLE001
        pass
    return text


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        # 截断 JSON 兜底：尽量提取已完整的 items 数组元素
        items = re.findall(r"\{[^{}]*\"id\"\s*:\s*\"[^\"]+\"[^{}]*\}", text)
        if items:
            parsed = []
            for chunk in items:
                try:
                    parsed.append(json.loads(chunk))
                except json.JSONDecodeError:
                    continue
            if parsed:
                return {"items": parsed}
        raise


def _heuristic_score(item: Dict[str, Any]) -> Dict[str, Any]:
    """无 LLM 时的关键词粗筛。"""
    text = f"{item.get('title','')} {item.get('content','')}"
    hot = [
        ("业绩", 2), ("预增", 3), ("预减", 3), ("暴雷", 4), ("立案", 4),
        ("回购", 2), ("增持", 2), ("减持", 2), ("中标", 3), ("重组", 3),
        ("并购", 3), ("涨停", 2), ("跌停", 2), ("央行", 2), ("降准", 3),
        ("降息", 3), ("制裁", 3), ("关税", 3), ("战争", 3), ("地震", 2),
        ("爆雷", 4), ("ST", 2), ("分红", 1), ("回购注销", 2),
    ]
    score = 1
    hits = []
    for k, w in hot:
        if k in text:
            score += w
            hits.append(k)
    score = min(score, 10)
    codes = re.findall(r"(?<!\d)([0-9]{6})(?!\d)", text)
    return {
        "id": item["id"],
        "importance": score,
        "important": score >= 5,
        "impact": "偏空" if any(x in text for x in ("暴雷", "立案", "预减", "跌停", "制裁")) else (
            "偏多" if any(x in text for x in ("预增", "中标", "回购", "增持", "涨停")) else "中性/待定"
        ),
        "stocks": [{"code": c, "name": "", "reason": "文中出现代码"} for c in codes[:5]],
        "summary": (item.get("title") or item.get("content") or "")[:80],
        "action": "关注" if score >= 5 else "略读",
        "reason": "关键词:" + (",".join(hits) if hits else "无明显热词"),
        "method": "heuristic",
    }


def _llm_triage(news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lines = []
    for i, n in enumerate(news[:18], 1):
        lines.append(
            f"{i}. id={n['id']} | {n.get('time','')} | {(n.get('title') or '')[:50]} | "
            f"{(n.get('content') or '')[:120]}"
        )
    prompt = (
        "下面是财联社快讯。请筛选对A股交易有参考价值的重大新闻，并推断可能受影响的标的。\n"
        "输出 JSON 对象，格式：\n"
        '{"items":[{"id":"...","importance":1-10,"important":true,'
        '"impact":"偏多","stocks":[{"code":"600519","name":"贵州茅台","reason":"业绩"}],'
        '"summary":"一句话","action":"建议关注","reason":"为何重要"}]}\n'
        "要求：importance>=6 才 important=true；stocks 尽量给6位A股代码，不确定可留空数组；"
        "最多返回8条重要新闻；字段值保持简短。\n\n"
        + "\n".join(lines)
    )
    text = _deepseek_chat(prompt, max_tokens=3500)
    data = _parse_json(text)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("bad llm shape")
    by_id = {n["id"]: n for n in news}
    out: List[Dict[str, Any]] = []
    for it in items:
        nid = str(it.get("id") or "")
        src = by_id.get(nid) or {}
        stocks = it.get("stocks") or []
        norm_stocks = []
        for s in stocks:
            if isinstance(s, dict):
                code = str(s.get("code") or "").zfill(6)[-6:]
                if code.isdigit():
                    norm_stocks.append(
                        {
                            "code": code,
                            "name": s.get("name") or "",
                            "reason": s.get("reason") or "",
                        }
                    )
        out.append(
            {
                "id": nid,
                "title": src.get("title") or it.get("summary") or "",
                "content": src.get("content") or "",
                "time": src.get("time"),
                "url": src.get("url"),
                "source": src.get("source") or "财联社",
                "importance": int(it.get("importance") or 0),
                "important": bool(it.get("important")),
                "impact": it.get("impact") or "中性/待定",
                "stocks": norm_stocks,
                "summary": it.get("summary") or "",
                "action": it.get("action") or "",
                "reason": it.get("reason") or "",
                "method": "deepseek",
            }
        )
    out.sort(key=lambda x: -int(x.get("importance") or 0))
    return out


def run_radar(*, limit: int = 40, use_llm: bool = True) -> Dict[str, Any]:
    raw = cls_telegraph.fetch_telegraph(limit=limit)
    analyzed: List[Dict[str, Any]] = []
    llm_error = None
    if use_llm and raw:
        try:
            analyzed = _llm_triage(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm triage failed: %s", exc)
            llm_error = str(exc)
    if not analyzed:
        analyzed = [_heuristic_score(n) for n in raw]
        for a in analyzed:
            src = next((n for n in raw if n["id"] == a["id"]), {})
            a.update(
                {
                    "title": src.get("title"),
                    "content": src.get("content"),
                    "time": src.get("time"),
                    "url": src.get("url"),
                    "source": src.get("source"),
                }
            )
        analyzed.sort(key=lambda x: -int(x.get("importance") or 0))

    important = [x for x in analyzed if x.get("important") or int(x.get("importance") or 0) >= 6]
    # 聚合推荐标的
    stock_map: Dict[str, Dict[str, Any]] = {}
    for n in important:
        for s in n.get("stocks") or []:
            code = s.get("code")
            if not code:
                continue
            row = stock_map.setdefault(
                code,
                {"code": code, "name": s.get("name") or "", "score": 0, "news": [], "impacts": []},
            )
            if s.get("name") and not row["name"]:
                row["name"] = s["name"]
            row["score"] += int(n.get("importance") or 0)
            row["news"].append(n.get("title") or n.get("summary"))
            row["impacts"].append(n.get("impact"))
    recommendations = sorted(stock_map.values(), key=lambda x: -x["score"])[:15]

    payload = {
        "asof": _now_iso(),
        "source": "cls.cn/v1/roll (+akshare fallback)",
        "llm_error": llm_error,
        "summary": {
            "n_raw": len(raw),
            "n_analyzed": len(analyzed),
            "n_important": len(important),
            "n_recommend_stocks": len(recommendations),
        },
        "important": important[:15],
        "recommendations": recommendations,
        "feed": raw[:30],
    }
    CACHE_FP.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FP.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_latest(*, refresh: bool = False, limit: int = 40, use_llm: bool = True) -> Dict[str, Any]:
    if not refresh and CACHE_FP.exists():
        try:
            cached = json.loads(CACHE_FP.read_text(encoding="utf-8"))
            # 30 分钟内可用
            asof = cached.get("asof")
            if asof:
                ts = datetime.fromisoformat(asof)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
                age = (datetime.now(ts.tzinfo) - ts).total_seconds()
                if age <= 1800:
                    cached["cached"] = True
                    cached["cache_age_sec"] = int(age)
                    return cached
        except Exception:  # noqa: BLE001
            pass
    data = run_radar(limit=limit, use_llm=use_llm)
    data["cached"] = False
    data["cache_age_sec"] = 0
    return data
