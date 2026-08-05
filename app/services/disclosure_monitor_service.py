# -*- coding: utf-8 -*-
"""公告/业绩预告/快报监控：定时拉取 → 与本地对比 → 规则+LLM筛选 → 触发相关因子。

数据源说明：
- 同花顺 data.10jqka.com.cn 页面 Ajax 有 chameleon 反爬（常 401），不稳定。
- 实际采集走东财分页 API（只取最近几页，适配 10 分钟轮询），栏目语义对齐同花顺，并保留同花顺栏目 URL。
"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from app.core.config import settings
from app.core.database import get_mongo_db, get_mongo_db_sync

logger = logging.getLogger("app.services.disclosure_monitor")

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = "market_disclosures"
RUNS_COLLECTION = "disclosure_poll_runs"
ALERTS_MD = ROOT / "data" / "factors" / "disclosure_alerts_today.md"

# 栏目 ↔ 同花顺入口（用户指定）
CATEGORY_META = {
    "ggsd": {
        "name": "公告速递",
        "ths_url": "https://data.10jqka.com.cn/market/ggsd/",
    },
    "yjgg": {
        "name": "业绩公告",
        "ths_url": "https://data.10jqka.com.cn/financial/yjgg/",
    },
    "yjyg": {
        "name": "业绩预告",
        "ths_url": "https://data.10jqka.com.cn/financial/yjyg/",
    },
    "yjkb": {
        "name": "业绩快报",
        "ths_url": "https://data.10jqka.com.cn/financial/yjkb/",
    },
}

# 有用公告后优先重算的因子（轻量子集）
EARNINGS_FACTOR_IDS = [
    "dual_margin_expand",
    "np_margin_regime",
    "gross_net_catchup",
    "contract_liab_expand",
    "dual_yoy_accel_break",
    "netprofit_accel_break",
    "expr_ros_improve_break",
    "fcst_profit_gap",
    "earnings_forecast",
    "high_margin_m20_hold51",
    "high_margin_m15_hold52",
]

USEFUL_GGSD_KEYWORDS = (
    "业绩预告",
    "业绩快报",
    "年度报告",
    "半年度报告",
    "一季度报告",
    "三季度报告",
    "利润分配",
    "高送转",
    "回购",
    "增持",
    "减持",
    "中标",
    "合同",
    "重大合同",
    "股权激励",
    "定增",
    "并购",
    "重组",
    "问询函",
    "立案",
    "亏损",
    "扭亏",
)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def _now() -> datetime:
    return datetime.now(_tz())


def in_poll_window(now: Optional[datetime] = None) -> bool:
    """07:00-08:00 / 11:30-13:00 / 19:00-21:00（按配置的时区，每天）。"""
    now = now or _now()
    t = now.time()
    windows = [
        (dtime(7, 0), dtime(8, 0)),
        (dtime(11, 30), dtime(13, 0)),
        (dtime(19, 0), dtime(21, 0)),
    ]
    return any(a <= t <= b for a, b in windows)


def _to_bs_code(code: str) -> str:
    c = re.sub(r"\D", "", str(code or ""))[-6:].zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def _doc_id(category: str, code: str, title: str, ann_date: str) -> str:
    raw = f"{category}|{code}|{title}|{ann_date}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def candidate_report_periods(today: Optional[datetime] = None) -> List[str]:
    """业绩预告/快报/报表接口需要报告期 YYYYMMDD。"""
    today = today or _now()
    y = today.year
    candidates = [
        f"{y}0630",
        f"{y}0331",
        f"{y-1}1231",
        f"{y-1}0930",
        f"{y-1}0630",
    ]
    # 去重保序
    out: List[str] = []
    for x in candidates:
        if x not in out:
            out.append(x)
    return out


def _em_get(
    report_name: str,
    *,
    filter_expr: str,
    pages: int = 2,
    page_size: int = 50,
    sort_columns: str = "NOTICE_DATE,SECURITY_CODE",
) -> List[Dict[str, Any]]:
    """东财 datacenter 分页拉取（按公告日倒序，只取最近几页）。"""
    import requests

    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/",
    }
    out: List[Dict[str, Any]] = []
    for page in range(1, max(1, pages) + 1):
        params = {
            "sortColumns": sort_columns,
            "sortTypes": "-1,-1",
            "pageSize": str(page_size),
            "pageNumber": str(page),
            "reportName": report_name,
            "columns": "ALL",
            "filter": filter_expr,
        }
        r = requests.get(url, params=params, headers=headers, timeout=25)
        r.raise_for_status()
        data = (r.json() or {}).get("result") or {}
        chunk = data.get("data") or []
        if not chunk:
            break
        out.extend(chunk)
        if page >= int(data.get("pages") or 1):
            break
    return out


def _period_iso(period_yyyymmdd: str) -> str:
    p = re.sub(r"\D", "", period_yyyymmdd)[:8]
    return f"{p[:4]}-{p[4:6]}-{p[6:8]}"


def allowed_ann_dates(*, lookback_days: int = 1, now: Optional[datetime] = None) -> List[str]:
    """有效公告日：默认仅当天（1 个交易日有效）。lookback_days=2 才含昨日。"""
    now = now or _now()
    n = max(1, int(lookback_days))
    return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _fetch_yjyg(ann_day: str, *, pages: int = 3) -> List[Dict[str, Any]]:
    # 按公告日过滤，不做全量报告期扫描
    filt = f"(NOTICE_DATE='{ann_day}')"
    raw = _em_get("RPT_PUBLIC_OP_NEWPREDICT", filter_expr=filt, pages=pages)
    rows = []
    for r in raw:
        code = str(r.get("SECURITY_CODE") or "").zfill(6)
        title = str(r.get("CHANGE_REASON_EXPLAIN") or r.get("PREDICT_CONTENT") or r.get("PREDICT_FINANCE") or "")
        if not title:
            title = f"{r.get('PREDICT_TYPE') or '预告'} {r.get('PREDICT_FINANCE') or ''}".strip()
        ann = str(r.get("NOTICE_DATE") or "")[:10]
        if ann != ann_day:
            continue
        period = str(r.get("REPORT_DATE") or "")[:10].replace("-", "")
        rows.append(
            {
                "category": "yjyg",
                "code": code,
                "name": str(r.get("SECURITY_NAME_ABBR") or ""),
                "title": title,
                "ann_date": ann,
                "url": CATEGORY_META["yjyg"]["ths_url"],
                "extra": {
                    "指标": r.get("PREDICT_FINANCE"),
                    "预告类型": r.get("PREDICT_TYPE") or r.get("PREDICT_TYPE_NAME"),
                    "变动幅度": r.get("ADD_AMP_AVG") or r.get("ADD_AMP_LOWER") or r.get("YIELD"),
                    "预测数值": r.get("PREDICT_AMT_AVG") or r.get("PREDICT_AMT_UPPER"),
                    "报告期": period,
                },
            }
        )
    return rows


def _fetch_yjkb(ann_day: str, *, pages: int = 2) -> List[Dict[str, Any]]:
    # 业绩快报：优先按 NOTICE_DATE；无结果再扫当前报告期近页并本地滤日
    filt = f"(NOTICE_DATE='{ann_day}')"
    raw = _em_get(
        "RPT_FCI_PERFORMANCEE",
        filter_expr=filt,
        pages=pages,
        sort_columns="NOTICE_DATE,SECURITY_CODE",
    )
    if not raw:
        period = candidate_report_periods()[0]
        raw = _em_get(
            "RPT_FCI_PERFORMANCEE",
            filter_expr=f"(REPORT_DATE='{_period_iso(period)}')",
            pages=pages,
            sort_columns="UPDATE_DATE,SECURITY_CODE",
        )
    rows = []
    for r in raw:
        code = str(r.get("SECURITY_CODE") or "").zfill(6)
        yoy = r.get("JLRTBZCL")
        ry = r.get("YSTZ")
        title = f"业绩快报 净利同比{yoy}% 营收同比{ry}%"
        ann = str(r.get("NOTICE_DATE") or r.get("UPDATE_DATE") or "")[:10]
        if ann != ann_day:
            continue
        period = str(r.get("REPORT_DATE") or "")[:10].replace("-", "")
        rows.append(
            {
                "category": "yjkb",
                "code": code,
                "name": str(r.get("SECURITY_NAME_ABBR") or ""),
                "title": title,
                "ann_date": ann,
                "url": CATEGORY_META["yjkb"]["ths_url"],
                "extra": {
                    "营收同比": ry,
                    "净利同比": yoy,
                    "净资产收益率": r.get("WEIGHTAVG_ROE"),
                    "报告期": period,
                },
            }
        )
    return rows


def _fetch_yjgg(ann_day: str, *, pages: int = 5) -> List[Dict[str, Any]]:
    # 业绩公告：按 NOTICE_DATE 只取当日
    filt = f"(NOTICE_DATE='{ann_day}')"
    raw = _em_get(
        "RPT_LICO_FN_CPD",
        filter_expr=filt,
        pages=pages,
        sort_columns="NOTICE_DATE,SECURITY_CODE",
    )
    rows = []
    for r in raw:
        code = str(r.get("SECURITY_CODE") or "").zfill(6)
        yoy = r.get("SJLTZ")
        ry = r.get("YSTZ")
        title = f"业绩公告 净利同比{yoy}% 营收同比{ry}%"
        ann = str(r.get("NOTICE_DATE") or r.get("UPDATE_DATE") or "")[:10]
        if ann != ann_day:
            continue
        period = str(r.get("REPORTDATE") or r.get("REPORT_DATE") or "")[:10].replace("-", "")
        rows.append(
            {
                "category": "yjgg",
                "code": code,
                "name": str(r.get("SECURITY_NAME_ABBR") or ""),
                "title": title,
                "ann_date": ann,
                "url": CATEGORY_META["yjgg"]["ths_url"],
                "extra": {
                    "营收同比": ry,
                    "净利同比": yoy,
                    "销售毛利率": r.get("XSMLL"),
                    "报告期": period,
                },
            }
        )
    return rows


def _fetch_ggsd(*, ann_days: Sequence[str], page_size: int = 50, max_pages: int = 8) -> List[Dict[str, Any]]:
    """公告速递：最新流翻页，遇早于目标日即停。"""
    import requests

    allowed = set(ann_days)
    min_day = min(ann_days) if ann_days else _now().strftime("%Y-%m-%d")
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/notices/"}
    rows: List[Dict[str, Any]] = []
    for page in range(1, max(1, max_pages) + 1):
        r = requests.get(
            url,
            params={
                "page_size": page_size,
                "page_index": page,
                "ann_type": "A",
                "client_source": "web",
                "f_node": "0",
                "s_node": "0",
            },
            headers=headers,
            timeout=25,
        )
        r.raise_for_status()
        items = ((r.json() or {}).get("data") or {}).get("list") or []
        if not items:
            break
        older_count = 0
        for it in items:
            codes = it.get("codes") or []
            code = ""
            name = ""
            if codes:
                code = str(codes[0].get("stock_code") or "").zfill(6)
                name = str(codes[0].get("short_name") or "")
            title = str(it.get("title") or it.get("notice_title") or "")
            ann = str(it.get("notice_date") or "")[:10]
            if ann and ann < min_day:
                older_count += 1
                continue
            if ann not in allowed:
                continue
            cols = it.get("columns") or []
            col_name = cols[0].get("column_name") if cols else ""
            art = it.get("art_code") or ""
            detail = (
                f"https://data.eastmoney.com/notices/detail/{code}/{art}.html"
                if code and art
                else CATEGORY_META["ggsd"]["ths_url"]
            )
            rows.append(
                {
                    "category": "ggsd",
                    "code": code,
                    "name": name,
                    "title": title,
                    "ann_date": ann,
                    "url": detail,
                    "extra": {"公告类型": col_name},
                }
            )
        # 整页都早于目标日 → 停止翻页
        if older_count >= len(items):
            break
    return rows


def fetch_all_sources(*, lookback_days: int = 1) -> List[Dict[str, Any]]:
    """只拉有效公告日（默认当天），不做全量历史爬取。"""
    now = _now()
    ann_days = allowed_ann_dates(lookback_days=lookback_days, now=now)
    all_rows: List[Dict[str, Any]] = []

    for day in ann_days:
        for name, fn in (("yjyg", _fetch_yjyg), ("yjkb", _fetch_yjkb), ("yjgg", _fetch_yjgg)):
            try:
                rows = fn(day)
                all_rows.extend(rows)
                logger.info("disclosure fetch %s day=%s n=%s", name, day, len(rows))
            except Exception as e:  # noqa: BLE001
                logger.warning("disclosure fetch fail %s/%s: %s", name, day, e)

    try:
        rows = _fetch_ggsd(ann_days=ann_days)
        all_rows.extend(rows)
        logger.info("disclosure fetch ggsd days=%s n=%s", ann_days, len(rows))
    except Exception as e:  # noqa: BLE001
        logger.warning("disclosure fetch fail ggsd: %s", e)

    allowed = set(ann_days)
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in all_rows:
        code = re.sub(r"\D", "", str(r.get("code") or ""))[-6:].zfill(6)
        title = (r.get("title") or "").strip()
        ann = str(r.get("ann_date") or "")[:10]
        cat = r["category"]
        if not code or not title or ann not in allowed:
            continue
        did = _doc_id(cat, code, title, ann)
        if did in seen:
            continue
        seen.add(did)
        out.append(
            {
                "_id": did,
                "category": cat,
                "category_name": CATEGORY_META[cat]["name"],
                "ths_url": CATEGORY_META[cat]["ths_url"],
                "code": code,
                "bs_code": _to_bs_code(code),
                "name": r.get("name") or "",
                "title": title,
                "ann_date": ann,
                "url": r.get("url") or CATEGORY_META[cat]["ths_url"],
                "extra": r.get("extra") or {},
                "source": "eastmoney_api",
            }
        )
    return out


def rule_useful(doc: Dict[str, Any]) -> Tuple[bool, str]:
    """规则初筛：尽量少烧 LLM。"""
    cat = doc.get("category")
    title = str(doc.get("title") or "")
    extra = doc.get("extra") or {}

    if cat == "yjyg":
        typ = str(extra.get("预告类型") or "")
        amp = pd.to_numeric(extra.get("变动幅度"), errors="coerce")
        if typ in ("预增", "略增", "扭亏", "续盈", "减亏"):
            if pd.isna(amp) or float(amp) >= 20:
                return True, f"预告类型={typ} 幅度={amp}"
            return True, f"预告类型={typ}"
        if typ in ("预减", "首亏", "续亏", "略减"):
            return True, f"负面预告={typ}"
        return False, "预告类型不在关注列表"

    if cat in ("yjkb", "yjgg"):
        yoy = pd.to_numeric(extra.get("净利同比"), errors="coerce")
        ry = pd.to_numeric(extra.get("营收同比"), errors="coerce")
        if (not pd.isna(yoy) and abs(float(yoy)) >= 20) or (not pd.isna(ry) and abs(float(ry)) >= 20):
            return True, f"净利同比={yoy} 营收同比={ry}"
        if not pd.isna(yoy) and float(yoy) >= 10:
            return True, f"净利同比={yoy}"
        return False, "同比变动不足"

    # ggsd
    if any(k in title for k in USEFUL_GGSD_KEYWORDS):
        return True, "标题关键词命中"
    return False, "普通公告"


def llm_batch_useful(docs: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[bool, str]]:
    """对规则不确定的公告做批量 LLM 判断；失败则全部视为无用（不阻断）。"""
    if not docs:
        return {}
    if not getattr(settings, "DISCLOSURE_LLM_FILTER_ENABLED", True):
        return {d["_id"]: (False, "llm_disabled") for d in docs}

    # 控成本：最多 N 条
    max_n = int(getattr(settings, "DISCLOSURE_LLM_MAX_PER_RUN", 20) or 20)
    docs = list(docs)[:max_n]

    lines = []
    for i, d in enumerate(docs, 1):
        lines.append(
            f"{i}. id={d['_id'][:10]} {d.get('code')} {d.get('name')} "
            f"[{d.get('category_name')}] {d.get('title')[:120]}"
        )
    prompt = (
        "你是A股公告筛选助手。判断下列公告是否对短线/基本面因子有交易参考价值。"
        "有价值包括：业绩预告/快报/正式业绩、超预期或大幅变脸、回购增持、重大合同/中标、"
        "高送转、并购重组、重大风险（立案/问询/事故）。\n"
        "对每条只输出一行：id前缀|YES或NO|简短理由\n\n" + "\n".join(lines)
    )
    try:
        from openai import OpenAI
        import os

        key = os.getenv("DEEPSEEK_API_KEY") or ""
        if not key or key.startswith("your_"):
            return {d["_id"]: (False, "no_api_key") for d in docs}
        client = OpenAI(api_key=key, base_url=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=800,
        )
        text = (resp.choices[0].message.content or "").strip()
        try:
            from app.services.llm_call_log_service import log_llm_call

            usage = getattr(resp, "usage", None)
            log_llm_call(
                provider="deepseek",
                model="deepseek-chat",
                input_text=prompt,
                output_text=text,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                meta={"adapter": "disclosure_monitor"},
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        logger.warning("disclosure llm filter failed: %s", e)
        try:
            from app.services.llm_call_log_service import log_llm_call

            log_llm_call(
                provider="deepseek",
                model="deepseek-chat",
                input_text=prompt[:2000],
                error=str(e),
                meta={"adapter": "disclosure_monitor"},
            )
        except Exception:  # noqa: BLE001
            pass
        return {d["_id"]: (False, f"llm_error:{e}") for d in docs}

    result: Dict[str, Tuple[bool, str]] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        prefix, flag = parts[0], parts[1].upper()
        reason = parts[2] if len(parts) > 2 else ""
        for d in docs:
            if d["_id"].startswith(prefix.replace("id=", "").strip()[:8]) or prefix in d["_id"]:
                result[d["_id"]] = (flag.startswith("Y"), reason or flag)
    for d in docs:
        if d["_id"] not in result:
            result[d["_id"]] = (False, "llm_no_parse")
    return result


def upsert_and_diff(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """写入 Mongo，返回新增列表。"""
    db = get_mongo_db_sync()
    col = db[COLLECTION]
    col.create_index([("ann_date", -1), ("category", 1)])
    col.create_index([("code", 1), ("ann_date", -1)])
    col.create_index([("useful", 1), ("first_seen_at", -1)])

    now = _now().isoformat(timespec="seconds")
    new_docs: List[Dict[str, Any]] = []
    for r in rows:
        did = r["_id"]
        existing = col.find_one({"_id": did}, {"_id": 1})
        if existing:
            col.update_one(
                {"_id": did},
                {"$set": {"last_seen_at": now, "extra": r.get("extra") or {}}},
            )
            continue
        doc = {
            **r,
            "first_seen_at": now,
            "last_seen_at": now,
            "useful": None,
            "useful_reason": None,
            "useful_by": None,
            "factor_triggered": False,
        }
        col.insert_one(doc)
        new_docs.append(doc)
    return {"fetched": len(rows), "new": len(new_docs), "new_docs": new_docs}


def mark_useful(
    docs: List[Dict[str, Any]],
    *,
    lookback_days: int = 1,
) -> List[Dict[str, Any]]:
    """规则 +（可选）LLM 标记 useful。非有效公告日（默认仅当天）不计入有用增量。"""
    db = get_mongo_db_sync()
    col = db[COLLECTION]
    useful_docs: List[Dict[str, Any]] = []
    need_llm: List[Dict[str, Any]] = []
    allowed = set(allowed_ann_dates(lookback_days=lookback_days))

    for d in docs:
        ann = str(d.get("ann_date") or "")[:10]
        if ann not in allowed:
            col.update_one(
                {"_id": d["_id"]},
                {
                    "$set": {
                        "useful": False,
                        "useful_reason": f"非有效公告日(仅{sorted(allowed)})",
                        "useful_by": "lookback",
                    }
                },
            )
            continue
        ok, reason = rule_useful(d)
        if ok:
            col.update_one(
                {"_id": d["_id"]},
                {"$set": {"useful": True, "useful_reason": reason, "useful_by": "rule"}},
            )
            d["useful"] = True
            d["useful_reason"] = reason
            useful_docs.append(d)
        elif d.get("category") == "ggsd":
            need_llm.append(d)
        else:
            col.update_one(
                {"_id": d["_id"]},
                {"$set": {"useful": False, "useful_reason": reason, "useful_by": "rule"}},
            )

    if need_llm:
        llm_map = llm_batch_useful(need_llm)
        for d in need_llm:
            ok, reason = llm_map.get(d["_id"], (False, "llm_miss"))
            col.update_one(
                {"_id": d["_id"]},
                {
                    "$set": {
                        "useful": bool(ok),
                        "useful_reason": reason,
                        "useful_by": "llm",
                    }
                },
            )
            if ok:
                d["useful"] = True
                d["useful_reason"] = reason
                useful_docs.append(d)
    return useful_docs


def trigger_related_factors(
    useful_docs: List[Dict[str, Any]],
    *,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """有用新增 → 重算业绩相关因子子集。"""
    if not useful_docs:
        return {"skipped": True, "reason": "no_useful"}
    if enabled is None:
        enabled = bool(getattr(settings, "DISCLOSURE_TRIGGER_FACTORS", True))
    if not enabled:
        return {"skipped": True, "reason": "trigger_disabled"}

    cats = {d.get("category") for d in useful_docs}
    # 仅业绩类或明确有用时触发
    if not (cats & {"yjyg", "yjkb", "yjgg"} or any(d.get("useful") for d in useful_docs)):
        return {"skipped": True, "reason": "no_earnings_cat"}

    asof = _now().strftime("%Y-%m-%d")
    only = ",".join(EARNINGS_FACTOR_IDS)
    script = ROOT / "scripts" / "recompute_factor_signals_today.py"
    cmd = [sys.executable, str(script), "--asof", asof, "--only", only]
    logger.info("disclosure trigger factors: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=int(getattr(settings, "DISCLOSURE_FACTOR_TIMEOUT_SEC", 1200) or 1200),
        )
        db = get_mongo_db_sync()
        db[COLLECTION].update_many(
            {"_id": {"$in": [d["_id"] for d in useful_docs]}},
            {"$set": {"factor_triggered": True, "factor_trigger_at": _now().isoformat(timespec="seconds")}},
        )
        return {
            "rc": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-600:],
            "stderr_tail": (proc.stderr or "")[-300:],
            "factors": EARNINGS_FACTOR_IDS,
        }
    except Exception as e:  # noqa: BLE001
        logger.error("trigger factors failed: %s", e)
        return {"error": str(e)}


def write_alerts_md(useful_docs: List[Dict[str, Any]], stats: Dict[str, Any]) -> None:
    ALERTS_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 公告监控增量 {_now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- 拉取 {stats.get('fetched')} 条，新增 {stats.get('new')} 条，有用 {len(useful_docs)} 条",
        f"- 范围：仅有效公告日（默认当天）· 东财 API（对齐同花顺栏目）",
        "",
    ]
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for d in useful_docs:
        by_cat.setdefault(d.get("category") or "?", []).append(d)
    for cat, rows in by_cat.items():
        meta = CATEGORY_META.get(cat, {})
        lines.append(f"## {meta.get('name', cat)} · {len(rows)}")
        lines.append(f"- 栏目: {meta.get('ths_url', '')}")
        for d in rows[:80]:
            lines.append(
                f"- {d.get('code')} {d.get('name')} · {d.get('ann_date')} · "
                f"{d.get('title')[:100]} · _{d.get('useful_reason')}_"
            )
        lines.append("")
    ALERTS_MD.write_text("\n".join(lines), encoding="utf-8")


def run_disclosure_poll(
    *,
    force: bool = False,
    lookback_days: int = 1,
    trigger_factors: Optional[bool] = None,
) -> Dict[str, Any]:
    """单次轮询入口。"""
    now = _now()
    if not force and not in_poll_window(now):
        return {"skipped": True, "reason": "out_of_window", "now": now.isoformat()}

    rows = fetch_all_sources(lookback_days=lookback_days)
    diff = upsert_and_diff(rows)
    useful = mark_useful(diff["new_docs"], lookback_days=lookback_days)
    do_trigger = True if trigger_factors is None else bool(trigger_factors)
    factor_res = (
        trigger_related_factors(useful, enabled=do_trigger) if useful else {"skipped": True}
    )
    stats = {
        "fetched": diff["fetched"],
        "new": diff["new"],
        "useful": len(useful),
        "factor": factor_res,
        "finished_at": now.isoformat(timespec="seconds"),
    }
    write_alerts_md(useful, stats)
    try:
        db = get_mongo_db_sync()
        db[RUNS_COLLECTION].insert_one({**stats, "window_ok": True})
    except Exception as e:  # noqa: BLE001
        logger.warning("poll run log fail: %s", e)
    logger.info(
        "disclosure poll done fetched=%s new=%s useful=%s",
        stats["fetched"],
        stats["new"],
        stats["useful"],
    )
    return stats


async def list_recent_disclosures(
    *,
    useful_only: bool = False,
    limit: int = 50,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    db = get_mongo_db()
    q: Dict[str, Any] = {}
    if useful_only:
        q["useful"] = True
    if category:
        q["category"] = category
    cur = db[COLLECTION].find(q, {"_id": 0}).sort("first_seen_at", -1).limit(max(1, min(limit, 200)))
    return [x async for x in cur]
