"""结构类信号大批量网格 · Round2（时间加权 + 去重）。

续挖：在 R1 成功族附近换新刻度（应收/费用/合同负债/存货/毛净/ROA…），
刻意避开已入库 #204–#219 与 R1 指纹；刚删 pad 槽可再挖相近变体。

- 目标：≥80–100 组配置 × HS300/CSI500/CSI1000
- 主分 = 0.2×Sh(2018–21)+0.3×Sh(2022–23)+0.5×Sh(2024+)；近2年崩 → 降权/剔除
- 去重：Mongo + 锚点 + mine_* 指纹；不写 Mongo
- 产物：data/factors/mine_struct_mass_round2/
- 静态成分有幸存者偏差（非 PIT）；腾讯 qfq；BaoStock 禁用

用法:
  .venv\\Scripts\\python.exe scripts/mine_struct_mass_round2.py --skip-build
  .venv\\Scripts\\python.exe scripts/mine_struct_mass_round2.py --universes hs300 --skip-build
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.services.factors import ashare_fin_db as fin_db  # noqa: E402
from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors.runner import collect_legs, prepare_shared_panel  # noqa: E402
from mine_factor_dedup import DedupIndex, build_inventory, write_inventory_markdown  # noqa: E402

OUT_ROOT = ROOT / "data" / "factors" / "mine_struct_mass_round2"
START = "2018-01-01"
MIN_ACCEPTED_LEGS = 25
TOP_N = 12
RECENT2Y_CUT = "2024-08-01"

SEGMENTS: List[Tuple[str, str, Optional[str], float]] = [
    ("y2018_2021", "2018-01-01", "2021-12-31", 0.20),
    ("y2022_2023", "2022-01-01", "2023-12-31", 0.30),
    ("y2024_now", "2024-01-01", None, 0.50),
]

UNIVERSES = ("hs300", "csi500", "csi1000")

BENCH = {
    "hs300": "sh.000300",
    "csi500": "sh.000905",
    "csi1000": "sh.000852",
}

SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame]
# cfg_id, family, fn, extras, need_profit, need_growth, need_fin_db, need_balance
GridRow = Tuple[str, str, SignalFn, Dict[str, Any], bool, bool, bool, bool]


def _base(universe: str) -> Dict[str, Any]:
    return {
        "universe": universe,
        "exclude_st": True,
        "price_start": "2016-01-01",
        "max_positions": 8,
        "commission_rate": 0.0001,
        "stamp_tax_sell": 0.001,
        "request_interval_sec": 0.05,
        "bench_code": BENCH.get(universe, "sh.000300"),
        "_cache_dir": str(kit.shared_cache_dir()),
    }


def _exit(
    hold: int,
    sl: float = 0.12,
    tp: float = 0.30,
    lag: int = 28,
    brk: int = 60,
    entry: str = "break",
    **more: Any,
) -> Dict[str, Any]:
    return {
        "funda_lag": lag,
        "break_days": brk,
        "hold_days": hold,
        "stop_loss": sl,
        "take_profit": tp,
        "entry": entry,
        **more,
    }


def _add(
    rows: List[GridRow],
    prefix: str,
    family: str,
    fn: SignalFn,
    tag: str,
    extra: Dict[str, Any],
    *,
    need_profit: bool = True,
    need_growth: bool = False,
    need_fin_db: bool = True,
    need_balance: bool = False,
) -> None:
    rows.append(
        (
            f"{prefix}__{tag}",
            family,
            fn,
            extra,
            need_profit,
            need_growth,
            need_fin_db,
            need_balance,
        )
    )


def _grid() -> List[GridRow]:
    """Round2 新刻度：在 R1 强族附近换参数，避开已入库指纹。"""
    rows: List[GridRow] = []

    # ========== 1) 合同负债 YoY 二阶（新刻度） ==========
    for tag, extra in [
        ("clacc05_y07_brk52_h36", _exit(36, tp=0.27, lag=24, brk=52, cl_accel=0.05, yoy_min=0.07)),
        ("clacc09_y11_brk60_h42", _exit(42, tp=0.30, lag=28, brk=60, cl_accel=0.09, yoy_min=0.11, np_min=0.04)),
        ("clacc12_y15_brk70_h46", _exit(46, tp=0.33, lag=26, brk=70, cl_accel=0.12, yoy_min=0.15, np_min=0.04)),
        ("clacc15_y20_brk78_h50", _exit(50, tp=0.35, lag=30, brk=78, cl_accel=0.15, yoy_min=0.20, roe_min=0.06)),
        ("clacc08_y10_pull_h40", _exit(40, tp=0.29, lag=27, brk=58, entry="pullback", cl_accel=0.08, yoy_min=0.10, dd_need=0.04)),
        ("clacc11_y13_base_h44", _exit(44, tp=0.31, lag=29, brk=72, entry="base_break", cl_accel=0.11, yoy_min=0.13, base_window=60, amp_max=0.20)),
        ("clacc07_y09_soft96_h41", _exit(41, tp=0.30, lag=25, brk=56, cl_accel=0.07, yoy_min=0.09, brk_soft=0.96)),
        ("clacc13_y17_brk82_h48", _exit(48, tp=0.34, lag=31, brk=82, cl_accel=0.13, yoy_min=0.17, np_min=0.05)),
    ]:
        _add(rows, "sm2_clacc", "cl_yoy_accel", sig.signal_cl_yoy_accel_break, tag, extra)

    # ========== 2) 毛利×营收双击 ==========
    for tag, extra in [
        ("gp035_ry05_brk52_h38", _exit(38, tp=0.28, lag=24, brk=52, gp_improve=0.0035, rev_yoy_min=0.05, margin_min=0.12, np_min=0.03)),
        ("gp06_ry10_brk62_h44", _exit(44, tp=0.32, lag=28, brk=62, gp_improve=0.006, rev_yoy_min=0.10, margin_min=0.15, np_min=0.06)),
        ("gp075_ry13_brk70_h48", _exit(48, tp=0.34, lag=30, brk=70, gp_improve=0.0075, rev_yoy_min=0.13, margin_min=0.17, np_min=0.07)),
        ("gp05_ry08_racc04_h42", _exit(42, tp=0.30, lag=26, brk=56, gp_improve=0.005, rev_yoy_min=0.08, growth_accel=0.04, margin_min=0.13)),
        ("gp055_ry09_pull_h40", _exit(40, tp=0.29, lag=29, brk=60, entry="pullback", gp_improve=0.0055, rev_yoy_min=0.09, margin_min=0.14, dd_need=0.04)),
        ("gp04_ry06_base_h43", _exit(43, tp=0.31, lag=27, brk=72, entry="base_break", gp_improve=0.004, rev_yoy_min=0.06, margin_min=0.11, base_window=52, amp_max=0.24)),
        ("gp065_ry11_soft97_h45", _exit(45, tp=0.32, lag=25, brk=64, gp_improve=0.0065, rev_yoy_min=0.11, margin_min=0.15, brk_soft=0.97, roe_min=0.07)),
    ]:
        _add(rows, "sm2_gprv", "gp_rev_dual", sig.signal_gp_rev_dual_hit_break, tag, extra)

    # ========== 3) 费用率↓×营收加速 ==========
    for tag, extra in [
        ("ox03_racc035_g04_brk50_h36", _exit(36, tp=0.27, lag=24, brk=50, opex_improve=0.003, growth_accel=0.035, growth_min=0.04, opex_max=0.46)),
        ("ox055_racc06_g08_brk60_h42", _exit(42, tp=0.30, lag=28, brk=60, opex_improve=0.0055, growth_accel=0.06, growth_min=0.08, opex_max=0.39, np_min=0.04)),
        ("ox08_racc05_g06_brk72_h46", _exit(46, tp=0.33, lag=26, brk=72, opex_improve=0.008, growth_accel=0.05, growth_min=0.06, opex_max=0.34)),
        ("ox045_racc07_g09_brk54_h40", _exit(40, tp=0.29, lag=27, brk=54, opex_improve=0.0045, growth_accel=0.07, growth_min=0.09, opex_max=0.41, roe_min=0.06)),
        ("ox06_racc055_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", opex_improve=0.006, growth_accel=0.055, growth_min=0.07, dd_need=0.04)),
        ("ox07_racc065_base_h44", _exit(44, tp=0.31, lag=29, brk=74, entry="base_break", opex_improve=0.007, growth_accel=0.065, growth_min=0.085, opex_max=0.35, base_window=58, amp_max=0.21)),
        ("ox04_racc045_g05_brk78_h49", _exit(49, tp=0.32, lag=32, brk=78, opex_improve=0.004, growth_accel=0.045, growth_min=0.05, opex_max=0.44)),
        ("ox05_racc09_g11_brk48_h38", _exit(38, tp=0.28, lag=25, brk=48, opex_improve=0.005, growth_accel=0.09, growth_min=0.11, opex_max=0.40)),
    ]:
        _add(rows, "sm2_opex", "opex_down_rev", sig.signal_opex_down_rev_accel_break, tag, extra)

    # ========== 4) 存货强度 ==========
    for tag, extra in [
        ("inv012_ry03_brk50_h35", _exit(35, tp=0.27, lag=24, brk=50, inv_improve=0.012, growth_min=0.03, inv_max=1.00)),
        ("inv022_ry06_brk58_h40", _exit(40, tp=0.29, lag=28, brk=58, inv_improve=0.022, growth_min=0.06, inv_max=0.80, np_min=0.035)),
        ("inv03_ry08_brk68_h45", _exit(45, tp=0.31, lag=26, brk=68, inv_improve=0.03, growth_min=0.08, inv_max=0.68, np_min=0.045)),
        ("inv04_ry10_brk74_h48", _exit(48, tp=0.33, lag=30, brk=74, inv_improve=0.04, growth_min=0.10, inv_max=0.60, roe_min=0.07)),
        ("inv016_ry045_pull_h37", _exit(37, tp=0.28, lag=29, brk=56, entry="pullback", inv_improve=0.016, growth_min=0.045, dd_need=0.035)),
        ("inv026_ry075_base_h43", _exit(43, tp=0.30, lag=27, brk=70, entry="base_break", inv_improve=0.026, growth_min=0.075, inv_max=0.72, base_window=52, amp_max=0.23)),
    ]:
        _add(rows, "sm2_inv", "inv_delever_rev", sig.signal_inv_delever_rev_break, tag, extra)

    # ========== 5) 应收强度 ==========
    for tag, extra in [
        ("ar01_ry03_brk50_h35", _exit(35, tp=0.27, lag=24, brk=50, ar_improve=0.01, growth_min=0.03, ar_max=0.65)),
        ("ar015_ry055_brk58_h40", _exit(40, tp=0.29, lag=28, brk=58, ar_improve=0.015, growth_min=0.055, ar_max=0.52, np_min=0.035)),
        ("ar022_ry08_brk68_h45", _exit(45, tp=0.32, lag=26, brk=68, ar_improve=0.022, growth_min=0.08, ar_max=0.42, np_min=0.045)),
        ("ar028_ry10_brk76_h49", _exit(49, tp=0.34, lag=30, brk=76, ar_improve=0.028, growth_min=0.10, ar_max=0.36, roe_min=0.08)),
        ("ar013_ry045_pull_h38", _exit(38, tp=0.28, lag=29, brk=56, entry="pullback", ar_improve=0.013, growth_min=0.045, dd_need=0.04)),
        ("ar019_ry07_base_h44", _exit(44, tp=0.31, lag=27, brk=72, entry="base_break", ar_improve=0.019, growth_min=0.07, ar_max=0.48, base_window=58, amp_max=0.20)),
        ("ar017_ry065_brk54_h41_roe065", _exit(41, tp=0.30, lag=25, brk=54, ar_improve=0.017, growth_min=0.065, ar_max=0.50, roe_min=0.065)),
    ]:
        _add(rows, "sm2_ar", "ar_tighten_rev", sig.signal_ar_tighten_rev_break, tag, extra)

    # ========== 6) 毛利↑×费用率↓ ==========
    for tag, extra in [
        ("gpo_gp035_ox035_m12_h38", _exit(38, tp=0.28, lag=25, brk=54, gp_improve=0.0035, opex_improve=0.0035, margin_min=0.12, opex_max=0.44)),
        ("gpo_gp05_ox055_m14_h42", _exit(42, tp=0.30, lag=28, brk=62, gp_improve=0.005, opex_improve=0.0055, margin_min=0.14, opex_max=0.38, np_min=0.04)),
        ("gpo_gp065_ox06_m16_h46", _exit(46, tp=0.33, lag=26, brk=70, gp_improve=0.0065, opex_improve=0.006, margin_min=0.16, opex_max=0.33, roe_min=0.075)),
        ("gpo_gp045_ox05_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", gp_improve=0.0045, opex_improve=0.005, margin_min=0.13, dd_need=0.035)),
        ("gpo_gp06_ox07_base_h43", _exit(43, tp=0.31, lag=29, brk=72, entry="base_break", gp_improve=0.006, opex_improve=0.007, margin_min=0.15, base_window=52, amp_max=0.22)),
        ("gpo_gp05_ox045_brk50_h40", _exit(40, tp=0.29, lag=24, brk=50, gp_improve=0.005, opex_improve=0.0045, margin_min=0.135, np_min=0.035)),
    ]:
        _add(rows, "sm2_gpopex", "gp_opex_dual", sig.signal_gp_opex_dual_break, tag, extra)

    # ========== 7) 应收+存货双改善 ==========
    for tag, extra in [
        ("ari_ar008_inv012_h38", _exit(38, tp=0.28, lag=25, brk=54, ar_improve=0.008, inv_improve=0.012, ar_max=0.58, inv_max=0.95, growth_min=0.025)),
        ("ari_ar012_inv018_h42", _exit(42, tp=0.30, lag=28, brk=62, ar_improve=0.012, inv_improve=0.018, ar_max=0.50, inv_max=0.78, growth_min=0.04)),
        ("ari_ar018_inv022_h46", _exit(46, tp=0.32, lag=26, brk=70, ar_improve=0.018, inv_improve=0.022, ar_max=0.44, inv_max=0.68, growth_min=0.055)),
        ("ari_ar01_inv016_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", ar_improve=0.01, inv_improve=0.016, dd_need=0.035, growth_min=0.035)),
        ("ari_ar014_inv02_base_h43", _exit(43, tp=0.31, lag=29, brk=72, entry="base_break", ar_improve=0.014, inv_improve=0.02, base_window=56, amp_max=0.22)),
        ("ari_ar016_inv024_h48", _exit(48, tp=0.33, lag=27, brk=74, ar_improve=0.016, inv_improve=0.024, ar_max=0.40, inv_max=0.66, growth_min=0.06, np_min=0.04)),
    ]:
        _add(rows, "sm2_arinv", "ar_inv_dual", sig.signal_ar_inv_dual_break, tag, extra)

    # ========== 8) ROE / ROA / 双击 ==========
    for tag, extra in [
        ("roe_imp003_r07_m12_h38", _exit(38, tp=0.28, lag=25, brk=54, roe_improve=0.003, roe_min=0.07, margin_min=0.12, np_min=0.04)),
        ("roe_imp005_r095_m15_h43", _exit(43, tp=0.31, lag=28, brk=62, roe_improve=0.005, roe_min=0.095, margin_min=0.15, np_min=0.055)),
        ("roe_imp0065_r11_brk70_h47", _exit(47, tp=0.33, lag=26, brk=70, roe_improve=0.0065, roe_min=0.11, margin_min=0.14, np_min=0.065)),
        ("roe_imp004_r085_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", roe_improve=0.004, roe_min=0.085, dd_need=0.035)),
        ("roe_imp0055_r09_base_h44", _exit(44, tp=0.31, lag=29, brk=72, entry="base_break", roe_improve=0.0055, roe_min=0.09, base_window=52, amp_max=0.23)),
    ]:
        _add(rows, "sm2_roe", "roe_struct", sig.signal_roe_struct_improve_break, tag, extra, need_fin_db=False)

    for tag, extra in [
        ("roa_imp0018_rm0035_h38", _exit(38, tp=0.28, lag=25, brk=54, roa_improve=0.0018, roa_min=0.0035, roe_min=0.065)),
        ("roa_imp0028_rm0055_h43", _exit(43, tp=0.31, lag=28, brk=62, roa_improve=0.0028, roa_min=0.0055, roe_min=0.085, np_min=0.035)),
        ("roa_imp0038_rm0075_h47", _exit(47, tp=0.33, lag=26, brk=70, roa_improve=0.0038, roa_min=0.0075, roe_min=0.095)),
        ("roa_imp0022_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", roa_improve=0.0022, roa_min=0.0045, dd_need=0.035)),
        ("roa_imp0032_base_h44", _exit(44, tp=0.31, lag=29, brk=72, entry="base_break", roa_improve=0.0032, roa_min=0.006, base_window=56, amp_max=0.21)),
    ]:
        _add(rows, "sm2_roa", "roa_improve", sig.signal_roa_improve_break, tag, extra)

    for tag, extra in [
        ("rr_r0025_a0012_r075_h38", _exit(38, tp=0.28, lag=25, brk=54, roe_improve=0.0025, roa_improve=0.0012, roe_min=0.075, roa_min=0.0035)),
        ("rr_r0045_a0022_r095_h44", _exit(44, tp=0.31, lag=28, brk=62, roe_improve=0.0045, roa_improve=0.0022, roe_min=0.095, roa_min=0.0055)),
        ("rr_r0055_a0028_r105_h48", _exit(48, tp=0.33, lag=26, brk=72, roe_improve=0.0055, roa_improve=0.0028, roe_min=0.105, roa_min=0.0065)),
        ("rr_r0035_a0016_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", roe_improve=0.0035, roa_improve=0.0016, dd_need=0.035)),
    ]:
        _add(rows, "sm2_rr", "roe_roa_sync", sig.signal_roe_roa_sync_break, tag, extra)

    # ========== 9) 杠杆 / CFO / 资产周转 ==========
    for tag, extra in [
        ("lev_imp018_max72_r065_h38", _exit(38, tp=0.28, lag=25, brk=54, lev_improve=0.018, lev_max=0.72, roe_min=0.065, np_min=0.035)),
        ("lev_imp028_max66_r085_h43", _exit(43, tp=0.31, lag=28, brk=62, lev_improve=0.028, lev_max=0.66, roe_min=0.085, np_min=0.045)),
        ("lev_imp038_max58_r10_h47", _exit(47, tp=0.33, lag=26, brk=70, lev_improve=0.038, lev_max=0.58, roe_min=0.10)),
        ("lev_imp022_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", lev_improve=0.022, lev_max=0.70, dd_need=0.035, roe_min=0.075)),
    ]:
        _add(rows, "sm2_lev", "lev_delever", sig.signal_lev_delever_quality_break, tag, extra)

    for tag, extra in [
        ("cfo_min075_h38", _exit(38, tp=0.28, lag=25, brk=54, cfo_min=0.75, np_min=0.035, roe_min=0.065)),
        ("cfo_min095_imp008_h43", _exit(43, tp=0.31, lag=28, brk=62, cfo_min=0.95, cfo_improve=0.08, np_min=0.045)),
        ("cfo_min115_imp012_h47", _exit(47, tp=0.33, lag=26, brk=70, cfo_min=1.15, cfo_improve=0.12, np_min=0.055, roe_min=0.085)),
        ("cfo_min085_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", cfo_min=0.85, dd_need=0.035, roe_min=0.075)),
    ]:
        _add(rows, "sm2_cfo", "cfo_quality", sig.signal_cfo_quality_break, tag, extra)

    for tag, extra in [
        ("at_imp008_min012_h38", _exit(38, tp=0.28, lag=25, brk=54, asset_turn_improve=0.008, asset_turn_min=0.12, roe_min=0.065)),
        ("at_imp014_min018_h43", _exit(43, tp=0.31, lag=28, brk=62, asset_turn_improve=0.014, asset_turn_min=0.18, roe_min=0.085)),
        ("at_imp018_min022_h47", _exit(47, tp=0.33, lag=26, brk=70, asset_turn_improve=0.018, asset_turn_min=0.22, roe_min=0.095)),
        ("at_imp01_pull_h39", _exit(39, tp=0.28, lag=30, brk=58, entry="pullback", asset_turn_improve=0.01, dd_need=0.035)),
    ]:
        _add(rows, "sm2_aturn", "asset_turn", sig.signal_asset_turn_up_break, tag, extra)

    # ========== 10) 需求定价 / 合同负债强度 ==========
    for tag, extra in [
        ("demand_m125_lag24_h38", _exit(38, tp=0.28, lag=24, brk=54, margin_min=0.125, margin_improve=0.0035, np_min=0.04, cl_rev_min=0.035)),
        ("demand_m145_lag28_h43", _exit(43, tp=0.31, lag=28, brk=62, margin_min=0.145, margin_improve=0.0045, np_min=0.055, cl_rev_min=0.055)),
        ("demand_m165_lag30_h47", _exit(47, tp=0.33, lag=30, brk=72, margin_min=0.165, margin_improve=0.0055, np_min=0.065, cl_rev_min=0.065)),
        ("demand_m135_pull_h40", _exit(40, tp=0.29, lag=29, brk=58, entry="pullback", margin_min=0.135, margin_improve=0.004, dd_need=0.04, cl_rev_min=0.045)),
        ("demand_m155_base_h44", _exit(44, tp=0.31, lag=27, brk=70, entry="base_break", margin_min=0.155, margin_improve=0.005, base_window=52, amp_max=0.22, cl_rev_min=0.05)),
    ]:
        _add(rows, "sm2_demand", "demand_pricing", sig.signal_demand_pricing_break, tag, extra, need_balance=True)

    for tag, extra in [
        ("cli_cr04_ii06_h38", _exit(38, tp=0.28, lag=25, brk=54, cl_rev_min=0.04, intensity_improve=0.06, np_min=0.04)),
        ("cli_cr06_ii09_h43", _exit(43, tp=0.31, lag=28, brk=62, cl_rev_min=0.06, intensity_improve=0.09, np_min=0.05)),
        ("cli_cr075_ii11_h47", _exit(47, tp=0.33, lag=26, brk=70, cl_rev_min=0.075, intensity_improve=0.11, np_min=0.045, roe_min=0.065)),
        ("cli_cr055_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", cl_rev_min=0.055, intensity_improve=0.08, dd_need=0.035)),
        ("cli_cr065_base_h44", _exit(44, tp=0.31, lag=29, brk=72, entry="base_break", cl_rev_min=0.065, intensity_improve=0.10, base_window=56, amp_max=0.20)),
    ]:
        _add(rows, "sm2_cli", "cl_intensity", sig.signal_cl_intensity_break, tag, extra, need_balance=True)

    # ========== 11) 毛净追赶 / 双升 / 连续毛利 ==========
    for tag, extra in [
        ("catch_lag24_h40", _exit(40, tp=0.29, lag=24, brk=54, margin_improve=0.0035, np_improve=0.0025, margin_min=0.12)),
        ("catch_lag28_h44", _exit(44, tp=0.31, lag=28, brk=64, margin_improve=0.0045, np_improve=0.0035, margin_min=0.14, np_min=0.04)),
        ("catch_lag32_h48_roe075", _exit(48, tp=0.33, lag=32, brk=72, margin_improve=0.0055, np_improve=0.0045, margin_min=0.15, roe_min=0.075)),
        ("catch_pull_h41", _exit(41, tp=0.29, lag=27, brk=58, entry="pullback", margin_improve=0.004, np_improve=0.003, dd_need=0.04)),
        ("catch_base_h45", _exit(45, tp=0.31, lag=29, brk=70, entry="base_break", margin_improve=0.005, np_improve=0.0035, base_window=54, amp_max=0.22)),
    ]:
        _add(rows, "sm2_catch", "gross_net_catchup", sig.signal_gross_net_catchup_break, tag, extra, need_fin_db=False)

    for tag, extra in [
        ("gnup_m135_h38", _exit(38, tp=0.28, lag=25, brk=54, margin_improve=0.0035, margin_min=0.135, np_improve=0.0025, np_min=0.04)),
        ("gnup_m155_h44", _exit(44, tp=0.31, lag=28, brk=64, margin_improve=0.0045, margin_min=0.155, np_improve=0.0035, np_min=0.055)),
        ("gnup_m17_h48", _exit(48, tp=0.33, lag=26, brk=72, margin_improve=0.0055, margin_min=0.17, np_improve=0.0045, np_min=0.065)),
        ("gnup_m145_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", margin_improve=0.004, margin_min=0.145, dd_need=0.035)),
    ]:
        _add(rows, "sm2_gnup", "gross_np_up", sig.signal_gross_np_up_break, tag, extra, need_fin_db=False)

    for tag, extra in [
        ("gpc_m135_imp0025_h38", _exit(38, tp=0.28, lag=25, brk=54, margin_improve=0.0025, margin_min=0.135, np_min=0.04)),
        ("gpc_m155_imp0035_h44", _exit(44, tp=0.31, lag=28, brk=64, margin_improve=0.0035, margin_min=0.155, np_min=0.055)),
        ("gpc_m165_imp0045_h48", _exit(48, tp=0.33, lag=26, brk=72, margin_improve=0.0045, margin_min=0.165, np_min=0.06, roe_min=0.075)),
        ("gpc_m145_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", margin_improve=0.003, margin_min=0.145, dd_need=0.035)),
    ]:
        _add(rows, "sm2_gpc", "gp_consec", sig.signal_gp_consec_break, tag, extra, need_fin_db=False)

    # ========== 12) NP regime / rev-roe / parent / roe accel ==========
    for tag, extra in [
        ("npr_n065_r065_h38", _exit(38, tp=0.28, lag=25, brk=54, margin_improve=0.0025, np_min=0.065, roe_min=0.065)),
        ("npr_n085_r085_h44", _exit(44, tp=0.31, lag=28, brk=64, margin_improve=0.0035, np_min=0.085, roe_min=0.085)),
        ("npr_n10_r095_h48", _exit(48, tp=0.33, lag=26, brk=70, margin_improve=0.0045, np_min=0.10, roe_min=0.095)),
        ("npr_n075_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", margin_improve=0.003, np_min=0.075, dd_need=0.035)),
    ]:
        _add(rows, "sm2_npr", "np_regime", sig.signal_np_regime_break, tag, extra, need_fin_db=False)

    for tag, extra in [
        ("rrs_ri0035_rm085_h38", _exit(38, tp=0.28, lag=25, brk=54, roe_improve=0.0035, roe_min=0.085, growth_min=0.05)),
        ("rrs_ri0045_rm095_h44", _exit(44, tp=0.31, lag=28, brk=64, roe_improve=0.0045, roe_min=0.095, growth_min=0.07)),
        ("rrs_ri0055_rm105_h48", _exit(48, tp=0.33, lag=26, brk=70, roe_improve=0.0055, roe_min=0.105, growth_min=0.09)),
        ("rrs_ri004_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", roe_improve=0.004, roe_min=0.09, dd_need=0.035, growth_min=0.06)),
    ]:
        _add(
            rows,
            "sm2_rrs",
            "rev_roe_sync",
            sig.signal_rev_roe_sync_break,
            tag,
            extra,
            need_growth=True,
            need_fin_db=False,
        )

    for tag, extra in [
        ("pl_lag24_h38", _exit(38, tp=0.28, lag=24, brk=54, roe_min=0.075, np_min=0.04, growth_min=0.07, lead_min=0.015)),
        ("pl_lag28_h44", _exit(44, tp=0.31, lag=28, brk=64, roe_min=0.095, np_min=0.055, growth_min=0.09, lead_min=0.025)),
        ("pl_lag30_h48", _exit(48, tp=0.33, lag=30, brk=72, roe_min=0.105, np_min=0.065, growth_min=0.11, lead_min=0.035)),
        ("pl_pull_h40", _exit(40, tp=0.29, lag=27, brk=58, entry="pullback", roe_min=0.085, dd_need=0.04, growth_min=0.075, lead_min=0.02)),
    ]:
        _add(
            rows,
            "sm2_pl",
            "parent_lead",
            sig.signal_parent_lead_break,
            tag,
            extra,
            need_growth=True,
            need_fin_db=False,
        )

    for tag, extra in [
        ("rae_imp0035_r075_h38", _exit(38, tp=0.28, lag=25, brk=54, roe_improve=0.0035, roe_min=0.075)),
        ("rae_imp0055_r095_h44", _exit(44, tp=0.31, lag=28, brk=64, roe_improve=0.0055, roe_min=0.095)),
        ("rae_imp0065_r105_h48", _exit(48, tp=0.33, lag=26, brk=70, roe_improve=0.0065, roe_min=0.105, np_min=0.045)),
        ("rae_imp0045_pull_h40", _exit(40, tp=0.29, lag=30, brk=58, entry="pullback", roe_improve=0.0045, roe_min=0.085, dd_need=0.035)),
    ]:
        _add(rows, "sm2_rae", "roe_accel", sig.signal_roe_accel_break, tag, extra, need_fin_db=False)

    return rows

def _slice_stats(daily: pd.DataFrame, start: str, end: Optional[str]) -> Dict[str, Any]:
    if daily is None or daily.empty or "date" not in daily.columns:
        return {"empty": True}
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    t0 = pd.Timestamp(start)
    t1 = pd.Timestamp(end) if end else d["date"].max()
    w = d[(d["date"] >= t0) & (d["date"] <= t1)]
    if w.empty or "equity" not in w.columns:
        return {"empty": True, "start": start, "end": str(end)}
    eq = pd.to_numeric(w["equity"], errors="coerce").dropna()
    if len(eq) < 5:
        return {"empty": True, "n": len(eq)}
    ret = eq.pct_change().dropna()
    if ret.empty:
        return {"empty": True}
    vol = float(ret.std())
    sharpe = float(ret.mean() / vol * (252**0.5)) if vol > 1e-12 else None
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    peak = eq.cummax()
    dd = float(((eq - peak) / peak.replace(0, pd.NA)).min())
    return {
        "empty": False,
        "start": str(w["date"].iloc[0].date()),
        "end": str(w["date"].iloc[-1].date()),
        "sharpe": sharpe,
        "total_return": total_return,
        "max_drawdown": dd,
        "n_bars": int(len(w)),
    }


def _time_weight_score(daily: pd.DataFrame) -> Dict[str, Any]:
    segs: Dict[str, Any] = {}
    tw = 0.0
    wsum = 0.0
    for label, a, b, w in SEGMENTS:
        st = _slice_stats(daily, a, b)
        segs[label] = st
        sh = st.get("sharpe")
        if sh is not None and not st.get("empty"):
            tw += float(sh) * w
            wsum += w
    tw_sharpe = (tw / wsum) if wsum > 0 else None
    recent2y = _slice_stats(daily, RECENT2Y_CUT, None)
    early = segs.get("y2018_2021") or {}
    mid = segs.get("y2022_2023") or {}
    late = segs.get("y2024_now") or {}
    flags: List[str] = []
    r2_ret = recent2y.get("total_return")
    r2_sh = recent2y.get("sharpe")
    early_sh = early.get("sharpe")
    if r2_ret is not None and float(r2_ret) < -0.20:
        flags.append("recent2y_big_loss")
    if r2_sh is not None and float(r2_sh) < -0.35:
        flags.append("recent2y_neg_sharpe")
    if early_sh is not None and float(early_sh) > 1.2 and (
        (r2_ret is not None and float(r2_ret) < -0.15)
        or (r2_sh is not None and float(r2_sh) < -0.2)
    ):
        flags.append("early_inflated_recent_poor")
    penalty = 0.0
    if "early_inflated_recent_poor" in flags:
        penalty += 0.50
    elif "recent2y_big_loss" in flags:
        penalty += 0.35
    elif "recent2y_neg_sharpe" in flags:
        penalty += 0.20
    tw_adj = (tw_sharpe - penalty) if tw_sharpe is not None else None
    return {
        "segments": segs,
        "tw_sharpe": tw_sharpe,
        "tw_score": tw_adj,
        "tw_penalty": penalty,
        "recent2y": recent2y,
        "late_sharpe": late.get("sharpe"),
        "late_return": late.get("total_return"),
        "mid_sharpe": mid.get("sharpe"),
        "early_sharpe": early.get("sharpe"),
        "tw_flags": flags,
    }


def _overfit_flags(summary: Dict[str, Any], tw: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    n = int(summary.get("n_legs_accepted") or 0)
    if n < MIN_ACCEPTED_LEGS:
        flags.append(f"few_legs<{MIN_ACCEPTED_LEGS}")
    if n > 0 and n < 40 and float(summary.get("total_return") or 0) > 8:
        flags.append("high_ret_few_legs")
    sharpe = summary.get("sharpe")
    if sharpe is not None and float(sharpe) > 2.5 and n < 40:
        flags.append("sus_sharpe_few_legs")
    flags.extend(tw.get("tw_flags") or [])
    return flags


def _eval_one(
    cfg_id: str,
    family: str,
    signal_fn: SignalFn,
    params: Dict[str, Any],
    panel: Dict[str, pd.DataFrame],
    bench: pd.DataFrame,
) -> Dict[str, Any]:
    t0 = time.time()
    legs = collect_legs(panel, signal_fn, params)
    daily, summary, accepted = kit.run_equal_weight_backtest(
        legs, params=params, bench_daily=bench, start=START
    )
    if not isinstance(summary, dict):
        summary = {"error": str(summary)}
    tw = (
        _time_weight_score(daily)
        if isinstance(daily, pd.DataFrame) and not daily.empty
        else {
            "tw_sharpe": None,
            "tw_score": None,
            "tw_penalty": 0.0,
            "recent2y": {"empty": True},
            "tw_flags": ["no_daily"],
            "segments": {},
        }
    )
    out = {
        "cfg_id": cfg_id,
        "family": family,
        "universe": params.get("universe"),
        "params": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "signal": getattr(signal_fn, "__name__", str(signal_fn)),
        "sharpe": summary.get("sharpe"),
        "total_return": summary.get("total_return"),
        "annual_return": summary.get("annual_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "n_legs_raw": summary.get("n_legs_raw", len(legs) if legs is not None else 0),
        "n_legs_accepted": summary.get(
            "n_legs_accepted", 0 if accepted is None else len(accepted)
        ),
        "avg_position": summary.get("avg_position"),
        "error": summary.get("error"),
        "elapsed_sec": round(time.time() - t0, 2),
        "tw_sharpe": tw.get("tw_sharpe"),
        "tw_score": tw.get("tw_score"),
        "tw_penalty": tw.get("tw_penalty"),
        "recent2y_sharpe": (tw.get("recent2y") or {}).get("sharpe"),
        "recent2y_return": (tw.get("recent2y") or {}).get("total_return"),
        "recent2y_max_dd": (tw.get("recent2y") or {}).get("max_drawdown"),
        "late_sharpe": tw.get("late_sharpe"),
        "late_return": tw.get("late_return"),
        "mid_sharpe": tw.get("mid_sharpe"),
        "early_sharpe": tw.get("early_sharpe"),
        "segments": tw.get("segments"),
        "tw_flags": tw.get("tw_flags") or [],
    }
    out["overfit_flags"] = _overfit_flags(out, tw)
    out["ok"] = out.get("error") is None and out.get("sharpe") is not None
    out["rejected"] = "early_inflated_recent_poor" in (out.get("overfit_flags") or [])
    return out


def build_universes(force: bool = False) -> Dict[str, Any]:
    cache = kit.shared_cache_dir()
    meta: Dict[str, Any] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "csindex_cons_xls_static",
        "survivor_bias_note": "静态「今天成分」有幸存者偏差；挖掘阶段先用静态，未用 PIT",
        "universes": {},
        "downloads": [],
    }
    for u in UNIVERSES:
        codes = kit.fetch_universe_codes(u, kit.RateLimiter(0.01), cache, force=force)
        daily = cache / "daily"
        have = sum(1 for c in codes if (daily / f"{c.replace('.', '_')}.parquet").exists())
        profit = cache / "profit"
        have_p = sum(1 for c in codes if (profit / f"{c.replace('.', '_')}.parquet").exists())
        meta["universes"][u] = {
            "n_codes": len(codes),
            "n_daily": have,
            "n_profit": have_p,
            "bench": BENCH[u],
        }
        print(f"[universe] {u}: n={len(codes)} daily={have} profit={have_p}", flush=True)
        if fin_db.db_available():
            stats = fin_db.export_profit_cache_from_fin_db(profit, codes=codes, only_missing=True)
            print(f"[profit-export] {u}: {stats}", flush=True)
            meta["downloads"].append({"kind": "profit_export_from_fin_db", "universe": u, "stats": stats})
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "universes_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def _rank_key(r: Dict[str, Any]) -> Tuple[float, float, float]:
    if not r.get("ok") or r.get("rejected"):
        return (-999.0, -999.0, -999.0)
    flags = r.get("overfit_flags") or []
    hard = [f for f in flags if f.startswith("few_legs") or f.startswith("sus_")]
    if hard:
        return (-500.0, float(r.get("tw_score") or -999), float(r.get("recent2y_sharpe") or -999))
    return (
        float(r.get("tw_score") if r.get("tw_score") is not None else -999),
        float(r.get("recent2y_sharpe") if r.get("recent2y_sharpe") is not None else -999),
        float(r.get("sharpe") or -999),
    )


def mine_universe(
    universe: str,
    grid: List[GridRow],
    dedup: Optional[DedupIndex] = None,
) -> Dict[str, Any]:
    print(f"\n======== mine struct_mass r2 {universe} ========", flush=True)
    base = _base(universe)
    need_growth = any(g[5] for g in grid)
    need_fin = any(g[6] for g in grid)
    need_bal = any(g[7] for g in grid)
    panel = prepare_shared_panel(
        base,
        need_profit=True,
        need_growth=need_growth,
        need_fin_db=need_fin,
        need_balance=need_bal,
        limit=0,
    )
    print(f"[panel] {universe} n={len(panel)} fin_db={need_fin} balance={need_bal}", flush=True)
    if panel:
        sample = next(iter(panel.values()))
        cols = [
            c
            for c in (
                "gpMargin",
                "npMargin",
                "roeAvg",
                "fin_rev_yoy",
                "fin_opex_ratio",
                "fin_inv_to_rev",
                "fin_ar_to_rev",
                "fin_lev",
                "fin_roa",
                "fin_asset_turn",
                "cfo_to_np",
                "contract_liab_yoy",
                "contract_liab_yoy_accel",
            )
            if c in sample.columns
        ]
        print(f"[panel-cols] sample has: {cols}", flush=True)

    cache = kit.shared_cache_dir()
    bench_code = BENCH[universe]
    bench_path = cache / "daily" / f"{bench_code.replace('.', '_')}.parquet"
    if not bench_path.exists():
        bench_path = cache / "daily" / "sh_000300.parquet"
    bench = pd.read_parquet(bench_path)
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")

    udir = OUT_ROOT / universe
    udir.mkdir(parents=True, exist_ok=True)
    ckpt_path = udir / "checkpoint.json"
    skipped: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    done_ids: set = set()
    if ckpt_path.exists():
        try:
            ck = json.loads(ckpt_path.read_text(encoding="utf-8"))
            results = list(ck.get("results") or [])
            skipped = list(ck.get("skipped") or [])
            done_ids = {r.get("cfg_id") for r in results if r.get("cfg_id")}
            done_ids |= {s.get("cfg_id") for s in skipped if s.get("cfg_id")}
            print(f"[resume] {universe} loaded checkpoint n_results={len(results)} n_skip={len(skipped)}", flush=True)
            if dedup is not None:
                for r in results:
                    if r.get("ok") and r.get("cfg_id"):
                        # 续跑时把已评估指纹加入去重，避免同宇宙重复
                        extra0 = {k: v for k, v in (r.get("params") or {}).items() if k != "universe"}
                        try:
                            fn0 = getattr(sig, str(r.get("signal") or ""), None)
                            if fn0 is not None:
                                dedup.add_seen(fn0, universe, {**extra0, "universe": universe}, factor_id=r["cfg_id"])
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            print(f"[resume] ignore bad checkpoint: {exc}", flush=True)
            results, skipped, done_ids = [], [], set()

    def _save_ckpt() -> None:
        ckpt_path.write_text(
            json.dumps(
                {
                    "universe": universe,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "n_results": len(results),
                    "n_skipped": len(skipped),
                    "results": results,
                    "skipped": skipped,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    for i, (cfg_id, family, fn, extra, _np, _ng, _nf, _nb) in enumerate(grid, 1):
        if cfg_id in done_ids:
            print(f"  [{i}/{len(grid)}] RESUME-SKIP {cfg_id}", flush=True)
            continue
        params = {**base, **extra, "bench_code": BENCH[universe]}
        params["_cache_dir"] = str(cache)
        if dedup is not None:
            skip, reason, hit = dedup.check(fn, universe, {**extra, "universe": universe})
            if skip:
                skipped.append(
                    {
                        "cfg_id": cfg_id,
                        "family": family,
                        "signal": getattr(fn, "__name__", str(fn)),
                        "reason": reason,
                        "hit_factor_id": (hit or {}).get("factor_id"),
                        "hit_source": (hit or {}).get("source"),
                    }
                )
                done_ids.add(cfg_id)
                print(f"  [{i}/{len(grid)}] SKIP {cfg_id}: {reason}", flush=True)
                if i % 5 == 0:
                    _save_ckpt()
                continue
        try:
            row = _eval_one(cfg_id, family, fn, params, panel, bench)
        except Exception as exc:  # noqa: BLE001
            row = {
                "cfg_id": cfg_id,
                "family": family,
                "universe": universe,
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "rejected": True,
                "traceback": traceback.format_exc()[-800:],
            }
        results.append(row)
        done_ids.add(cfg_id)
        if dedup is not None and row.get("ok"):
            dedup.add_seen(fn, universe, {**extra, "universe": universe}, factor_id=cfg_id)
        print(
            f"  [{i}/{len(grid)}] {cfg_id}: tw={row.get('tw_score')} "
            f"full_sh={row.get('sharpe')} r2y_sh={row.get('recent2y_sharpe')} "
            f"r2y_ret={row.get('recent2y_return')} legs={row.get('n_legs_accepted')} "
            f"flags={row.get('overfit_flags')} sec={row.get('elapsed_sec')}",
            flush=True,
        )
        if i % 3 == 0 or i == len(grid):
            _save_ckpt()
    _save_ckpt()

    ranked = sorted(results, key=_rank_key, reverse=True)
    ok_clean = [
        r
        for r in ranked
        if r.get("ok")
        and not r.get("rejected")
        and not any(
            str(f).startswith("few_legs") or str(f).startswith("sus_")
            for f in (r.get("overfit_flags") or [])
        )
    ]
    top = ok_clean[:TOP_N]
    if len(top) < TOP_N:
        extra_rows = [r for r in ranked if r.get("ok") and r not in top and not r.get("rejected")]
        top = (top + extra_rows)[:TOP_N]

    udir = OUT_ROOT / universe
    udir.mkdir(parents=True, exist_ok=True)
    payload = {
        "universe": universe,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_panel": len(panel),
        "n_cfgs_grid": len(grid),
        "n_cfgs": len(results),
        "n_skipped": len(skipped),
        "skipped": skipped,
        "min_accepted_legs": MIN_ACCEPTED_LEGS,
        "struct_口径": {
            "fin_opex_ratio": "(销售费用+管理费用)/营业收入",
            "fin_inv_to_rev": "存货/营业收入",
            "fin_ar_to_rev": "应收账款/营业收入",
            "fin_lev": "总负债/总资产",
            "fin_roa": "归母净利/总资产",
            "cfo_to_np": "经营现金流/归母净利",
            "fin_asset_turn": "营业收入/总资产",
            "contract_liab_yoy_accel": "合同负债 YoY 相邻报告差分",
        },
        "time_weight": {
            "segments": [
                {"label": a, "start": b, "end": c, "weight": d} for a, b, c, d in SEGMENTS
            ],
            "recent2y_cut": RECENT2Y_CUT,
            "primary_metric": "tw_score = weighted_segment_sharpe - penalty",
        },
        "survivor_bias_note": "静态成分；非 PIT",
        "top": top,
        "ranked_by_tw": [
            {
                k: r.get(k)
                for k in (
                    "cfg_id",
                    "family",
                    "tw_score",
                    "tw_sharpe",
                    "tw_penalty",
                    "sharpe",
                    "total_return",
                    "recent2y_sharpe",
                    "recent2y_return",
                    "late_sharpe",
                    "mid_sharpe",
                    "early_sharpe",
                    "n_legs_accepted",
                    "max_drawdown",
                    "overfit_flags",
                    "rejected",
                    "signal",
                )
            }
            for r in ranked
            if r.get("ok")
        ][:40],
        "all": results,
    }
    (udir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _write_universe_md(universe, payload)
    return payload


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "-"
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _write_universe_md(universe: str, payload: Dict[str, Any]) -> Path:
    lines = [
        f"# Struct Mass Round2 · {universe}",
        "",
        f"- 时间：{payload.get('built_at')}",
        f"- panel={payload.get('n_panel')} eval={payload.get('n_cfgs')} "
        f"skip={payload.get('n_skipped')} grid={payload.get('n_cfgs_grid')}",
        "- 主分：`tw_score` = 0.2*Sh(2018-21)+0.3*Sh(2022-23)+0.5*Sh(2024+) - penalty",
        f"- 近2年切：`{RECENT2Y_CUT}`~今",
        "",
        "## Top（按 tw_score）",
        "",
        "| # | cfg | family | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | legs | flags |",
        "|---|-----|--------|----------|---------|----------|--------|--------|------|-------|",
    ]
    for i, r in enumerate(payload.get("top") or [], 1):
        lines.append(
            f"| {i} | `{r.get('cfg_id')}` | {r.get('family')} | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
            f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
            f"{r.get('n_legs_accepted')} | {r.get('overfit_flags') or []} |"
        )
    lines.append("")
    path = OUT_ROOT / universe / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_round_summary(all_univ: Dict[str, Dict[str, Any]], univ_meta: Dict[str, Any]) -> Path:
    lines = [
        "# 结构类信号大批量挖掘 · Round2（时间加权 + 去重）",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 行情：腾讯前复权 `_shared/daily`；BaoStock 禁用",
        "- 成分：中证官网静态 xls（**幸存者偏差**；非 PIT）",
        "- 财务：本地 `1.0_A股财务数据库.db` → 派生费用率/应收存货强度/杠杆/ROA/现金流质量等",
        "- Mongo：未写入（先挖再选择性入库；下一号 ≥220；不覆盖 #166–#219）",
        "- 去重：`scripts/mine_factor_dedup.py`",
        "",
        "## 下载了什么",
        "",
        "- **未新下东财/akshare**：本轮派生字段均可由本地三大表计算",
        "- profit cache：仅 `export_profit_cache_from_fin_db(only_missing=True)` 补洞（若有）",
        f"- universes_meta.downloads：`{json.dumps(univ_meta.get('downloads') or [], ensure_ascii=False)[:500]}`",
        "",
        "## 结构 → 信号族",
        "",
        "| family | 结构含义 | signal |",
        "|--------|----------|--------|",
        "| cl_yoy_accel | 合同负债 YoY 二阶 | `signal_cl_yoy_accel_break` |",
        "| gp_rev_dual | 毛利↑ × 营收 | `signal_gp_rev_dual_hit_break` |",
        "| opex_down_rev | 费用率↓ × 营收加速 | `signal_opex_down_rev_accel_break` |",
        "| inv_delever_rev | 存货强度↓ × 营收 | `signal_inv_delever_rev_break` |",
        "| ar_tighten_rev | 应收强度↓ × 营收 | `signal_ar_tighten_rev_break` |",
        "| gp_opex_dual | 毛利↑ × 费用率↓ | `signal_gp_opex_dual_break` |",
        "| ar_inv_dual | 应收+存货双改善 | `signal_ar_inv_dual_break` |",
        "| roe_struct | ROE 结构改善 | `signal_roe_struct_improve_break` |",
        "| roa_improve | ROA 改善 | `signal_roa_improve_break` |",
        "| roe_roa_sync | ROE×ROA 双击 | `signal_roe_roa_sync_break` |",
        "| lev_delever | 杠杆下行+质量 | `signal_lev_delever_quality_break` |",
        "| cfo_quality | 现金流质量 | `signal_cfo_quality_break` |",
        "| asset_turn | 资产周转提升 | `signal_asset_turn_up_break` |",
        "| demand_pricing | 需求定价结构 | `signal_demand_pricing_break` |",
        "| cl_intensity | 合同负债强度 | `signal_cl_intensity_break` |",
        "| gross_net_catchup | 毛净追赶 | `signal_gross_net_catchup_break` |",
        "| gross_np_up | 毛净双升 | `signal_gross_np_up_break` |",
        "| gp_consec | 连续毛利改善 | `signal_gp_consec_break` |",
        "| np_regime | 净利 regime | `signal_np_regime_break` |",
        "| rev_roe_sync | 营收×ROE 同步 | `signal_rev_roe_sync_break` |",
        "| parent_lead | 归属净利领先 | `signal_parent_lead_break` |",
        "| roe_accel | ROE 加速 | `signal_roe_accel_break` |",
        "",
        "## 时间加权",
        "",
        "| 分段 | 区间 | 权重 |",
        "|------|------|------|",
        "| early | 2018-2021 | 0.20 |",
        "| mid | 2022-2023 | 0.30 |",
        "| late | 2024-今 | 0.50 |",
        "",
        f"- 近2年窗口：`{RECENT2Y_CUT}`~样本末",
        "- **主排序键**：`tw_score`",
        "",
        "## 各宇宙 Top",
        "",
    ]
    global_rows: List[Dict[str, Any]] = []
    n_grid = 0
    n_eval = 0
    n_skip = 0
    for u in UNIVERSES:
        p = all_univ.get(u) or {}
        n_grid = max(n_grid, int(p.get("n_cfgs_grid") or 0))
        n_eval += int(p.get("n_cfgs") or 0)
        n_skip += int(p.get("n_skipped") or 0)
        lines.append(f"### {u}")
        lines.append(
            f"- skip={p.get('n_skipped')} / grid={p.get('n_cfgs_grid')} / eval={p.get('n_cfgs')}"
        )
        lines.append(
            "| cfg | family | tw_score | full_sh | full_ret | r2y_sh | r2y_ret | late_sh | legs |"
        )
        lines.append(
            "|-----|--------|----------|---------|----------|--------|--------|---------|------|"
        )
        for r in p.get("top") or []:
            lines.append(
                f"| `{r.get('cfg_id')}` | {r.get('family')} | {_fmt(r.get('tw_score'))} | "
                f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('total_return'))} | "
                f"{_fmt(r.get('recent2y_sharpe'))} | {_fmt(r.get('recent2y_return'))} | "
                f"{_fmt(r.get('late_sharpe'))} | {r.get('n_legs_accepted')} |"
            )
            if r.get("ok") and not r.get("rejected"):
                global_rows.append({**r, "universe": u})
        lines.append("")

    global_rows = sorted(global_rows, key=_rank_key, reverse=True)
    # 全局：从各宇宙 ranked 再拼一遍（含非 top 但可用）
    for u in UNIVERSES:
        p = all_univ.get(u) or {}
        for r in p.get("all") or []:
            if not r.get("ok") or r.get("rejected"):
                continue
            flags = r.get("overfit_flags") or []
            if any(str(f).startswith("few_legs") or str(f).startswith("sus_") for f in flags):
                continue
            # 明显近2年崩：不进入库候选池
            r2 = r.get("recent2y_return")
            if r2 is not None and float(r2) < -0.25:
                continue
            if r2 is not None and float(r2) < -0.15 and (r.get("recent2y_sharpe") or 0) < -0.2:
                continue
            key = (u, r.get("cfg_id"))
            if any((x.get("universe"), x.get("cfg_id")) == key for x in global_rows):
                continue
            global_rows.append({**r, "universe": u})
    global_rows = sorted(global_rows, key=_rank_key, reverse=True)

    lines.extend(
        [
            f"## 规模",
            "",
            f"- 网格配置数：{n_grid}",
            f"- 实际评估（去重后）：{n_eval}（三宇宙合计）",
            f"- 去重跳过：{n_skip}",
            "",
            "## 全局 Top 候选（近2年不崩优先，未入库，已去重）",
            "",
            "| univ | cfg | family | tw_score | full_sh | r2y_sh | r2y_ret | legs |",
            "|------|-----|--------|----------|---------|--------|--------|------|",
        ]
    )
    for r in global_rows[:30]:
        lines.append(
            f"| {r.get('universe')} | `{r.get('cfg_id')}` | {r.get('family')} | {_fmt(r.get('tw_score'))} | "
            f"{_fmt(r.get('sharpe'))} | {_fmt(r.get('recent2y_sharpe'))} | "
            f"{_fmt(r.get('recent2y_return'))} | {r.get('n_legs_accepted')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 与 #166–#219 并行；本目录独立，不覆盖旧号",
            "- 入库前：`DedupIndex.check` + `max(序号)+1`（≥220）；目标一次挂 10–16 条",
            "- 成分：静态 xls **幸存者偏差**（非 PIT）",
            "",
        ]
    )
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    top_payload = [
        {
            k: r.get(k)
            for k in (
                "universe",
                "cfg_id",
                "family",
                "signal",
                "tw_score",
                "sharpe",
                "total_return",
                "recent2y_sharpe",
                "recent2y_return",
                "n_legs_accepted",
                "overfit_flags",
                "params",
            )
        }
        for r in global_rows[:40]
    ]
    (OUT_ROOT / "global_top.json").write_text(
        json.dumps(top_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universes", default="hs300,csi500,csi1000")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--force-build", action="store_true")
    ap.add_argument("--max-cfgs", type=int, default=0, help="调试用：截断网格前 N 条")
    ap.add_argument("--families", default="", help="逗号分隔 family 过滤")
    args = ap.parse_args()

    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (qfq local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    univs = [u.strip() for u in str(args.universes).split(",") if u.strip()]
    for u in univs:
        if u not in UNIVERSES:
            raise SystemExit(f"unknown universe: {u}")

    print("[dedup] building inventory...", flush=True)
    inv = build_inventory()
    (OUT_ROOT / "existing_inventory.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_inventory_markdown(inv, OUT_ROOT / "EXISTING_INVENTORY.md")
    dedup = DedupIndex(inv)

    univ_meta: Dict[str, Any] = {}
    if not args.skip_build:
        univ_meta = build_universes(force=args.force_build)
    elif (OUT_ROOT / "universes_meta.json").exists():
        univ_meta = json.loads((OUT_ROOT / "universes_meta.json").read_text(encoding="utf-8"))
    else:
        univ_meta = build_universes(force=False)

    grid = _grid()
    fam_filter = {x.strip() for x in str(args.families).split(",") if x.strip()}
    if fam_filter:
        grid = [g for g in grid if g[1] in fam_filter]
    if args.max_cfgs and args.max_cfgs > 0:
        grid = grid[: int(args.max_cfgs)]
    print(
        f"[grid] n={len(grid)} families={sorted({g[1] for g in grid})}",
        flush=True,
    )
    if len(grid) < 80 and not args.max_cfgs and not fam_filter:
        print(f"[warn] grid size {len(grid)} < 80 target", flush=True)

    all_univ: Dict[str, Dict[str, Any]] = {}
    for u in univs:
        all_univ[u] = mine_universe(u, grid, dedup=dedup)

    path = write_round_summary(all_univ, univ_meta)
    print(f"\n[done] summary -> {path}", flush=True)


if __name__ == "__main__":
    main()
