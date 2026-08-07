"""本地「1.0_A股财务数据库.db」只读适配。

Wind 风格 SQLite：三大报表 + 业绩预告/快报 + 公司基本资料。
默认路径：data/factors/_shared/1.0_A股财务数据库.db（与腾讯日线同目录）。
代码映射：600160.SH ↔ sh.600160；输出统一带 pubDate/statDate，供 merge_asof。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger("webapi.factors.ashare_fin_db")

ROOT = Path(__file__).resolve().parents[3]

# Wind STATEMENT_TYPE：合并报表（库内主类型）
STMT_MERGED = 408001000

TABLE_BASIC = "中国A股与公司基本资料"
TABLE_INCOME = "中国A股利润表"
TABLE_BALANCE = "中国A股资产负债表"
TABLE_CASHFLOW = "中国A股现金流量表"
TABLE_FORECAST = "中国A股业绩预告"
TABLE_EXPRESS = "中国A股业绩快报"

# 输出列：Wind 原列 → 因子面板友好名
INCOME_MAP = {
    "OPER_REV": "fin_oper_rev",
    "TOT_OPER_REV": "fin_tot_oper_rev",
    "OPER_PROFIT": "fin_oper_profit",
    "TOT_PROFIT": "fin_tot_profit",
    "NET_PROFIT_EXCL_MIN_INT_INC": "fin_net_profit_parent",
    "NET_PROFIT_INCL_MIN_INT_INC": "fin_net_profit",
    "NET_PROFIT_AFTER_DED_NR_LP": "fin_net_profit_deducted",
    "S_FA_EPS_BASIC": "fin_eps_basic",
    "S_FA_EPS_DILUTED": "fin_eps_diluted",
    "EBIT": "fin_ebit",
    "EBITDA": "fin_ebitda",
    "RD_EXPENSE": "fin_rd_expense",
    "LESS_SELLING_DIST_EXP": "fin_selling_exp",
    "LESS_GERL_ADMIN_EXP": "fin_admin_exp",
    "LESS_FIN_EXP": "fin_fin_exp",
    # 银行特色：利息 / 中收 / 信用减值
    "INT_INC": "fin_int_inc",
    "LESS_INT_EXP": "fin_int_exp",
    "NET_INT_INC": "fin_net_int_inc",
    "NET_HANDLING_CHRG_COMM_INC": "fin_fee_inc_net",
    "LESS_HANDLING_CHRG_COMM_EXP": "fin_fee_exp",
    "CREDIT_IMPAIRMENT_LOSS": "fin_credit_impair",
    "LESS_IMPAIR_LOSS_ASSETS": "fin_asset_impair",
}

BALANCE_MAP = {
    "TOT_ASSETS": "fin_tot_assets",
    "TOT_LIAB": "fin_tot_liab",
    "TOT_SHRHLDR_EQY_EXCL_MIN_INT": "fin_equity_parent",
    "MONETARY_CAP": "fin_monetary_cap",
    "INVENTORIES": "fin_inventories",
    "ACCT_RCV": "fin_acct_rcv",
    "NOTES_RCV": "fin_notes_rcv",
    "PREPAY": "fin_prepay",
    "ADV_FROM_CUST": "advance_recv",
    # 原始合同负债；合并口径 contract_liab 在 merged / fetch_contract_bundle 中派生
    "CONTRACT_LIABILITIES": "contract_liab_raw",
    "TOT_CUR_ASSETS": "fin_tot_cur_assets",
    "TOT_CUR_LIAB": "fin_tot_cur_liab",
    "ST_BORROW": "fin_st_borrow",
    "LT_BORROW": "fin_lt_borrow",
    "TOT_SHR": "fin_tot_share",
    "FIX_ASSETS": "fin_fix_assets",
    "CONST_IN_PROG": "fin_cip",
    "ACCT_PAYABLE": "fin_acct_pay",
    "INTANG_ASSETS": "fin_intang_assets",
    "GOODWILL": "fin_goodwill",
    # 银行特色：贷款 / 拨备（名义风险准备更全）
    "LOANS_AND_ADV_GRANTED": "fin_loans",
    "PROVISIONS": "fin_provisions",
    "PROV_NOM_RISKS": "fin_prov_nom_risks",
    "LOANS_TO_OTH_BANKS": "fin_loans_to_banks",
    "BORROW_CENTRAL_BANK": "fin_borrow_cb",
    "CASH_DEPOSITS_CENTRAL_BANK": "fin_cash_at_cb",
}

CASHFLOW_MAP = {
    "NET_CASH_FLOWS_OPER_ACT": "cfo",
    "NET_CASH_FLOWS_INV_ACT": "cfi",
    "NET_CASH_FLOWS_FNC_ACT": "cff",
    "CASH_RECP_SG_AND_RS": "fin_cash_from_sales",
    "CASH_PAY_ACQ_CONST_FIOLTA": "fin_capex",
    "NET_INCR_CASH_CASH_EQU": "fin_net_cash_incr",
}

EXPRESS_MAP = {
    "OPER_REV": "expr_oper_rev",
    "OPER_PROFIT": "expr_oper_profit",
    "TOT_PROFIT": "expr_tot_profit",
    "NET_PROFIT_EXCL_MIN_INT_INC": "expr_net_profit",
    "EPS_DILUTED": "expr_eps",
    "ROE_DILUTED": "expr_roe",
    "S_FA_YOYSALES": "expr_yoy_sales",
    "S_FA_YOYNETPROFIT_DEDUCTED": "expr_yoy_np_deducted",
    "S_FA_YOYEPS_BASIC": "expr_yoy_eps",
    # 上年同期（同公告行内，便于 PIT 算 ΔROS，无需跨行对齐）
    "LAST_YEAR_OPER_REV": "expr_ly_oper_rev",
    "LAST_YEAR_NET_PROFIT_EXCL_INC": "expr_ly_net_profit",
    "YOYNET_PROFIT_EXCL_MIN_INT_INC": "expr_yoy_np",
}

FORECAST_MAP = {
    "S_PROFITNOTICE_STYLE": "fcst_style",
    "S_PROFITNOTICE_CHANGEMIN": "fcst_change_min",
    "S_PROFITNOTICE_CHANGEMAX": "fcst_change_max",
    "S_PROFITNOTICE_NETPROFITMIN": "fcst_np_min",
    "S_PROFITNOTICE_NETPROFITMAX": "fcst_np_max",
    "S_PROFITNOTICE_ABSTRACT": "fcst_abstract",
}


def project_root() -> Path:
    return ROOT


def resolve_db_path(explicit: str | Path | None = None) -> Optional[Path]:
    """查找财务库路径。

    优先级：显式参数 > Settings/环境变量 > data/factors/_shared > data/ > 项目根。
    """
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    try:
        from app.core.config import settings

        cfg = (getattr(settings, "ASHARE_FIN_DB", None) or "").strip()
        if cfg:
            p = Path(cfg)
            if p.exists():
                return p
    except Exception:  # noqa: BLE001
        pass
    env = (os.environ.get("ASHARE_FIN_DB") or os.environ.get("LAHM_ASHARE_FIN_DB") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p

    candidates: list[Path] = [
        ROOT / "data" / "factors" / "_shared",
        ROOT / "data" / "market",
        ROOT / "data",
        ROOT,
    ]
    for base in candidates:
        if not base.exists():
            continue
        matches = sorted(base.glob("1.0_*.db"))
        if matches:
            return matches[0]
    return None


def db_available(explicit: str | Path | None = None) -> bool:
    return resolve_db_path(explicit) is not None


def bs_to_wind(code: str) -> str:
    """sh.600160 / sz.000001 → 600160.SH / 000001.SZ"""
    s = str(code or "").strip()
    if not s:
        return ""
    if "." in s:
        left, right = s.split(".", 1)
        if left.lower() in ("sh", "sz", "bj") and right.isdigit():
            return f"{right}.{left.upper()}"
        if right.upper() in ("SH", "SZ", "BJ") and left.isdigit():
            return f"{left}.{right.upper()}"
    if s.isdigit() and len(s) == 6:
        if s.startswith(("5", "6", "9")):
            return f"{s}.SH"
        if s.startswith(("4", "8")):
            return f"{s}.BJ"
        return f"{s}.SZ"
    return s


def wind_to_bs(code: str) -> str:
    """600160.SH → sh.600160"""
    s = str(code or "").strip()
    if not s:
        return ""
    if "." in s:
        left, right = s.split(".", 1)
        if right.upper() in ("SH", "SZ", "BJ") and left.isdigit():
            return f"{right.lower()}.{left}"
        if left.lower() in ("sh", "sz", "bj") and right.isdigit():
            return f"{left.lower()}.{right}"
    return s


def _ymd_to_ts(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    # 已是 ISO
    out = pd.to_datetime(s, errors="coerce")
    # YYYYMMDD
    mask = out.isna() & s.str.match(r"^\d{8}$")
    if mask.any():
        out.loc[mask] = pd.to_datetime(s.loc[mask], format="%Y%m%d", errors="coerce")
    return out


@lru_cache(maxsize=2)
def _connect_ro(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def connect(explicit: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_db_path(explicit)
    if path is None:
        raise FileNotFoundError(
            "A股财务数据库未找到。请将 1.0_A股财务数据库.db 放在 "
            "data/factors/_shared/ ，或设置环境变量 ASHARE_FIN_DB。"
        )
    return _connect_ro(str(path.resolve()))


def list_tables(explicit: str | Path | None = None) -> List[str]:
    con = connect(explicit)
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def cache_dir(base: Path | None = None) -> Path:
    # v2：contract_liab_raw + 合并口径派生
    root = base or (ROOT / "data" / "factors" / "_shared" / "ashare_fin" / "v2")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _query_df(
    sql: str,
    params: Sequence[Any] = (),
    *,
    explicit: str | Path | None = None,
) -> pd.DataFrame:
    con = connect(explicit)
    return pd.read_sql_query(sql, con, params=list(params))


def fetch_basic(explicit: str | Path | None = None) -> pd.DataFrame:
    df = _query_df(
        f'SELECT S_INFO_WINDCODE, S_INFO_NAME, S_INFO_LISTDATE, '
        f'S_INFO_DELISTDATE, S_INFO_LISTBOARD FROM "{TABLE_BASIC}"',
        explicit=explicit,
    )
    if df.empty:
        return df
    df["code"] = df["S_INFO_WINDCODE"].map(wind_to_bs)
    df["name"] = df["S_INFO_NAME"]
    return df


def _merge_asof_local(price: pd.DataFrame, funda: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    import numpy as np

    if funda is None or funda.empty:
        out = price.copy()
        for c in cols:
            if c not in out.columns:
                out[c] = np.nan
        return out
    f = funda.dropna(subset=["pubDate"]).sort_values("pubDate")
    keep = ["pubDate"] + [c for c in cols if c in f.columns]
    f = f[keep].copy()
    p = price.sort_values("date")
    return pd.merge_asof(
        p,
        f.rename(columns={"pubDate": "date"}),
        on="date",
        direction="backward",
    )


def _fetch_statement(
    table: str,
    wind_code: str,
    col_map: Dict[str, str],
    *,
    ann_col: str = "ANN_DT",
    period_col: str = "REPORT_PERIOD",
    actual_ann_col: str | None = "ACTUAL_ANN_DT",
    statement_type: int | None = STMT_MERGED,
    explicit: str | Path | None = None,
    cache_base: Path | None = None,
) -> pd.DataFrame:
    """按股票读一张报表，结果缓存为 parquet。"""
    wcode = bs_to_wind(wind_code)
    bs_code = wind_to_bs(wcode)
    cdir = cache_dir(cache_base) / table
    cdir.mkdir(parents=True, exist_ok=True)
    cache_fp = cdir / f"{bs_code.replace('.', '_')}.parquet"
    if cache_fp.exists():
        try:
            cached = pd.read_parquet(cache_fp)
            need_cols = list(col_map.values())
            if cached is not None and (not need_cols or all(c in cached.columns for c in need_cols)):
                return cached
        except Exception:  # noqa: BLE001
            pass

    src_cols = list(col_map.keys())
    select_cols = [ann_col, period_col] + src_cols
    if actual_ann_col:
        select_cols.insert(0, actual_ann_col)
    if statement_type is not None:
        select_cols.append("STATEMENT_TYPE")
    # 去重保序
    seen = set()
    ordered = []
    for c in select_cols:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    col_sql = ", ".join(ordered)
    if statement_type is not None:
        sql = (
            f'SELECT {col_sql} FROM "{table}" '
            f"WHERE S_INFO_WINDCODE = ? AND STATEMENT_TYPE = ? "
            f"ORDER BY {period_col}, {ann_col}"
        )
        params: Sequence[Any] = (wcode, statement_type)
    else:
        sql = (
            f'SELECT {col_sql} FROM "{table}" '
            f"WHERE S_INFO_WINDCODE = ? "
            f"ORDER BY {period_col}, {ann_col}"
        )
        params = (wcode,)

    try:
        raw = _query_df(sql, params, explicit=explicit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ashare_fin query %s %s: %s", table, wcode, exc)
        return pd.DataFrame(columns=["pubDate", "statDate", "code"] + list(col_map.values()))

    if raw.empty:
        out = pd.DataFrame(columns=["pubDate", "statDate", "code"] + list(col_map.values()))
        out.to_parquet(cache_fp, index=False)
        return out

    pub = None
    if actual_ann_col and actual_ann_col in raw.columns:
        pub = _ymd_to_ts(raw[actual_ann_col])
    ann = _ymd_to_ts(raw[ann_col]) if ann_col in raw.columns else pd.Series(pd.NaT, index=raw.index)
    if pub is None:
        pub = ann
    else:
        pub = pub.fillna(ann)
    out = pd.DataFrame(
        {
            "pubDate": pub,
            "statDate": _ymd_to_ts(raw[period_col]),
            "code": bs_code,
        }
    )
    for src, dst in col_map.items():
        if src in raw.columns:
            out[dst] = pd.to_numeric(raw[src], errors="coerce")
        else:
            out[dst] = pd.NA
    out = out.dropna(subset=["pubDate"]).sort_values("pubDate").drop_duplicates("pubDate", keep="last")
    try:
        out.to_parquet(cache_fp, index=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache write fail %s: %s", cache_fp, exc)
    return out.reset_index(drop=True)


def fetch_income(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    return _fetch_statement(
        TABLE_INCOME, code, INCOME_MAP, explicit=explicit, cache_base=cache_base
    )


def fetch_balance(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    return _fetch_statement(
        TABLE_BALANCE, code, BALANCE_MAP, explicit=explicit, cache_base=cache_base
    )


def fetch_cashflow(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    return _fetch_statement(
        TABLE_CASHFLOW, code, CASHFLOW_MAP, explicit=explicit, cache_base=cache_base
    )


def _attach_express_ros(df: pd.DataFrame) -> pd.DataFrame:
    """快报派生 ROS=净利/营收，及同比 ΔROS（优先用上年同行字段）。"""
    if df is None or df.empty:
        return df
    out = df.copy()
    rev = (
        pd.to_numeric(out["expr_oper_rev"], errors="coerce")
        if "expr_oper_rev" in out.columns
        else pd.Series(pd.NA, index=out.index)
    )
    np_ = (
        pd.to_numeric(out["expr_net_profit"], errors="coerce")
        if "expr_net_profit" in out.columns
        else pd.Series(pd.NA, index=out.index)
    )
    ros = np_ / rev.replace(0, pd.NA)
    out["expr_ros"] = ros

    ros_ly = pd.Series(float("nan"), index=out.index, dtype="float64")
    if "expr_ly_oper_rev" in out.columns and "expr_ly_net_profit" in out.columns:
        ly_rev = pd.to_numeric(out["expr_ly_oper_rev"], errors="coerce")
        ly_np = pd.to_numeric(out["expr_ly_net_profit"], errors="coerce")
        ros_ly = ly_np / ly_rev.replace(0, pd.NA)
    elif "statDate" in out.columns and ros.notna().sum() >= 2:
        tmp = pd.DataFrame({"statDate": out["statDate"], "ros": ros})
        tmp = tmp.dropna(subset=["statDate", "ros"]).sort_values("statDate")
        by_ym = {
            (int(sd.year), int(sd.month)): float(rv)
            for sd, rv in zip(tmp["statDate"], tmp["ros"])
        }
        aligned = []
        for dt, v in zip(out["statDate"], ros):
            if pd.isna(dt) or pd.isna(v):
                aligned.append(float("nan"))
                continue
            prev = by_ym.get((int(dt.year) - 1, int(dt.month)))
            aligned.append(float(prev) if prev is not None else float("nan"))
        ros_ly = pd.Series(aligned, index=out.index, dtype="float64")

    out["expr_ros_ly"] = ros_ly
    out["expr_dros"] = ros.astype(float) - pd.to_numeric(ros_ly, errors="coerce")
    return out


def fetch_express(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    raw = _fetch_statement(
        TABLE_EXPRESS,
        code,
        EXPRESS_MAP,
        ann_col="ANN_DT",
        period_col="REPORT_PERIOD",
        actual_ann_col="ACTUAL_ANN_DT",
        statement_type=None,
        explicit=explicit,
        cache_base=cache_base,
    )
    # 缓存缺新列时回源（LAST_YEAR / YoY 字段扩展后）
    need = ("expr_ly_oper_rev", "expr_ly_net_profit")
    if raw is not None and not raw.empty and any(c not in raw.columns for c in need):
        cdir = cache_dir(cache_base) / TABLE_EXPRESS
        fp = cdir / f"{wind_to_bs(bs_to_wind(code)).replace('.', '_')}.parquet"
        if fp.exists():
            try:
                fp.unlink()
            except Exception:  # noqa: BLE001
                pass
        raw = _fetch_statement(
            TABLE_EXPRESS,
            code,
            EXPRESS_MAP,
            ann_col="ANN_DT",
            period_col="REPORT_PERIOD",
            actual_ann_col="ACTUAL_ANN_DT",
            statement_type=None,
            explicit=explicit,
            cache_base=cache_base,
        )
    return _attach_express_ros(raw)


def fetch_forecast(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    """业绩预告：公告日列名不同。"""
    wcode = bs_to_wind(code)
    bs_code = wind_to_bs(wcode)
    cdir = cache_dir(cache_base) / TABLE_FORECAST
    cdir.mkdir(parents=True, exist_ok=True)
    cache_fp = cdir / f"{bs_code.replace('.', '_')}.parquet"
    if cache_fp.exists():
        try:
            return pd.read_parquet(cache_fp)
        except Exception:  # noqa: BLE001
            pass
    src_cols = list(FORECAST_MAP.keys())
    col_sql = ", ".join(
        ["S_PROFITNOTICE_DATE", "S_PROFITNOTICE_PERIOD", "S_PROFITNOTICE_FIRSTANNDATE"] + src_cols
    )
    sql = (
        f'SELECT {col_sql} FROM "{TABLE_FORECAST}" '
        f"WHERE S_INFO_WINDCODE = ? ORDER BY S_PROFITNOTICE_DATE"
    )
    try:
        raw = _query_df(sql, (wcode,), explicit=explicit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("forecast %s: %s", wcode, exc)
        return pd.DataFrame(columns=["pubDate", "statDate", "code"] + list(FORECAST_MAP.values()))
    if raw.empty:
        out = pd.DataFrame(columns=["pubDate", "statDate", "code"] + list(FORECAST_MAP.values()))
        out.to_parquet(cache_fp, index=False)
        return out
    pub = _ymd_to_ts(raw["S_PROFITNOTICE_FIRSTANNDATE"]).fillna(
        _ymd_to_ts(raw["S_PROFITNOTICE_DATE"])
    )
    out = pd.DataFrame(
        {
            "pubDate": pub,
            "statDate": _ymd_to_ts(raw["S_PROFITNOTICE_PERIOD"]),
            "code": bs_code,
        }
    )
    for src, dst in FORECAST_MAP.items():
        if src in raw.columns:
            if dst == "fcst_abstract":
                out[dst] = raw[src].astype(str)
            else:
                out[dst] = pd.to_numeric(raw[src], errors="coerce")
        else:
            out[dst] = pd.NA
    out = out.dropna(subset=["pubDate"]).sort_values("pubDate").drop_duplicates("pubDate", keep="last")
    out.to_parquet(cache_fp, index=False)
    return out.reset_index(drop=True)


def _attach_contract_fields(df: pd.DataFrame) -> pd.DataFrame:
    """派生 contract_liab（合同负债+预收合并）与同比（约同比季：shift 4）。"""
    if df is None or df.empty:
        return df
    out = df.sort_values("statDate" if "statDate" in df.columns else "pubDate").copy()
    cl = (
        pd.to_numeric(out["contract_liab_raw"], errors="coerce")
        if "contract_liab_raw" in out.columns
        else pd.Series(pd.NA, index=out.index)
    )
    ar = (
        pd.to_numeric(out["advance_recv"], errors="coerce")
        if "advance_recv" in out.columns
        else pd.Series(pd.NA, index=out.index)
    )
    combined = cl.fillna(0.0) + ar.fillna(0.0)
    combined = combined.where(cl.notna() | ar.notna(), pd.NA)
    out["contract_liab_raw"] = cl
    out["advance_recv"] = ar
    out["contract_liab"] = combined
    prev_y = combined.shift(4)
    out["contract_liab_yoy"] = (combined - prev_y) / prev_y.replace(0, pd.NA)
    return out


def _attach_single_q_np_fields(df: pd.DataFrame) -> pd.DataFrame:
    """累计净利差分 → 单季 NP，并派生同比/环比/上年同季同比。

    口径：归属母公司净利润（fin_net_profit_parent），缺省回退 fin_net_profit。
    Q1 单季=当期累计；Q2/Q3/Q4 单季=当期累计−同年上一报告期累计。
    同比按 (年, 月) 对齐上年同季，基期≤0 时 YoY 置空（排除扭亏伪翻倍）。
    """
    if df is None or df.empty:
        return df
    np_col = None
    for c in ("fin_net_profit_parent", "fin_net_profit"):
        if c in df.columns:
            np_col = c
            break
    if np_col is None or "statDate" not in df.columns:
        return df

    out = df.copy()
    tmp = out.dropna(subset=["statDate"]).copy()
    tmp["_cum_np"] = pd.to_numeric(tmp[np_col], errors="coerce")
    period = (
        tmp.dropna(subset=["_cum_np"])
        .sort_values(["statDate", "pubDate"] if "pubDate" in tmp.columns else ["statDate"])
        .drop_duplicates("statDate", keep="last")
        .loc[:, ["statDate", "_cum_np"]]
        .sort_values("statDate")
        .reset_index(drop=True)
    )
    if period.empty:
        out["q_np"] = float("nan")
        out["q_np_yoy"] = float("nan")
        out["q_np_qoq"] = float("nan")
        out["q_np_prior_yoy"] = float("nan")
        return out

    period["year"] = period["statDate"].dt.year
    period["month"] = period["statDate"].dt.month
    cum_by_ym = {
        (int(y), int(m)): float(v)
        for y, m, v in zip(period["year"], period["month"], period["_cum_np"])
    }

    q_list: list[float | None] = []
    for y, m, cum in zip(period["year"], period["month"], period["_cum_np"]):
        y_i, m_i, cum_f = int(y), int(m), float(cum)
        if m_i == 3:
            q_list.append(cum_f)
            continue
        prev_m = {6: 3, 9: 6, 12: 9}.get(m_i)
        if prev_m is None:
            q_list.append(None)
            continue
        prev_cum = cum_by_ym.get((y_i, prev_m))
        if prev_cum is None:
            q_list.append(None)
        else:
            q_list.append(cum_f - prev_cum)
    period["q_np"] = q_list

    q_by_ym = {
        (int(y), int(m)): q
        for y, m, q in zip(period["year"], period["month"], period["q_np"])
        if q is not None and pd.notna(q)
    }

    yoy_list: list[float | None] = []
    qoq_list: list[float | None] = []
    for y, m, q in zip(period["year"], period["month"], period["q_np"]):
        if q is None or pd.isna(q):
            yoy_list.append(None)
            qoq_list.append(None)
            continue
        q_f = float(q)
        prior = q_by_ym.get((int(y) - 1, int(m)))
        if prior is None or prior <= 0 or q_f <= 0:
            yoy_list.append(None)
        else:
            yoy_list.append(q_f / prior - 1.0)

        prev_m = {3: 12, 6: 3, 9: 6, 12: 9}.get(int(m))
        prev_y = int(y) - 1 if int(m) == 3 else int(y)
        if prev_m is None:
            qoq_list.append(None)
        else:
            pq = q_by_ym.get((prev_y, prev_m))
            if pq is None or pq <= 0 or q_f <= 0:
                qoq_list.append(None)
            else:
                qoq_list.append(q_f / pq - 1.0)

    period["q_np_yoy"] = yoy_list
    period["q_np_qoq"] = qoq_list
    yoy_by_ym = {
        (int(y), int(m)): yy
        for y, m, yy in zip(period["year"], period["month"], period["q_np_yoy"])
        if yy is not None and pd.notna(yy)
    }
    period["q_np_prior_yoy"] = [
        yoy_by_ym.get((int(y) - 1, int(m))) for y, m in zip(period["year"], period["month"])
    ]

    meta = period[["statDate", "q_np", "q_np_yoy", "q_np_qoq", "q_np_prior_yoy"]]
    # 去掉旧列再合并，避免重复后缀
    for c in ("q_np", "q_np_yoy", "q_np_qoq", "q_np_prior_yoy"):
        if c in out.columns:
            out = out.drop(columns=[c])
    out = out.merge(meta, on="statDate", how="left")
    # 仅在当期累计净利已披露的行保留派生，避免资负/现流更早公告日带入前视
    has_np = pd.to_numeric(out[np_col], errors="coerce").notna()
    for c in ("q_np", "q_np_yoy", "q_np_qoq", "q_np_prior_yoy"):
        out.loc[~has_np, c] = float("nan")
    return out


def _attach_same_period_yoy(df: pd.DataFrame, src_col: str, out_col: str) -> pd.DataFrame:
    """累计口径同报告期同比：按 (年, 月) 对齐上年同期。

    口径：累计值（如 OPER_REV / 归母净利累计）相对上年同月报告期；
    基期≤0 或当期≤0 时置空（排除扭亏伪高增）。
    """
    if df is None or df.empty or src_col not in df.columns or "statDate" not in df.columns:
        return df
    out = df.copy()
    if out_col in out.columns:
        out = out.drop(columns=[out_col])
    tmp = out.dropna(subset=["statDate"]).copy()
    tmp["_v"] = pd.to_numeric(tmp[src_col], errors="coerce")
    period = (
        tmp.dropna(subset=["_v"])
        .sort_values(["statDate", "pubDate"] if "pubDate" in tmp.columns else ["statDate"])
        .drop_duplicates("statDate", keep="last")
        .loc[:, ["statDate", "_v"]]
        .sort_values("statDate")
        .reset_index(drop=True)
    )
    if period.empty:
        out[out_col] = float("nan")
        return out
    period["year"] = period["statDate"].dt.year
    period["month"] = period["statDate"].dt.month
    by_ym = {
        (int(y), int(m)): float(v)
        for y, m, v in zip(period["year"], period["month"], period["_v"])
    }
    yoy_list: list[float | None] = []
    for y, m, v in zip(period["year"], period["month"], period["_v"]):
        prior = by_ym.get((int(y) - 1, int(m)))
        cur = float(v)
        if prior is None or prior <= 0 or cur <= 0:
            yoy_list.append(None)
        else:
            yoy_list.append(cur / prior - 1.0)
    period[out_col] = yoy_list
    meta = period[["statDate", out_col]]
    out = out.merge(meta, on="statDate", how="left")
    has_src = pd.to_numeric(out[src_col], errors="coerce").notna()
    out.loc[~has_src, out_col] = float("nan")
    return out


def fetch_contract_bundle(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    """兼容旧 balance 接口：合同负债 + 预收 + 同比。"""
    bal = fetch_balance(code, explicit=explicit, cache_base=cache_base)
    if bal.empty:
        return pd.DataFrame(
            columns=["pubDate", "statDate", "contract_liab", "advance_recv", "contract_liab_raw", "contract_liab_yoy"]
        )
    enriched = _attach_contract_fields(bal)
    return enriched[
        ["pubDate", "statDate", "contract_liab", "advance_recv", "contract_liab_raw", "contract_liab_yoy"]
    ].reset_index(drop=True)


def fetch_all_for_code(
    code: str,
    *,
    explicit: str | Path | None = None,
    cache_base: Path | None = None,
    include_express: bool = True,
    include_forecast: bool = True,
) -> Dict[str, pd.DataFrame]:
    """一次取齐该股全部财务表。"""
    out = {
        "income": fetch_income(code, explicit=explicit, cache_base=cache_base),
        "balance": fetch_balance(code, explicit=explicit, cache_base=cache_base),
        "cashflow": fetch_cashflow(code, explicit=explicit, cache_base=cache_base),
    }
    if include_express:
        out["express"] = fetch_express(code, explicit=explicit, cache_base=cache_base)
    if include_forecast:
        out["forecast"] = fetch_forecast(code, explicit=explicit, cache_base=cache_base)
    return out


def merged_funda_frame(
    code: str,
    *,
    explicit: str | Path | None = None,
    cache_base: Path | None = None,
) -> pd.DataFrame:
    """将三大表按 pubDate 外合并成宽表（供 enrich）。"""
    parts = [
        fetch_income(code, explicit=explicit, cache_base=cache_base),
        fetch_balance(code, explicit=explicit, cache_base=cache_base),
        fetch_cashflow(code, explicit=explicit, cache_base=cache_base),
        fetch_express(code, explicit=explicit, cache_base=cache_base),
        fetch_forecast(code, explicit=explicit, cache_base=cache_base),
    ]
    base: Optional[pd.DataFrame] = None
    for p in parts:
        if p is None or p.empty:
            continue
        use = p.drop(columns=["code"], errors="ignore")
        if base is None:
            base = use
        else:
            base = pd.merge(base, use, on=["pubDate", "statDate"], how="outer", suffixes=("", "_dup"))
            dup_cols = [c for c in base.columns if c.endswith("_dup")]
            if dup_cols:
                base = base.drop(columns=dup_cols)
    if base is None or base.empty:
        return pd.DataFrame(columns=["pubDate", "statDate"])
    base = base.sort_values(["statDate", "pubDate"], na_position="last").reset_index(drop=True)
    base = _attach_contract_fields(base)
    base = _attach_single_q_np_fields(base)
    # 累计口径同报告期 YoY（营收/归母净利）：标准「同比增长」
    base = _attach_same_period_yoy(base, "fin_oper_rev", "fin_rev_yoy")
    np_yoy_src = (
        "fin_net_profit_parent"
        if "fin_net_profit_parent" in base.columns
        else ("fin_net_profit" if "fin_net_profit" in base.columns else None)
    )
    if np_yoy_src:
        base = _attach_same_period_yoy(base, np_yoy_src, "fin_np_yoy")
    # 派生：现金流质量 / 资产周转
    if "cfo" in base.columns and "fin_net_profit_parent" in base.columns:
        np_ = pd.to_numeric(base["fin_net_profit_parent"], errors="coerce")
        cfo = pd.to_numeric(base["cfo"], errors="coerce")
        base["cfo_to_np"] = cfo / np_.replace(0, pd.NA)
    if "fin_oper_rev" in base.columns and "fin_tot_assets" in base.columns:
        rev = pd.to_numeric(base["fin_oper_rev"], errors="coerce")
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_asset_turn"] = rev / assets.replace(0, pd.NA)
    # 结构挖掘：杠杆 / ROA（与 profit 表 roeAvg 互补）
    if "fin_tot_liab" in base.columns and "fin_tot_assets" in base.columns:
        liab = pd.to_numeric(base["fin_tot_liab"], errors="coerce")
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_lev"] = liab / assets.replace(0, pd.NA)
    if "fin_net_profit_parent" in base.columns and "fin_tot_assets" in base.columns:
        np_ = pd.to_numeric(base["fin_net_profit_parent"], errors="coerce")
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_roa"] = np_ / assets.replace(0, pd.NA)
    elif "fin_net_profit" in base.columns and "fin_tot_assets" in base.columns:
        np_ = pd.to_numeric(base["fin_net_profit"], errors="coerce")
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_roa"] = np_ / assets.replace(0, pd.NA)

    # 利润因果链 L2：费用率 / 营运资本强度 / 合同负债 YoY 二阶
    # 按报告期排序后做相邻报告差分（日线 merge_asof 后用 _funda_event 对齐披露日）
    base = base.sort_values(["statDate", "pubDate"], na_position="last").reset_index(drop=True)
    rev = (
        pd.to_numeric(base["fin_oper_rev"], errors="coerce")
        if "fin_oper_rev" in base.columns
        else None
    )
    if rev is not None:
        sell = (
            pd.to_numeric(base["fin_selling_exp"], errors="coerce")
            if "fin_selling_exp" in base.columns
            else pd.Series(pd.NA, index=base.index)
        )
        admin = (
            pd.to_numeric(base["fin_admin_exp"], errors="coerce")
            if "fin_admin_exp" in base.columns
            else pd.Series(pd.NA, index=base.index)
        )
        opex = sell.fillna(0.0) + admin.fillna(0.0)
        has_opex = sell.notna() | admin.notna()
        base["fin_opex_ratio"] = (opex / rev.replace(0, pd.NA)).where(has_opex)
        if "fin_inventories" in base.columns:
            inv = pd.to_numeric(base["fin_inventories"], errors="coerce")
            base["fin_inv_to_rev"] = inv / rev.replace(0, pd.NA)
        if "fin_acct_rcv" in base.columns:
            ar = pd.to_numeric(base["fin_acct_rcv"], errors="coerce")
            base["fin_ar_to_rev"] = ar / rev.replace(0, pd.NA)
    if "contract_liab_yoy" in base.columns:
        cl_yoy = pd.to_numeric(base["contract_liab_yoy"], errors="coerce")
        cl_yoy = cl_yoy.where(cl_yoy.abs() <= 5.0, cl_yoy / 100.0)
        base["contract_liab_yoy"] = cl_yoy
        base["contract_liab_yoy_accel"] = cl_yoy - cl_yoy.shift(1)

    # ----- 物理世界结构：收现 / 在建工程转固 / 应付授信 / 资本开支 -----
    if rev is not None:
        if "fin_cash_from_sales" in base.columns:
            cash_sales = pd.to_numeric(base["fin_cash_from_sales"], errors="coerce")
            base["fin_cash_collect"] = cash_sales / rev.replace(0, pd.NA)
        if "fin_acct_pay" in base.columns:
            ap = pd.to_numeric(base["fin_acct_pay"], errors="coerce")
            base["fin_ap_to_rev"] = ap / rev.replace(0, pd.NA)
        if "fin_capex" in base.columns:
            capex = pd.to_numeric(base["fin_capex"], errors="coerce").abs()
            base["fin_capex_to_rev"] = capex / rev.replace(0, pd.NA)
    if "fin_cip" in base.columns and "fin_fix_assets" in base.columns:
        cip = pd.to_numeric(base["fin_cip"], errors="coerce")
        fa = pd.to_numeric(base["fin_fix_assets"], errors="coerce")
        denom = (cip.fillna(0.0) + fa.fillna(0.0)).replace(0, pd.NA)
        base["fin_cip_share"] = cip / denom
        # 转固信号原料：CIP 环比下降 + FA 环比上升（同报告期相邻）
        base["fin_cip_delta"] = cip - cip.shift(1)
        base["fin_fa_delta"] = fa - fa.shift(1)
    if "cfo" in base.columns:
        base = _attach_same_period_yoy(base, "cfo", "fin_cfo_yoy")
        if "fin_cfo_yoy" in base.columns:
            cy = pd.to_numeric(base["fin_cfo_yoy"], errors="coerce")
            base["fin_cfo_yoy_accel"] = cy - cy.shift(1)

    # ----- 银行特色：净息 / 中收 / 减值 / 贷款拨备 -----
    # 存款科目在本库 J66 覆盖为 0，不做贷存比；不良率/官方 NIM 需外源。
    if "fin_net_int_inc" in base.columns:
        base = _attach_same_period_yoy(base, "fin_net_int_inc", "fin_net_int_yoy")
        if "fin_net_int_yoy" in base.columns:
            niy = pd.to_numeric(base["fin_net_int_yoy"], errors="coerce")
            base["fin_net_int_yoy_accel"] = niy - niy.shift(1)
    if "fin_fee_inc_net" in base.columns:
        base = _attach_same_period_yoy(base, "fin_fee_inc_net", "fin_fee_yoy")
    if "fin_loans" in base.columns:
        base = _attach_same_period_yoy(base, "fin_loans", "fin_loan_growth")
    if "fin_credit_impair" in base.columns:
        base = _attach_same_period_yoy(base, "fin_credit_impair", "fin_impair_yoy")

    net_int = (
        pd.to_numeric(base["fin_net_int_inc"], errors="coerce")
        if "fin_net_int_inc" in base.columns
        else None
    )
    loans = (
        pd.to_numeric(base["fin_loans"], errors="coerce")
        if "fin_loans" in base.columns
        else None
    )
    if net_int is not None and loans is not None:
        # 粗口径息差代理：累计净息收入 / 期末贷款（趋势可比，非监管 NIM）
        base["fin_nim_proxy"] = net_int / loans.replace(0, pd.NA)
        base["fin_nim_proxy_delta"] = base["fin_nim_proxy"] - base["fin_nim_proxy"].shift(1)

    if "fin_fee_inc_net" in base.columns and "fin_oper_rev" in base.columns:
        fee = pd.to_numeric(base["fin_fee_inc_net"], errors="coerce")
        orev = pd.to_numeric(base["fin_oper_rev"], errors="coerce")
        base["fin_fee_share"] = fee / orev.replace(0, pd.NA)
        base["fin_fee_share_delta"] = base["fin_fee_share"] - base["fin_fee_share"].shift(1)

    if "fin_credit_impair" in base.columns and "fin_oper_profit" in base.columns:
        impair = pd.to_numeric(base["fin_credit_impair"], errors="coerce").abs()
        op = pd.to_numeric(base["fin_oper_profit"], errors="coerce")
        base["fin_impair_to_op"] = impair / op.replace(0, pd.NA)
        base["fin_impair_to_op_delta"] = base["fin_impair_to_op"] - base["fin_impair_to_op"].shift(1)

    if "fin_int_inc" in base.columns and "fin_int_exp" in base.columns:
        ii = pd.to_numeric(base["fin_int_inc"], errors="coerce")
        ie = pd.to_numeric(base["fin_int_exp"], errors="coerce")
        base["fin_int_spread"] = (ii - ie) / ii.replace(0, pd.NA)
        base["fin_int_spread_delta"] = base["fin_int_spread"] - base["fin_int_spread"].shift(1)

    # 拨备厚度：优先名义风险准备（J66 覆盖更全），否则 PROVISIONS
    prov = None
    if "fin_prov_nom_risks" in base.columns:
        prov = pd.to_numeric(base["fin_prov_nom_risks"], errors="coerce")
    if "fin_provisions" in base.columns:
        p2 = pd.to_numeric(base["fin_provisions"], errors="coerce")
        prov = p2 if prov is None else prov.fillna(p2)
    if prov is not None and loans is not None:
        base["fin_prov_loan"] = prov / loans.replace(0, pd.NA)
        base["fin_prov_loan_delta"] = base["fin_prov_loan"] - base["fin_prov_loan"].shift(1)

    if loans is not None and "fin_tot_assets" in base.columns:
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_loan_assets"] = loans / assets.replace(0, pd.NA)

    return base.sort_values("pubDate").reset_index(drop=True)


def enrich_price_with_fin_db(
    price: pd.DataFrame,
    code: str,
    *,
    explicit: str | Path | None = None,
    cache_base: Path | None = None,
    prefer_overwrite_balance: bool = True,
) -> pd.DataFrame:
    """把本地财务宽表 merge_asof 到日线面板。"""
    funda = merged_funda_frame(code, explicit=explicit, cache_base=cache_base)
    if funda.empty:
        return price
    cols = [c for c in funda.columns if c not in ("pubDate", "statDate", "code")]
    if not prefer_overwrite_balance:
        cols = [c for c in cols if c not in price.columns]
    return _merge_asof_local(price, funda, cols)


def summary(explicit: str | Path | None = None) -> Dict[str, Any]:
    path = resolve_db_path(explicit)
    if path is None:
        return {"available": False}
    con = connect(explicit)
    tables = {}
    for t in list_tables(explicit):
        try:
            n = con.execute(f'SELECT COUNT(1) FROM "{t}"').fetchone()[0]
        except Exception:  # noqa: BLE001
            n = -1
        tables[t] = n
    return {
        "available": True,
        "path": str(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
        "tables": tables,
        "stmt_merged": STMT_MERGED,
    }


def profit_like_from_income(
    *,
    explicit: str | Path | None = None,
    codes: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """从利润表派生 baostock 风格 profit 字段（gpMargin/npMargin/netProfit/MBRevenue）。

    毛利率 ≈ (营业收入 - 营业成本) / 营业收入；净利率 ≈ 归母净利 / 营业收入。
    银证保等无营业成本时 gpMargin 为空（与 baostock 一致）。
    总股本优先取同期资产负债表 TOT_SHR。
    """
    sql = (
        f'SELECT S_INFO_WINDCODE, ANN_DT, ACTUAL_ANN_DT, REPORT_PERIOD, '
        f"OPER_REV, LESS_OPER_COST, NET_PROFIT_EXCL_MIN_INT_INC, S_FA_EPS_BASIC "
        f'FROM "{TABLE_INCOME}" WHERE STATEMENT_TYPE = ?'
    )
    df = _query_df(sql, (STMT_MERGED,), explicit=explicit)
    if df.empty:
        return df
    df["code"] = df["S_INFO_WINDCODE"].map(wind_to_bs)
    if codes is not None:
        want = {str(c) for c in codes}
        df = df[df["code"].isin(want)]
    pub = _ymd_to_ts(df["ACTUAL_ANN_DT"])
    pub = pub.fillna(_ymd_to_ts(df["ANN_DT"]))
    df["pubDate"] = pub
    df["statDate"] = _ymd_to_ts(df["REPORT_PERIOD"])
    rev = pd.to_numeric(df["OPER_REV"], errors="coerce")
    cost = pd.to_numeric(df["LESS_OPER_COST"], errors="coerce")
    np_ = pd.to_numeric(df["NET_PROFIT_EXCL_MIN_INT_INC"], errors="coerce")
    eps = pd.to_numeric(df["S_FA_EPS_BASIC"], errors="coerce")
    df["MBRevenue"] = rev
    df["netProfit"] = np_
    df["epsTTM"] = eps
    df["gpMargin"] = (rev - cost) / rev.replace(0, pd.NA)
    df["npMargin"] = np_ / rev.replace(0, pd.NA)
    df["roeAvg"] = pd.NA
    # 同期总股本
    bal_sql = (
        f'SELECT S_INFO_WINDCODE, REPORT_PERIOD, TOT_SHR '
        f'FROM "{TABLE_BALANCE}" WHERE STATEMENT_TYPE = ?'
    )
    bal = _query_df(bal_sql, (STMT_MERGED,), explicit=explicit)
    if not bal.empty:
        bal["code"] = bal["S_INFO_WINDCODE"].map(wind_to_bs)
        if codes is not None:
            bal = bal[bal["code"].isin(want)]
        bal["statDate"] = _ymd_to_ts(bal["REPORT_PERIOD"])
        bal["totalShare"] = pd.to_numeric(bal["TOT_SHR"], errors="coerce")
        bal = (
            bal.dropna(subset=["code", "statDate"])
            .sort_values(["code", "statDate"])
            .drop_duplicates(["code", "statDate"], keep="last")
        )
        df = df.merge(bal[["code", "statDate", "totalShare"]], on=["code", "statDate"], how="left")
    else:
        df["totalShare"] = pd.NA
    df["liqaShare"] = df["totalShare"]
    out = (
        df.dropna(subset=["pubDate", "code"])
        .sort_values(["code", "pubDate", "statDate"])
        .drop_duplicates(["code", "statDate"], keep="last")
    )
    cols = [
        "code",
        "pubDate",
        "statDate",
        "roeAvg",
        "npMargin",
        "gpMargin",
        "netProfit",
        "epsTTM",
        "MBRevenue",
        "totalShare",
        "liqaShare",
    ]
    return out[cols].reset_index(drop=True)


def fill_total_share_in_profit_cache(
    out_dir: Path,
    *,
    codes: Optional[Sequence[str]] = None,
    explicit: str | Path | None = None,
) -> Dict[str, int]:
    """给已有 profit parquet 补 totalShare（缺或全空时用财务库同期股本）。"""
    out_dir = Path(out_dir)
    wide = profit_like_from_income(explicit=explicit, codes=codes)
    if wide.empty:
        return {"patched": 0, "skipped": 0}
    share = (
        wide.dropna(subset=["totalShare"])
        .sort_values(["code", "statDate"])[["code", "statDate", "totalShare", "liqaShare"]]
    )
    patched = 0
    skipped = 0
    for code, g in share.groupby("code", sort=False):
        fp = out_dir / f"{str(code).replace('.', '_')}.parquet"
        if not fp.exists():
            skipped += 1
            continue
        try:
            old = pd.read_parquet(fp)
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        if old.empty:
            skipped += 1
            continue
        if "totalShare" in old.columns and pd.to_numeric(old["totalShare"], errors="coerce").notna().any():
            skipped += 1
            continue
        old = old.copy()
        old["statDate"] = pd.to_datetime(old["statDate"], errors="coerce")
        g2 = g.copy()
        g2["statDate"] = pd.to_datetime(g2["statDate"], errors="coerce")
        merged = old.merge(
            g2[["statDate", "totalShare", "liqaShare"]],
            on="statDate",
            how="left",
            suffixes=("", "_new"),
        )
        if "totalShare_new" in merged.columns:
            merged["totalShare"] = pd.to_numeric(merged.get("totalShare"), errors="coerce")
            merged["totalShare"] = merged["totalShare"].fillna(merged["totalShare_new"])
            merged.drop(columns=["totalShare_new"], inplace=True)
        if "liqaShare_new" in merged.columns:
            merged["liqaShare"] = pd.to_numeric(merged.get("liqaShare"), errors="coerce")
            merged["liqaShare"] = merged["liqaShare"].fillna(merged["liqaShare_new"])
            merged.drop(columns=["liqaShare_new"], inplace=True)
        merged.to_parquet(fp, index=False)
        patched += 1
    return {"patched": patched, "skipped": skipped}


def export_profit_cache_from_fin_db(
    out_dir: Path,
    *,
    codes: Optional[Sequence[str]] = None,
    only_missing: bool = True,
    explicit: str | Path | None = None,
) -> Dict[str, int]:
    """把利润表派生的 profit 写入 `_shared/profit/*.parquet`。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wide = profit_like_from_income(explicit=explicit, codes=codes)
    if wide.empty:
        return {"codes": 0, "written": 0, "skipped": 0}
    written = 0
    skipped = 0
    for code, g in wide.groupby("code", sort=False):
        fp = out_dir / f"{str(code).replace('.', '_')}.parquet"
        if only_missing and fp.exists():
            try:
                old = pd.read_parquet(fp)
                if not old.empty and "gpMargin" in old.columns and old["gpMargin"].notna().any():
                    skipped += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
        g = g.sort_values("pubDate").reset_index(drop=True)
        g.to_parquet(fp, index=False)
        written += 1
    return {"codes": int(wide["code"].nunique()), "written": written, "skipped": skipped}
