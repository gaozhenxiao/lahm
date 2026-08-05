"""下载并缓存沪深300股指期货 IF0 + 基差 + 期权波动率代理到 _shared。

数据源：akshare（新浪主力连续 IF0；中证500/300 波动率 QVIX 用 300ETF 期权隐含波动）
BaoStock 禁用。股票现货仍用腾讯 qfq 本地 `daily/sh_000300.parquet`。

产物：
  data/factors/_shared/futures/IF0_daily.parquet
  data/factors/_shared/futures/IF0_basis.parquet   # IF vs spot 升贴水
  data/factors/_shared/options/qvix_300etf.parquet
  data/factors/_shared/futures/meta.json

局限：
  - IF0 为新浪主力连续，换月跳空未做回测修正
  - IO 单合约日频链难以精确定价；用 300ETF QVIX 作波动率代理（非真实期权盈亏）
  - index_option_300index_qvix 当前接口返回全 NaN，故不用
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

SHARED = kit.shared_cache_dir()
FUT_DIR = SHARED / "futures"
OPT_DIR = SHARED / "options"


def _download_if0() -> pd.DataFrame:
    import akshare as ak

    raw = ak.futures_zh_daily_sina(symbol="IF0")
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume", "hold", "settle"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df["symbol"] = "IF0"
    df["source"] = "akshare:futures_zh_daily_sina"
    df["ret"] = df["close"].pct_change()
    return df


def _load_spot() -> pd.DataFrame:
    path = SHARED / "daily" / "sh_000300.parquet"
    if not path.exists():
        raise SystemExit(f"missing HS300 spot cache: {path}")
    spot = pd.read_parquet(path)
    spot["date"] = pd.to_datetime(spot["date"], errors="coerce")
    spot["close"] = pd.to_numeric(spot["close"], errors="coerce")
    spot = spot.dropna(subset=["date", "close"]).sort_values("date")
    return spot[["date", "close"]].rename(columns={"close": "spot_close"})


def _build_basis(if0: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    m = if0[["date", "close", "ret"]].rename(columns={"close": "if_close", "ret": "if_ret"})
    m = m.merge(spot, on="date", how="inner")
    m["basis"] = m["if_close"] - m["spot_close"]
    m["basis_pct"] = m["basis"] / m["spot_close"]
    m["spot_ret"] = m["spot_close"].pct_change()
    # 贴水=负；升水=正
    m["discount"] = m["basis_pct"] < 0
    # 近20日分位：越低越贴水
    m["basis_pct_rank20"] = m["basis_pct"].rolling(20, min_periods=10).apply(
        lambda s: float(pd.Series(s).rank(pct=True).iloc[-1]), raw=False
    )
    m["basis_pct_z60"] = (
        (m["basis_pct"] - m["basis_pct"].rolling(60, min_periods=20).mean())
        / m["basis_pct"].rolling(60, min_periods=20).std()
    )
    return m


def _download_qvix() -> pd.DataFrame:
    import akshare as ak

    raw = ak.index_option_300etf_qvix()
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df["symbol"] = "qvix_300etf"
    df["source"] = "akshare:index_option_300etf_qvix"
    df["qvix_ret"] = df["close"].pct_change()
    df["qvix_z60"] = (
        (df["close"] - df["close"].rolling(60, min_periods=20).mean())
        / df["close"].rolling(60, min_periods=20).std()
    )
    return df


def main() -> None:
    FUT_DIR.mkdir(parents=True, exist_ok=True)
    OPT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/3] download IF0 ...", flush=True)
    if0 = _download_if0()
    if0_path = FUT_DIR / "IF0_daily.parquet"
    if0.to_parquet(if0_path, index=False)
    print(f"  -> {if0_path} rows={len(if0)} {if0['date'].min().date()}~{if0['date'].max().date()}", flush=True)

    print("[2/3] build basis vs HS300 spot ...", flush=True)
    spot = _load_spot()
    basis = _build_basis(if0, spot)
    basis_path = FUT_DIR / "IF0_basis.parquet"
    basis.to_parquet(basis_path, index=False)
    print(
        f"  -> {basis_path} rows={len(basis)} "
        f"basis_pct mean={basis['basis_pct'].mean():.4%} "
        f"median={basis['basis_pct'].median():.4%}",
        flush=True,
    )

    print("[3/3] download 300ETF QVIX (options vol proxy) ...", flush=True)
    qvix = _download_qvix()
    qvix_path = OPT_DIR / "qvix_300etf.parquet"
    qvix.to_parquet(qvix_path, index=False)
    print(
        f"  -> {qvix_path} rows={len(qvix)} {qvix['date'].min().date()}~{qvix['date'].max().date()}",
        flush=True,
    )

    meta: Dict[str, Any] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "baostock": "disabled",
        "if0": {
            "path": str(if0_path.relative_to(ROOT)),
            "rows": int(len(if0)),
            "start": str(if0["date"].min().date()),
            "end": str(if0["date"].max().date()),
            "source": "akshare:futures_zh_daily_sina symbol=IF0",
            "note": "主力连续；换月跳空未修正",
        },
        "basis": {
            "path": str(basis_path.relative_to(ROOT)),
            "rows": int(len(basis)),
            "spot": "data/factors/_shared/daily/sh_000300.parquet",
            "formula": "basis_pct = (IF_close - spot_close) / spot_close；负=贴水",
        },
        "qvix_300etf": {
            "path": str(qvix_path.relative_to(ROOT)),
            "rows": int(len(qvix)),
            "start": str(qvix["date"].min().date()),
            "end": str(qvix["date"].max().date()),
            "source": "akshare:index_option_300etf_qvix",
            "note": "波动率代理，非真实 IO 合约盈亏；300index_qvix 接口全 NaN 故弃用",
        },
    }
    meta_path = FUT_DIR / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] meta -> {meta_path}", flush=True)
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
