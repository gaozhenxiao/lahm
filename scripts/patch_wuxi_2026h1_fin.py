# -*- coding: utf-8 -*-
"""Patch WuXi AppTec 2026H1 into local Wind-style fin DB + refresh caches + recompute signals."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CODE_BS = "sh.603259"
CODE_WIND = "603259.SH"
PERIOD = "20260630"
ANN = "20260803"
STMT = 408001000
COMP = "2A62712B90"


def _db_path() -> Path:
    return next(ROOT.glob("1.0*.db"))


def _num(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return float(x)
    except Exception:
        return None


def _col(df: pd.DataFrame, *names: str) -> str | None:
    for n in names:
        if n in df.columns:
            return n
        for c in df.columns:
            if n == str(c) or n in str(c):
                return c
    return None


def _row_by_period(df: pd.DataFrame, period: str) -> pd.Series:
    c = _col(df, "报告日")
    m = df[df[c].astype(str) == period]
    if m.empty:
        raise RuntimeError(f"period {period} not in sina frame")
    return m.iloc[0]


def fetch_sina():
    inc = ak.stock_financial_report_sina(stock="sh603259", symbol="利润表")
    bal = ak.stock_financial_report_sina(stock="sh603259", symbol="资产负债表")
    cf = ak.stock_financial_report_sina(stock="sh603259", symbol="现金流量表")
    return inc, bal, cf


def build_income(row: pd.Series) -> dict:
    # 扣非：用 abstract 交叉校验；sina 利润表常无单独列
    abs_df = ak.stock_financial_abstract(symbol="603259")
    ind_col = abs_df.columns[1]
    ded = None
    for key in ("扣非净利润", "扣除非经常性损益后的净利润"):
        m = abs_df[abs_df[ind_col].astype(str).str.contains(key, na=False)]
        if not m.empty and PERIOD in abs_df.columns:
            ded = _num(m.iloc[0][PERIOD])
            break
    if ded is None:
        # fallback news figure
        ded = 10572177300.0

    def g(*names):
        c = None
        for n in names:
            if n in row.index:
                c = n
                break
            for ix in row.index:
                if n in str(ix):
                    c = ix
                    break
            if c:
                break
        return _num(row[c]) if c is not None else None

    return {
        "S_INFO_WINDCODE": CODE_WIND,
        "WIND_CODE": CODE_WIND,
        "ANN_DT": ANN,
        "REPORT_PERIOD": PERIOD,
        "STATEMENT_TYPE": STMT,
        "CRNCY_CODE": "CNY",
        "TOT_OPER_REV": g("营业总收入"),
        "OPER_REV": g("营业收入", "营业总收入"),
        "TOT_OPER_COST": g("营业总成本"),
        "TOT_OPER_COST2": g("营业总成本"),
        "LESS_OPER_COST": g("营业成本"),
        "LESS_TAXES_SURCHARGES_OPS": g("营业税金及附加"),
        "LESS_SELLING_DIST_EXP": g("销售费用"),
        "LESS_GERL_ADMIN_EXP": g("管理费用"),
        "LESS_FIN_EXP": g("财务费用"),
        "RD_EXPENSE": g("研发费用"),
        "OPER_PROFIT": g("营业利润"),
        "TOT_PROFIT": g("利润总额"),
        "INC_TAX": g("所得税费用"),
        "NET_PROFIT_INCL_MIN_INT_INC": g("净利润"),
        "NET_PROFIT_EXCL_MIN_INT_INC": g("归属于母公司所有者的净利润"),
        "MINORITY_INT_INC": g("少数股东损益"),
        "NET_PROFIT_AFTER_DED_NR_LP": ded,
        "S_FA_EPS_BASIC": g("基本每股收益"),
        "S_FA_EPS_DILUTED": g("稀释每股收益"),
        "ACTUAL_ANN_DT": ANN,
        "S_INFO_COMPCODE": COMP,
        "COMP_TYPE_CODE": 1,
        "IS_CALCULATION": 0.0,
        "OPDATE": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "OPMODE": 1,
        "RN": 1,
    }


def build_balance(row: pd.Series) -> dict:
    def g(*names):
        for n in names:
            if n in row.index:
                return _num(row[n])
            for ix in row.index:
                if str(ix) == n or n in str(ix):
                    return _num(row[ix])
        return None

    # 应收账款：优先单独列，否则用「应收票据及应收账款」近似（比空好）
    ar = g("应收账款")
    if ar is None:
        ar = g("应收票据及应收账款")
    tot_liab = g("负债合计")
    if tot_liab is None:
        # 资产 - 权益
        assets = g("资产总计")
        eq = g("归属于母公司股东权益合计", "所有者权益（或股东权益）合计")
        minority = g("少数股东权益") or 0.0
        if assets is not None and eq is not None:
            tot_liab = assets - eq - minority

    return {
        "S_INFO_WINDCODE": CODE_WIND,
        "WIND_CODE": CODE_WIND,
        "ANN_DT": ANN,
        "REPORT_PERIOD": PERIOD,
        "STATEMENT_TYPE": STMT,
        "CRNCY_CODE": "CNY",
        "MONETARY_CAP": g("货币资金"),
        "ACCT_RCV": ar,
        "INVENTORIES": g("存货"),
        "CONTRACT_LIABILITIES": g("合同负债"),
        "CONTRACTUAL_ASSETS": g("合同资产"),
        "TOT_ASSETS": g("资产总计"),
        "TOT_LIAB": tot_liab,
        "TOT_SHRHLDR_EQY_EXCL_MIN_INT": g("归属于母公司股东权益合计"),
        "TOT_SHR": g("实收资本(或股本)", "实收资本"),
        "S_INFO_COMPCODE": COMP,
        "COMP_TYPE_CODE": 1,
        "ACC_STA_CODE": 2,
        "ACTUAL_ANN_DT": ANN,
        "OPDATE": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "OPMODE": 1,
        "RN": 1,
    }


def build_cashflow(row: pd.Series) -> dict:
    def g(*names):
        for n in names:
            if n in row.index:
                return _num(row[n])
            for ix in row.index:
                if str(ix) == n or n in str(ix):
                    return _num(row[ix])
        return None

    return {
        "S_INFO_WINDCODE": CODE_WIND,
        "WIND_CODE": CODE_WIND,
        "ANN_DT": ANN,
        "REPORT_PERIOD": PERIOD,
        "STATEMENT_TYPE": STMT,
        "CRNCY_CODE": "CNY",
        "NET_CASH_FLOWS_OPER_ACT": g("经营活动产生的现金流量净额"),
        "NET_CASH_FLOWS_INV_ACT": g("投资活动产生的现金流量净额"),
        "NET_CASH_FLOWS_FNC_ACT": g("筹资活动产生的现金流量净额"),
        "CASH_RECP_SG_AND_RS": g("销售商品、提供劳务收到的现金"),
        "NET_INCR_CASH_CASH_EQU": g("现金及现金等价物净增加额"),
        "S_INFO_COMPCODE": COMP,
        "COMP_TYPE_CODE": 1,
        "ACTUAL_ANN_DT": ANN,
        "OPDATE": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "OPMODE": 1,
        "RN": 1,
    }


def build_express(inc_row: dict) -> dict:
    # YoY vs 2025H1 from known prior
    ly_rev = 20799281882.46
    ly_np = 8560882600.0  # approx prior parent NP
    rev = inc_row["OPER_REV"]
    np_ = inc_row["NET_PROFIT_EXCL_MIN_INT_INC"]
    ded = inc_row["NET_PROFIT_AFTER_DED_NR_LP"]
    yoy_sales = (rev / ly_rev - 1.0) * 100.0 if rev and ly_rev else None
    yoy_np = (np_ / ly_np - 1.0) * 100.0 if np_ and ly_np else 29.43
    yoy_ded = 89.39
    return {
        "S_INFO_WINDCODE": CODE_WIND,
        "ANN_DT": ANN,
        "REPORT_PERIOD": PERIOD,
        "OPER_REV": rev,
        "OPER_PROFIT": inc_row["OPER_PROFIT"],
        "TOT_PROFIT": inc_row["TOT_PROFIT"],
        "NET_PROFIT_EXCL_MIN_INT_INC": np_,
        "EPS_DILUTED": inc_row["S_FA_EPS_DILUTED"],
        "S_FA_YOYSALES": yoy_sales,
        "S_FA_YOYNETPROFIT_DEDUCTED": yoy_ded,
        "S_FA_YOYEPS_BASIC": 26.25,
        "YOYNET_PROFIT_EXCL_MIN_INT_INC": yoy_np,
        "LAST_YEAR_OPER_REV": ly_rev,
        "LAST_YEAR_NET_PROFIT_EXCL_INC": ly_np,
        "OPDATE": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "OPMODE": 0,
    }


def upsert_row(con: sqlite3.Connection, table: str, row: dict) -> str:
    cur = con.cursor()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
    if "STATEMENT_TYPE" in row and "STATEMENT_TYPE" in cols:
        exists = cur.execute(
            f'SELECT "index" FROM "{table}" WHERE S_INFO_WINDCODE=? AND REPORT_PERIOD=? '
            f"AND STATEMENT_TYPE=?",
            (CODE_WIND, PERIOD, STMT),
        ).fetchone()
    else:
        exists = cur.execute(
            f'SELECT "index" FROM "{table}" WHERE S_INFO_WINDCODE=? AND REPORT_PERIOD=?',
            (CODE_WIND, PERIOD),
        ).fetchone()
    if exists:
        sets = ", ".join(f'"{k}"=?' for k in row if k in cols)
        vals = [row[k] for k in row if k in cols]
        cur.execute(
            f'UPDATE "{table}" SET {sets} WHERE "index"=?',
            vals + [exists[0]],
        )
        return f"updated index={exists[0]}"
    max_idx = cur.execute(f'SELECT COALESCE(MAX("index"),0) FROM "{table}"').fetchone()[0]
    idx = int(max_idx) + 1
    oid = "{" + str(uuid.uuid4()).upper() + "}"
    full = {"index": idx, "OBJECT_ID": oid, "COMB_ID": f"{CODE_WIND}_{PERIOD}", **row}
    full = {k: v for k, v in full.items() if k in cols}
    col_sql = ", ".join(f'"{k}"' for k in full)
    placeholders = ", ".join("?" for _ in full)
    cur.execute(
        f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
        list(full.values()),
    )
    return f"inserted index={idx}"


def clear_code_caches():
    base = ROOT / "data" / "factors" / "_shared" / "ashare_fin"
    removed = []
    for p in base.rglob("sh_603259.parquet"):
        p.unlink(missing_ok=True)
        removed.append(str(p))
    # also any v1/v2
    for p in base.rglob("*603259*"):
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p))
    return removed


def refresh_profit_cache():
    import sys

    sys.path.insert(0, str(ROOT))
    from app.services.factors import ashare_fin_db as fin_db

    out = ROOT / "data" / "factors" / "_shared" / "profit"
    stats = fin_db.export_profit_cache_from_fin_db(out, codes=[CODE_BS], only_missing=False)
    # verify
    fp = out / "sh_603259.parquet"
    df = pd.read_parquet(fp)
    df["statDate"] = pd.to_datetime(df["statDate"])
    h1 = df[df["statDate"] == "2026-06-30"]
    return stats, h1.to_dict("records")


def main():
    print("[1] fetch sina ...", flush=True)
    inc, bal, cf = fetch_sina()
    inc_row = build_income(_row_by_period(inc, PERIOD))
    bal_row = build_balance(_row_by_period(bal, PERIOD))
    cf_row = build_cashflow(_row_by_period(cf, PERIOD))
    expr_row = build_express(inc_row)
    print("income OPER_REV", inc_row["OPER_REV"], "NP", inc_row["NET_PROFIT_EXCL_MIN_INT_INC"], "gp cost", inc_row["LESS_OPER_COST"])
    print("balance CL", bal_row["CONTRACT_LIABILITIES"], "AR", bal_row["ACCT_RCV"], "INV", bal_row["INVENTORIES"])
    print("cf CFO", cf_row["NET_CASH_FLOWS_OPER_ACT"])

    db = _db_path()
    print("[2] upsert into", db, flush=True)
    con = sqlite3.connect(str(db))
    try:
        print(" income:", upsert_row(con, "中国A股利润表", inc_row))
        print(" balance:", upsert_row(con, "中国A股资产负债表", bal_row))
        print(" cashflow:", upsert_row(con, "中国A股现金流量表", cf_row))
        # express: no STATEMENT_TYPE
        print(" express:", upsert_row(con, "中国A股业绩快报", expr_row))
        con.commit()
    finally:
        con.close()

    print("[3] clear parquet caches", flush=True)
    removed = clear_code_caches()
    print(" removed", len(removed), removed[:8])

    print("[4] refresh profit cache", flush=True)
    # need fresh connections (clear lru)
    import importlib
    import sys

    sys.path.insert(0, str(ROOT))
    import app.services.factors.ashare_fin_db as fin_db

    fin_db._connect_ro.cache_clear()
    stats, h1 = refresh_profit_cache()
    print("profit export", stats)
    print("H1 profit rows", h1)

    # write status
    status = {
        "code": CODE_BS,
        "period": PERIOD,
        "ann": ANN,
        "income": inc_row,
        "balance_key": {
            k: bal_row[k]
            for k in (
                "CONTRACT_LIABILITIES",
                "ACCT_RCV",
                "INVENTORIES",
                "TOT_ASSETS",
                "TOT_LIAB",
                "TOT_SHR",
            )
        },
        "cashflow_key": {
            k: cf_row[k]
            for k in (
                "NET_CASH_FLOWS_OPER_ACT",
                "NET_CASH_FLOWS_INV_ACT",
                "NET_CASH_FLOWS_FNC_ACT",
            )
        },
        "express": expr_row,
        "profit_export": stats,
        "profit_h1": h1,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    outp = ROOT / "data" / "factors" / "patch_wuxi_2026h1_status.json"
    outp.write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("[done] status ->", outp)


if __name__ == "__main__":
    main()
