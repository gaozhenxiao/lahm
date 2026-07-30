"""Factors registry + national-team factor computation."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import get_mongo_db
from app.models.factors import FactorCreate, FactorUpdate
from app.utils.timezone import now_tz
from app.services.factors.national_team import compute_national_team_signal
from app.services.factors.dip_buy import compute_dip_buy_signal

logger = logging.getLogger("webapi")
FACTORS = "factors"
FACTOR_SIGNALS = "factor_signals"

# factor_id -> artifact_id -> metadata (filename under data/factors/)
FACTOR_ARTIFACTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "dip_buy": {
        "equity_curve": {
            "label": "净值图 · dip_buy",
            "filename": "dip_buy_equity_curve.png",
            "kind": "image",
        },
        "summary": {
            "label": "回测摘要 JSON",
            "filename": "dip_buy_backtest.json",
            "kind": "json",
        },
        "trades": {
            "label": "操作历史",
            "filename": "dip_buy_trade_history.csv",
            "kind": "csv",
        },
        "daily": {
            "label": "日度回测",
            "filename": "dip_buy_backtest.csv",
            "kind": "csv",
        },
    },
    "national_team": {
        "equity_curve": {
            "label": "净值图 · long_hold",
            "filename": "national_team_equity_curve.png",
            "kind": "image",
            "logic": "long_hold",
        },
        "equity_curve_continuous": {
            "label": "净值图 · continuous",
            "filename": "national_team_equity_curve_continuous.png",
            "kind": "image",
            "logic": "continuous",
        },
        "share_curve": {
            "label": "汇金 ETF 份额曲线",
            "filename": "huijin_etf_share_curve.png",
            "kind": "image",
        },
        "summary": {
            "label": "回测摘要 JSON",
            "filename": "national_team_backtest.json",
            "kind": "json",
        },
        "trades_long_hold": {
            "label": "操作历史 · long_hold",
            "filename": "national_team_trade_history_long_hold.csv",
            "kind": "csv",
            "logic": "long_hold",
        },
        "trades_continuous": {
            "label": "操作历史 · continuous",
            "filename": "national_team_trade_history_continuous.csv",
            "kind": "csv",
            "logic": "continuous",
        },
        "daily_long_hold": {
            "label": "日度回测 · long_hold",
            "filename": "national_team_backtest.csv",
            "kind": "csv",
            "logic": "long_hold",
        },
        "daily_continuous": {
            "label": "日度回测 · continuous",
            "filename": "national_team_backtest_continuous.csv",
            "kind": "csv",
            "logic": "continuous",
        },
    },
}


def _factors_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "factors"


def _guides_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "features" / "guides"


def load_factor_guide(factor_id: str) -> Optional[Dict[str, Any]]:
    """Load user-facing markdown guide for a factor."""
    path = _guides_dir() / f"{factor_id}.md"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("failed to read factor guide %s", path)
        return None
    title = factor_id
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return {
        "factor_id": factor_id,
        "title": title,
        "format": "markdown",
        "content": text,
        "path": str(path.relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/"),
    }


def _metric_slice(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "roundtrips",
        "start",
        "end",
        "bars",
        "buy_hold_return",
        "avg_position",
        "position_logic",
        "mode",
    )
    return {k: row.get(k) for k in keys if k in row}


def _load_national_team_backtest() -> Optional[Dict[str, Any]]:
    path = _factors_data_dir() / "national_team_backtest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("failed to read national_team_backtest.json")
        return None


def _build_backtest_summary(factor_id: str) -> Optional[Dict[str, Any]]:
    """Attach lightweight backtest summary + artifact links for list/detail."""
    registry = FACTOR_ARTIFACTS.get(factor_id)
    if not registry:
        return None

    artifacts: List[Dict[str, Any]] = []
    data_dir = _factors_data_dir()
    for artifact_id, meta in registry.items():
        path = data_dir / str(meta["filename"])
        artifacts.append(
            {
                "id": artifact_id,
                "label": meta.get("label") or artifact_id,
                "kind": meta.get("kind"),
                "logic": meta.get("logic"),
                "available": path.exists(),
                "url": f"/api/factors/{factor_id}/artifacts/{artifact_id}",
            }
        )

    out: Dict[str, Any] = {
        "available": False,
        "primary_logic": "long_hold",
        "logics": {},
        "artifacts": artifacts,
        "updated_at": None,
    }

    if factor_id == "national_team":
        raw = _load_national_team_backtest()
        if raw:
            results = raw.get("results") or {}
            logics: Dict[str, Any] = {}
            for key, row in results.items():
                if not isinstance(row, dict):
                    continue
                logic = str(row.get("position_logic") or key.split(":")[0])
                logics[logic] = _metric_slice(row)
            summary_path = data_dir / "national_team_backtest.json"
            out.update(
                {
                    "available": bool(logics),
                    "logics": logics,
                    "updated_at": (
                        datetime.fromtimestamp(summary_path.stat().st_mtime).isoformat(timespec="seconds")
                        if summary_path.exists()
                        else None
                    ),
                }
            )
    elif factor_id == "dip_buy":
        summary_path = data_dir / "dip_buy_backtest.json"
        if summary_path.exists():
            try:
                raw = json.loads(summary_path.read_text(encoding="utf-8"))
                results = raw.get("results") or {}
                logics: Dict[str, Any] = {}
                for key, row in results.items():
                    if isinstance(row, dict):
                        logics[str(row.get("position_logic") or key)] = _metric_slice(row)
                out.update(
                    {
                        "available": bool(logics),
                        "primary_logic": "dip_buy",
                        "logics": logics,
                        "updated_at": datetime.fromtimestamp(summary_path.stat().st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to read dip_buy_backtest.json")
    return out


BUILTIN_FACTORS: List[Dict[str, Any]] = [
    {
        "factor_id": "national_team",
        "name": "国家队因子",
        "category": "sentiment",
        "description": (
            "信号只用汇金高占比沪深300ETF份额判断增减仓；"
            "具体买入跟随当时动作（早期宽基→银行+300→银行+半导体）。"
        ),
        "tags": ["国家队", "汇金", "510300", "银行", "半导体"],
        "builtin": True,
    },
    {
        "factor_id": "dip_buy",
        "name": "暴跌抄底因子",
        "category": "macro",
        "description": (
            "监测沪深300/创业板/中证500急跌与回撤；"
            "结合 PE/PB 历史分位：高估不抄、低估提高仓位；"
            "回测按信号宇宙交易对应 ETF（含159915），空仓计约1.4%年化利息。"
        ),
        "tags": ["抄底", "择时", "估值", "回撤", "创业板"],
        "builtin": True,
        "params": {
            "universes": ["csi300", "cyb", "csi500"],
            "cheap_pct": 30,
            "expensive_pct": 75,
            "buy_threshold": 0.18,
            "aggression": 1.35,
            "trade_mode": "best_etf",
            "cash_annual": 0.014,
        },
    },
]

# 已下线因子：ensure_builtins 时从库中移除
RETIRED_FACTOR_IDS = ("nt_dip", "ma20_cross")


def _serialize_factor(doc: Dict[str, Any], *, include_backtest: bool = True) -> Dict[str, Any]:
    factor_id = doc.get("factor_id")
    out = {
        "factor_id": factor_id,
        "name": doc.get("name"),
        "category": doc.get("category"),
        "description": doc.get("description", ""),
        "status": doc.get("status", "active"),
        "params": doc.get("params") or {},
        "tags": doc.get("tags") or [],
        "builtin": bool(doc.get("builtin", False)),
        "latest_signal": doc.get("latest_signal"),
        "latest_value": doc.get("latest_value"),
        "latest_asof": doc.get("latest_asof"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
    if include_backtest and factor_id:
        out["backtest"] = _build_backtest_summary(str(factor_id))
    if factor_id:
        out["has_guide"] = (_guides_dir() / f"{factor_id}.md").exists()
    return out


class FactorsService:
    async def ensure_builtins(self) -> None:
        db = get_mongo_db()
        now = now_tz()
        if RETIRED_FACTOR_IDS:
            await db[FACTORS].delete_many({"factor_id": {"$in": list(RETIRED_FACTOR_IDS)}})
            await db[FACTOR_SIGNALS].delete_many({"factor_id": {"$in": list(RETIRED_FACTOR_IDS)}})
        for f in BUILTIN_FACTORS:
            await db[FACTORS].update_one(
                {"factor_id": f["factor_id"]},
                {
                    "$setOnInsert": {
                        **f,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )

    async def list_factors(self) -> List[Dict[str, Any]]:
        await self.ensure_builtins()
        db = get_mongo_db()
        cursor = db[FACTORS].find({}).sort("factor_id", 1)
        return [_serialize_factor(d) async for d in cursor]

    async def get_factor(self, factor_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_builtins()
        db = get_mongo_db()
        doc = await db[FACTORS].find_one({"factor_id": factor_id})
        return _serialize_factor(doc) if doc else None

    async def create_factor(self, payload: FactorCreate) -> Dict[str, Any]:
        db = get_mongo_db()
        now = now_tz()
        exists = await db[FACTORS].find_one({"factor_id": payload.factor_id})
        if exists:
            raise ValueError("factor_id already exists")
        doc = {
            **payload.model_dump(),
            "category": payload.category.value,
            "status": payload.status.value,
            "builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        await db[FACTORS].insert_one(doc)
        return _serialize_factor(doc)

    async def update_factor(self, factor_id: str, payload: FactorUpdate) -> Dict[str, Any]:
        db = get_mongo_db()
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        for key in ("category", "status"):
            if key in updates and hasattr(updates[key], "value"):
                updates[key] = updates[key].value
        updates["updated_at"] = now_tz()
        doc = await db[FACTORS].find_one_and_update(
            {"factor_id": factor_id},
            {"$set": updates},
            return_document=True,
        )
        if not doc:
            raise LookupError("factor not found")
        return _serialize_factor(doc)

    async def compute_signal(self, factor_id: str, asof: Optional[str] = None) -> Dict[str, Any]:
        await self.ensure_builtins()
        factor = await self.get_factor(factor_id)
        if not factor:
            raise LookupError("factor not found")

        if factor_id == "national_team":
            # 份额/新闻拉取为同步 IO，放到线程池避免卡住事件循环
            result = await asyncio.to_thread(
                compute_national_team_signal,
                factor.get("params") or {},
                asof,
            )
        elif factor_id == "dip_buy":
            result = await asyncio.to_thread(
                compute_dip_buy_signal,
                factor.get("params") or {},
                asof,
            )
        else:
            result = {
                "factor_id": factor_id,
                "asof": now_tz(),
                "signal": "neutral",
                "value": 0.0,
                "components": {},
                "note": "该因子尚未实现独立计算器，仅作目录占位",
            }

        db = get_mongo_db()
        await db[FACTOR_SIGNALS].insert_one({**result, "created_at": now_tz()})
        await db[FACTORS].update_one(
            {"factor_id": factor_id},
            {
                "$set": {
                    "latest_signal": result.get("signal"),
                    "latest_value": result.get("value"),
                    "latest_asof": result.get("asof"),
                    "updated_at": now_tz(),
                }
            },
        )
        # jsonify datetime
        out = dict(result)
        if isinstance(out.get("asof"), datetime):
            pass
        return out

    async def list_signals(self, factor_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        db = get_mongo_db()
        cursor = db[FACTOR_SIGNALS].find({"factor_id": factor_id}).sort("asof", -1).limit(limit)
        items = []
        async for d in cursor:
            d.pop("_id", None)
            items.append(d)
        return items

    async def get_backtest(self, factor_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_builtins()
        factor = await self.get_factor(factor_id)
        if not factor:
            return None
        summary = _build_backtest_summary(factor_id)
        if summary is None:
            return {
                "factor_id": factor_id,
                "available": False,
                "logics": {},
                "artifacts": [],
                "note": "该因子暂无回测产物",
            }
        return {"factor_id": factor_id, **summary}

    async def get_guide(self, factor_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_builtins()
        factor = await self.get_factor(factor_id)
        if not factor:
            return None
        guide = load_factor_guide(factor_id)
        if not guide:
            return {
                "factor_id": factor_id,
                "title": factor.get("name") or factor_id,
                "format": "markdown",
                "content": (
                    f"# {factor.get('name') or factor_id}\n\n"
                    f"{factor.get('description') or '暂无更详细说明。'}\n"
                ),
                "fallback": True,
            }
        return guide

    def resolve_artifact(self, factor_id: str, artifact_id: str) -> Tuple[Path, Dict[str, Any]]:
        registry = FACTOR_ARTIFACTS.get(factor_id)
        if not registry or artifact_id not in registry:
            raise LookupError("artifact not found")
        meta = registry[artifact_id]
        path = (_factors_data_dir() / str(meta["filename"])).resolve()
        root = _factors_data_dir().resolve()
        if root not in path.parents and path != root:
            raise LookupError("artifact path invalid")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(meta["filename"])
        return path, meta


factors_service = FactorsService()
