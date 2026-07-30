"""刷新国家队因子所需行情/份额缓存至最近交易日，并可选重跑回测产物。

用法:
  python scripts/refresh_national_team_data.py
  python scripts/refresh_national_team_data.py --end 2026-07-28 --backtest
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from functools import reduce
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "factors"

# 交易指数
INDEX_SYMBOLS = {
    "000016": "sh000016",  # 上证50
    "000300": "sh000300",  # 沪深300
    "000688": "sh000688",  # 科创50
    "399997": "sz399997",  # 中证全指半导体
}
# 信号 ETF 日线
ETF_DAILY = ["510300", "510310", "510330", "510050", "512800", "588000"]
# 信号 ETF 份额
ETF_SHARE = ["510300", "510310", "510330", "510050", "512800", "588000"]
# BANK4 成分（等权）
BANK4_CODES = ["sh.601398", "sh.601939", "sh.601288", "sh.601328"]


def _clear_proxy() -> None:
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def _merge_daily(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    if new is None or new.empty:
        if path.exists():
            return pd.read_parquet(path)
        return pd.DataFrame()
    new = new.copy()
    new["date"] = pd.to_datetime(new["date"], errors="coerce")
    if "close" in new.columns:
        new["close"] = pd.to_numeric(new["close"], errors="coerce")
    if "amount" in new.columns:
        new["amount"] = pd.to_numeric(new["amount"], errors="coerce")
    keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount"] if c in new.columns]
    new = new[keep].dropna(subset=["date", "close"])
    if path.exists():
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"], errors="coerce")
        merged = pd.concat([old, new], ignore_index=True)
    else:
        merged = new
    merged = merged.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last").sort_values("date")
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)
    return merged


def refresh_index(symbol: str, ak_symbol: str, start: str) -> None:
    import akshare as ak

    path = OUT / f"{symbol}_daily.parquet"
    try:
        df = ak.stock_zh_index_daily(symbol=ak_symbol)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] index {symbol} failed: {exc}")
        return
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "amount" not in df.columns:
        df["amount"] = df.get("volume")
    df = df[df["date"] >= pd.Timestamp(start)]
    out = _merge_daily(path, df)
    print(f"[ok] {symbol}_daily -> {out['date'].max().date()} ({len(out)} rows)")
    if symbol == "399997":
        out.to_parquet(OUT / "SEMI_daily.parquet", index=False)


def refresh_etf_daily(code: str, start: str, end: str) -> None:
    from app.services.factors.national_team import fetch_etf_hist

    path = OUT / f"{code}_daily.parquet"
    df = fetch_etf_hist(code, start=start.replace("-", ""), end=end.replace("-", ""))
    out = _merge_daily(path, df)
    if out.empty:
        print(f"[warn] {code}_daily empty")
    else:
        print(f"[ok] {code}_daily -> {out['date'].max().date()} ({len(out)} rows)")


def refresh_etf_share(code: str, lookback: int = 40) -> None:
    """强制拉近日份额并写回缓存。"""
    os.environ["NT_FORCE_SHARE_LIVE"] = "1"
    from app.services.factors.national_team import fetch_etf_share_series, load_cached_etf_share

    path = OUT / f"{code}_share.parquet"
    live = fetch_etf_share_series(code, lookback_calendar_days=lookback)
    cached = load_cached_etf_share(code)
    frames = [x for x in (cached, live) if x is not None and not x.empty]
    if not frames:
        print(f"[warn] {code}_share empty")
        return
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["share"] = pd.to_numeric(out["share"], errors="coerce")
    out = out.dropna(subset=["date", "share"]).drop_duplicates("date", keep="last").sort_values("date")
    out["share_chg"] = out["share"].pct_change()
    out.to_parquet(path, index=False)
    print(f"[ok] {code}_share -> {out['date'].max().date()} ({len(out)} rows)")


def refresh_bank4(end: str) -> None:
    import baostock as bs

    path = OUT / "BANK4_daily.parquet"
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[warn] baostock login failed: {lg.error_msg}")
        return
    frames = []
    try:
        for code in BANK4_CODES:
            rs = bs.query_history_k_data_plus(
                code,
                "date,close",
                start_date="2012-01-01",
                end_date=end,
                frequency="d",
                adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            df = pd.DataFrame(rows, columns=["date", "close"])
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.rename(columns={"close": code[-6:]})
            frames.append(df)
            print(f"  bank {code[-6:]} {len(df)}")
    finally:
        bs.logout()
    if not frames:
        print("[warn] BANK4 empty")
        return
    m = reduce(lambda a, b: pd.merge(a, b, on="date", how="outer"), frames).sort_values("date")
    cols = [c for c in m.columns if c != "date"]
    rets = m[cols].pct_change()
    basket_ret = rets.mean(axis=1, skipna=True)
    close = (1 + basket_ret.fillna(0)).cumprod() * 1000.0
    # 锚定：若已有历史，用旧序列起点对齐避免整体重置
    out = pd.DataFrame({"date": m["date"], "close": close})
    if path.exists():
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"], errors="coerce")
        # 用重叠日比例缩放新序列，保持净值连续
        both = out.merge(old.rename(columns={"close": "old"}), on="date", how="inner").dropna()
        if len(both) >= 5:
            scale = float((both["old"] / both["close"]).median())
            out["close"] = out["close"] * scale
    out = _merge_daily(path, out[["date", "close"]])
    print(f"[ok] BANK4_daily -> {out['date'].max().date()} ({len(out)} rows)")


def refresh_share_curve(end: str) -> None:
    """重画份额历史曲线 + 面板 CSV。"""
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    codes = [("510300", 0.60, "华泰柏瑞沪深300"), ("510310", 0.22, "易方达沪深300"), ("510330", 0.18, "华夏沪深300")]
    bt_path = OUT / "national_team_backtest.csv"
    if not bt_path.exists():
        print("[skip] share curve: no backtest csv yet")
        return
    bt = pd.read_csv(bt_path)
    bt["date"] = pd.to_datetime(bt["date"])
    cal = bt[["date"]].drop_duplicates().sort_values("date")
    panel = cal.copy()
    for code, w, _name in codes:
        sub = pd.read_parquet(OUT / f"{code}_share.parquet")
        sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
        sub = sub[["date", "share"]].dropna().sort_values("date")
        m = pd.merge_asof(cal, sub, on="date", direction="backward")
        panel[code] = m["share"]
        panel[code] = panel[code].ffill()
    panel["w_share"] = sum(panel[c] * w for c, w, _ in codes)
    if "share_z" in bt.columns:
        panel = panel.merge(bt[["date", "share_z", "position", "episode_state"]], on="date", how="left")
    panel.to_csv(OUT / "huijin_etf_share_history.csv", index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), dpi=140, sharex=True)
    ax = axes[0]
    for code, w, name in codes:
        ax.plot(panel["date"], panel[code] / 1e8, lw=1.25, label=f"{code} {name}")
    ax.set_ylabel("份额（亿份）")
    ax.set_title("汇金信号ETF份额历史（510300 / 510310 / 510330）")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.25)

    ax = axes[1]
    for code, w, name in codes:
        s = panel[code]
        base = s.dropna().iloc[0]
        ax.plot(panel["date"], s / base * 100.0, lw=1.2, label=f"{code}")
    ws = panel["w_share"]
    ax.plot(panel["date"], ws / ws.dropna().iloc[0] * 100.0, color="#c0392b", lw=1.8, label="加权合成 60/22/18")
    ax.set_ylabel("份额指数（起点=100）")
    ax.set_title("份额相对变化")
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=2)
    ax.grid(True, alpha=0.25)

    ax = axes[2]
    if "share_z" in panel.columns:
        ax.plot(panel["date"], panel["share_z"], color="#1f4e79", lw=1.1, label="share_z")
        ax.axhline(0.03, color="#1a7f37", ls="--", lw=0.9, label="确认线 0.03")
        ax.axhline(-0.14, color="#e67e22", ls="--", lw=0.9, label="软减仓 -0.14")
        ax.axhline(-0.28, color="#c0392b", ls="--", lw=0.9, label="硬减仓 -0.28")
    ax.set_ylabel("share_z")
    ax.set_xlabel("日期")
    ax.set_title("策略份额因子 share_z")
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=2)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "huijin_etf_share_curve.png", bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] huijin_etf_share_curve.png / history.csv (end~{panel['date'].max().date()})")


def write_trade_history() -> None:
    def extract(csv_path: Path, logic: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"])
        # 优先用已落地的执行仓位；否则用决策仓位
        pos_col = "position_exec" if "position_exec" in df.columns else "position"
        pos = df[pos_col].fillna(0.0)
        prev = pos.shift(1).fillna(0.0)
        state = df["episode_state"] if "episode_state" in df.columns else None
        if "strategy_ret" in df.columns:
            equity = (1.0 + df["strategy_ret"].fillna(0.0)).cumprod()
        else:
            equity = pd.Series(1.0, index=df.index)
        rows = []
        for i in range(len(df)):
            p, q = float(pos.iloc[i]), float(prev.iloc[i])
            if q <= 0.02 and p > 0.02:
                action = "开仓"
            elif q > 0.02 and p <= 0.02:
                action = "清仓"
            elif abs(p - q) >= 0.05 and max(p, q) > 0.02:
                action = "加仓" if p > q else "减仓"
            else:
                continue
            rows.append(
                {
                    "date": df["date"].iloc[i].strftime("%Y-%m-%d"),
                    "logic": logic,
                    "action": action,
                    "position_before": round(q, 4),
                    "position_after": round(p, 4),
                    "delta": round(p - q, 4),
                    "equity": round(float(equity.iloc[i]), 4),
                    "day_ret": None
                    if "strategy_ret" not in df.columns or pd.isna(df["strategy_ret"].iloc[i])
                    else f"{float(df['strategy_ret'].iloc[i]) * 100:.2f}%",
                    "state": state.iloc[i] if state is not None else "",
                    "share_z": None
                    if "share_z" not in df.columns or pd.isna(df["share_z"].iloc[i])
                    else round(float(df["share_z"].iloc[i]), 4),
                    "era": df["era"].iloc[i] if "era" in df.columns else None,
                    "close": float(df["close"].iloc[i]) if "close" in df.columns else None,
                }
            )
        return pd.DataFrame(rows)

    lh = extract(OUT / "national_team_backtest.csv", "long_hold")
    ct = extract(OUT / "national_team_backtest_continuous.csv", "continuous")
    lh.to_csv(OUT / "national_team_trade_history_long_hold.csv", index=False, encoding="utf-8-sig")
    ct.to_csv(OUT / "national_team_trade_history_continuous.csv", index=False, encoding="utf-8-sig")
    pd.concat([lh, ct], ignore_index=True).to_csv(
        OUT / "national_team_trade_history.csv", index=False, encoding="utf-8-sig"
    )
    print(f"[ok] trade history long_hold={len(lh)} continuous={len(ct)}")


def main() -> None:
    _clear_proxy()
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--backtest", action="store_true", help="刷新后重跑 compare 回测并写操作历史")
    parser.add_argument("--share-lookback", type=int, default=45)
    args = parser.parse_args()
    end = args.end
    print(f"[refresh] end={end}")

    print("\n== indices ==")
    for sym, ak_sym in INDEX_SYMBOLS.items():
        refresh_index(sym, ak_sym, args.start)

    print("\n== BANK4 ==")
    refresh_bank4(end)

    print("\n== ETF daily ==")
    for code in ETF_DAILY:
        refresh_etf_daily(code, "20120101", end)

    print("\n== ETF share ==")
    for code in ETF_SHARE:
        refresh_etf_share(code, lookback=args.share_lookback)

    if args.backtest:
        print("\n== backtest ==")
        import subprocess

        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "backtest_national_team_factor.py"),
            "--logic",
            "compare",
            "--mode",
            "long_flat",
            "--start",
            "2012-05-28",
            "--end",
            end,
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        subprocess.check_call(cmd, cwd=str(ROOT), env=env)
        refresh_share_curve(end)
        write_trade_history()

    print("\n[refresh] done")
    # summary
    for pattern in ("*_daily.parquet", "*_share.parquet"):
        for p in sorted(OUT.glob(pattern)):
            try:
                d = pd.read_parquet(p)
                dt = pd.to_datetime(d["date"], errors="coerce")
                print(f"  {p.name:28} {dt.min().date()} -> {dt.max().date()}  n={len(d)}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {p.name}: {exc}")


if __name__ == "__main__":
    main()
