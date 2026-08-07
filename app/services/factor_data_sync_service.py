"""Factor data sync jobs: K-line + financials + signal recompute."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("webapi.factor_data_sync")

ROOT = Path(__file__).resolve().parents[2]

# DB system_settings 键 ↔ pydantic Settings 属性
_FACTOR_SETTING_MAP = {
    "factor_kline_auto_sync_enabled": ("FACTOR_KLINE_AUTO_SYNC_ENABLED", bool),
    "factor_kline_auto_sync_cron": ("FACTOR_KLINE_AUTO_SYNC_CRON", str),
    "factor_kline_sync_universe": ("FACTOR_KLINE_SYNC_UNIVERSE", str),
    "factor_kline_sync_timeout_sec": ("FACTOR_KLINE_SYNC_TIMEOUT_SEC", int),
    "factor_kline_data_source": ("FACTOR_KLINE_DATA_SOURCE", str),
    "factor_financial_auto_sync_enabled": ("FACTOR_FINANCIAL_AUTO_SYNC_ENABLED", bool),
    "factor_financial_auto_sync_cron": ("FACTOR_FINANCIAL_AUTO_SYNC_CRON", str),
    "factor_financial_sync_universe": ("FACTOR_FINANCIAL_SYNC_UNIVERSE", str),
    "factor_financial_sync_timeout_sec": ("FACTOR_FINANCIAL_SYNC_TIMEOUT_SEC", int),
    "factor_financial_data_source": ("FACTOR_FINANCIAL_DATA_SOURCE", str),
    "factor_financial_recent_years": ("FACTOR_FINANCIAL_RECENT_YEARS", int),
    "factor_signals_auto_refresh_enabled": ("FACTOR_SIGNALS_AUTO_REFRESH_ENABLED", bool),
    "factor_signals_auto_refresh_cron": ("FACTOR_SIGNALS_AUTO_REFRESH_CRON", str),
    "factor_signals_after_backtest": ("FACTOR_SIGNALS_AFTER_BACKTEST", bool),
    "factor_backtest_auto_enabled": ("FACTOR_BACKTEST_AUTO_ENABLED", bool),
    "factor_backtest_auto_cron": ("FACTOR_BACKTEST_AUTO_CRON", str),
    "factor_backtest_auto_sync_kline": ("FACTOR_BACKTEST_AUTO_SYNC_KLINE", bool),
    "factor_backtest_timeout_sec": ("FACTOR_BACKTEST_TIMEOUT_SEC", int),
    "factor_backtest_workers": ("FACTOR_BACKTEST_WORKERS", int),
}

FACTOR_SYNC_DEFAULTS: Dict[str, Any] = {
    "factor_kline_auto_sync_enabled": True,
    "factor_kline_auto_sync_cron": "0 12 * * 1-5",
    "factor_kline_sync_universe": "hs300_csi500_csi1000",
    "factor_kline_sync_timeout_sec": 7200,
    "factor_kline_data_source": "tencent",
    "factor_financial_auto_sync_enabled": True,
    "factor_financial_auto_sync_cron": "0 8,21 * * *",
    "factor_financial_sync_universe": "hs300_csi500_csi1000",
    "factor_financial_sync_timeout_sec": 10800,
    "factor_financial_data_source": "fin_db_then_baostock",
    "factor_financial_recent_years": 2,
    "factor_signals_auto_refresh_enabled": False,
    "factor_signals_auto_refresh_cron": "0 12,19 * * *",
    "factor_signals_after_backtest": True,
    "factor_backtest_auto_enabled": True,
    "factor_backtest_auto_cron": "0 8,16 * * *",
    "factor_backtest_auto_sync_kline": True,
    "factor_backtest_timeout_sec": 14400,
    "factor_backtest_workers": 1,
}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n"):
        return False
    return default


def _cast(value: Any, typ: type, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        if typ is bool:
            return _as_bool(value, bool(default))
        if typ is int:
            return int(value)
        return str(value)
    except Exception:  # noqa: BLE001
        return default


async def resolve_factor_sync_config() -> Dict[str, Any]:
    """合并 DB 系统设置与 pydantic/.env 默认值（DB 优先，除非 ENV 覆盖同名键）。"""
    from app.core.config import settings

    eff: Dict[str, Any] = {}
    try:
        from app.services.config_provider import config_provider

        eff = await config_provider.get_effective_system_settings()
    except Exception as exc:  # noqa: BLE001
        logger.debug("factor-sync config: effective settings unavailable: %s", exc)

    out: Dict[str, Any] = {}
    for db_key, (attr, typ) in _FACTOR_SETTING_MAP.items():
        default = getattr(settings, attr, FACTOR_SYNC_DEFAULTS.get(db_key))
        raw = eff.get(db_key, default)
        out[db_key] = _cast(raw, typ, default)

    out["timezone"] = str(
        eff.get("app_timezone")
        or getattr(settings, "TIMEZONE", None)
        or "Asia/Shanghai"
    )
    return out


def factor_sync_settings_for_ui(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """供 /api/factors/update/settings 展示。"""
    after_bt = bool(cfg.get("factor_signals_after_backtest", True))
    return {
        "kline": {
            "enabled": bool(cfg["factor_kline_auto_sync_enabled"]),
            "cron": cfg["factor_kline_auto_sync_cron"],
            "universe": cfg["factor_kline_sync_universe"],
            "data_source": cfg["factor_kline_data_source"],
            "timeout_sec": int(cfg["factor_kline_sync_timeout_sec"]),
            "times_hint": "默认工作日 12:00（8/16 随回测流水线拉取）",
        },
        "financial": {
            "enabled": bool(cfg["factor_financial_auto_sync_enabled"]),
            "cron": cfg["factor_financial_auto_sync_cron"],
            "universe": cfg["factor_financial_sync_universe"],
            "data_source": cfg["factor_financial_data_source"],
            "recent_years": int(cfg["factor_financial_recent_years"]),
            "timeout_sec": int(cfg["factor_financial_sync_timeout_sec"]),
            "times_hint": "默认每天 08:00 / 21:00（可在系统设置中修改）",
        },
        "backtest": {
            "enabled": bool(cfg["factor_backtest_auto_enabled"]),
            "cron": cfg["factor_backtest_auto_cron"],
            "sync_kline_first": bool(cfg["factor_backtest_auto_sync_kline"]),
            "timeout_sec": int(cfg["factor_backtest_timeout_sec"]),
            "workers": int(cfg["factor_backtest_workers"]),
            "times_hint": "默认每天 08:00 / 16:00；流水线：K线→增量回测→机会信号",
        },
        "signals": {
            "enabled": bool(cfg["factor_signals_auto_refresh_enabled"]) and not after_bt,
            "cron": cfg["factor_signals_auto_refresh_cron"],
            "after_backtest": after_bt,
            "standalone_enabled": bool(cfg["factor_signals_auto_refresh_enabled"]),
        },
        "timezone": cfg.get("timezone") or "Asia/Shanghai",
    }


def _run_script(args: List[str], *, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    cmd = [sys.executable, *args]
    logger.info("factor-sync run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "error": f"timeout after {timeout_sec}s",
            "stdout_tail": ((exc.stdout or "") if isinstance(exc.stdout, str) else "")[-800:],
        }
    return {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-1200:],
        "stderr_tail": (proc.stderr or "")[-600:],
    }


async def sync_factor_klines(
    *,
    universe: Optional[str] = None,
    datalen: int = 15,
    reason: str = "manual",
) -> Dict[str, Any]:
    """前复权日线增量（数据源可配置，当前支持 tencent）。"""
    cfg = await resolve_factor_sync_config()
    uni = universe or cfg["factor_kline_sync_universe"]
    source = str(cfg["factor_kline_data_source"] or "tencent").strip().lower()
    timeout_sec = int(cfg["factor_kline_sync_timeout_sec"] or 7200)

    if source not in ("tencent", "tencent_qfq", "tencent_fqkline"):
        return {
            "ok": False,
            "step": "kline",
            "reason": reason,
            "error": f"unsupported kline data_source: {source}",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }

    result = await asyncio.to_thread(
        _run_script,
        [
            "scripts/download_daily_qfq_tencent.py",
            "--universe",
            str(uni),
            "--incremental",
            "--datalen",
            str(int(datalen)),
            "--interval",
            "0.1",
        ],
        timeout_sec=timeout_sec,
    )
    result["step"] = "kline"
    result["reason"] = reason
    result["data_source"] = source
    result["universe"] = uni
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if result.get("ok"):
        logger.info("factor-sync kline ok (%s / %s)", reason, source)
    else:
        logger.warning(
            "factor-sync kline failed (%s): %s",
            reason,
            result.get("error") or result.get("stderr_tail"),
        )
    return result


async def sync_factor_financials(
    *,
    universe: Optional[str] = None,
    recent_years: Optional[int] = None,
    reason: str = "manual",
) -> Dict[str, Any]:
    """利润/成长财报增量（数据源可配置）。"""
    cfg = await resolve_factor_sync_config()
    uni = universe or cfg["factor_financial_sync_universe"]
    years = int(recent_years if recent_years is not None else cfg["factor_financial_recent_years"] or 2)
    source = str(cfg["factor_financial_data_source"] or "fin_db_then_baostock").strip().lower()
    timeout_sec = int(cfg["factor_financial_sync_timeout_sec"] or 10800)

    args = [
        "scripts/download_factor_financials_incremental.py",
        "--universe",
        str(uni),
        "--recent-years",
        str(years),
        "--interval",
        "0.2",
    ]
    if source in ("fin_db", "local_fin_db", "ashare_fin_db"):
        args.append("--skip-baostock")
    elif source in ("baostock", "bs"):
        args.append("--skip-fin-db")
    elif source not in ("fin_db_then_baostock", "auto", "default"):
        return {
            "ok": False,
            "step": "financial",
            "reason": reason,
            "error": f"unsupported financial data_source: {source}",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }

    result = await asyncio.to_thread(_run_script, args, timeout_sec=timeout_sec)
    result["step"] = "financial"
    result["reason"] = reason
    result["data_source"] = source
    result["universe"] = uni
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if result.get("ok"):
        logger.info("factor-sync financial ok (%s / %s)", reason, source)
    else:
        logger.warning(
            "factor-sync financial failed (%s): %s",
            reason,
            result.get("error") or result.get("stderr_tail"),
        )
    return result


async def recompute_factor_signals(*, reason: str = "manual") -> Dict[str, Any]:
    """重算今日因子信号。"""
    asof = datetime.now().strftime("%Y-%m-%d")
    result = await asyncio.to_thread(
        _run_script,
        ["scripts/recompute_factor_signals_today.py", "--asof", asof],
        timeout_sec=3600,
    )
    result["step"] = "signals"
    result["reason"] = reason
    result["asof"] = asof
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return result


async def run_factor_backtests(*, reason: str = "manual") -> Dict[str, Any]:
    """增量回测并写回 Mongo / artifacts（近窗信号 + 历史腿合并）。"""
    cfg = await resolve_factor_sync_config()
    timeout_sec = int(cfg.get("factor_backtest_timeout_sec") or 14400)
    workers = max(1, int(cfg.get("factor_backtest_workers") or 1))
    lookback_days = int(cfg.get("factor_backtest_lookback_days") or 180)
    warmup_days = int(cfg.get("factor_backtest_warmup_days") or 800)
    result = await asyncio.to_thread(
        _run_script,
        [
            "scripts/incremental_backtest_factors.py",
            "--workers",
            str(workers),
            "--lookback-days",
            str(lookback_days),
            "--warmup-days",
            str(warmup_days),
            "--plot",
        ],
        timeout_sec=timeout_sec,
    )
    result["step"] = "backtest"
    result["mode"] = "incremental"
    result["reason"] = reason
    result["workers"] = workers
    result["lookback_days"] = lookback_days
    result["warmup_days"] = warmup_days
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if result.get("ok"):
        logger.info("factor-sync incremental backtest ok (%s)", reason)
    else:
        logger.warning(
            "factor-sync incremental backtest failed (%s): %s",
            reason,
            result.get("error") or result.get("stderr_tail") or result.get("returncode"),
        )
    return result


async def run_factor_backtest_pipeline(*, reason: str = "cron") -> Dict[str, Any]:
    """定时回测流水线：可选 K 线增量 → 增量回测 →（可选）机会信号。"""
    cfg = await resolve_factor_sync_config()
    out: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "steps": {},
    }
    if bool(cfg.get("factor_backtest_auto_sync_kline", True)):
        kline = await sync_factor_klines(reason=f"{reason}:pre_backtest")
        out["steps"]["kline"] = kline
        if not kline.get("ok"):
            logger.warning(
                "factor-sync backtest pipeline: kline failed, continue with existing data (%s)",
                reason,
            )

    backtest = await run_factor_backtests(reason=reason)
    out["steps"]["backtest"] = backtest

    if bool(cfg.get("factor_signals_after_backtest", True)):
        if backtest.get("ok"):
            out["steps"]["signals"] = await recompute_factor_signals(
                reason=f"{reason}:post_backtest"
            )
        else:
            out["steps"]["signals"] = {
                "ok": False,
                "step": "signals",
                "skipped": True,
                "reason": "backtest_failed",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }
            logger.warning("factor-sync skip signals after failed backtest (%s)", reason)

    out["finished_at"] = datetime.now().isoformat(timespec="seconds")
    out["ok"] = bool(backtest.get("ok"))
    return out


async def run_factor_data_update(
    *,
    include_kline: bool = True,
    include_financial: bool = True,
    include_signals: bool = True,
    reason: str = "manual",
) -> Dict[str, Any]:
    """手动/定时统一更新：K线 → 财报 → 信号。"""
    out: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "steps": {},
    }
    if include_kline:
        out["steps"]["kline"] = await sync_factor_klines(reason=reason)
    if include_financial:
        out["steps"]["financial"] = await sync_factor_financials(reason=reason)
    if include_signals:
        out["steps"]["signals"] = await recompute_factor_signals(reason=reason)
    out["finished_at"] = datetime.now().isoformat(timespec="seconds")
    out["ok"] = all(bool(v.get("ok")) for v in out["steps"].values()) if out["steps"] else True
    return out


async def apply_factor_sync_scheduler() -> Dict[str, Any]:
    """按当前配置重排 K线/财报/回测/信号定时任务（保存系统设置后调用）。"""
    from apscheduler.triggers.cron import CronTrigger

    from app.services import scheduler_service as sch_mod

    cfg = await resolve_factor_sync_config()
    scheduler = getattr(sch_mod, "_scheduler_instance", None)
    if scheduler is None:
        return {"ok": False, "error": "scheduler not ready"}

    tz = cfg["timezone"]
    applied: Dict[str, Any] = {"ok": True, "timezone": tz, "jobs": {}}
    after_bt = bool(cfg.get("factor_signals_after_backtest", True))
    signals_standalone = bool(cfg["factor_signals_auto_refresh_enabled"]) and not after_bt

    jobs = [
        (
            "factor_kline_auto_sync",
            cfg["factor_kline_auto_sync_cron"],
            bool(cfg["factor_kline_auto_sync_enabled"]),
        ),
        (
            "factor_financial_auto_sync",
            cfg["factor_financial_auto_sync_cron"],
            bool(cfg["factor_financial_auto_sync_enabled"]),
        ),
        (
            "factor_backtest_auto",
            cfg["factor_backtest_auto_cron"],
            bool(cfg["factor_backtest_auto_enabled"]),
        ),
        (
            "factor_signals_auto_refresh",
            cfg["factor_signals_auto_refresh_cron"],
            signals_standalone,
        ),
    ]
    for job_id, cron, enabled in jobs:
        try:
            scheduler.reschedule_job(
                job_id,
                trigger=CronTrigger.from_crontab(str(cron), timezone=tz),
            )
            if enabled:
                scheduler.resume_job(job_id)
            else:
                scheduler.pause_job(job_id)
            applied["jobs"][job_id] = {"cron": cron, "enabled": enabled}
            logger.info(
                "factor-sync scheduler updated: %s cron=%s enabled=%s",
                job_id,
                cron,
                enabled,
            )
        except Exception as exc:  # noqa: BLE001
            applied["ok"] = False
            applied["jobs"][job_id] = {"error": str(exc), "cron": cron, "enabled": enabled}
            logger.warning("factor-sync scheduler update failed for %s: %s", job_id, exc)
    applied["signals_after_backtest"] = after_bt
    return applied
