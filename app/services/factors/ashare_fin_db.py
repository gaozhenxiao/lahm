"""本地「1.0_A股财务数据库.db」只读适配。

Wind 风格 SQLite：三大报表 + 业绩预告/快报 + 公司基本资料。
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
    "INTANG_ASSETS": "fin_intang_assets",
    "GOODWILL": "fin_goodwill",
}

CASHFLOW_MAP = {
    "NET_CASH_FLOWS_OPER_ACT": "cfo",
    "NET_CASH_FLOWS_INV_ACT": "cfi",
    "NET_CASH_FLOWS_FNC_ACT": "cff",
    "CASH_RECP_SG_AND_RS": "fin_cash_from_sales",
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
    """查找财务库路径：显式参数 > Settings/环境变量 > 项目根目录 1.0_*.db。"""
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
    matches = sorted(ROOT.glob("1.0_*.db"))
    if matches:
        return matches[0]
    matches = sorted((ROOT / "data").glob("1.0_*.db")) if (ROOT / "data").exists() else []
    return matches[0] if matches else None


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
            "A股财务数据库未找到。请将 1.0_A股财务数据库.db 放在项目根目录，"
            "或设置环境变量 ASHARE_FIN_DB。"
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
            return pd.read_parquet(cache_fp)
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


def fetch_express(code: str, *, explicit: str | Path | None = None, cache_base: Path | None = None) -> pd.DataFrame:
    return _fetch_statement(
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
    # 派生：现金流质量 / 资产周转
    if "cfo" in base.columns and "fin_net_profit_parent" in base.columns:
        np_ = pd.to_numeric(base["fin_net_profit_parent"], errors="coerce")
        cfo = pd.to_numeric(base["cfo"], errors="coerce")
        base["cfo_to_np"] = cfo / np_.replace(0, pd.NA)
    if "fin_oper_rev" in base.columns and "fin_tot_assets" in base.columns:
        rev = pd.to_numeric(base["fin_oper_rev"], errors="coerce")
        assets = pd.to_numeric(base["fin_tot_assets"], errors="coerce")
        base["fin_asset_turn"] = rev / assets.replace(0, pd.NA)
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
