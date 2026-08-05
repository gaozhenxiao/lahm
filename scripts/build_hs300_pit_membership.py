"""从新浪「历史成分」抓取沪深300纳入/剔除区间，构建点位可用的成分表。"""
from __future__ import annotations

import time
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "factors" / "_shared" / "hs300_membership_sina.csv"
URL = (
    "https://vip.stock.finance.sina.com.cn/corp/view/"
    "vII_HistoryComponent.php?page={page}&indexid=000300"
)


def _fetch_page(page: int) -> pd.DataFrame:
    req = urllib.request.Request(
        URL.format(page=page),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("gb18030", "ignore")
    dfs = pd.read_html(StringIO(html))
    tab = None
    for d in dfs:
        if d.shape[1] >= 4 and d.shape[0] > 5:
            tab = d.copy()
            break
    if tab is None:
        return pd.DataFrame()
    tab.columns = [f"c{i}" for i in range(tab.shape[1])]
    head0 = str(tab.iloc[0, 0])
    if ("代码" in head0) or (not str(tab.iloc[0, 0]).isdigit()):
        # 首行多为表头
        if not str(tab.iloc[1, 0]).replace(".0", "").isdigit():
            pass
        else:
            tab = tab.iloc[1:]
    tab = tab.iloc[:, :4]
    tab.columns = ["raw", "name", "in_date", "out_date"]
    tab["raw"] = (
        tab["raw"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    tab = tab[tab["raw"].str.match(r"^\d{6}$", na=False)]
    return tab.reset_index(drop=True)


def to_bs(code6: str) -> str:
    c = str(code6).zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def main() -> None:
    frames = []
    for page in range(1, 50):
        tab = _fetch_page(page)
        if tab.empty:
            print(f"[stop] empty page={page}", flush=True)
            break
        frames.append(tab)
        print(f"[page] {page} n={len(tab)}", flush=True)
        time.sleep(0.3)
    if not frames:
        raise SystemExit("no membership rows")
    df = pd.concat(frames, ignore_index=True)
    df["in_date"] = pd.to_datetime(df["in_date"], errors="coerce")
    df["out_date"] = pd.to_datetime(df["out_date"], errors="coerce")
    df["code"] = df["raw"].map(to_bs)
    df = df.dropna(subset=["in_date"]).drop_duplicates(
        ["code", "in_date", "out_date"], keep="last"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(
        f"[ok] rows={len(df)} unique={df['code'].nunique()} -> {OUT}",
        flush=True,
    )
    # 仍在指数内：out_date 为空或未来
    open_n = df["out_date"].isna().sum()
    print(f"[ok] open-ended memberships={open_n}", flush=True)


if __name__ == "__main__":
    main()
