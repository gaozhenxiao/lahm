"""因子末日持仓 → 机会/警醒书（供 Leads 机会列表）。

持仓口径与 Factors「持仓分布」一致：buy ≤ asOf ≤ sell（买入即显示；卖出日仍计入）；
未平仓不伪造卖出日。日度 n_pos 仍为引擎隔夜会计，与此展示口径在买入日可能不一致。
同一 (code, factor_id) 只展示一条当前持仓：多笔重叠开仓腿合并（最早 buy_date、权重相加），
不按买入流水重复列出。
好坏口径对齐 mine_overnight：Sharpe≥0.15 优质；<0.05（含负）弱势警醒；中间为中性观察。
"""
from __future__ import annotations

import csv
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.factors.factor_registry import FACTOR_IMPL
from app.services.factors_service import (
    FACTOR_ARTIFACTS,
    RETIRED_FACTOR_IDS,
    _build_backtest_summary,
    _factors_data_dir,
)
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi")

# 与 scripts/mine_overnight.py 冒烟门槛对齐；可通过 API query 覆盖
DEFAULT_GOOD_SHARPE = 0.15
DEFAULT_WEAK_SHARPE = 0.05

_CACHE_LOCK = threading.Lock()
_MEM_CACHE: Dict[str, Any] = {"key": None, "payload": None, "built_at": 0.0}


@dataclass(frozen=True)
class QualityThresholds:
    good_sharpe: float = DEFAULT_GOOD_SHARPE
    weak_sharpe: float = DEFAULT_WEAK_SHARPE


def _norm_code(code: str) -> str:
    c = (code or "").strip()
    if not c:
        return ""
    # baostock: sh.600519 / sz.000001
    if "." in c and c[:3].lower() in ("sh.", "sz.", "bj."):
        num, mkt = c.split(".", 1)[1], c.split(".", 1)[0].upper()
        # keep ts-like 600519.SH for leads consistency when digit
        if num.isdigit() and len(num) == 6:
            return f"{num}.{mkt}"
        return c.upper()
    cu = c.upper()
    if "." in cu:
        return cu
    if cu.isdigit() and len(cu) == 6:
        return cu + (".SH" if cu.startswith(("5", "6", "9")) else ".SZ")
    return cu


def _classify_sharpe(sharpe: Optional[float], th: QualityThresholds) -> str:
    if sharpe is None:
        return "unknown"
    if sharpe >= th.good_sharpe:
        return "good"
    if sharpe < th.weak_sharpe:
        return "warn"
    return "neutral"


def _primary_sharpe(summary: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str]]:
    if not summary or not summary.get("available"):
        return None, None
    logics = summary.get("logics") or {}
    if not isinstance(logics, dict) or not logics:
        return None, None
    primary = summary.get("primary_logic")
    row = logics.get(primary) if primary else None
    if not isinstance(row, dict):
        # 多逻辑取 Sharpe 最高者
        best_key, best_row, best_s = None, None, None
        for k, v in logics.items():
            if not isinstance(v, dict):
                continue
            s = v.get("sharpe")
            if isinstance(s, (int, float)) and (best_s is None or s > best_s):
                best_key, best_row, best_s = k, v, float(s)
        row = best_row
        primary = best_key
    if not isinstance(row, dict):
        return None, None
    s = row.get("sharpe")
    return (float(s) if isinstance(s, (int, float)) else None), (str(primary) if primary else None)


def _trade_history_path(factor_id: str) -> Optional[Path]:
    data_dir = _factors_data_dir()
    registry = FACTOR_ARTIFACTS.get(factor_id) or {}
    # 优先标准 trades；national_team 用 long_hold
    for aid in ("trades", "trades_long_hold"):
        meta = registry.get(aid)
        if meta and meta.get("filename"):
            p = data_dir / str(meta["filename"])
            if p.exists():
                return p
    p = data_dir / f"{factor_id}_trade_history.csv"
    return p if p.exists() else None


def _open_holdings_from_csv(path: Path, as_of_hint: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    """解析 trade_history，返回 (asOf, holdings)。"""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:  # noqa: BLE001
        logger.warning("read trade history failed: %s", path)
        return "", []

    stacks: Dict[str, List[Dict[str, Any]]] = {}
    legs: List[Dict[str, Any]] = []
    last_trade = ""

    def _take(code: str, sell_note: str) -> Optional[Dict[str, Any]]:
        lst = stacks.get(code) or []
        if not lst:
            return None
        # 与前端 takeStackEntry 近似：有买入日备注则优先匹配，否则 LIFO
        if sell_note:
            for i, ent in enumerate(lst):
                if ent.get("date") and ent["date"] in sell_note:
                    return lst.pop(i)
        return lst.pop()

    for r in rows:
        action = str(r.get("action") or "")
        code = str(r.get("code") or "").strip()
        if not code:
            continue
        dt = str(r.get("date") or "")[:10]
        if dt:
            last_trade = dt
        name = str(r.get("name") or r.get("code_name") or "").strip()
        try:
            price = float(r.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            w_raw = float(r.get("buy_position") or 0)
        except (TypeError, ValueError):
            w_raw = 0.0
        w = w_raw if w_raw > 0 else 0.125
        note = str(r.get("note") or "")

        if ("开" in action) or ("加" in action):
            stacks.setdefault(code, []).append(
                {"date": dt, "price": price, "w": w, "name": name, "note": note}
            )
        elif ("清" in action) or ("卖" in action) or ("平" in action):
            ent = _take(code, note)
            if not ent:
                continue
            legs.append(
                {
                    "code": code,
                    "name": name or ent.get("name") or "",
                    "buy_date": ent["date"],
                    "sell_date": dt,
                    "weight": float(ent["w"]),
                    "buy_price": float(ent.get("price") or 0),
                    "note": note or ent.get("note") or "",
                }
            )

    as_of = (as_of_hint or last_trade or "")[:10]
    for code, lst in stacks.items():
        for ent in lst:
            legs.append(
                {
                    "code": code,
                    "name": ent.get("name") or "",
                    "buy_date": ent["date"],
                    "sell_date": "",
                    "weight": float(ent["w"]),
                    "buy_price": float(ent.get("price") or 0),
                    "note": ent.get("note") or "",
                }
            )

    if not as_of:
        return "", []

    # 买入即显示：buy ≤ asOf；未平或 sell ≥ asOf（卖出日仍计入）
    held = [
        x
        for x in legs
        if x["buy_date"]
        and x["buy_date"] <= as_of
        and (not x["sell_date"] or x["sell_date"] >= as_of)
    ]
    # 机会书要「是否持仓」而非开仓流水：同标的多腿合并为一条
    held = _merge_open_holdings_by_code(held)
    held.sort(key=lambda x: (-x["weight"], x["code"]))
    return as_of, held


def _merge_open_holdings_by_code(held: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 code 的重叠持仓腿 → 一条：最早 buy_date、最晚 latest_buy_date、权重相加、n_legs 记腿数。"""
    by_code: Dict[str, Dict[str, Any]] = {}
    for h in held:
        raw = str(h.get("code") or "").strip()
        if not raw:
            continue
        key = _norm_code(raw) or raw
        bd = str(h.get("buy_date") or "")
        cur = by_code.get(key)
        if not cur:
            by_code[key] = {
                "code": raw,
                "name": str(h.get("name") or ""),
                "buy_date": bd,
                "latest_buy_date": bd,
                "sell_date": str(h.get("sell_date") or ""),
                "weight": float(h.get("weight") or 0),
                "buy_price": float(h.get("buy_price") or 0),
                "note": str(h.get("note") or ""),
                "n_legs": 1,
            }
            continue
        cur["n_legs"] = int(cur.get("n_legs") or 1) + 1
        cur["weight"] = float(cur.get("weight") or 0) + float(h.get("weight") or 0)
        if h.get("name") and not cur.get("name"):
            cur["name"] = str(h["name"])
        if bd and (not cur.get("buy_date") or bd < cur["buy_date"]):
            cur["buy_date"] = bd
            # 买入价跟最早开仓腿
            try:
                cur["buy_price"] = float(h.get("buy_price") or 0)
            except (TypeError, ValueError):
                pass
            if h.get("note"):
                cur["note"] = str(h["note"])
        if bd and (not cur.get("latest_buy_date") or bd > cur["latest_buy_date"]):
            cur["latest_buy_date"] = bd
        # 仍有未平仓腿则整体视为未平；否则取最晚卖出日
        sd = str(h.get("sell_date") or "")
        if not sd or not cur.get("sell_date"):
            cur["sell_date"] = ""
        elif sd > cur["sell_date"]:
            cur["sell_date"] = sd
    return list(by_code.values())


def _is_new_open(buy_date: str, as_of: str, *, within_days: int = 5) -> bool:
    """相对回测末日 as_of，买入日在 within_days 个自然日内（含当日）视为新开。"""
    bd = (buy_date or "")[:10]
    ao = (as_of or "")[:10]
    if len(bd) < 10 or len(ao) < 10:
        return False
    try:
        from datetime import date

        d0 = date.fromisoformat(bd)
        d1 = date.fromisoformat(ao)
    except ValueError:
        return False
    delta = (d1 - d0).days
    return 0 <= delta <= int(within_days)


def _holdings_fingerprint() -> str:
    data_dir = _factors_data_dir()
    latest = 0.0
    n = 0
    try:
        for p in data_dir.glob("*_trade_history.csv"):
            n += 1
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return f"n{n}:m{int(latest)}"


_HOLDINGS_LIST_CACHE: Dict[str, Any] = {"key": None, "payload": None}


def _open_holdings_brief_one(factor_id: str, *, new_open_days: int = 5) -> Dict[str, Any]:
    """单因子末日持仓摘要（列表页用）。"""
    path = _trade_history_path(factor_id)
    if not path:
        return {"as_of": "", "holdings": []}
    summary = _build_backtest_summary(factor_id)
    as_of_hint = ""
    if summary and isinstance(summary.get("logics"), dict):
        primary = summary.get("primary_logic")
        logics = summary.get("logics") or {}
        row = logics.get(primary) if primary else None
        if not isinstance(row, dict):
            for v in logics.values():
                if isinstance(v, dict) and v.get("end"):
                    row = v
                    break
        if isinstance(row, dict) and row.get("end"):
            as_of_hint = str(row.get("end"))[:10]
    as_of, holdings = _open_holdings_from_csv(path, as_of_hint=as_of_hint)
    brief: List[Dict[str, Any]] = []
    for h in holdings:
        latest_buy = str(h.get("latest_buy_date") or h.get("buy_date") or "")[:10]
        brief.append(
            {
                "code": str(h.get("code") or ""),
                "name": str(h.get("name") or ""),
                "buy_date": str(h.get("buy_date") or "")[:10],
                "latest_buy_date": latest_buy,
                "weight": float(h.get("weight") or 0),
                "is_new": _is_new_open(latest_buy, as_of, within_days=new_open_days),
            }
        )
    brief.sort(key=lambda x: (-float(x.get("weight") or 0), str(x.get("code") or "")))
    return {"as_of": as_of, "holdings": brief}


def build_open_holdings_by_factor(
    factor_ids: List[str],
    *,
    new_open_days: int = 5,
    refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """factor_id → {as_of, holdings[]}；带目录级缓存，供因子列表挂载。"""
    key = f"{_holdings_fingerprint()}:d{int(new_open_days)}"
    with _CACHE_LOCK:
        if (
            not refresh
            and _HOLDINGS_LIST_CACHE.get("key") == key
            and isinstance(_HOLDINGS_LIST_CACHE.get("payload"), dict)
        ):
            cached: Dict[str, Dict[str, Any]] = _HOLDINGS_LIST_CACHE["payload"]
            return {fid: cached.get(fid) or {"as_of": "", "holdings": []} for fid in factor_ids}

    ids = [str(x) for x in factor_ids if x]
    out: Dict[str, Dict[str, Any]] = {}
    if ids:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(_open_holdings_brief_one, fid, new_open_days=new_open_days): fid for fid in ids}
            for fut in as_completed(futs):
                fid = futs[fut]
                try:
                    out[fid] = fut.result()
                except Exception:  # noqa: BLE001
                    logger.exception("open holdings brief failed: %s", fid)
                    out[fid] = {"as_of": "", "holdings": []}

    with _CACHE_LOCK:
        # 合并进全量缓存，便于下次按子集命中
        prev = _HOLDINGS_LIST_CACHE.get("payload") if _HOLDINGS_LIST_CACHE.get("key") == key else None
        merged = dict(prev) if isinstance(prev, dict) else {}
        merged.update(out)
        _HOLDINGS_LIST_CACHE["key"] = key
        _HOLDINGS_LIST_CACHE["payload"] = merged
    return {fid: out.get(fid) or {"as_of": "", "holdings": []} for fid in ids}


def _upsert_factor_ref(bucket: List[Dict[str, Any]], ref: Dict[str, Any]) -> None:
    """同一 factor_id 在 factors_* 桶内只保留一条（合并权重 / 最早买入）。"""
    fid = ref.get("factor_id")
    for i, existing in enumerate(bucket):
        if existing.get("factor_id") != fid:
            continue
        w0 = existing.get("weight")
        w1 = ref.get("weight")
        try:
            existing["weight"] = float(w0 or 0) + float(w1 or 0)
        except (TypeError, ValueError):
            existing["weight"] = w1 if w1 is not None else w0
        n0 = int(existing.get("n_legs") or 1)
        n1 = int(ref.get("n_legs") or 1)
        existing["n_legs"] = n0 + n1
        bd0 = str(existing.get("buy_date") or "")
        bd1 = str(ref.get("buy_date") or "")
        if bd1 and (not bd0 or bd1 < bd0):
            existing["buy_date"] = bd1
            existing["buy_price"] = ref.get("buy_price")
            if ref.get("note"):
                existing["note"] = ref["note"]
        bucket[i] = existing
        return
    bucket.append(ref)


def _load_champion_id() -> Optional[str]:
    path = _factors_data_dir() / "overnight_champion.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        champ = raw.get("champion") or {}
        return str(champ.get("id") or "") or None
    except Exception:  # noqa: BLE001
        return None


def _factor_catalog() -> List[Tuple[str, str]]:
    """(factor_id, display_name)；跳过 RETIRED。"""
    retired = set(RETIRED_FACTOR_IDS)
    out: List[Tuple[str, str]] = []
    # 特殊内置（非 FACTOR_IMPL）
    for fid, name in (
        ("national_team", "国家队因子"),
        ("dip_buy", "暴跌抄底因子"),
        ("earnings_forecast", "业绩预告双路径因子"),
        ("dividend_etf_swing", "红利ETF波段"),
    ):
        if fid not in retired:
            out.append((fid, name))
    for fid, meta in FACTOR_IMPL.items():
        if fid in retired:
            continue
        out.append((fid, str(meta.get("name") or fid)))
    # 去重保序
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for fid, name in out:
        if fid in seen:
            continue
        seen.add(fid)
        uniq.append((fid, name))
    return uniq


def _disk_cache_path() -> Path:
    return _factors_data_dir() / "_leads_factor_book_cache.json"


def _process_one(
    factor_id: str,
    name: str,
    th: QualityThresholds,
    champion_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    path = _trade_history_path(factor_id)
    if not path:
        return None
    summary = _build_backtest_summary(factor_id)
    sharpe, logic = _primary_sharpe(summary)
    quality = _classify_sharpe(sharpe, th)
    as_of_hint = ""
    if summary and isinstance(summary.get("logics"), dict):
        for row in (summary.get("logics") or {}).values():
            if isinstance(row, dict) and row.get("end"):
                as_of_hint = str(row.get("end"))[:10]
                break
    as_of, holdings = _open_holdings_from_csv(path, as_of_hint=as_of_hint)
    if not holdings:
        return None
    return {
        "factor_id": factor_id,
        "factor_name": name,
        "sharpe": sharpe,
        "quality": quality,
        "logic": logic,
        "as_of": as_of,
        "is_champion": bool(champion_id and factor_id == champion_id),
        "holdings": holdings,
    }


def _build_book(th: QualityThresholds) -> Dict[str, Any]:
    champion_id = _load_champion_id()
    catalog = _factor_catalog()
    factor_rows: List[Dict[str, Any]] = []

    # 并行扫 CSV（CPU/IO 混合）；限制线程避免磁盘抖动
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {
            pool.submit(_process_one, fid, name, th, champion_id): fid
            for fid, name in catalog
        }
        for fut in as_completed(futs):
            try:
                row = fut.result()
            except Exception:  # noqa: BLE001
                logger.exception("factor book row failed: %s", futs[fut])
                continue
            if row:
                factor_rows.append(row)

    # 按标的聚合
    by_code: Dict[str, Dict[str, Any]] = {}
    for fr in factor_rows:
        q = fr["quality"]
        for h in fr["holdings"]:
            raw_code = str(h.get("code") or "")
            code = _norm_code(raw_code) or raw_code
            if not code:
                continue
            slot = by_code.get(code)
            if not slot:
                slot = {
                    "code": code,
                    "name": str(h.get("name") or ""),
                    "market": "CN",
                    "factors_good": [],
                    "factors_warn": [],
                    "factors_neutral": [],
                    "weights": [],
                    "as_of": fr["as_of"],
                    "source": "factor",
                    "status": "watching",
                }
                by_code[code] = slot
            if h.get("name") and not slot["name"]:
                slot["name"] = str(h["name"])
            if fr["as_of"] and (not slot["as_of"] or fr["as_of"] > slot["as_of"]):
                slot["as_of"] = fr["as_of"]

            ref = {
                "factor_id": fr["factor_id"],
                "name": fr["factor_name"],
                "sharpe": fr["sharpe"],
                "quality": q,
                "weight": h.get("weight"),
                "buy_date": h.get("buy_date"),
                "buy_price": h.get("buy_price"),
                "as_of": fr["as_of"],
                "is_champion": fr["is_champion"],
                "note": h.get("note") or "",
                "n_legs": int(h.get("n_legs") or 1),
            }
            if q == "good":
                _upsert_factor_ref(slot["factors_good"], ref)
            elif q == "warn":
                _upsert_factor_ref(slot["factors_warn"], ref)
            else:
                # neutral + unknown → 中性观察（弱于优质，强于明确弱势）
                _upsert_factor_ref(slot["factors_neutral"], ref)
            # weights 与 factors_* 同口径：同 factor_id 只一条
            w_slot = next((w for w in slot["weights"] if w.get("factor_id") == fr["factor_id"]), None)
            if w_slot is None:
                slot["weights"].append(
                    {
                        "factor_id": fr["factor_id"],
                        "weight": h.get("weight"),
                        "quality": q,
                        "n_legs": int(h.get("n_legs") or 1),
                    }
                )
            else:
                try:
                    w_slot["weight"] = float(w_slot.get("weight") or 0) + float(h.get("weight") or 0)
                except (TypeError, ValueError):
                    w_slot["weight"] = h.get("weight")
                w_slot["n_legs"] = int(w_slot.get("n_legs") or 1) + int(h.get("n_legs") or 1)

    items: List[Dict[str, Any]] = []
    now = now_tz()
    for code, slot in by_code.items():
        good = slot["factors_good"]
        warn = slot["factors_warn"]
        neutral = slot["factors_neutral"]
        # 各桶内按 sharpe 降序
        for bucket in (good, warn, neutral):
            bucket.sort(key=lambda x: (-(x.get("sharpe") if isinstance(x.get("sharpe"), (int, float)) else -999), x["factor_id"]))

        if good and (warn or neutral):
            kind = "mixed"
        elif good:
            kind = "opportunity"
        elif warn:
            kind = "alert"
        else:
            kind = "watch"

        max_good = max((x.get("sharpe") for x in good if isinstance(x.get("sharpe"), (int, float))), default=None)
        # 评分：有优质因子时用最佳 Sharpe 映射到 0-100；纯警醒给低分
        score: Optional[float]
        if isinstance(max_good, (int, float)):
            score = round(min(100.0, max(0.0, float(max_good) / 2.0 * 100.0)), 1)
        elif warn:
            score = 15.0
        else:
            score = 35.0

        good_names = "、".join(x["name"] for x in good[:4])
        warn_names = "、".join(x["name"] for x in warn[:4])
        if kind == "opportunity":
            reason = f"优质因子末日持仓：{good_names}"
        elif kind == "mixed":
            reason = f"优质持仓（{good_names}）；同时弱势因子也持有：{warn_names or '见中性/警醒徽章'}"
        elif kind == "alert":
            reason = f"警醒：弱势因子仍持有 — {warn_names}"
        else:
            neu = "、".join(x["name"] for x in neutral[:4])
            reason = f"观察：中性因子持有 — {neu}"

        tags = ["factor_book", kind]
        if any(x.get("is_champion") for x in good + warn + neutral):
            tags.append("champion")

        items.append(
            {
                "id": f"fb:{code}",
                "code": code,
                "name": slot["name"],
                "market": "CN",
                "source": "factor",
                "status": "watching",
                "kind": kind,
                "score": score,
                "reason": reason,
                "tags": tags,
                "factors_good": good,
                "factors_warn": warn,
                "factors_neutral": neutral,
                "weights": slot["weights"],
                "as_of": slot["as_of"],
                "factor_id": good[0]["factor_id"] if good else (warn[0]["factor_id"] if warn else (neutral[0]["factor_id"] if neutral else None)),
                "created_at": now,
                "updated_at": now,
            }
        )

    # 机会优先，再按最佳优质 Sharpe / 警醒数量
    def sort_key(it: Dict[str, Any]) -> Tuple:
        kind_rank = {"opportunity": 0, "mixed": 1, "watch": 2, "alert": 3}.get(it["kind"], 9)
        best = None
        for x in it["factors_good"]:
            s = x.get("sharpe")
            if isinstance(s, (int, float)) and (best is None or s > best):
                best = s
        return (kind_rank, -(best or -999), -len(it["factors_good"]), it["code"])

    items.sort(key=sort_key)

    stats = {
        "factors_scanned": len(catalog),
        "factors_with_holdings": len(factor_rows),
        "names_opportunity": sum(1 for x in items if x["kind"] == "opportunity"),
        "names_mixed": sum(1 for x in items if x["kind"] == "mixed"),
        "names_alert": sum(1 for x in items if x["kind"] == "alert"),
        "names_watch": sum(1 for x in items if x["kind"] == "watch"),
        "total_names": len(items),
    }
    return {
        "as_of": max((x["as_of"] for x in items if x.get("as_of")), default=""),
        "updated_at": now.isoformat() if hasattr(now, "isoformat") else str(now),
        "thresholds": {
            "good_sharpe": th.good_sharpe,
            "weak_sharpe": th.weak_sharpe,
            "note": "优质=Sharpe≥good；警醒=Sharpe<weak；中间=中性观察。已下线 RETIRED 不参与。",
        },
        "champion_id": champion_id,
        "stats": stats,
        "items": items,
    }


def _cache_key(th: QualityThresholds) -> str:
    data_dir = _factors_data_dir()
    paths = [data_dir / "overnight_champion.json"]
    # 用目录级粗指纹：统计 trade_history 数量与最新 mtime，避免扫 600 次 stat 细节仍可接受
    latest = 0.0
    n = 0
    try:
        for p in data_dir.glob("*_trade_history.csv"):
            n += 1
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return f"g{th.good_sharpe}:w{th.weak_sharpe}:n{n}:m{int(latest)}"


class FactorBookService:
    def build(
        self,
        *,
        refresh: bool = False,
        good_sharpe: float = DEFAULT_GOOD_SHARPE,
        weak_sharpe: float = DEFAULT_WEAK_SHARPE,
        filter_mode: str = "all",
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        th = QualityThresholds(good_sharpe=float(good_sharpe), weak_sharpe=float(weak_sharpe))
        key = _cache_key(th)

        with _CACHE_LOCK:
            if not refresh and _MEM_CACHE.get("key") == key and _MEM_CACHE.get("payload"):
                payload = _MEM_CACHE["payload"]
            else:
                disk = _disk_cache_path()
                payload = None
                if not refresh and disk.exists():
                    try:
                        cached = json.loads(disk.read_text(encoding="utf-8"))
                        if cached.get("cache_key") == key:
                            payload = cached.get("payload")
                    except Exception:  # noqa: BLE001
                        payload = None
                if payload is None:
                    t0 = time.time()
                    payload = _build_book(th)
                    payload["build_ms"] = int((time.time() - t0) * 1000)
                    _MEM_CACHE["key"] = key
                    _MEM_CACHE["payload"] = payload
                    _MEM_CACHE["built_at"] = time.time()
                    try:
                        disk.write_text(
                            json.dumps({"cache_key": key, "payload": payload}, ensure_ascii=False, default=str),
                            encoding="utf-8",
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning("write factor book disk cache failed", exc_info=True)
                else:
                    _MEM_CACHE["key"] = key
                    _MEM_CACHE["payload"] = payload

        items = list(payload.get("items") or [])
        mode = (filter_mode or "all").strip().lower()
        if mode in ("good", "good_only", "opportunity"):
            items = [x for x in items if x.get("kind") in ("opportunity", "mixed")]
        elif mode in ("alert", "alerts", "warn"):
            items = [x for x in items if x.get("kind") in ("alert", "mixed") or x.get("factors_warn")]
        elif mode in ("alert_only", "warn_only"):
            items = [x for x in items if x.get("kind") == "alert"]
        elif mode in ("watch",):
            items = [x for x in items if x.get("kind") == "watch"]

        if keyword:
            kw = keyword.strip().lower()
            if kw:
                items = [
                    x
                    for x in items
                    if kw in str(x.get("code", "")).lower()
                    or kw in str(x.get("name", "")).lower()
                    or any(kw in str(f.get("name", "")).lower() or kw in str(f.get("factor_id", "")).lower() for f in (x.get("factors_good") or []) + (x.get("factors_warn") or []) + (x.get("factors_neutral") or []))
                ]

        return {
            **{k: v for k, v in payload.items() if k != "items"},
            "filter_mode": mode,
            "total": len(items),
            "items": items,
        }


factor_book_service = FactorBookService()
