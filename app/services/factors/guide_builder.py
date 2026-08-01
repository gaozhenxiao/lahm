"""因子说明：选股步骤 + 真实成交案例（供 UI 与文档生成共用）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

_CODE_NAMES = {
    "sz.002463": "沪电股份",
    "sz.002466": "天齐锂业",
    "sz.002594": "比亚迪",
    "sz.002311": "海大集团",
    "sz.002460": "赣锋锂业",
    "sz.300122": "智飞生物",
    "sz.300015": "爱尔眼科",
    "sz.300274": "阳光电源",
    "sh.600176": "中国巨石",
    "sh.601021": "春秋航空",
    "sh.600115": "中国东航",
    "sh.601111": "中国国航",
    "sh.601238": "广汽集团",
    "sz.000338": "潍柴动力",
    "sz.002558": "巨人网络",
    "sz.002028": "思源电气",
    "sh.600900": "长江电力",
    "sh.600188": "兖矿能源",
    "sh.603288": "海天味业",
    "sz.300450": "先导智能",
    "sh.600183": "生益科技",
    "sh.601633": "长城汽车",
}


def _pct(v: Any) -> str:
    """始终按小数收益率格式化为百分数（1.72 → 172.00%）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{x:.2%}"


def _num(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:g}"


_SIG_LABELS = {
    "signal_gross_high_np_break": "毛利率扩张 + 高净利率后突破",
    "signal_gross_expand_break": "毛利率扩张后突破",
    "signal_gross_np_up_break": "毛利率扩张 + 净利率改善后突破",
    "signal_gp_np_expand_break": "毛利/净利双扩张后突破",
    "signal_gp_np_tight_break": "毛利/净利收紧扩张后突破",
    "signal_dual_improve_base_break": "双改善横盘突破",
    "signal_dual_improve_breakout": "双改善突破",
    "signal_eps_dual_confirm_break": "EPS 双确认突破",
    "signal_high_margin_breakout": "高毛利率突破",
    "signal_gp_expand_cheap_break": "毛利率扩张 + 低估突破",
    "signal_roe_expand_breakout": "ROE 扩张突破",
    "signal_gross_net_catchup_break": "毛利扩张净利追赶突破",
}


def _fmt_level(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x) <= 1.5:
        return f"{x:.0%}" if abs(x * 100 - round(x * 100)) < 1e-6 else f"{x:.2%}".rstrip("0").rstrip(".")
    return _num(x)


def variant_overview(meta: Dict[str, Any]) -> str:
    """按实际 params 生成可区分的一句话说明（参数网格变体专用）。"""
    p = dict(meta.get("params") or {})
    sig = getattr(meta.get("signal"), "__name__", "") or ""
    head = _SIG_LABELS.get(sig) or (meta.get("name") and str(meta["name"])) or "规则变体"

    bits: List[str] = []
    if p.get("margin_min") is not None:
        bits.append(f"毛利≥{_fmt_level(p['margin_min'])}")
    elif p.get("gp_min") is not None:
        bits.append(f"毛利≥{_fmt_level(p['gp_min'])}")
    if p.get("gap_min") is not None:
        bits.append(f"毛净利差缺口≥{_fmt_level(p['gap_min'])}")
    if p.get("margin_improve") is not None or p.get("gp_improve") is not None:
        imp = p.get("margin_improve", p.get("gp_improve"))
        bits.append(f"毛利环比升≥{_fmt_level(imp)}")
    if p.get("gp_consec"):
        bits.append("毛利连续两期改善")
    if p.get("np_min") is not None:
        bits.append(f"净利≥{_fmt_level(p['np_min'])}")
    if p.get("np_improve") is not None:
        bits.append(f"净利环比升≥{_fmt_level(p['np_improve'])}")
    if p.get("roe_min") is not None:
        bits.append(f"ROE≥{_fmt_level(p['roe_min'])}")
    if p.get("growth_min") is not None:
        bits.append(f"同比≥{_fmt_level(p['growth_min'])}")
    if p.get("growth_accel") is not None or p.get("accel_min") is not None:
        acc = p.get("growth_accel", p.get("accel_min"))
        bits.append(f"增速加速≥{_fmt_level(acc)}")
    if p.get("yoy_min") is not None:
        bits.append(f"合同负债同比≥{_fmt_level(p['yoy_min'])}")
    if p.get("qoq_min") is not None:
        bits.append(f"合同负债环比≥{_fmt_level(p['qoq_min'])}")
    if p.get("funda_lag") is not None:
        bits.append(f"财务热窗{int(p['funda_lag'])}日")
    entry = str(p.get("entry") or "")
    brk = int(p.get("break_days") or 60)
    ma_days = int(p.get("ma_days") or 20)
    if entry == "reclaim":
        bits.append(f"入场=上穿MA{ma_days}")
    elif entry == "pullback":
        bits.append("入场=趋势回踩")
    elif entry in ("either", "or"):
        bits.append(f"入场=突破或回踩(二选一)")
    elif entry == "base_break" or (p.get("amp_max") is not None and entry == "base_break"):
        bits.append(f"入场=横盘突破(振幅≤{_fmt_level(p.get('amp_max') or 0.24)})")
    else:
        soft = p.get("brk_soft")
        if soft is not None and float(soft) != 1.0:
            bits.append(f"入场={brk}日高×{float(soft):g}+MA{ma_days}")
        else:
            bits.append(f"入场={brk}日高+MA{ma_days}")
    if p.get("ma_cross"):
        bits.append(f"需上穿MA{ma_days}")
    if p.get("amp_max") is not None and entry != "base_break":
        bits.append(f"振幅≤{_fmt_level(p['amp_max'])}")
    if p.get("dd_need") is not None:
        bits.append(f"回撤过滤{_fmt_level(abs(float(p['dd_need'])))}")
    if p.get("ret20_max") is not None:
        bits.append(f"20日涨幅≤{_fmt_level(p['ret20_max'])}")
    if p.get("amt_dry_ratio") is not None:
        bits.append(f"缩量≤均量{_fmt_level(p['amt_dry_ratio'])}")
    if p.get("hold_days") is not None:
        bits.append(f"持有{int(p['hold_days'])}日")
    if p.get("stop_loss") is not None:
        bits.append(f"止损{_fmt_level(abs(float(p['stop_loss'])))}")
    if p.get("take_profit") is not None:
        bits.append(f"止盈{_fmt_level(p['take_profit'])}")
    else:
        bits.append("无固定止盈")
    if p.get("trail_stop") is not None:
        bits.append(f"移动止盈回撤{_fmt_level(p['trail_stop'])}")
    if p.get("pe_pct_max") is not None:
        bits.append(f"PE分位≤{_fmt_level(p['pe_pct_max'])}")
    if p.get("pb_pct_max") is not None:
        bits.append(f"PB分位≤{_fmt_level(p['pb_pct_max'])}")
    if p.get("lead_min") is not None:
        bits.append(f"归属领先≥{_fmt_level(p['lead_min'])}")
    if p.get("cl_rev_min") is not None:
        bits.append(f"合同负债/营收≥{_fmt_level(p['cl_rev_min'])}")
    if p.get("asset_yoy_max") is not None:
        bits.append(f"资产同比≤{_fmt_level(p['asset_yoy_max'])}")

    if not bits:
        return (meta.get("description") or head or "").strip()
    return f"{head}：{'；'.join(bits)}。"


def selection_steps(params: Dict[str, Any], meta: Dict[str, Any]) -> List[str]:
    """根据注册参数生成「同时满足才买入」的步骤列表。"""
    p = params or {}
    steps: List[str] = []
    uni = p.get("universe") or "hs300"
    steps.append(f"**股票池**：默认 `{uni}` 成分；对每只股票逐日检查，下列条件需同时满足才开仓。")

    # —— 基本面闸门 ——
    if p.get("pb_pct_max") is not None:
        steps.append(f"**估值闸门**：PB 历史分位 ≤ **{_pct(p['pb_pct_max'])}**（窗口 `{p.get('val_window') or 756}` 交易日）")
    if p.get("pe_pct_max") is not None:
        steps.append(f"**估值闸门**：PE 历史分位 ≤ **{_pct(p['pe_pct_max'])}**（窗口 `{p.get('val_window') or 756}` 交易日）")
    if p.get("pb_max") is not None:
        steps.append(f"**估值闸门**：PB 绝对值 ≤ **{_num(p['pb_max'])}**")

    if p.get("roe_min") is not None:
        steps.append(f"**质量底线**：ROE ≥ **{_pct(p['roe_min'])}**")
    if p.get("roe_improve") is not None:
        steps.append(f"**ROE 改善**：相对上一披露期上升 ≥ **{_pct(p['roe_improve'])}**（百分点/小数按数据口径）")
    if p.get("margin_improve") is not None or p.get("gp_improve") is not None:
        imp = p.get("margin_improve", p.get("gp_improve"))
        steps.append(f"**利润率改善**：毛利率/净利率环比上升 ≥ **{_pct(imp)}**")
    if p.get("margin_min") is not None:
        steps.append(f"**利润率水平**：毛利率（或规则指定利润率）≥ **{_pct(p['margin_min'])}**")
    if p.get("np_min") is not None:
        steps.append(f"**净利率过滤**：净利率 ≥ **{_pct(p['np_min'])}**")
    if p.get("np_improve") is not None:
        steps.append(f"**净利率改善**：环比上升 ≥ **{_pct(p['np_improve'])}**")

    if p.get("growth_min") is not None:
        steps.append(f"**成长闸门**：净利/营收同比 ≥ **{_pct(p['growth_min'])}**")
    if p.get("growth_accel") is not None or p.get("accel_min") is not None:
        acc = p.get("growth_accel", p.get("accel_min"))
        steps.append(f"**增速加速**：同比相对上期再抬升 ≥ **{_pct(acc)}**")
    if p.get("lead_min") is not None:
        steps.append(f"**归属领先**：YOYPNI − YOYNI ≥ **{_pct(p['lead_min'])}**")

    if p.get("yoy_min") is not None or p.get("qoq_min") is not None:
        bits = []
        if p.get("yoy_min") is not None:
            bits.append(f"同比 ≥ {_pct(p['yoy_min'])}")
        if p.get("qoq_min") is not None:
            bits.append(f"环比 ≥ {_pct(p['qoq_min'])}")
        steps.append("**合同负债/预收款扩张**：" + " 或 ".join(bits) + "（新准则合同负债与旧准则预收款合并口径）")
    if p.get("cl_rev_min") is not None:
        steps.append(
            f"**预收强度**：合同负债 / 营收 ≥ **{_pct(p['cl_rev_min'])}**，"
            f"且强度环比升幅 ≥ **{_pct(p.get('intensity_improve') or 0.08)}**（过滤非预收型噪声）"
        )
    if p.get("asset_yoy_max") is not None:
        steps.append(f"**轻资产约束**：总资产同比 ≤ **{_pct(p['asset_yoy_max'])}**（或缺失视为通过）")

    sig_name = getattr(meta.get("signal"), "__name__", "") or ""
    if p.get("gp_consec") or sig_name == "signal_gp_consec_break":
        steps.append("**连续改善**：毛利率连续两期环比上升（非单季脉冲）")
    if sig_name == "signal_demand_pricing_break":
        steps.append("**双确认**：合同负债扩张热窗 ∩ 毛利率扩张热窗（需求 × 定价）")
    if sig_name == "signal_cl_intensity_break" and p.get("cl_rev_min") is None:
        steps.append("**预收强度**：合同负债占营收达到门槛且强度上升")
    if sig_name == "signal_rev_qoq_break":
        steps.append("**营收环比**：主营业务收入相对上一披露期上升（非净利代理）")
    if sig_name == "signal_parent_lead_break":
        steps.append("**归属质量**：母公司净利同比领先整体净利同比")
    if sig_name == "signal_asset_light_cl_break":
        steps.append("**结构**：轻资产扩张约束下的合同负债/预收款扩张")

    if p.get("funda_lag") is not None:
        steps.append(f"**财务热窗**：上述财务事件发生后的 **{_num(p['funda_lag'])}** 个交易日内才允许技术信号")

    # —— 技术图形 ——
    entry = str(p.get("entry") or "")
    if entry == "base_break" or p.get("amp_max") is not None and entry == "base_break":
        steps.append(
            f"**图形·横盘突破**：近 `{p.get('base_window') or 60}` 日振幅 ≤ **{_pct(p.get('amp_max') or 0.24)}**，"
            f"收盘突破箱体上沿，且站上均线"
        )
    elif entry == "pullback":
        steps.append(
            f"**图形·趋势回踩**：MA60 上行；近 20 日回撤 ≥ **{_pct(p.get('dd_need') or 0.03)}**；"
            f"收盘重新站上 MA20 且仍在 MA60 上方"
        )
    elif entry == "reclaim":
        ma = "MA60" if int(p.get("ma_days") or 20) >= 60 else "MA20"
        steps.append(f"**图形·回踩确认**：收盘价上穿 **{ma}**（昨日在下、今日站上）")
    else:
        brk = int(p.get("break_days") or 60)
        ma_days = int(p.get("ma_days") or 20)
        ma = f"MA{ma_days}" if ma_days in (20, 60, 120) else "MA20"
        if p.get("amp_max") is not None:
            steps.append(
                f"**图形·收窄后突破**：振幅 ≤ {_pct(p['amp_max'])} 的横盘背景下，"
                f"收盘 ≥ 昨日起算 **{brk}** 日高，且 > {ma}"
            )
        else:
            steps.append(f"**图形·突破确认**：收盘 ≥ 昨日起算 **{brk}** 日最高价，且收盘 > **{ma}**")

    if p.get("dd_need") is not None and entry != "pullback":
        steps.append(f"**回撤过滤**：近 20 日回撤 ≤ **−{_pct(abs(float(p['dd_need'])))}**（避免追高）")
    if p.get("ret20_max") is not None:
        steps.append(f"**动量不过热**：近 20 日涨幅 ≤ **{_pct(p['ret20_max'])}**")
    if p.get("amt_dry_ratio") is not None:
        steps.append(f"**缩量背景**：前一日成交额 ≤ 20 日均量的 **{_pct(p['amt_dry_ratio'])}**")
    if p.get("mom_min") is not None:
        steps.append(f"**动量下限**：动量指标 ≥ **{_pct(p['mom_min'])}**")

    max_pos = p.get("max_positions") or 8
    steps.append(f"**组合约束**：最多同时持有 **{_num(max_pos)}** 只，等权；有空位才开新仓")

    # 出场
    exits: List[str] = []
    if p.get("take_profit") is not None:
        exits.append(f"固定止盈 +**{_pct(p['take_profit'])}**")
    if p.get("trail_stop") is not None:
        exits.append(f"移动止盈回撤 **{_pct(p['trail_stop'])}**")
    if p.get("stop_loss") is not None:
        exits.append(f"止损 **−{_pct(abs(float(p['stop_loss'])))}**")
    if p.get("hold_days") is not None:
        exits.append(f"持有满 **{_num(p['hold_days'])}** 个交易日")
    if exits:
        steps.append("**出场（任一触发）**：" + "；".join(exits))

    desc = (meta.get("description") or "").strip()
    if desc and len(steps) <= 3:
        steps.insert(1, f"**核心逻辑**：{desc}")
    return steps


def _parse_pct_cell(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    raw = str(v).strip()
    has_pct = "%" in raw
    s = raw.replace("%", "").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    # "1.50%" → 0.015；无百分号且 |x|>1 视为已是百分数点
    if has_pct:
        return x / 100.0
    if abs(x) > 1.0:
        return x / 100.0
    return x


def pick_trade_example(factor_id: str, data_dir: Path) -> Optional[Dict[str, Any]]:
    """从 trade_history 挑一笔盈利腿作案例。"""
    path = data_dir / f"{factor_id}_trade_history.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return None
    if df.empty or "action" not in df.columns:
        return None
    exits = df[df["action"].astype(str) == "清仓"].copy()
    if exits.empty:
        return None
    exits["_pnl"] = exits.get("nav_pnl", pd.Series(dtype=object)).map(_parse_pct_cell)
    exits = exits.dropna(subset=["_pnl"])
    if exits.empty:
        return None

    def _leg_ret_from_note(note: str, sell_px: Any) -> Optional[float]:
        m2 = re.search(r"成本价\s*([0-9.]+)", str(note or ""))
        if not m2:
            return None
        try:
            cost = float(m2.group(1))
            px = float(sell_px)
        except (TypeError, ValueError):
            return None
        if cost <= 0:
            return None
        return px / cost - 1.0

    exits["_leg"] = [
        _leg_ret_from_note(r.get("note"), r.get("price")) for _, r in exits.iterrows()
    ]
    # 优先：组合贡献为正，且单腿涨跌在约 5%～60%（教学友好，避开极端妖腿）
    pos = exits[exits["_pnl"] > 0.002].copy()
    if not pos.empty:
        nice = pos[pos["_leg"].map(lambda x: x is not None and 0.05 <= float(x) <= 0.60)]
        pool = nice if not nice.empty else pos
        row = pool.sort_values("_pnl", ascending=False).iloc[0]
    else:
        row = exits.sort_values("_pnl", ascending=False).iloc[0]
    code = str(row.get("code") or "")
    note = str(row.get("note") or "")
    # 从 note 解析买入日与成本：hold_end；买入2019-08-30 成本价18.23
    buy_date = None
    cost = None
    m = re.search(r"买入(\d{4}-\d{2}-\d{2})", note)
    if m:
        buy_date = m.group(1)
    m2 = re.search(r"成本价\s*([0-9.]+)", note)
    if m2:
        try:
            cost = float(m2.group(1))
        except ValueError:
            cost = None
    sell_date = str(row.get("date") or "")
    sell_px = row.get("price")
    try:
        sell_px_f = float(sell_px) if sell_px is not None and str(sell_px) != "nan" else None
    except (TypeError, ValueError):
        sell_px_f = None
    ret = None
    if cost and sell_px_f and cost > 0:
        ret = sell_px_f / cost - 1.0
    # 开仓 note
    open_note = ""
    if buy_date and code:
        opens = df[(df["action"].astype(str) == "开仓") & (df["code"].astype(str) == code)]
        opens = opens[opens["date"].astype(str) == buy_date]
        if not opens.empty:
            open_note = str(opens.iloc[0].get("note") or "")
            if cost is None:
                try:
                    cost = float(opens.iloc[0].get("price"))
                except (TypeError, ValueError):
                    pass
    name = _CODE_NAMES.get(code, "")
    return {
        "code": code,
        "name": name,
        "buy_date": buy_date,
        "sell_date": sell_date,
        "cost": cost,
        "sell_price": sell_px_f,
        "leg_return": ret,
        "nav_pnl": float(row["_pnl"]),
        "exit_note": note,
        "open_note": open_note,
    }


def load_backtest_metrics(factor_id: str, data_dir: Path) -> Optional[Dict[str, Any]]:
    for name in (f"{factor_id}_summary.json", f"{factor_id}_backtest.json"):
        path = data_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and "sharpe" in data:
            return data
        if isinstance(data, dict) and isinstance(data.get("metrics"), dict):
            return data["metrics"]
    # 有些产物是 {logic: metrics}
    path = data_dir / f"{factor_id}_backtest.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and "sharpe" in v:
                        return v
        except Exception:  # noqa: BLE001
            pass
    return None


def render_guide_markdown(
    factor_id: str,
    meta: Dict[str, Any],
    *,
    data_dir: Path,
    include_run: bool = True,
) -> str:
    """生成完整用户说明正文（含选股步骤与案例）。"""
    name = str(meta.get("name") or factor_id)
    desc = (meta.get("description") or "").strip()
    params = dict(meta.get("params") or {})
    tags = meta.get("tags") or []

    overview = variant_overview(meta)
    lines: List[str] = [f"# {name}（{factor_id}）", ""]
    if overview:
        lines += [overview, ""]
    if desc and desc.rstrip("。") not in overview:
        lines += [f"备注：{desc}", ""]
    if tags:
        lines.append("标签：" + " · ".join(f"`{t}`" for t in tags))
        lines.append("")

    lines += ["## 怎么选股（逐步）", ""]
    for i, step in enumerate(selection_steps(params, meta), 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    sig = meta.get("signal")
    sig_name = getattr(sig, "__name__", None) or ""
    if sig_name:
        lines.append(f"信号实现：`{sig_name}`（`app/services/factors/signal_specs.py`）。")
        lines.append("")

    ex = pick_trade_example(factor_id, data_dir)
    if ex:
        title = f"{ex['code']}" + (f" {ex['name']}" if ex.get("name") else "")
        lines += ["## 举例：回测里真实成交的一腿", ""]
        lines.append(f"来源：`data/factors/{factor_id}_trade_history.csv`")
        lines.append("")
        lines.append("| 项目 | 内容 |")
        lines.append("|---|---|")
        lines.append(f"| 标的 | **{title}** |")
        if ex.get("buy_date"):
            cost_s = f"，约 {ex['cost']:.4g} 元" if ex.get("cost") else ""
            lines.append(f"| 开仓 | {ex['buy_date']}{cost_s} |")
        if ex.get("sell_date"):
            px_s = f"，约 {ex['sell_price']:.4g} 元" if ex.get("sell_price") else ""
            lines.append(f"| 清仓 | {ex['sell_date']}{px_s} |")
        if ex.get("leg_return") is not None:
            lines.append(f"| 单腿涨跌 | **{_pct(ex['leg_return'])}** |")
        lines.append(f"| 当日组合贡献 | NAV {_pct(ex['nav_pnl'])} |")
        if ex.get("exit_note"):
            lines.append(f"| 出场备注 | {ex['exit_note']} |")
        lines.append("")
        if ex.get("open_note"):
            lines.append(f"**开仓信号备注**：{ex['open_note']}")
            lines.append("")
        lines.append(
            "解读：开仓日报价满足「财务闸门 + 技术图形」；清仓由止盈/止损/到期之一触发。"
            "案例用于理解规则，不构成推荐。"
        )
        lines.append("")

    metrics = load_backtest_metrics(factor_id, data_dir)
    if metrics:
        lines += ["## 全量回测（摘要）", "", "| 指标 | 值 |", "|---|---|"]
        mapping = [
            ("sharpe", "Sharpe", lambda v: f"**{float(v):.4f}**"),
            ("total_return", "总收益", lambda v: _pct(v)),
            ("annual_return", "年化", lambda v: _pct(v)),
            ("max_drawdown", "最大回撤", lambda v: _pct(v)),
            ("n_legs_accepted", "成交腿数", lambda v: str(int(v))),
            ("volatility", "波动", lambda v: _pct(v)),
        ]
        for key, label, fmt in mapping:
            if metrics.get(key) is not None:
                try:
                    lines.append(f"| {label} | {fmt(metrics[key])} |")
                except Exception:  # noqa: BLE001
                    lines.append(f"| {label} | {metrics[key]} |")
        if metrics.get("start") and metrics.get("end"):
            lines.append(f"| 区间 | {metrics['start']} → {metrics['end']} |")
        lines.append("| 成本 | 佣金 0.0001 + 卖出印花税 0.001（默认） |")
        lines.append("")

    if include_run:
        lines += [
            "## 怎么跑",
            "",
            "```bash",
            f"python scripts/run_new_factors.py --only {factor_id} --limit 40",
            f"python scripts/run_new_factors.py --only {factor_id} --limit 0",
            "```",
            "",
            f"产物：`data/factors/{factor_id}_*`",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"
