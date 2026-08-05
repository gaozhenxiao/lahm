"""通宵持续挖因子：分波次冒烟→全量→裁剪→同步，循环不停。

用法:
  python scripts/mine_overnight.py
  python scripts/mine_overnight.py --once   # 只跑一轮

原则：基本面为主，技术面做结构确认；不做纯量价。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "factors" / "mine_overnight.log"
STATE = ROOT / "data" / "factors" / "overnight_state.json"
KEEP_ALL = ROOT / "data" / "factors" / "overnight_keep.json"
PAUSE = ROOT / "data" / "factors" / "overnight_pause.json"
LOCK = ROOT / "data" / "factors" / "mine_overnight.lock"

# 波次：先不依赖 balance，再跑需要合同负债的
WAVES: list[dict] = [
    {
        "name": "wave7_hybrid_core",
        "ids": [
            "long_base_roe_break",
            "cheap_quality_base_break",
            "growth_trend_pullback",
            "margin_expand_ma60",
            "eps_accel_breakout",
            "pead_base_reclaim",
        ],
        "need_balance": False,
    },
    {
        "name": "wave8_hybrid_more",
        "ids": [
            "asset_light_trend",
            "dual_improve_breakout",
            "value_repair_reclaim",
            "quality_coil_break",
            "parent_lead_reclaim",
            "base_funda_breakout",
            "base_funda_reclaim",
        ],
        "need_balance": False,
    },
    {
        "name": "wave9_contract",
        "ids": [
            "contract_liab_expand",
            "contract_liab_base_break",
        ],
        "need_balance": True,
    },
    {
        "name": "wave10_funda_more",
        "ids": [
            "gross_expand_break",
            "rev_accel_base_break",
            "consec_improve_break",
            "pb_floor_quality_break",
            "growth_not_expensive_pullback",
        ],
        "need_balance": False,
    },
    {
        "name": "wave11_winner_variants",
        "ids": [
            "gross_expand_base_break",
            "dual_improve_reclaim",
            "eps_accel_base_break",
            "cheap_quality_reclaim",
            "gp_np_expand_break",
            "contract_liab_reclaim",
        ],
        "need_balance": False,
    },
    {
        "name": "wave12_top_neighbors",
        "ids": [
            "gp_np_expand_reclaim",
            "contract_liab_ma60",
            "gross_expand_ma60",
            "dual_improve_base_break",
            "gp_np_tight_break",
            "contract_liab_yoy_break",
        ],
        "need_balance": False,
    },
    {
        "name": "wave13_w12_variants",
        "ids": [
            "dual_improve_base_reclaim",
            "gp_np_tight_base",
            "contract_yoy_base_break",
            "dual_improve_ma60",
            "gp_np_tight_reclaim",
            "contract_yoy_reclaim",
        ],
        "need_balance": False,
    },
    {
        "name": "wave14_combo",
        "ids": [
            "gross_dual_stack_break",
            "dual_improve_long_base",
            "contract_reclaim_quality",
            "gp_expand_cheap_break",
            "eps_dual_confirm_break",
            "quality_base_dual",
        ],
        "need_balance": False,
    },
    {
        "name": "wave15_param_tilt",
        "ids": [
            "gross_expand_break_tight",
            "dual_improve_breakout_wide",
            "dual_improve_base_tight",
            "gp_np_expand_lag",
            "contract_liab_reclaim_strict",
            "eps_dual_confirm_base",
        ],
        "need_balance": False,
    },
    {
        "name": "wave16_winner_tilt",
        "ids": [
            "dual_improve_base_tight2",
            "gp_np_expand_lag_base",
            "dual_wide_base",
            "contract_strict_base",
            "gross_tight_base",
            "gross_dual_stack_tight",
        ],
        "need_balance": False,
    },
    {
        "name": "wave17_winner_neighbors",
        "ids": [
            "gross_dual_base",
            "gross_dual_base_tight",
            "dual_mid_base",
            "gross_expand_hold40",
            "gp_np_lag_hold35",
            "dual_tight_hold35",
        ],
        "need_balance": False,
    },
    {
        "name": "wave18_hold_tilt",
        "ids": [
            "dual_mid_hold40",
            "dual_mid_amp22",
            "gp_np_lag_hold45",
            "gp_np_lag_base_hold35",
            "gross_expand_hold50",
            "gross_dual_mid_base",
        ],
        "need_balance": False,
    },
    {
        "name": "wave19_hold_extend",
        "ids": [
            "gross_expand_hold60",
            "gross_expand_tight_hold40",
            "gross_expand_base_hold40",
            "dual_mid_hold50",
            "gp_np_lag_hold60",
            "dual_mid_reclaim",
        ],
        "need_balance": False,
    },
    {
        "name": "wave20_top_neighbors",
        "ids": [
            "gross_expand_hold55",
            "gross_expand_mid_hold50",
            "gross_expand_hold50_stop10",
            "dual_mid_hold45",
            "gp_np_lag_hold40",
            "dual_mid_amp18",
        ],
        "need_balance": False,
    },
    {
        "name": "wave21_fine_tilt",
        "ids": [
            "gross_expand_mid_hold55",
            "gross_expand_mid_hold45",
            "gross_expand_mid_stop10",
            "gross_expand_hold52",
            "gp_np_lag_hold42",
            "dual_mid_hold42",
        ],
        "need_balance": False,
    },
    {
        "name": "wave22_cross_tilt",
        "ids": [
            "gross_expand_hold53",
            "gross_expand_mid_hold48",
            "gross_expand_mid_lag20",
            "gross_expand_mid_m22",
            "gross_dual_mid_hold50",
            "gp_np_lag_stop10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave23_threshold_cross",
        "ids": [
            "gross_expand_imp007",
            "gross_expand_lag30",
            "gp_expand_cheap_hold50",
            "dual_break_hold50",
            "gp_np_mid_hold50",
            "gross_base_mid_hold50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave24_lag_neighbors",
        "ids": [
            "gross_expand_lag28",
            "gross_expand_lag32",
            "gross_expand_lag30_stop10",
            "gross_expand_lag30_hold55",
            "dual_break_mid_hold50",
            "gp_cheap_mid_hold50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave25_lag28_fine",
        "ids": [
            "gross_expand_lag27",
            "gross_expand_lag29",
            "gross_expand_lag28_hold55",
            "gross_expand_lag28_stop10",
            "gross_expand_lag28_hold52",
            "gp_cheap_lag28",
        ],
        "need_balance": False,
    },
    {
        "name": "wave26_hold52_migrate",
        "ids": [
            "dual_mid_hold52",
            "gp_np_lag_hold52",
            "gross_dual_stack_hold52",
            "quality_coil_hold50",
            "contract_yoy_hold50",
            "gross_expand_lag29_hold52",
        ],
        "need_balance": True,
    },
    {
        "name": "wave27_lag29_fine",
        "ids": [
            "gross_expand_lag29_hold51",
            "gross_expand_lag29_hold53",
            "gross_expand_lag28_hold51",
            "gross_expand_lag29_stop10",
            "dual_tight_hold52",
            "rev_accel_hold50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave28_hold51_peak",
        "ids": [
            "gross_expand_lag27_hold51",
            "gross_expand_lag28_hold51_stop10",
            "gross_expand_lag28_hold50_mid",
            "gross_expand_lag28_hold51_imp005",
            "dual_mid_hold51",
            "gp_np_lag_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave29_peak_cross",
        "ids": [
            "gross_expand_lag28_hold51_m18",
            "gross_expand_lag28_hold51_m22",
            "gp_cheap_lag28_hold51",
            "dual_tight_hold51",
            "gross_expand_ma60_hold50",
            "high_margin_break_hold50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave30_dual_np_tilt",
        "ids": [
            "dual_tight_hold50",
            "dual_tight_hold53",
            "dual_tight_amp16",
            "high_margin_break_hold51",
            "high_margin_break_m15",
            "gp_np_tight_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave31_gp_np_peak",
        "ids": [
            "gp_np_tight_lag28_hold51",
            "gp_np_tight_lag29_hold51",
            "gp_np_tight_hold52",
            "gp_np_tight_lag28_hold52",
            "dual_tight_amp16_hold52",
            "high_margin_m15_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave32_lag29_np_fine",
        "ids": [
            "gp_np_tight_lag30_hold51",
            "gp_np_tight_lag29_hold52",
            "gp_np_tight_lag29_hold50",
            "high_margin_m15_hold52",
            "high_margin_m18_hold51",
            "gp_cheap_lag29_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave33_diversify_hold",
        "ids": [
            "gp_np_tight_lag30_hold52",
            "gp_np_tight_lag31_hold51",
            "high_margin_m18_hold52",
            "consec_improve_lag28_hold51",
            "consec_improve_lag30_hold51",
            "gross_dual_stack_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave34_theme_hold51",
        "ids": [
            "quality_coil_hold51",
            "pb_floor_hold51",
            "eps_dual_hold51",
            "parent_lead_lag28_hold51",
            "roe_expand_hold51",
            "high_margin_m20_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave35_eps_roe_fine",
        "ids": [
            "eps_dual_hold52",
            "eps_dual_hold50",
            "eps_dual_accel08",
            "roe_expand_hold52",
            "roe_expand_r12_hold51",
            "high_margin_m20_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave36_gross_np_cross",
        "ids": [
            "eps_dual_lag28_hold51",
            "eps_dual_lag30_hold51",
            "gross_high_np_lag28_hold51",
            "gross_high_np_lag28_hold51_np10",
            "gross_high_np_lag30_hold51",
            "gross_high_np_m22_hold51",
        ],
        "need_balance": False,
    },
    {
        "name": "wave37_high_np_peak",
        "ids": [
            "gross_high_np_lag28_np09",
            "gross_high_np_lag28_np11",
            "gross_high_np_lag28_np12",
            "gross_high_np_lag29_np10",
            "gross_high_np_lag27_np10",
            "gross_high_np_lag28_np10_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave38_np_hold_cross",
        "ids": [
            "gross_high_np_np11_hold52",
            "gross_high_np_np10_hold53",
            "gross_high_np_np10_hold50",
            "gross_high_np_np11_hold53",
            "gross_high_np_np10_m18",
            "gross_high_np_np10_imp005",
        ],
        "need_balance": False,
    },
    {
        "name": "wave39_imp_m_fine",
        "ids": [
            "gross_high_np_np10_imp004",
            "gross_high_np_np10_imp0055",
            "gross_high_np_m18_imp005",
            "gross_high_np_np10_m19",
            "gross_high_np_np10_m17",
            "gross_high_np_imp005_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave40_stop_cross",
        "ids": [
            "gross_high_np_champ_stop10",
            "gross_high_np_champ_stop14",
            "gross_high_np_m17_imp0055",
            "gross_high_np_m17_imp005",
            "gross_high_np_imp0055_hold52",
            "gross_high_np_np10_imp0065",
        ],
        "need_balance": False,
    },
    {
        "name": "wave41_np_up_catchup",
        "ids": [
            "gross_np_up_lag28_hold51",
            "gross_np_up_lag28_np08",
            "gross_np_up_lag28_np10",
            "gross_np_up_imp005",
            "catchup_break_lag28",
            "catchup_break_lag28_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave42_np_up_peak",
        "ids": [
            "gross_np_up_np10_hold52",
            "gross_np_up_np10_hold50",
            "gross_np_up_np11",
            "gross_np_up_np09",
            "gross_np_up_np10_lag29",
            "gross_np_up_np10_nimp005",
        ],
        "need_balance": False,
    },
    {
        "name": "wave43_contract_dual_roe",
        "ids": [
            "contract_np_lag28_hold51",
            "contract_np_lag28_np10",
            "dual_lag28_hold51",
            "dual_lag28_np10",
            "roe_lag28_hold51",
            "roe_lag28_np10",
        ],
        "need_balance": True,
    },
    {
        "name": "wave44_dual_lag_peak",
        "ids": [
            "dual_lag28_hold52",
            "dual_lag28_hold50",
            "dual_lag28_np08",
            "dual_lag28_np11",
            "dual_lag29_hold51",
            "dual_lag28_tight",
        ],
        "need_balance": False,
    },
    {
        "name": "wave45_champ_tech",
        "ids": [
            "gross_high_np_ma60",
            "gross_high_np_ma60_cross",
            "gross_high_np_roe12",
            "gross_high_np_roe10",
            "gross_high_np_ma60_roe12",
            "gross_high_np_imp005_roe12",
        ],
        "need_balance": False,
    },
    {
        "name": "wave46_ma60_peak",
        "ids": [
            "gross_high_np_ma60_hold52",
            "gross_high_np_ma60_hold50",
            "gross_high_np_ma60_imp005",
            "gross_high_np_ma60_m17",
            "gross_high_np_ma60_np11",
            "gross_high_np_ma60_hold53",
        ],
        "need_balance": False,
    },
    {
        "name": "wave47_entry_variants",
        "ids": [
            "gross_high_np_reclaim",
            "gross_high_np_reclaim_ma60",
            "gross_high_np_either",
            "gross_high_np_amp22",
            "gross_high_np_pb30",
            "gross_high_np_reclaim_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave48_growth_filter",
        "ids": [
            "gross_high_np_g08",
            "gross_high_np_g12",
            "gross_high_np_g15",
            "gross_high_np_g08_hold52",
            "gross_high_np_g08_imp005",
            "gross_high_np_g08_m17",
        ],
        "need_balance": False,
    },
    {
        "name": "wave49_growth_accel",
        "ids": [
            "gross_high_np_g03",
            "gross_high_np_g05",
            "gross_high_np_g03_m17",
            "gross_high_np_gacc05",
            "gross_high_np_gacc08",
            "gross_high_np_gacc05_m17",
        ],
        "need_balance": False,
    },
    {
        "name": "wave50_nimp_pe",
        "ids": [
            "gross_high_np_nimp003",
            "gross_high_np_nimp005",
            "gross_high_np_nimp003_m17",
            "gross_high_np_nimp003_hold52",
            "gross_high_np_pe45",
            "gross_high_np_pe55",
        ],
        "need_balance": False,
    },
    {
        "name": "wave51_nimp_peak",
        "ids": [
            "gross_high_np_nimp002_m17",
            "gross_high_np_nimp004_m17",
            "gross_high_np_nimp003_m16",
            "gross_high_np_nimp003_m18",
            "gross_high_np_nimp003_m17_imp005",
            "gross_high_np_nimp003_m17_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave52_nimp_m16",
        "ids": [
            "gross_high_np_nimp003_m15",
            "gross_high_np_nimp002_m16",
            "gross_high_np_nimp003_m16_imp005",
            "gross_high_np_nimp003_m16_hold52",
            "gross_high_np_nimp003_m16_lag27",
            "gross_high_np_nimp003_m16_lag29",
        ],
        "need_balance": False,
    },
    {
        "name": "wave53_break_window",
        "ids": [
            "gross_high_np_brk40",
            "gross_high_np_brk50",
            "gross_high_np_brk80",
            "gross_high_np_m16_imp005_brk50",
            "gross_high_np_m16_imp005_brk40",
            "gross_high_np_champ_brk50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave54_brk80_peak",
        "ids": [
            "gross_high_np_brk70",
            "gross_high_np_brk90",
            "gross_high_np_brk100",
            "gross_high_np_brk80_hold52",
            "gross_high_np_brk80_imp005",
            "gross_high_np_brk80_m17",
        ],
        "need_balance": False,
    },
    {
        "name": "wave55_brk80_m17",
        "ids": [
            "gross_high_np_brk80_m16",
            "gross_high_np_brk80_m18",
            "gross_high_np_brk75_m17",
            "gross_high_np_brk85_m17",
            "gross_high_np_brk80_m17_imp005",
            "gross_high_np_brk80_m17_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave56_brk80_m17_cross",
        "ids": [
            "gross_high_np_brk80_m17_nimp003",
            "gross_high_np_brk80_m17_nimp002",
            "gross_high_np_brk80_m17_np09",
            "gross_high_np_brk80_m17_np11",
            "gross_high_np_brk80_m17_lag27",
            "gross_high_np_brk80_m17_lag29",
        ],
        "need_balance": False,
    },
    {
        "name": "wave57_eps_dual_brk",
        "ids": [
            "eps_dual_lag28_brk80",
            "eps_dual_lag28_brk60",
            "eps_dual_lag28_np10_brk80",
            "eps_dual_lag28_brk80_hold52",
            "eps_dual_lag28_accel08_brk80",
            "eps_dual_lag30_brk80",
        ],
        "need_balance": False,
    },
    {
        "name": "wave58_np_up_brk",
        "ids": [
            "gross_np_up_brk80",
            "gross_np_up_brk70",
            "gross_np_up_brk80_m17",
            "gross_np_up_brk80_hold52",
            "gross_np_up_brk80_imp005",
            "gross_np_up_brk80_nimp005",
        ],
        "need_balance": False,
    },
    {
        "name": "wave59_np_up_brk80_peak",
        "ids": [
            "gross_np_up_brk75",
            "gross_np_up_brk85",
            "gross_np_up_brk90",
            "gross_np_up_brk80_lag27",
            "gross_np_up_brk80_lag29",
            "gross_np_up_brk80_np09",
            "gross_np_up_brk80_np11",
        ],
        "need_balance": False,
    },
    {
        "name": "wave60_catchup_dual_brk",
        "ids": [
            "catchup_brk80",
            "catchup_brk70",
            "catchup_brk90",
            "catchup_brk80_gp22",
            "catchup_brk80_gap04",
            "dual_brk80_lag28",
        ],
        "need_balance": False,
    },
    {
        "name": "wave61_gross_expand_brk",
        "ids": [
            "gross_expand_brk80",
            "gross_expand_brk90",
            "gross_expand_brk70",
            "gross_expand_brk80_m17",
            "gross_expand_brk80_imp005",
            "roe_expand_brk80_np10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave62_gross_expand_m17",
        "ids": [
            "gross_expand_brk80_m16",
            "gross_expand_brk80_m18",
            "gross_expand_brk85_m17",
            "gross_expand_brk75_m17",
            "gross_expand_brk80_m17_imp005",
            "gross_expand_brk80_m17_lag29",
        ],
        "need_balance": False,
    },
    {
        "name": "wave63_expand_np_bridge",
        "ids": [
            "gross_expand_brk80_m17_np08",
            "gross_expand_brk80_m17_np10",
            "gross_expand_brk80_m17_np12",
            "gross_expand_brk80_np10",
            "gross_expand_brk60_m17_np10",
            "gross_expand_brk80_m17_np10_hold50",
        ],
        "need_balance": False,
    },
    {
        "name": "wave64_brk60_m17_np10",
        "ids": [
            "gross_expand_brk60_m16_np10",
            "gross_expand_brk60_m18_np10",
            "gross_expand_brk60_m17_np09",
            "gross_expand_brk60_m17_np11",
            "gross_expand_brk60_m17_np10_hold52",
            "gross_expand_brk60_m17_np10_imp005",
            "gross_expand_brk60_m17_np10_lag29",
        ],
        "need_balance": False,
    },
    {
        "name": "wave65_lag29_peak",
        "ids": [
            "gross_expand_brk60_m17_np10_lag27",
            "gross_expand_brk60_m17_np10_lag30",
            "gross_expand_brk60_m17_np10_lag31",
            "gross_expand_brk60_m16_np10_lag29",
            "gross_expand_brk60_m18_np10_lag29",
            "gross_expand_brk60_m17_np10_lag29_imp005",
            "gross_expand_brk60_m17_np11_lag29",
        ],
        "need_balance": False,
    },
    {
        "name": "wave66_champ_hold_highnp",
        "ids": [
            "gross_expand_brk60_m17_np10_lag29_hold52",
            "gross_expand_brk60_m17_np10_lag29_hold50",
            "gross_expand_brk60_m17_np10_lag29_stop10",
            "gross_expand_brk60_m19_np10_lag29",
            "gross_high_np_m17_lag29_np10",
            "gross_high_np_m18_lag29_np10",
            "gross_high_np_m17_lag30_np10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave67_near_champ_tech",
        "ids": [
            "gross_expand_brk60_m17_np10_lag29_ma60",
            "gross_expand_brk60_m17_np10_lag29_hold53",
            "gross_high_np_m17_lag30_np10_hold52",
            "gross_high_np_m16_lag30_np10",
            "gross_high_np_m17_lag30_imp005_np10",
            "gross_np_up_m17_lag29_np10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave68_entry_amp_diversify",
        "ids": [
            "gross_high_np_m17_lag29_reclaim",
            "gross_high_np_m17_lag29_either",
            "gross_high_np_m17_lag29_amp18",
            "gross_high_np_m17_lag29_amp22",
            "gross_expand_brk60_m17_np10_lag29_stop14",
            "dual_m17_lag29_np10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave69_nimp_contract",
        "ids": [
            "gross_expand_brk60_m17_np10_lag29_nimp002",
            "gross_expand_brk60_m17_np10_lag29_nimp003",
            "gross_expand_brk60_m17_np10_lag29_nimp005",
            "contract_np_lag29_np10",
            "contract_np_lag29_np08",
            "contract_np_lag29_yoy25",
        ],
        "need_balance": True,
    },
    {
        "name": "wave70_champ_micro",
        "ids": [
            "gross_expand_brk60_m175_np10_lag29",
            "gross_expand_brk60_m17_np095_lag29",
            "gross_expand_brk60_m17_np105_lag29",
            "gross_expand_brk60_m17_np10_lag29_imp0055",
            "gross_expand_brk60_m17_np10_lag29_imp0065",
            "gross_expand_brk60_m17_np10_lag29_stop13",
        ],
        "need_balance": False,
    },
    {
        "name": "wave71_brk_hold_micro",
        "ids": [
            "gross_expand_brk55_m17_np10_lag29",
            "gross_expand_brk65_m17_np10_lag29",
            "gross_expand_brk58_m17_np10_lag29",
            "gross_expand_brk62_m17_np10_lag29",
            "gross_expand_brk60_m17_np10_lag29_hold49",
            "gross_expand_brk60_m17_np10_lag29_hold54",
        ],
        "need_balance": False,
    },
    {
        "name": "wave72_champ_quality",
        "ids": [
            "gross_expand_champ_roe10",
            "gross_expand_champ_roe12",
            "gross_expand_champ_pe45",
            "gross_expand_champ_pe55",
            "gross_expand_champ_pb40",
            "gross_expand_champ_roe10_pe55",
        ],
        "need_balance": False,
    },
    {
        "name": "wave73_gp_np_cheap",
        "ids": [
            "gp_np_lag29_m17_np10",
            "gp_np_lag29_m17_np10_imp005",
            "gp_np_lag29_m20_np10",
            "gp_cheap_lag29_m17_np10",
            "gp_cheap_lag29_m17_pe60",
            "gp_cheap_lag29_m17_np10_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave74_gp_np_nimp",
        "ids": [
            "gp_np_lag29_m17_nimp004",
            "gp_np_lag29_m17_nimp006",
            "gp_np_lag28_m17_nimp005",
            "gp_np_lag30_m17_nimp005",
            "gp_np_lag29_m16_nimp005",
            "gp_np_lag29_m17_nimp005_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave75_gp2_twin",
        "ids": [
            "gross_expand_champ_gp2",
            "gross_expand_champ_gp2_imp005",
            "gross_expand_champ_gp2_m18",
            "twin_yoy_lag29_g12",
            "twin_yoy_lag29_g15",
            "twin_yoy_lag29_g10_hold52",
        ],
        "need_balance": False,
    },
    {
        "name": "wave76_regime_parent",
        "ids": [
            "np_regime_lag29_brk60",
            "np_regime_lag29_m08",
            "parent_lead_lag29_brk60",
            "parent_lead_lag29_g12",
            "gross_expand_champ_yoy03",
            "gross_expand_champ_yoy05",
        ],
        "need_balance": False,
    },
    {
        "name": "wave77_momcap_light",
        "ids": [
            "gross_expand_champ_yoy0",
            "gross_expand_champ_ret20_15",
            "gross_expand_champ_ret20_20",
            "gross_expand_champ_amtdry60",
            "asset_light_lag29_brk60",
            "asset_light_lag29_g10",
        ],
        "need_balance": False,
    },
    {
        "name": "wave78_soft_entry",
        "ids": [
            "gross_expand_champ_soft98",
            "gross_expand_champ_soft99",
            "gross_expand_champ_dd03",
            "gross_expand_champ_ret20_30",
            "gross_expand_champ_soft97",
            "gross_expand_champ_dd05",
        ],
        "need_balance": False,
    },
    {
        "name": "wave79_take_profit",
        "ids": [
            "gross_expand_champ_tp15",
            "gross_expand_champ_tp20",
            "gross_expand_champ_tp25",
            "gross_expand_champ_tp30",
            "gross_expand_champ_tp20_hold60",
            "gp_np_peak_tp20",
        ],
        "need_balance": False,
    },
    {
        "name": "wave80_tp_trail",
        "ids": [
            "gross_expand_champ_tp35",
            "gross_expand_champ_tp40",
            "gross_expand_champ_tp50",
            "gross_expand_champ_trail10",
            "gross_expand_champ_trail12",
            "gross_expand_champ_trail15",
        ],
        "need_balance": False,
    },
    {
        "name": "wave81_tp35_peak",
        "ids": [
            "gross_expand_champ_tp32",
            "gross_expand_champ_tp34",
            "gross_expand_champ_tp36",
            "gross_expand_champ_tp38",
            "gross_expand_champ_tp35_hold55",
            "gross_expand_champ_tp35_trail15",
        ],
        "need_balance": False,
    },
    {
        "name": "wave82_tp35_migrate",
        "ids": [
            "gross_expand_m18_lag29_tp35",
            "gross_expand_ma60_tp35",
            "gross_expand_imp0065_tp35",
            "gross_high_np_lag30_tp35",
            "gross_expand_champ_tp35_stop10",
            "gross_expand_champ_tp35_stop14",
        ],
        "need_balance": False,
    },
    {
        "name": "wave83_tp35_micro",
        "ids": [
            "gross_expand_champ_tp35_hold49",
            "gross_expand_champ_tp35_hold50",
            "gross_expand_champ_tp35_hold52",
            "gross_expand_champ_tp35_hold53",
            "gross_expand_champ_tp35_np09",
            "gross_expand_champ_tp35_np11",
        ],
        "need_balance": False,
    },
    {
        "name": "wave84_new_struct_demand",
        "ids": [
            "cl_intensity_break",
            "cl_intensity_break_np",
            "cl_intensity_reclaim",
            "demand_pricing_break",
            "demand_pricing_np",
            "rev_qoq_break",
        ],
        "need_balance": True,
    },
    {
        "name": "wave85_new_struct_quality",
        "ids": [
            "parent_lead_break",
            "parent_lead_quality",
            "asset_light_cl_break",
            "asset_light_cl_roe",
            "gp_consec_break",
            "gp_consec_np",
        ],
        "need_balance": True,
    },
    {
        "name": "wave86_funda_chart_hybrid",
        "ids": [
            "demand_pricing_base",
            "demand_pricing_pullback",
            "cl_intensity_base",
            "cl_intensity_pullback",
            "gp_consec_base",
            "rev_qoq_base",
        ],
        "need_balance": True,
    },
    {
        "name": "wave87_funda_chart_deep",
        "ids": [
            "demand_pricing_base_np",
            "demand_pricing_base_tight",
            "parent_lead_base",
            "asset_light_cl_base",
            "gp_consec_pullback",
            "rev_qoq_pullback",
        ],
        "need_balance": True,
    },
    # ----- 非毛利率主线：全新结构（禁止扫毛利率扩张高原细网格）-----
    {
        "name": "wave88_non_gp_core",
        "ids": [
            "np_regime_break",
            "np_regime_roe",
            "np_expand_cheap_break",
            "np_expand_cheap_reclaim",
            "rev_roe_sync_break",
            "rev_roe_sync_np",
        ],
        "need_balance": False,
    },
    {
        "name": "wave89_non_gp_growth",
        "ids": [
            "parent_eps_twin_break",
            "parent_eps_twin_quality",
            "share_buyback_reclaim",
            "share_buyback_break",
            "asset_light_ni_break",
            "asset_light_ni_roe",
        ],
        "need_balance": False,
    },
    {
        "name": "wave90_non_gp_cl_yoy",
        "ids": [
            "cl_intensity_roe_break",
            "cl_intensity_roe_reclaim",
            "dual_yoy_accel_break",
            "dual_yoy_accel_base",
            "roe_accel_break",
            "roe_accel_np",
        ],
        "need_balance": True,
    },
    {
        "name": "wave91_non_gp_chart",
        "ids": [
            "ni_quality_break",
            "ni_quality_cheap_break",
            "np_regime_base",
            "np_regime_pullback",
            "rev_roe_sync_base",
            "asset_light_ni_reclaim",
            "parent_eps_twin_reclaim",
        ],
        "need_balance": False,
    },
    # ----- 非毛利 × 图形技术深度结合 -----
    {
        "name": "wave92_non_gp_funda_chart",
        "ids": [
            "np_expand_cheap_base",
            "np_expand_cheap_pullback",
            "rev_roe_sync_pullback",
            "rev_roe_sync_amp",
            "parent_eps_twin_base",
            "parent_eps_twin_pullback",
            "share_buyback_base",
            "share_buyback_pullback",
        ],
        "need_balance": False,
    },
    {
        "name": "wave93_non_gp_chart_deep",
        "ids": [
            "asset_light_ni_base",
            "asset_light_ni_pullback",
            "asset_light_ni_amp",
            "cl_intensity_roe_base",
            "cl_intensity_roe_pullback",
            "dual_yoy_accel_pullback",
            "dual_yoy_accel_reclaim",
        ],
        "need_balance": True,
    },
    {
        "name": "wave94_non_gp_chart_roe_ni",
        "ids": [
            "roe_accel_base",
            "roe_accel_pullback",
            "ni_quality_base",
            "ni_quality_pullback",
            "ni_quality_reclaim",
            "np_regime_amp",
            "np_regime_ma60",
        ],
        "need_balance": False,
    },
    # ----- 更大结构差异：股本/绝对利润/TTM/股权利差/预收/量能×基本面 -----
    {
        "name": "wave95_struct_scale_float",
        "ids": [
            "rev_per_share_accel",
            "rev_per_share_accel_base",
            "float_concentration_break",
            "float_concentration_growth",
            "float_concentration_reclaim",
            "netprofit_accel_break",
            "netprofit_accel_roe",
        ],
        "need_balance": False,
    },
    {
        "name": "wave96_struct_ttm_equity",
        "ids": [
            "eps_ttm_mom_cheap",
            "eps_ttm_mom_base",
            "equity_outrun_break",
            "equity_outrun_quality",
            "equity_outrun_pullback",
        ],
        "need_balance": False,
    },
    {
        "name": "wave97_struct_advance_recv",
        "ids": [
            "advance_recv_lead_break",
            "advance_recv_lead_roe",
            "advance_recv_lead_base",
        ],
        "need_balance": True,
    },
    {
        "name": "wave98_struct_micro_funda",
        "ids": [
            "turn_dry_growth_break",
            "turn_dry_growth_roe",
            "turn_dry_growth_reclaim",
            "amount_coil_outrun",
            "amount_coil_outrun_base",
        ],
        "need_balance": False,
    },
]


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], *, timeout: int | None = None) -> int:
    log("[cmd] " + " ".join(cmd))
    p = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout)
    return int(p.returncode)


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"wave_idx": 0, "round": 0, "done_waves": [], "good": [], "weak": []}


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def rank_summary(path: Path) -> list[tuple]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    from app.services.factors.factor_registry import FACTOR_IMPL

    rows = []
    for k, v in data.items():
        if isinstance(v, dict) and "sharpe" in v:
            rows.append(
                (
                    k,
                    FACTOR_IMPL.get(k, {}).get("name", k),
                    v.get("total_return"),
                    v.get("sharpe"),
                    v.get("max_drawdown"),
                    v.get("n_legs_accepted"),
                )
            )
        elif isinstance(v, dict) and "error" in v:
            log(f"[warn] {k}: {v['error']}")
    rows.sort(key=lambda x: -(x[3] if isinstance(x[3], (int, float)) else -999))
    return rows


def plot_ids(ids: list[str]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
    except Exception as exc:  # noqa: BLE001
        log(f"[warn] plot skip: {exc}")
        return
    factors = ROOT / "data" / "factors"
    for fid in ids:
        csv = factors / f"{fid}_backtest.csv"
        png = factors / f"{fid}_equity_curve.png"
        if not csv.exists():
            continue
        try:
            df = pd.read_csv(csv, parse_dates=["date"])
            if "equity" not in df.columns:
                continue
            fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
            axes[0].plot(df["date"], df["equity"], color="#1f4e79", label=fid)
            if "bench_ret" in df.columns:
                bh = (1 + df["bench_ret"].fillna(0)).cumprod()
                axes[0].plot(df["date"], bh, color="#999999", alpha=0.85, label="bench")
            axes[0].legend(loc="upper left")
            axes[0].set_title(fid)
            axes[0].grid(True, alpha=0.25)
            if "position" in df.columns:
                axes[1].fill_between(df["date"], 0, df["position"].fillna(0), color="#2a9d8f", alpha=0.55)
                axes[1].set_ylim(0, 1.05)
            axes[1].grid(True, alpha=0.25)
            fig.tight_layout()
            fig.savefig(png, dpi=120)
            plt.close(fig)
        except Exception as exc:  # noqa: BLE001
            log(f"[warn] plot {fid}: {exc}")


def run_wave(wave: dict, st: dict) -> None:
    name = wave["name"]
    ids = list(wave["ids"])
    # 过滤已强裁剪的弱因子
    weak = set(st.get("weak") or [])
    ids = [i for i in ids if i not in weak]
    if not ids:
        log(f"[skip] {name} empty after weak filter")
        return

    smoke_out = ROOT / "data" / "factors" / f"{name}_smoke.json"
    full_out = ROOT / "data" / "factors" / f"{name}_full.json"
    only = ",".join(ids)

    rc = run(
        [
            str(PY),
            "scripts/run_new_factors.py",
            "--limit",
            "40",
            "--only",
            only,
            "--start",
            "2018-01-01",
            "--out",
            str(smoke_out.relative_to(ROOT)).replace("\\", "/"),
        ]
    )
    if rc != 0:
        log(f"[fail] smoke {name} rc={rc}")
        return

    smoke_rows = rank_summary(smoke_out)
    keep = [r[0] for r in smoke_rows if isinstance(r[3], (int, float)) and r[3] >= 0.05]
    if len(keep) < 3:
        keep = [r[0] for r in smoke_rows if isinstance(r[3], (int, float))][:6]
    if not keep:
        keep = ids[:]
    log(f"[smoke] {name} keep={keep}")

    rc = run(
        [
            str(PY),
            "scripts/run_new_factors.py",
            "--limit",
            "0",
            "--only",
            ",".join(keep),
            "--start",
            "2018-01-01",
            "--out",
            str(full_out.relative_to(ROOT)).replace("\\", "/"),
        ]
    )
    if rc != 0:
        log(f"[fail] full {name} rc={rc}")
        return

    plot_ids(keep)
    rows = rank_summary(full_out)
    good = [r[0] for r in rows if isinstance(r[3], (int, float)) and r[3] >= 0.15]
    weak_now = [r[0] for r in rows if isinstance(r[3], (int, float)) and r[3] < 0.05]
    smoke_data = json.loads(smoke_out.read_text(encoding="utf-8")) if smoke_out.exists() else {}
    for k, v in smoke_data.items():
        if isinstance(v, dict) and ("error" in v or (v.get("sharpe") is not None and v["sharpe"] < 0.05)):
            if k not in good:
                weak_now.append(k)
    weak_now = sorted(set(weak_now) - set(good))

    st["good"] = sorted(set(st.get("good") or []) | set(good))
    st["weak"] = sorted(set(st.get("weak") or []) | set(weak_now))
    st.setdefault("done_waves", []).append(
        {
            "name": name,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "good": good,
            "weak": weak_now,
            "rank": [
                {"id": r[0], "name": r[1], "ret": r[2], "sharpe": r[3], "mdd": r[4], "legs": r[5]}
                for r in rows
            ],
        }
    )
    KEEP_ALL.write_text(
        json.dumps({"good": st["good"], "weak": st["weak"], "waves": st["done_waves"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 写 wave keep 供 sync_prune 读取
    (ROOT / "data" / "factors" / f"{name}_keep.json").write_text(
        json.dumps({"good": good, "weak": weak_now, "all": [r[0] for r in rows]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"[full] {name} GOOD={good} WEAK={weak_now}")
    for r in rows:
        log(f"  {r[0]:28} sharpe={r[3]} ret={r[2]} legs={r[5]}")

    # 通宵只 upsert Mongo，不自动退役（避免冒烟误杀）；早晨可手动 prune
    run([str(PY), "scripts/sync_prune_and_mongo.py", "--sync-only"])


def ensure_contract_finished(st: dict) -> None:
    """若合同负债进程产物未齐，先补跑。"""
    summary = ROOT / "data" / "factors" / "contract_liab_expand_summary.json"
    csv = ROOT / "data" / "factors" / "contract_liab_expand_backtest.csv"
    if summary.exists() and csv.exists():
        log("[ok] contract_liab_expand already has artifacts")
        return
    bal = ROOT / "data" / "factors" / "_shared" / "balance"
    n = len(list(bal.glob("*.parquet"))) if bal.exists() else 0
    log(f"[info] balance cache n={n}; launching contract backtest")
    run([str(PY), "scripts/backtest_contract_liab_expand.py", "--limit", "0"])


def load_waves() -> list[dict]:
    """从本文件重新解析 WAVES，便于通宵热加波次。"""
    try:
        path = Path(__file__).resolve()
        code = path.read_text(encoding="utf-8")
        code = code.replace('if __name__ == "__main__":', 'if False and __name__ == "__main__":')
        ns: dict = {"__file__": str(path), "__name__": "_mine_overnight_hot"}
        exec(compile(code, str(path), "exec"), ns)  # noqa: S102
        waves = ns.get("WAVES")
        if waves:
            log(f"[hot] loaded {len(waves)} waves: {[w.get('name') for w in waves]}")
            return list(waves)
        return WAVES
    except Exception as exc:  # noqa: BLE001
        log(f"[warn] load_waves fallback: {exc}")
        return WAVES


def wave_needs_run(wave: dict, st: dict) -> bool:
    """已测过且无新候选时跳过，避免通宵反复全量复验。"""
    good = set(st.get("good") or [])
    weak = set(st.get("weak") or [])
    ids = [i for i in wave.get("ids") or [] if i not in weak]
    if not ids:
        return False
    untested = [i for i in ids if i not in good]
    full = ROOT / "data" / "factors" / f"{wave['name']}_full.json"
    if full.exists():
        try:
            data = json.loads(full.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
        # 全量文件里已有结果的，不再因未进 good 而反复复测
        missing = [i for i in untested if i not in data]
        if not missing:
            log(f"[skip] {wave['name']} full exists; no new ids")
            return False
        return True
    return bool(untested) or True


def one_round(st: dict) -> None:
    st["round"] = int(st.get("round") or 0) + 1
    log(f"===== overnight round {st['round']} =====")
    if PAUSE.exists():
        try:
            meta = json.loads(PAUSE.read_text(encoding="utf-8"))
            reason = meta.get("reason") or "paused"
            paused = bool(meta.get("paused", True))
        except Exception:  # noqa: BLE001
            reason = "paused"
            paused = True
        if paused:
            log(f"[pause] skip waves: {reason}")
            save_state(st)
            return
        log(f"[pause] file present but paused=false; continue ({reason})")
    ensure_contract_finished(st)
    # 允许外部在休眠期间改 overnight_state.json 的 wave_idx
    try:
        disk = load_state()
        if "wave_idx" in disk:
            st["wave_idx"] = int(disk.get("wave_idx") or 0)
    except Exception:  # noqa: BLE001
        pass
    waves = load_waves()
    idx = int(st.get("wave_idx") or 0) % max(1, len(waves))
    ran = 0
    for offset in range(len(waves)):
        wave = waves[(idx + offset) % len(waves)]
        if int(st.get("round") or 0) >= 2 and not wave_needs_run(wave, st):
            continue
        try:
            run_wave(wave, st)
            ran += 1
        except Exception:  # noqa: BLE001
            log("[exception]\n" + traceback.format_exc())
        save_state(st)
    st["wave_idx"] = (idx + 1) % max(1, len(waves))
    save_state(st)
    log(f"===== round {st['round']} done; ran={ran}; cumulative good={st.get('good')} =====")


def main() -> None:
    import argparse
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--sleep-sec", type=int, default=180, help="轮次间隔秒")
    args = ap.parse_args()

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip().split()[0])
            # Windows: 进程仍在则退出，避免双开互踩
            import subprocess as _sp

            chk = _sp.run(
                ["tasklist", "/FI", f"PID eq {old}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
            )
            if str(old) in (chk.stdout or "") and "python" in (chk.stdout or "").lower():
                print(f"another miner running pid={old}; exit", flush=True)
                raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001
            pass
    LOCK.write_text(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8")

    st = load_state()
    log("overnight miner started")
    try:
        while True:
            try:
                one_round(st)
            except Exception:  # noqa: BLE001
                log("[round exception]\n" + traceback.format_exc())
                save_state(st)
            if args.once:
                break
            log(f"sleep {args.sleep_sec}s then continue...")
            time.sleep(max(30, int(args.sleep_sec)))
    finally:
        try:
            if LOCK.exists() and LOCK.read_text(encoding="utf-8").startswith(str(os.getpid())):
                LOCK.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
