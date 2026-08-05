# -*- coding: utf-8 -*-
"""QMT / xtquant 探测与连接状态（执行通道占位）。"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.strategies.common import DATA_DIR, now_iso

logger = logging.getLogger("webapi.strategies.qmt")

CONFIG_FP = DATA_DIR / "qmt.json"

# 常见 MiniQMT / 投研端路径片段
_CANDIDATE_ROOTS = [
    Path(os.environ.get("QMT_PATH", "")),
    Path(r"D:\Programs\QMT"),
    Path(r"D:\QMT"),
    Path(r"C:\QMT"),
    Path(r"D:\国金证券QMT交易端"),
    Path(r"D:\华泰证券QMT"),
    Path(r"D:\迅投极速交易终端"),
]


def _load_config() -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FP.exists():
        try:
            return json.loads(CONFIG_FP.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    cfg = {
        "userdata_path": "",
        "session_id": "lahm",
        "account_id": "",
        "account_type": "STOCK",
        "enabled": False,
        "note": "安装并启动 MiniQMT 后填写 userdata_path，或设置环境变量 QMT_PATH / QMT_USERDATA",
    }
    CONFIG_FP.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _load_config()
    for k, v in patch.items():
        if k in ("userdata_path", "session_id", "account_id", "account_type", "enabled", "note"):
            cfg[k] = v
    CONFIG_FP.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def _find_xtquant_paths() -> List[str]:
    found: List[str] = []
    env = os.environ.get("QMT_PATH") or os.environ.get("XTQUANT_PATH")
    if env and Path(env).exists():
        found.append(env)
    for root in _CANDIDATE_ROOTS:
        if not root or not root.exists():
            continue
        for p in root.rglob("xtquant"):
            if p.is_dir() and (p / "__init__.py").exists():
                found.append(str(p.parent))
                break
        for exe in ("XtMiniQmt.exe", "MiniQMT.exe", "xtminiqmt.exe"):
            hits = list(root.rglob(exe))
            for h in hits[:3]:
                # userdata 常在同级 userdata_mini
                found.append(str(h.parent))
    # dedupe
    out: List[str] = []
    for x in found:
        if x and x not in out:
            out.append(x)
    return out[:10]


def _try_import_xtquant() -> Dict[str, Any]:
    # 先按配置/发现路径塞进 sys.path
    cfg = _load_config()
    extras = []
    ud = cfg.get("userdata_path") or os.environ.get("QMT_USERDATA") or ""
    if ud:
        # userdata 旁常见 bin.x64 / bin
        p = Path(ud)
        for cand in (p, p.parent, p.parent / "bin.x64", p.parent / "bin"):
            if cand.exists():
                extras.append(str(cand))
    extras.extend(_find_xtquant_paths())
    for e in extras:
        if e not in sys.path:
            sys.path.insert(0, e)

    try:
        import xtquant  # type: ignore

        return {
            "importable": True,
            "module_path": getattr(xtquant, "__file__", None),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"importable": False, "module_path": None, "error": str(exc)}


def get_status() -> Dict[str, Any]:
    cfg = _load_config()
    imp = _try_import_xtquant()
    connected = False
    connect_error = None
    if imp["importable"] and cfg.get("enabled") and (cfg.get("userdata_path") or os.environ.get("QMT_USERDATA")):
        try:
            from xtquant.xttrader import XtQuantTrader  # type: ignore

            ud = cfg.get("userdata_path") or os.environ.get("QMT_USERDATA")
            session = int(hash(cfg.get("session_id") or "lahm") % 100000)
            trader = XtQuantTrader(ud, session)
            trader.start()
            # connect 可能阻塞；短超时依赖本地已登录的 miniqmt
            r = trader.connect()
            connected = r == 0
            if not connected:
                connect_error = f"connect returned {r}"
            try:
                trader.stop()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            connect_error = str(exc)

    return {
        "asof": now_iso(),
        "config_path": str(CONFIG_FP).replace("\\", "/"),
        "config": {
            "userdata_path": cfg.get("userdata_path"),
            "account_id": cfg.get("account_id"),
            "account_type": cfg.get("account_type"),
            "enabled": bool(cfg.get("enabled")),
            "note": cfg.get("note"),
        },
        "xtquant": imp,
        "discovered_paths": _find_xtquant_paths(),
        "connected": connected,
        "connect_error": connect_error,
        "ready_for_orders": bool(connected and cfg.get("account_id")),
        "checklist": [
            "安装并启动 MiniQMT，登录交易账号",
            f"在 {CONFIG_FP.name} 填写 userdata_path（MiniQMT userdata 目录）",
            "设置 enabled=true 与 account_id",
            "将 xtquant 所在目录加入环境或安装到当前 venv",
            "策略扫描可先跑；自动下单接口将按策略逐步接通",
        ],
    }
