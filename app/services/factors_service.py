"""Factors registry + national-team factor computation."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import get_mongo_db
from app.models.factors import FactorCreate, FactorUpdate
from app.utils.timezone import now_tz
from app.services.factors.national_team import compute_national_team_signal
from app.services.factors.dip_buy import compute_dip_buy_signal
from app.services.factors.earnings_forecast import compute_earnings_forecast_signal
from app.services.factors.factor_registry import FACTOR_IMPL, compute_factor_signal

logger = logging.getLogger("webapi")
FACTORS = "factors"
FACTOR_SIGNALS = "factor_signals"


def _standard_artifacts(factor_id: str, label: str) -> Dict[str, Dict[str, Any]]:
    return {
        "equity_curve": {
            "label": f"净值图 · {label}",
            "filename": f"{factor_id}_equity_curve.png",
            "kind": "image",
        },
        "summary": {
            "label": "回测摘要 JSON",
            "filename": f"{factor_id}_backtest.json",
            "kind": "json",
        },
        "trades": {
            "label": "操作历史",
            "filename": f"{factor_id}_trade_history.csv",
            "kind": "csv",
        },
        "daily": {
            "label": "日度回测",
            "filename": f"{factor_id}_backtest.csv",
            "kind": "csv",
        },
    }


# factor_id -> artifact_id -> metadata (filename under data/factors/)
FACTOR_ARTIFACTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "dip_buy": _standard_artifacts("dip_buy", "dip_buy"),
    "earnings_forecast": _standard_artifacts("earnings_forecast", "earnings_forecast"),
    "national_team": {
        "equity_curve": {
            "label": "净值图",
            "filename": "national_team_equity_curve.png",
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
        "trades": {
            "label": "操作历史",
            "filename": "national_team_trade_history.csv",
            "kind": "csv",
            "logic": "continuous",
        },
        "daily": {
            "label": "日度回测",
            "filename": "national_team_backtest.csv",
            "kind": "csv",
            "logic": "continuous",
        },
    },
}

# 注册表因子自动挂上标准产物
for _fid, _meta in FACTOR_IMPL.items():
    FACTOR_ARTIFACTS[_fid] = _standard_artifacts(_fid, _meta["name"])


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
        "primary_logic": "continuous",
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
                if logic == "long_hold":
                    continue
                logics[logic] = _metric_slice(row)
            summary_path = data_dir / "national_team_backtest.json"
            out.update(
                {
                    "available": bool(logics),
                    "primary_logic": "continuous",
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
    elif factor_id == "earnings_forecast":
        summary_path = data_dir / "earnings_forecast_backtest.json"
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
                        "primary_logic": "dual_path_3factor_chase",
                        "logics": logics,
                        "updated_at": datetime.fromtimestamp(summary_path.stat().st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to read earnings_forecast_backtest.json")
    else:
        # 标准单逻辑因子：{id}_backtest.json
        summary_path = data_dir / f"{factor_id}_backtest.json"
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
                        "primary_logic": factor_id,
                        "logics": logics,
                        "updated_at": datetime.fromtimestamp(summary_path.stat().st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to read %s_backtest.json", factor_id)
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
    {
        "factor_id": "earnings_forecast",
        "name": "业绩预告双路径因子",
        "category": "fundamental",
        "description": (
            "正向前瞻业绩预告后分情况追高："
            "综合超预期幅度（爆发 vs 一般强增）、中长期股价位置、短期涨幅；"
            "够格则公告收盘直买，否则等回调；持有约20日，计佣金+印花税。"
        ),
        "tags": ["业绩预告", "超预期", "追高三维", "公告后回调", "baostock"],
        "builtin": True,
        "params": {
            "universe": "hs300",
            "explosive_chg_pct_dwn": 100,
            "strong_chg_pct_dwn": 30,
            "pre_run_lookback": 20,
            "pre_run_max": 0.05,
            "pre_run_max_explosive": 0.10,
            "lt_lookback": 504,
            "lt_quiet_max": 0.40,
            "lt_hot_min": 1.0,
            "pullback_pct": 0.08,
            "stop_loss": 0.15,
            "min_days_after_announce": 3,
            "max_days_wait": 45,
            "hold_days": 20,
            "max_positions": 8,
            "commission_rate": 0.0001,
            "stamp_tax_sell": 0.001,
        },
    },
]

# 注册表因子并入内置目录
for _fid, _meta in FACTOR_IMPL.items():
    BUILTIN_FACTORS.append(
        {
            "factor_id": _fid,
            "name": _meta["name"],
            "category": _meta.get("category") or "fundamental",
            "description": _meta.get("description") or "",
            "tags": _meta.get("tags") or [],
            "builtin": True,
            "params": _meta.get("params") or {},
        }
    )

# 按定义顺序写入生成时间，供列表「按生成时间」排序（先生成的在前）
_FACTOR_GEN_BASE = datetime(2026, 6, 1, 12, 0, 0)
for _i, _f in enumerate(BUILTIN_FACTORS):
    _f["created_at"] = _FACTOR_GEN_BASE + timedelta(hours=_i)

# 已下线因子：ensure_builtins 时从库中移除（含冒烟负收益因子）
RETIRED_FACTOR_IDS = (
    "nt_dip",
    "ma20_cross",
    "pe_low_ma_reclaim",
    "cheap_roe_bounce",
    "eps_growth_reclaim",
    "ma_trend_quality",
    "high_margin_pullback",
    "low_vol_reclaim",
    "momentum_ma_pullback",
    "ma120_pullback",
    "turnover_dryup_bounce",
    "gap_down_recover",
    "consecutive_down_bounce",
)


def _json_time(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


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
        "latest_asof": _json_time(doc.get("latest_asof")),
        "created_at": _json_time(doc.get("created_at")),
        "updated_at": _json_time(doc.get("updated_at")),
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
            # 内置因子元数据每次同步；created_at 用注册表生成时间，保证列表排序稳定
            payload = {
                **f,
                "status": "active",
                "builtin": True,
                "updated_at": now,
            }
            if f.get("created_at") is not None:
                payload["created_at"] = f["created_at"]
            else:
                payload.setdefault("created_at", now)
            await db[FACTORS].update_one(
                {"factor_id": f["factor_id"]},
                {"$set": payload},
                upsert=True,
            )

    async def list_factors(self) -> List[Dict[str, Any]]:
        await self.ensure_builtins()
        db = get_mongo_db()
        # 按生成时间升序：先做的在前；无时间戳的排最后
        cursor = db[FACTORS].find({}).sort([("created_at", 1), ("factor_id", 1)])
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
        elif factor_id == "earnings_forecast":
            result = await asyncio.to_thread(
                compute_earnings_forecast_signal,
                factor.get("params") or {},
                asof,
            )
        elif factor_id in FACTOR_IMPL:
            result = await asyncio.to_thread(
                compute_factor_signal,
                factor_id,
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

    async def get_portfolio(self, factor_id: str) -> Optional[Dict[str, Any]]:
        """当前/回测末日持仓 + 近期回合腿 + 最近交易。"""
        await self.ensure_builtins()
        factor = await self.get_factor(factor_id)
        if not factor:
            return None
        backtest = _build_backtest_summary(factor_id) or {"available": False, "logics": {}, "artifacts": []}
        data_dir = _factors_data_dir()
        holdings: List[Dict[str, Any]] = []
        recent_legs: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        asof: Optional[str] = None
        exposure: Optional[float] = None
        note = ""

        legs_path = data_dir / factor_id / "trade_legs.parquet"
        if legs_path.exists():
            try:
                import pandas as pd

                legs = pd.read_parquet(legs_path)
                if not legs.empty and {"entry_date", "exit_date", "code"}.issubset(legs.columns):
                    legs = legs.copy()
                    legs["entry_date"] = pd.to_datetime(legs["entry_date"], errors="coerce")
                    legs["exit_date"] = pd.to_datetime(legs["exit_date"], errors="coerce")
                    asof_ts = legs["exit_date"].max()
                    # 优先用回测摘要 end
                    primary = (backtest.get("primary_logic") or "")
                    logic_row = (backtest.get("logics") or {}).get(primary) or {}
                    if not logic_row and backtest.get("logics"):
                        logic_row = next(iter(backtest["logics"].values()), {}) or {}
                    if logic_row.get("end"):
                        asof_ts = pd.Timestamp(logic_row["end"])
                    asof = str(asof_ts.date()) if pd.notna(asof_ts) else None
                    if asof:
                        open_m = (legs["entry_date"] <= asof_ts) & (legs["exit_date"] > asof_ts)
                        for _, r in legs.loc[open_m].iterrows():
                            holdings.append(
                                {
                                    "code": r["code"],
                                    "entry_date": str(pd.Timestamp(r["entry_date"]).date()),
                                    "entry_price": round(float(r["entry_price"]), 4)
                                    if pd.notna(r.get("entry_price"))
                                    else None,
                                    "exit_date": str(pd.Timestamp(r["exit_date"]).date())
                                    if pd.notna(r.get("exit_date"))
                                    else None,
                                    "note": r.get("note") or "",
                                    "status": "open",
                                }
                            )
                    closed = legs.sort_values("exit_date", ascending=False).head(40)
                    for _, r in closed.iterrows():
                        ep = float(r["entry_price"]) if pd.notna(r.get("entry_price")) else None
                        xp = float(r["exit_price"]) if pd.notna(r.get("exit_price")) else None
                        ret = None
                        if ep and xp and ep != 0:
                            ret = round(xp / ep - 1.0, 4)
                        recent_legs.append(
                            {
                                "code": r["code"],
                                "entry_date": str(pd.Timestamp(r["entry_date"]).date())
                                if pd.notna(r.get("entry_date"))
                                else None,
                                "exit_date": str(pd.Timestamp(r["exit_date"]).date())
                                if pd.notna(r.get("exit_date"))
                                else None,
                                "entry_price": round(ep, 4) if ep is not None else None,
                                "exit_price": round(xp, 4) if xp is not None else None,
                                "return": ret,
                                "reason": r.get("reason") or "",
                                "note": r.get("note") or "",
                                "status": "closed",
                            }
                        )
            except Exception:  # noqa: BLE001
                logger.exception("read trade_legs failed %s", factor_id)

        # 连续仓位类：从日度回测取末日仓位
        daily_name = None
        registry = FACTOR_ARTIFACTS.get(factor_id) or {}
        for meta in registry.values():
            if meta.get("kind") == "csv" and str(meta.get("filename", "")).endswith("_backtest.csv"):
                if "continuous" in str(meta.get("filename")) and factor_id == "national_team":
                    continue
                daily_name = meta["filename"]
                if meta.get("logic") in (None, backtest.get("primary_logic"), "continuous"):
                    break
        if factor_id == "national_team":
            daily_name = "national_team_backtest.csv"
        daily_path = data_dir / str(daily_name) if daily_name else None
        if daily_path and daily_path.exists():
            try:
                import pandas as pd

                daily = pd.read_csv(daily_path)
                if not daily.empty and "position" in daily.columns:
                    last = daily.iloc[-1]
                    asof = asof or str(last.get("date") or "")[:10]
                    exposure = float(last["position"]) if pd.notna(last["position"]) else None
                    if exposure and exposure > 0.02 and not holdings:
                        holdings.append(
                            {
                                "code": last.get("era") or last.get("best_universe") or factor_id,
                                "entry_date": asof,
                                "entry_price": float(last["close"])
                                if "close" in daily.columns and pd.notna(last.get("close"))
                                else None,
                                "exit_date": None,
                                "note": f"末日仓位 {exposure:.2%} · state={last.get('episode_state') or last.get('state') or ''}",
                                "status": "open",
                                "weight": round(exposure, 4),
                            }
                        )
                    note = f"回测末日敞口 {exposure:.2%}" if exposure is not None else note
            except Exception:  # noqa: BLE001
                logger.exception("read daily backtest failed %s", factor_id)

        trades_name = None
        for aid, meta in registry.items():
            if "trade" in aid or (meta.get("label") or "").find("操作") >= 0:
                trades_name = meta["filename"]
                break
        if not trades_name:
            cand = data_dir / f"{factor_id}_trade_history.csv"
            if cand.exists():
                trades_name = cand.name
        if trades_name:
            tpath = data_dir / str(trades_name)
            if tpath.exists():
                try:
                    import pandas as pd

                    tdf = pd.read_csv(tpath)
                    if not tdf.empty:
                        tdf = tdf.sort_values("date", ascending=False).head(80)
                        trades = json.loads(tdf.to_json(orient="records", force_ascii=False))
                except Exception:  # noqa: BLE001
                    logger.exception("read trades failed %s", factor_id)

        return {
            "factor_id": factor_id,
            "name": factor.get("name"),
            "asof": asof,
            "exposure": exposure,
            "note": note,
            "backtest": backtest,
            "holdings": holdings,
            "recent_legs": recent_legs,
            "trades": trades,
            "latest_signal": factor.get("latest_signal"),
            "latest_value": factor.get("latest_value"),
            "latest_asof": factor.get("latest_asof"),
            "description": factor.get("description"),
            "tags": factor.get("tags") or [],
        }

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
