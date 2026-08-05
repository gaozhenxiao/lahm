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
from app.services.factors.dividend_etf_swing import (
    DEFAULT_PARAMS as DIVIDEND_ETF_DEFAULT_PARAMS,
    compute_dividend_etf_swing_signal,
)
from app.services.factors.dividend_etf_slope_grid import (
    DEFAULT_PARAMS as DIVIDEND_SLOPE_GRID_DEFAULT_PARAMS,
    compute_dividend_etf_slope_grid_signal,
)
from app.services.factors.factor_registry import FACTOR_IMPL, compute_factor_signal
from app.services.factors.guide_builder import (
    pick_trade_example,
    selection_steps,
    variant_overview,
)
from app.services.factors.match_stock import match_stock_against_factors

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
    "dividend_etf_swing": _standard_artifacts("dividend_etf_swing", "红利ETF波段"),
    "dividend_etf_slope_grid": {
        **_standard_artifacts("dividend_etf_slope_grid", "红利ETF倾斜网格"),
        "signals": {
            "label": "价位买卖点",
            "filename": "dividend_etf_slope_grid_signals.png",
            "kind": "image",
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


_PARAM_LABELS = {
    "universe": "股票池",
    "price_start": "行情起始",
    "max_positions": "最大持仓数",
    "commission_rate": "佣金率（双边）",
    "stamp_tax_sell": "印花税（卖出）",
    "hold_days": "持有天数",
    "stop_loss": "止损",
    "take_profit": "固定止盈",
    "trail_stop": "移动止盈回撤",
    "val_window": "估值分位窗口（交易日）",
    "pe_pct_max": "PE分位上限",
    "pb_pct_max": "PB分位上限",
    "pb_max": "PB绝对值上限",
    "roe_min": "ROE下限",
    "margin_min": "利润率/毛利率下限",
    "np_min": "净利率下限",
    "np_improve": "净利率改善阈值",
    "growth_min": "同比增速下限",
    "mom_min": "动量下限",
    "dd_need": "回撤触发幅度",
    "roe_improve": "ROE改善阈值",
    "margin_improve": "利润率改善阈值",
    "gp_improve": "毛利率改善阈值",
    "peg_max": "PEG近似上限",
    "accel_min": "增速加速阈值",
    "growth_accel": "成长加速阈值",
    "score_min": "Neff分值下限",
    "vol_q": "波动分位上限",
    "bench_code": "基准代码",
    "funda_lag": "财务热窗（交易日）",
    "break_days": "突破回看天数",
    "ma_days": "确认均线天数",
    "base_window": "横盘窗口",
    "amp_max": "横盘振幅上限",
    "entry": "技术图形入场类型",
    "yoy_min": "合同负债同比下限",
    "qoq_min": "环比扩张下限",
    "cl_rev_min": "合同负债/营收强度下限",
    "intensity_improve": "预收强度提升阈值",
    "asset_yoy_max": "资产同比上限（轻资产）",
    "lead_min": "归属净利领先幅度",
    "ret20_max": "20日涨幅上限",
    "amt_dry_ratio": "缩量比例",
    "explosive_chg": "爆发增速下限（%）",
    "prior_yoy_max": "上年同季增速上限（断层，%）",
    "qoq_gap_min": "单季环比跨越下限（%）",
    "require_ma20": "要求站上MA20",
}


def _fmt_param_value(key: str, val: Any) -> str:
    if val is None:
        return "-"
    pct_keys = {
        "commission_rate",
        "stamp_tax_sell",
        "stop_loss",
        "take_profit",
        "trail_stop",
        "dd_need",
        "mom_min",
        "roe_min",
        "margin_min",
        "np_min",
        "np_improve",
        "growth_min",
        "roe_improve",
        "margin_improve",
        "gp_improve",
        "accel_min",
        "growth_accel",
        "yoy_min",
        "qoq_min",
        "cl_rev_min",
        "intensity_improve",
        "asset_yoy_max",
        "lead_min",
        "amp_max",
        "ret20_max",
        "amt_dry_ratio",
    }
    if key in pct_keys and isinstance(val, (int, float)):
        return f"{float(val):.2%}"
    if (key.endswith("_pct_max") or key.endswith("_pct_min") or key == "vol_q") and isinstance(
        val, (int, float)
    ):
        return f"{float(val):.0%}"
    if isinstance(val, float):
        return f"{val:.4g}"
    return str(val)


def _fmt_pct_md(v: Any) -> str:
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_num_md(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_factor_guide_markdown(factor: Dict[str, Any], *, file_guide: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """拼装面向用户的详细说明：思路、参数、回测、产物；文件说明过短时用自动稿增强。"""
    factor_id = str(factor.get("factor_id") or "")
    name = str(factor.get("name") or factor_id)
    desc = (factor.get("description") or "").strip()
    tags = factor.get("tags") or []
    category = factor.get("category") or ""
    params = factor.get("params") or {}
    meta = FACTOR_IMPL.get(factor_id) or {}

    overview = variant_overview(meta) if meta else ""
    lines: List[str] = [f"# {name}", ""]
    lines += ["## 思路概览", ""]
    if overview:
        lines += [overview, ""]
        if desc and desc.rstrip("。") not in overview:
            lines += [f"备注（挖掘记录）：{desc}", ""]
    elif desc:
        lines += [desc, ""]
    else:
        lines += ["暂无文字描述，请结合下方参数与回测理解该因子。", ""]

    meta_bits = []
    if category:
        meta_bits.append(f"**分类**：{category}")
    if tags:
        meta_bits.append("**标签**：" + " · ".join(f"`{t}`" for t in tags))
    meta_bits.append(f"**因子 ID**：`{factor_id}`")
    lines += ["## 基本信息", "", "  \n".join(meta_bits), ""]

    # 入场与确认（来自注册表 title/flags）
    lines += ["## 信号与交易规则", ""]
    title = meta.get("title") or name
    lines.append(f"- **策略标题**：{title}")
    if meta.get("need_profit"):
        lines.append("- **财务依赖**：需要利润表字段（如 ROE / 净利率 / 毛利率 / 营收）")
    if meta.get("need_growth"):
        lines.append("- **成长依赖**：需要成长表字段（如 YOYNI / YOYEPS / YOYPNI）")
    if meta.get("need_balance"):
        lines.append("- **资产负债表**：需要合同负债 / 预收款（本地财务库优先，否则东财合并口径）")
    if meta.get("need_fin_db"):
        lines.append("- **本地财务库**：合并利润表/资产负债表/现金流量表及业绩预告、快报字段")
    if not meta.get("need_profit") and not meta.get("need_growth") and factor_id in FACTOR_IMPL:
        lines.append("- **财务依赖**：主要使用价量 / 估值分位，不强制合并利润或成长表")
    lines.append("- **仓位模型**：等权持仓；到期或触发止损/止盈后换仓（详见参数）")
    lines.append("")

    # 选股步骤（核心：基本面闸门 + 技术图形）
    steps = selection_steps(params if isinstance(params, dict) else {}, meta)
    if steps:
        lines += ["## 怎么选股（逐步）", ""]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")
        sig = meta.get("signal")
        sig_name = getattr(sig, "__name__", "") or ""
        if sig_name:
            lines.append(f"信号实现：`{sig_name}`。")
            lines.append("")

    ex = pick_trade_example(factor_id, _factors_data_dir()) if factor_id else None
    if ex:
        title_ex = f"{ex['code']}" + (f" {ex['name']}" if ex.get("name") else "")
        lines += ["## 举例：回测真实成交一笔", ""]
        lines.append("| 项目 | 内容 |")
        lines.append("|---|---|")
        lines.append(f"| 标的 | **{title_ex}** |")
        if ex.get("buy_date"):
            cost_s = f"，约 {ex['cost']:.4g}" if ex.get("cost") else ""
            lines.append(f"| 开仓 | {ex['buy_date']}{cost_s} |")
        if ex.get("sell_date"):
            px_s = f"，约 {ex['sell_price']:.4g}" if ex.get("sell_price") else ""
            lines.append(f"| 清仓 | {ex['sell_date']}{px_s} |")
        if ex.get("leg_return") is not None:
            lines.append(f"| 单笔涨跌 | {_fmt_pct_md(ex['leg_return'])} |")
        lines.append(f"| 组合贡献 | NAV {_fmt_pct_md(ex.get('nav_pnl'))} |")
        if ex.get("open_note"):
            lines.append(f"| 开仓备注 | {ex['open_note']} |")
        if ex.get("exit_note"):
            lines.append(f"| 出场备注 | {ex['exit_note']} |")
        lines += ["", "案例用于理解「财务 + 图形」如何同时打勾，不构成投资建议。", ""]

    # 参数表
    show_keys = [
        k
        for k in params.keys()
        if k
        not in {
            "request_interval_sec",
            "note",
            "position_logic",
        }
        and not str(k).startswith("_")
    ]
    # 重要参数优先
    priority = [
        "universe",
        "hold_days",
        "stop_loss",
        "commission_rate",
        "stamp_tax_sell",
        "pe_pct_max",
        "pb_pct_max",
        "roe_min",
        "margin_min",
        "growth_min",
        "mom_min",
        "val_window",
        "max_positions",
    ]
    ordered = [k for k in priority if k in show_keys] + [k for k in show_keys if k not in priority]
    if ordered:
        lines += ["## 关键参数", "", "| 参数 | 含义 | 取值 |", "|---|---|---|"]
        for k in ordered:
            label = _PARAM_LABELS.get(k, k)
            lines.append(f"| `{k}` | {label} | {_fmt_param_value(k, params.get(k))} |")
        lines.append("")

    # 回测
    bt = _build_backtest_summary(factor_id) if factor_id else None
    lines += ["## 回测表现", ""]
    if bt and bt.get("available") and bt.get("logics"):
        lines.append("成本约定一般为：**佣金万一（买卖）+ 卖出印花税千一**（ETF 类因子可能免印花税）。")
        lines.append("")
        lines.append("| 逻辑 | 区间 | 累计收益 | CAGR | 夏普 | 最大回撤 | 基准买入持有 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for logic, m in (bt.get("logics") or {}).items():
            if not isinstance(m, dict):
                continue
            span = "—"
            if m.get("start") and m.get("end"):
                span = f"{m['start']} ~ {m['end']}"
            lines.append(
                f"| `{logic}` | {span} | {_fmt_pct_md(m.get('total_return'))} | "
                f"{_fmt_pct_md(m.get('annual_return'))} | {_fmt_num_md(m.get('sharpe'))} | "
                f"{_fmt_pct_md(m.get('max_drawdown'))} | {_fmt_pct_md(m.get('buy_hold_return'))} |"
            )
        if bt.get("updated_at"):
            lines += ["", f"回测产物更新于：`{bt['updated_at']}`"]
        arts = [a for a in (bt.get("artifacts") or []) if a.get("available")]
        if arts:
            lines += ["", "### 可查看产物", ""]
            for a in arts:
                lines.append(f"- {a.get('label') or a.get('id')}（`{a.get('kind')}`）")
        lines.append("")
    else:
        lines += ["暂无可用回测摘要。可先在列表页查看是否已生成净值图 / JSON 产物。", ""]

    lines += [
        "## 使用提示",
        "",
        "- 列表中的累计 / CAGR / 夏普 / 回撤来自本地回测产物，便于横向对比；点开说明可看完整参数与区间。",
        "- 冒烟子集（如前 40 只）夏普往往偏高，**以全市场或全成分回测为准**。",
        "- 「计算信号」给出的是最近时点候选，不代表立刻下单建议。",
        "",
    ]

    auto_body = "\n".join(lines).strip() + "\n"

    # 已有文档：足够详细则保留正文并附上回测；过短则用自动稿为主并附录原文
    if file_guide and (file_guide.get("content") or "").strip():
        raw = file_guide["content"].strip()
        # 去掉纯「怎么跑」脚手架后仍很短 → 视为过简
        substantive = raw
        for marker in ("## 怎么跑", "## 产物", "```"):
            if marker in substantive:
                substantive = substantive.split(marker)[0]
        if len(substantive.strip()) >= 280:
            # 丰富文档：正文 + 自动回测/参数附录（避免重复标题）
            # 参数网格因子的旧 guide 开篇备注常雷同：在标题后注入可区分要点
            body = raw
            if overview:
                raw_lines = raw.splitlines()
                if raw_lines and raw_lines[0].startswith("# "):
                    rest = "\n".join(raw_lines[1:]).lstrip("\n")
                    # 去掉旧开篇短备注（直到空行或「标签」/二级标题），避免与要点重复
                    rest_lines = rest.splitlines()
                    i = 0
                    while i < len(rest_lines) and not rest_lines[i].strip():
                        i += 1
                    if i < len(rest_lines) and not rest_lines[i].startswith("#") and not rest_lines[i].startswith("标签"):
                        # 单段旧 description
                        j = i + 1
                        while j < len(rest_lines) and rest_lines[j].strip():
                            j += 1
                        old_para = "\n".join(rest_lines[i:j]).strip()
                        if old_para and (old_para == desc or len(old_para) < 80):
                            rest = "\n".join(rest_lines[j:]).lstrip("\n")
                    body = f"{raw_lines[0]}\n\n## 本变体要点\n\n{overview}\n\n{rest}".rstrip() + "\n"
                else:
                    body = f"## 本变体要点\n\n{overview}\n\n{raw}".rstrip() + "\n"
            bt_only = []
            capturing = False
            for line in auto_body.splitlines():
                if line.startswith("## 回测表现"):
                    capturing = True
                if capturing:
                    bt_only.append(line)
                if capturing and line.startswith("## 使用提示"):
                    break
            content = body + "\n---\n\n" + "\n".join(bt_only).strip() + "\n"
            return {
                "factor_id": factor_id,
                "title": file_guide.get("title") or name,
                "format": "markdown",
                "content": content,
                "path": file_guide.get("path"),
                "fallback": False,
            }
        # 过简：自动详细稿 + 原文附录
        content = (
            auto_body
            + "\n---\n\n## 原始说明（文档）\n\n"
            + raw
            + "\n"
        )
        return {
            "factor_id": factor_id,
            "title": name,
            "format": "markdown",
            "content": content,
            "path": file_guide.get("path"),
            "fallback": True,
        }

    return {
        "factor_id": factor_id,
        "title": name,
        "format": "markdown",
        "content": auto_body,
        "fallback": True,
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
        "error",
        "note",
        "n_legs_raw",
        "n_legs_accepted",
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
    # 新注册因子若进程未热加载，仍按标准产物约定挂载，避免列表有名无回测
    if not registry:
        registry = _standard_artifacts(factor_id, factor_id)

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
        "primary_logic": factor_id,
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
    elif factor_id == "dividend_etf_swing":
        summary_path = data_dir / "dividend_etf_swing_backtest.json"
        if summary_path.exists():
            try:
                raw = json.loads(summary_path.read_text(encoding="utf-8"))
                results = raw.get("results") or {}
                logics: Dict[str, Any] = {}
                for key, row in results.items():
                    if isinstance(row, dict) and "sharpe" in row:
                        logics[str(row.get("position_logic") or key)] = _metric_slice(row)
                out.update(
                    {
                        "available": bool(logics),
                        "primary_logic": "ma_pullback",
                        "logics": logics,
                        "updated_at": datetime.fromtimestamp(summary_path.stat().st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to read dividend_etf_swing_backtest.json")
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
    {
        "factor_id": "dividend_etf_swing",
        "name": "红利ETF波段",
        "category": "alternative",
        "description": (
            "在红利类ETF（默认515080）上做防守波段："
            "MA60趋势过滤 + MA20回踩确认入场；跌破均线/止损/到期离场。"
            "ETF免印花税，佣金万一；适合作为组合卫星仓。"
        ),
        "tags": ["另类", "红利", "ETF", "波段", "515080"],
        "builtin": True,
        "params": {k: v for k, v in DIVIDEND_ETF_DEFAULT_PARAMS.items() if k != "fallback_etfs"},
    },
    {
        "factor_id": "dividend_etf_slope_grid",
        "name": "红利ETF倾斜网格",
        "category": "alternative",
        "description": (
            "红利ETF向上倾斜网格（与策略同源）：中枢=max(旧,MA90)只升不降；"
            "跌超0.8%加档、涨超0.8%减档，至少保留2档底仓。"
            "默认515080；ETF免印花税，佣金万一。"
        ),
        "tags": ["另类", "红利", "ETF", "网格", "倾斜", "515080"],
        "builtin": True,
        "params": {
            k: v for k, v in DIVIDEND_SLOPE_GRID_DEFAULT_PARAMS.items() if k != "fallback_etfs"
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
    # 下列 5 个仍在 FACTOR_IMPL / BUILTIN，不得列入 RETIRED（否则 ensure 会删掉并导致 UI 序号前移吞掉 #166）
    # "pe_low_ma_reclaim",
    # "cheap_roe_bounce",
    # "eps_growth_reclaim",
    # "ma_trend_quality",
    # "high_margin_pullback",
    "low_vol_reclaim",
    "momentum_ma_pullback",
    "ma120_pullback",
    "turnover_dryup_bounce",
    "gap_down_recover",
    "consecutive_down_bounce",
    # 效果差 / 用户明确不入库
    "quality_on_sale",
    "templeton_panic",
    "greenblatt_magic",
    "dreman_growth_filter",
    "earnings_accel_reclaim",
    "gp_margin_expand",
    "margin_roe_reclaim",
    "pb_below_growth",
    "pb_cheap_growth_mom",
    "pe_pb_growth_triple",
    "triple_quality",
    "value_quality_mom",
    "decrowd_trend_hold",
    "gap_down_intraday_reclaim",
    "illiquid_quality_bounce",
    "month_end_quality",
    "neglect_reawakening",
    "pricing_power_gap",
    "roe_turnaround",
    "rs_momentum_pullback",
    "amount_dryup_thrust",
    "gap_down_fill",
    "inside_day_break",
    "two_bar_reversal_quality",
    # 第五波纯量价 / 日历量价（用户要求侧重基本面）
    "nr7_breakout",
    "ma60_slope_turn",
    "friday_quality_dip",
    "intraday_recovery",
    "vol_expansion_trend",
    "turn_climax_cool",
    "quiet_breakout",
    "asset_light_efficiency",
    "eps_ni_sync_growth",
    "parent_profit_lead",
    "revenue_up_roe",
    "roe_pb_misprice",
    "roe_persist_reclaim",
    "share_shrink_quality",
    "advance_recv_lead_base",
    "advance_recv_lead_roe",
    "amount_coil_outrun_base",
    "asset_light_cl_base",
    "asset_light_lag29_g10",
    "asset_light_ni_amp",
    "asset_light_ni_base",
    "asset_light_ni_pullback",
    "asset_light_ni_reclaim",
    "asset_light_ni_roe",
    "catchup_break_lag28",
    "catchup_break_lag28_hold52",
    "catchup_brk80",
    "catchup_brk80_gap04",
    "catchup_brk80_gp22",
    "cl_intensity_base",
    "cl_intensity_break_np",
    "cl_intensity_reclaim",
    "cl_intensity_roe_base",
    "cl_intensity_roe_reclaim",
    "consec_improve_lag28_hold51",
    "consec_improve_lag30_hold51",
    "contract_liab_base_break",
    "contract_liab_reclaim_strict",
    "contract_np_lag28_hold51",
    "contract_np_lag28_np10",
    "contract_np_lag29_np08",
    "contract_np_lag29_np10",
    "contract_np_lag29_yoy25",
    "demand_pricing_base",
    "demand_pricing_base_np",
    "demand_pricing_break",
    "demand_pricing_pullback",
    "dual_break_hold50",
    "dual_break_mid_hold50",
    "dual_brk80_lag28",
    "dual_improve_base_tight2",
    "dual_improve_breakout_wide",
    "dual_lag28_hold50",
    "dual_lag28_hold51",
    "dual_lag28_hold52",
    "dual_lag28_np08",
    "dual_lag28_np10",
    "dual_lag28_np11",
    "dual_lag29_hold51",
    "dual_m17_lag29_np10",
    "dual_mid_amp18",
    "dual_mid_amp22",
    "dual_mid_hold40",
    "dual_mid_hold42",
    "dual_mid_hold45",
    "dual_mid_hold50",
    "dual_mid_hold51",
    "dual_mid_hold52",
    "dual_tight_amp16",
    "dual_tight_amp16_hold52",
    "dual_tight_hold35",
    "dual_tight_hold50",
    "dual_tight_hold51",
    "dual_tight_hold52",
    "dual_tight_hold53",
    "dual_wide_base",
    "dual_yoy_accel_base",
    "dual_yoy_accel_reclaim",
    "eps_dual_accel08",
    "eps_dual_confirm_break",
    "eps_dual_hold50",
    "eps_dual_lag28_accel08_brk80",
    "eps_dual_lag28_brk60",
    "eps_dual_lag28_brk80",
    "eps_dual_lag28_brk80_hold52",
    "eps_dual_lag28_hold51",
    "eps_dual_lag28_np10_brk80",
    "eps_dual_lag30_brk80",
    "eps_dual_lag30_hold51",
    "eps_ttm_mom_base",
    "equity_outrun_break",
    "equity_outrun_pullback",
    "float_concentration_reclaim",
    "gp_cheap_lag28",
    "gp_cheap_lag28_hold51",
    "gp_cheap_lag29_m17_np10",
    "gp_cheap_lag29_m17_np10_hold52",
    "gp_cheap_lag29_m17_pe60",
    "gp_cheap_mid_hold50",
    "gp_consec_base",
    "gp_consec_break",
    "gp_consec_pullback",
    "gp_expand_cheap_break",
    "gp_expand_cheap_hold50",
    "gp_np_expand_break",
    "gp_np_expand_lag",
    "gp_np_lag28_m17_nimp005",
    "gp_np_lag29_m16_nimp005",
    "gp_np_lag29_m17_nimp004",
    "gp_np_lag29_m17_nimp005_hold52",
    "gp_np_lag29_m17_nimp006",
    "gp_np_lag29_m17_np10",
    "gp_np_lag29_m20_np10",
    "gp_np_lag30_m17_nimp005",
    "gp_np_lag_base_hold35",
    "gp_np_lag_hold35",
    "gp_np_lag_hold42",
    "gp_np_lag_hold45",
    "gp_np_lag_hold51",
    "gp_np_lag_hold52",
    "gp_np_lag_hold60",
    "gp_np_lag_stop10",
    "gp_np_mid_hold50",
    "gp_np_peak_tp20",
    "gp_np_tight_break",
    "gp_np_tight_hold51",
    "gp_np_tight_lag28_hold52",
    "gp_np_tight_lag29_hold50",
    "gp_np_tight_lag29_hold51",
    "gp_np_tight_lag29_hold52",
    "gp_np_tight_lag30_hold51",
    "gp_np_tight_lag30_hold52",
    "gp_np_tight_lag31_hold51",
    "gross_base_mid_hold50",
    "gross_dual_base_tight",
    "gross_dual_mid_hold50",
    "gross_dual_stack_break",
    "gross_dual_stack_hold51",
    "gross_dual_stack_hold52",
    "gross_expand_break",
    "gross_expand_break_tight",
    "gross_expand_brk55_m17_np10_lag29",
    "gross_expand_brk58_m17_np10_lag29",
    "gross_expand_brk60_m16_np10",
    "gross_expand_brk60_m16_np10_lag29",
    "gross_expand_brk60_m175_np10_lag29",
    "gross_expand_brk60_m17_np09",
    "gross_expand_brk60_m17_np095_lag29",
    "gross_expand_brk60_m17_np10",
    "gross_expand_brk60_m17_np105_lag29",
    "gross_expand_brk60_m17_np10_hold52",
    "gross_expand_brk60_m17_np10_imp005",
    "gross_expand_brk60_m17_np10_lag27",
    "gross_expand_brk60_m17_np10_lag29",
    "gross_expand_brk60_m17_np10_lag29_hold49",
    "gross_expand_brk60_m17_np10_lag29_hold50",
    "gross_expand_brk60_m17_np10_lag29_hold52",
    "gross_expand_brk60_m17_np10_lag29_hold53",
    "gross_expand_brk60_m17_np10_lag29_hold54",
    "gross_expand_brk60_m17_np10_lag29_imp005",
    "gross_expand_brk60_m17_np10_lag29_imp0055",
    "gross_expand_brk60_m17_np10_lag29_imp0065",
    "gross_expand_brk60_m17_np10_lag29_ma60",
    "gross_expand_brk60_m17_np10_lag29_nimp002",
    "gross_expand_brk60_m17_np10_lag29_nimp003",
    "gross_expand_brk60_m17_np10_lag29_nimp005",
    "gross_expand_brk60_m17_np10_lag29_stop10",
    "gross_expand_brk60_m17_np10_lag29_stop13",
    "gross_expand_brk60_m17_np10_lag29_stop14",
    "gross_expand_brk60_m17_np10_lag30",
    "gross_expand_brk60_m17_np10_lag31",
    "gross_expand_brk60_m17_np11",
    "gross_expand_brk60_m17_np11_lag29",
    "gross_expand_brk60_m18_np10",
    "gross_expand_brk60_m18_np10_lag29",
    "gross_expand_brk60_m19_np10_lag29",
    "gross_expand_brk62_m17_np10_lag29",
    "gross_expand_brk65_m17_np10_lag29",
    "gross_expand_brk70",
    "gross_expand_brk75_m17",
    "gross_expand_brk80",
    "gross_expand_brk80_imp005",
    "gross_expand_brk80_m16",
    "gross_expand_brk80_m17",
    "gross_expand_brk80_m17_imp005",
    "gross_expand_brk80_m17_lag29",
    "gross_expand_brk80_m17_np08",
    "gross_expand_brk80_m17_np10",
    "gross_expand_brk80_m17_np10_hold50",
    "gross_expand_brk80_m17_np12",
    "gross_expand_brk80_m18",
    "gross_expand_brk80_np10",
    "gross_expand_brk85_m17",
    "gross_expand_brk90",
    "gross_expand_champ_amtdry60",
    "gross_expand_champ_dd03",
    "gross_expand_champ_dd05",
    "gross_expand_champ_gp2",
    "gross_expand_champ_gp2_imp005",
    "gross_expand_champ_pb40",
    "gross_expand_champ_pe45",
    "gross_expand_champ_pe55",
    "gross_expand_champ_ret20_15",
    "gross_expand_champ_ret20_20",
    "gross_expand_champ_ret20_30",
    "gross_expand_champ_roe10",
    "gross_expand_champ_roe10_pe55",
    "gross_expand_champ_roe12",
    "gross_expand_champ_soft97",
    "gross_expand_champ_soft98",
    "gross_expand_champ_soft99",
    "gross_expand_champ_tp15",
    "gross_expand_champ_tp20",
    "gross_expand_champ_tp20_hold60",
    "gross_expand_champ_tp25",
    "gross_expand_champ_tp30",
    "gross_expand_champ_tp32",
    "gross_expand_champ_tp34",
    "gross_expand_champ_tp35",
    "gross_expand_champ_tp35_hold49",
    "gross_expand_champ_tp35_hold50",
    "gross_expand_champ_tp35_hold52",
    "gross_expand_champ_tp35_hold53",
    "gross_expand_champ_tp35_hold55",
    "gross_expand_champ_tp35_np09",
    "gross_expand_champ_tp35_np11",
    "gross_expand_champ_tp35_stop10",
    "gross_expand_champ_tp35_stop14",
    "gross_expand_champ_tp35_trail15",
    "gross_expand_champ_tp36",
    "gross_expand_champ_tp38",
    "gross_expand_champ_tp40",
    "gross_expand_champ_tp50",
    "gross_expand_champ_trail10",
    "gross_expand_champ_trail12",
    "gross_expand_champ_trail15",
    "gross_expand_champ_yoy0",
    "gross_expand_champ_yoy03",
    "gross_expand_champ_yoy05",
    "gross_expand_hold40",
    "gross_expand_hold50",
    "gross_expand_hold50_stop10",
    "gross_expand_hold52",
    "gross_expand_hold53",
    "gross_expand_hold55",
    "gross_expand_hold60",
    "gross_expand_imp007",
    "gross_expand_lag27",
    "gross_expand_lag27_hold51",
    "gross_expand_lag28",
    "gross_expand_lag28_hold50_mid",
    "gross_expand_lag28_hold51",
    "gross_expand_lag28_hold51_imp005",
    "gross_expand_lag28_hold51_m18",
    "gross_expand_lag28_hold51_m22",
    "gross_expand_lag28_hold51_stop10",
    "gross_expand_lag28_hold52",
    "gross_expand_lag28_hold55",
    "gross_expand_lag28_stop10",
    "gross_expand_lag29",
    "gross_expand_lag29_hold51",
    "gross_expand_lag29_hold52",
    "gross_expand_lag29_hold53",
    "gross_expand_lag29_stop10",
    "gross_expand_lag30",
    "gross_expand_lag30_hold55",
    "gross_expand_lag30_stop10",
    "gross_expand_lag32",
    "gross_expand_ma60_tp35",
    "gross_expand_mid_hold45",
    "gross_expand_mid_hold48",
    "gross_expand_mid_hold50",
    "gross_expand_mid_hold55",
    "gross_expand_mid_lag20",
    "gross_expand_mid_m22",
    "gross_expand_mid_stop10",
    "gross_expand_tight_hold40",
    "gross_high_np_amp22",
    "gross_high_np_brk100",
    "gross_high_np_brk40",
    "gross_high_np_brk50",
    "gross_high_np_brk70",
    "gross_high_np_brk75_m17",
    "gross_high_np_brk80",
    "gross_high_np_brk80_hold52",
    "gross_high_np_brk80_imp005",
    "gross_high_np_brk80_m16",
    "gross_high_np_brk80_m17",
    "gross_high_np_brk80_m17_hold52",
    "gross_high_np_brk80_m17_imp005",
    "gross_high_np_brk80_m17_lag27",
    "gross_high_np_brk80_m17_lag29",
    "gross_high_np_brk80_m17_nimp002",
    "gross_high_np_brk80_m17_nimp003",
    "gross_high_np_brk80_m17_np09",
    "gross_high_np_brk80_m17_np11",
    "gross_high_np_brk80_m18",
    "gross_high_np_brk85_m17",
    "gross_high_np_brk90",
    "gross_high_np_champ_brk50",
    "gross_high_np_champ_stop10",
    "gross_high_np_champ_stop14",
    "gross_high_np_either",
    "gross_high_np_g03",
    "gross_high_np_g03_m17",
    "gross_high_np_g05",
    "gross_high_np_g08",
    "gross_high_np_g08_hold52",
    "gross_high_np_g08_imp005",
    "gross_high_np_g08_m17",
    "gross_high_np_g12",
    "gross_high_np_g15",
    "gross_high_np_gacc05",
    "gross_high_np_gacc05_m17",
    "gross_high_np_gacc08",
    "gross_high_np_imp0055_hold52",
    "gross_high_np_imp005_hold52",
    "gross_high_np_imp005_roe12",
    "gross_high_np_lag27_np10",
    "gross_high_np_lag28_hold51",
    "gross_high_np_lag28_hold51_np10",
    "gross_high_np_lag28_np09",
    "gross_high_np_lag28_np10_hold52",
    "gross_high_np_lag28_np11",
    "gross_high_np_lag28_np12",
    "gross_high_np_lag29_np10",
    "gross_high_np_lag30_hold51",
    "gross_high_np_m16_imp005_brk40",
    "gross_high_np_m16_imp005_brk50",
    "gross_high_np_m16_lag30_np10",
    "gross_high_np_m17_imp005",
    "gross_high_np_m17_imp0055",
    "gross_high_np_m17_lag29_amp18",
    "gross_high_np_m17_lag29_amp22",
    "gross_high_np_m17_lag29_either",
    "gross_high_np_m17_lag29_np10",
    "gross_high_np_m17_lag29_reclaim",
    "gross_high_np_m17_lag30_imp005_np10",
    "gross_high_np_m17_lag30_np10",
    "gross_high_np_m17_lag30_np10_hold52",
    "gross_high_np_m18_imp005",
    "gross_high_np_m18_lag29_np10",
    "gross_high_np_m22_hold51",
    "gross_high_np_ma60",
    "gross_high_np_ma60_hold50",
    "gross_high_np_ma60_hold52",
    "gross_high_np_ma60_hold53",
    "gross_high_np_ma60_imp005",
    "gross_high_np_ma60_m17",
    "gross_high_np_ma60_np11",
    "gross_high_np_ma60_roe12",
    "gross_high_np_nimp002_m16",
    "gross_high_np_nimp002_m17",
    "gross_high_np_nimp003",
    "gross_high_np_nimp003_hold52",
    "gross_high_np_nimp003_m15",
    "gross_high_np_nimp003_m16",
    "gross_high_np_nimp003_m16_hold52",
    "gross_high_np_nimp003_m16_imp005",
    "gross_high_np_nimp003_m16_lag27",
    "gross_high_np_nimp003_m16_lag29",
    "gross_high_np_nimp003_m17",
    "gross_high_np_nimp003_m17_hold52",
    "gross_high_np_nimp003_m17_imp005",
    "gross_high_np_nimp003_m18",
    "gross_high_np_nimp004_m17",
    "gross_high_np_nimp005",
    "gross_high_np_np10_hold50",
    "gross_high_np_np10_hold53",
    "gross_high_np_np10_imp004",
    "gross_high_np_np10_imp005",
    "gross_high_np_np10_imp0055",
    "gross_high_np_np10_imp0065",
    "gross_high_np_np10_m17",
    "gross_high_np_np10_m18",
    "gross_high_np_np10_m19",
    "gross_high_np_np11_hold52",
    "gross_high_np_np11_hold53",
    "gross_high_np_pb30",
    "gross_high_np_pe45",
    "gross_high_np_pe55",
    "gross_high_np_reclaim",
    "gross_high_np_reclaim_hold52",
    "gross_high_np_reclaim_ma60",
    "gross_high_np_roe10",
    "gross_high_np_roe12",
    "gross_np_up_brk70",
    "gross_np_up_brk75",
    "gross_np_up_brk80",
    "gross_np_up_brk80_hold52",
    "gross_np_up_brk80_imp005",
    "gross_np_up_brk80_lag27",
    "gross_np_up_brk80_lag29",
    "gross_np_up_brk80_m17",
    "gross_np_up_brk80_nimp005",
    "gross_np_up_brk80_np09",
    "gross_np_up_brk80_np11",
    "gross_np_up_brk85",
    "gross_np_up_brk90",
    "gross_np_up_lag28_hold51",
    "gross_np_up_lag28_np08",
    "gross_np_up_lag28_np10",
    "gross_np_up_m17_lag29_np10",
    "gross_np_up_np09",
    "gross_np_up_np10_hold50",
    "gross_np_up_np10_lag29",
    "gross_np_up_np10_nimp005",
    "gross_np_up_np11",
    "gross_tight_base",
    "high_margin_break_hold50",
    "high_margin_break_hold51",
    "high_margin_break_m15",
    "high_margin_breakout",
    "high_margin_m15_hold51",
    "high_margin_m18_hold51",
    "high_margin_m18_hold52",
    "high_margin_m20_hold52",
    "ni_quality_base",
    "ni_quality_cheap_break",
    "ni_quality_pullback",
    "ni_quality_reclaim",
    "np_expand_cheap_break",
    "np_expand_cheap_pullback",
    "np_regime_amp",
    "np_regime_base",
    "np_regime_break",
    "np_regime_lag29_brk60",
    "np_regime_ma60",
    "np_regime_pullback",
    "np_regime_roe",
    "parent_eps_twin_base",
    "parent_eps_twin_pullback",
    "parent_eps_twin_quality",
    "parent_eps_twin_reclaim",
    "parent_lead_break",
    "parent_lead_lag29_g12",
    "parent_lead_reclaim",
    "pb_floor_hold51",
    "quality_coil_break",
    "rev_accel_hold50",
    "rev_per_share_accel",
    "rev_per_share_accel_base",
    "rev_qoq_pullback",
    "rev_roe_sync_base",
    "rev_roe_sync_break",
    "rev_roe_sync_np",
    "rev_roe_sync_pullback",
    "roe_accel_base",
    "roe_accel_break",
    "roe_accel_np",
    "roe_accel_pullback",
    "roe_expand_brk80_np10",
    "roe_expand_hold51",
    "roe_expand_r12_hold51",
    "roe_lag28_hold51",
    "roe_lag28_np10",
    "share_buyback_base",
    "share_buyback_break",
    "share_buyback_pullback",
    "turn_dry_growth_roe",
    "twin_yoy_breakout",
    "twin_yoy_lag29_g10_hold52",
    "twin_yoy_lag29_g15",
    # 回测无腿 / 用户要求下线
    "roe_dip_reclaim",
    # 用户删除原 catchup/UI#192（Mongo 用 _gen_pad_ui165 / _gen_pad_ui193 占位保序）
    "struct_catchup_gp28_lag26_csi500_r3",
    # 用户删除 UI#239/#240/#242（Mongo pad 保序）
    "phys_cip_convert_c35",
    "phys_cip_convert_c35_ry05",
    "phys_cash_collect_c38",
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
        "last_backtest_error": doc.get("last_backtest_error"),
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
        # 仍在 BUILTIN / FACTOR_IMPL 的因子绝不能删：否则 UI 序号前移，会吞掉原 #166 等稳定位。
        # 新因子应永远挂到 max(序号)+1，不要靠删旧号填空洞。
        builtin_ids = {str(f.get("factor_id") or "") for f in BUILTIN_FACTORS}
        builtin_ids.update(str(x) for x in FACTOR_IMPL.keys())
        retired_to_drop = [
            fid for fid in RETIRED_FACTOR_IDS if fid and str(fid) not in builtin_ids
        ]
        if retired_to_drop:
            await db[FACTORS].delete_many({"factor_id": {"$in": list(retired_to_drop)}})
            await db[FACTOR_SIGNALS].delete_many({"factor_id": {"$in": list(retired_to_drop)}})
        for f in BUILTIN_FACTORS:
            # 内置因子元数据每次同步；已有文档保留原 created_at，避免序号漂移。
            # 新增因子：挂到 max(created_at)+1h，禁止用定义序合成时间插到中间挤占。
            fid = f.get("factor_id")
            existing = await db[FACTORS].find_one({"factor_id": fid}, {"created_at": 1}) if fid else None
            payload = {
                **f,
                "status": "active",
                "builtin": True,
                "updated_at": now,
            }
            if existing and existing.get("created_at") is not None:
                payload["created_at"] = existing["created_at"]
            else:
                payload["created_at"] = await self._next_factor_created_at(db, now)
            await db[FACTORS].update_one(
                {"factor_id": f["factor_id"]},
                {"$set": payload},
                upsert=True,
            )

    @staticmethod
    async def _next_factor_created_at(db: Any, now: datetime) -> datetime:
        """新因子序号：永远挂到当前最大 created_at 之后。"""
        latest = await db[FACTORS].find_one(
            {"created_at": {"$ne": None}},
            sort=[("created_at", -1)],
            projection={"created_at": 1},
        )
        if not latest or latest.get("created_at") is None:
            return now
        try:
            nxt = latest["created_at"] + timedelta(hours=1)
        except Exception:
            return now
        return now if now > nxt else nxt


    @staticmethod
    def _is_seq_pad(doc: Dict[str, Any]) -> bool:
        """序号占位（已删槽位），Mongo 保留保序，列表不展示。"""
        fid = str(doc.get("factor_id") or "")
        tags = doc.get("tags") or []
        if fid.startswith("_gen_pad"):
            return True
        if "gen_seq_pad" in tags or "deleted_slot" in tags:
            return True
        return False

    async def list_factors(self) -> List[Dict[str, Any]]:
        await self.ensure_builtins()
        db = get_mongo_db()
        # 按生成时间升序：先做的在前；无时间戳的排最后
        cursor = db[FACTORS].find({}).sort([("created_at", 1), ("factor_id", 1)])
        docs = [d async for d in cursor]
        out: List[Dict[str, Any]] = []
        for i, d in enumerate(docs, 1):
            if self._is_seq_pad(d):
                # 占位仍占 UI 序号空洞（#165/#193），但不出现在因子列表
                continue
            row = _serialize_factor(d)
            row["gen_seq"] = i
            out.append(row)
        return out

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
        # 新因子永远挂到当前最大 created_at 之后（max+1），不填空洞、不挤占
        created_at = await self._next_factor_created_at(db, now)
        doc = {
            **payload.model_dump(),
            "category": payload.category.value,
            "status": payload.status.value,
            "builtin": False,
            "created_at": created_at,
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

    async def match_stock(self, code: str, asof: Optional[str] = None) -> Dict[str, Any]:
        """单票对 active 因子做当前入场信号匹配（本地缓存优先）。"""
        await self.ensure_builtins()
        items = await self.list_factors()
        return await asyncio.to_thread(match_stock_against_factors, code, items, asof=asof)

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
        elif factor_id == "dividend_etf_swing":
            result = await asyncio.to_thread(
                compute_dividend_etf_swing_signal,
                factor.get("params") or {},
                asof,
            )
        elif factor_id == "dividend_etf_slope_grid":
            result = await asyncio.to_thread(
                compute_dividend_etf_slope_grid_signal,
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

    async def get_guide(self, factor_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_builtins()
        factor = await self.get_factor(factor_id)
        if not factor:
            return None
        # 以注册表为准拼装说明（Mongo 里 description/params 常过简或滞后）
        if factor_id in FACTOR_IMPL:
            meta = FACTOR_IMPL[factor_id]
            factor = {
                **factor,
                "name": meta.get("name") or factor.get("name"),
                "description": meta.get("description") or factor.get("description"),
                "tags": meta.get("tags") or factor.get("tags") or [],
                "category": meta.get("category") or factor.get("category"),
                "params": {**(factor.get("params") or {}), **(meta.get("params") or {})},
            }
        file_guide = load_factor_guide(factor_id)
        return build_factor_guide_markdown(factor, file_guide=file_guide)

    def resolve_artifact(self, factor_id: str, artifact_id: str) -> Tuple[Path, Dict[str, Any]]:
        registry = FACTOR_ARTIFACTS.get(factor_id)
        # 与 _build_backtest_summary 一致：注册表缺失时仍按标准产物约定解析
        # （例如已从 FACTOR_IMPL 下线但仍有回测文件的因子）
        if not registry or artifact_id not in registry:
            registry = _standard_artifacts(factor_id, factor_id)
        if artifact_id not in registry:
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
