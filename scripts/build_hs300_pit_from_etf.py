"""用沪深300ETF(510300)季报持仓近似构建点位成分（2017+）。

说明：官方逐日成分需中证/Tushare；全复制型300ETF季报持仓是公开可复现的近似。
"""
from __future__ import annotations

import codecs
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_SNAP = ROOT / "data" / "factors" / "_shared" / "hs300_pit_etf510300_snapshots.parquet"
OUT_MEM = ROOT / "data" / "factors" / "_shared" / "hs300_pit_etf510300_membership.csv"

URL = (
    "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?"
    "type=jjcc&code=510300&topline=400&year={year}&month={month}&rt=0.1"
)


def to_bs(code6: str) -> str:
    c = str(code6).zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def fetch_quarter(year: int, month: int) -> pd.DataFrame:
    req = urllib.request.Request(
        URL.format(year=year, month=month),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", "ignore")
    m = re.search(r'content:"(.*)",arryear', text)
    if not m:
        return pd.DataFrame()
    html = codecs.decode(m.group(1), "unicode_escape")
    # 持仓表里的股票代码链接更稳
    codes = re.findall(
        r"quote\.eastmoney\.com/(?:sz|sh)(\d{6})\.html",
        html,
        flags=re.I,
    )
    if not codes:
        codes = re.findall(r"(?<!\d)([036]\d{5})(?!\d)", html)
    codes = sorted(set(codes))
    if not codes:
        return pd.DataFrame()
    out = pd.DataFrame({"raw": codes})
    out["code"] = out["raw"].map(to_bs)
    out["asof_year"] = year
    out["asof_month"] = month
    out["effective_from"] = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return out


# 东财季报偶发只返回前十大/残缺持仓；稀疏期丢弃，沿用上一完整快照
MIN_PERIOD_SIZE = 200


def filter_complete_snapshots(snaps: pd.DataFrame, min_n: int = MIN_PERIOD_SIZE) -> pd.DataFrame:
    sizes = snaps.groupby("effective_from")["code"].nunique()
    keep = sizes[sizes >= min_n].index
    dropped = sizes[sizes < min_n]
    for k, v in dropped.items():
        print(f"[drop sparse] {pd.Timestamp(k).date()} n={int(v)} < {min_n}", flush=True)
    out = snaps[snaps["effective_from"].isin(keep)].copy()
    return out


def snapshots_to_membership(snaps: pd.DataFrame) -> pd.DataFrame:
    periods = (
        snaps[["effective_from"]]
        .drop_duplicates()
        .sort_values("effective_from")["effective_from"]
        .tolist()
    )
    rows = []
    for i, p0 in enumerate(periods):
        p1 = periods[i + 1] if i + 1 < len(periods) else pd.Timestamp("2100-01-01")
        codes = snaps.loc[snaps["effective_from"] == p0, "code"].astype(str).tolist()
        for c in codes:
            rows.append(
                {
                    "code": c,
                    "in_date": p0,
                    "out_date": p1,
                    "source": "etf510300",
                }
            )
    return pd.DataFrame(rows)


def write_outputs(snaps_raw: pd.DataFrame) -> None:
    OUT_SNAP.parent.mkdir(parents=True, exist_ok=True)
    snaps_raw.to_parquet(OUT_SNAP, index=False)
    snaps = filter_complete_snapshots(snaps_raw)
    if snaps.empty:
        raise SystemExit("no complete ETF snapshots after sparse filter")
    mem = snapshots_to_membership(snaps)
    mem.to_csv(OUT_MEM, index=False, encoding="utf-8-sig")
    sizes_all = snaps_raw.groupby("effective_from")["code"].nunique()
    sizes_used = snaps.groupby("effective_from")["code"].nunique()
    print(
        f"[ok] raw_periods={len(sizes_all)} used_periods={len(sizes_used)} "
        f"unique={snaps['code'].nunique()} mem_rows={len(mem)} -> {OUT_MEM}",
        flush=True,
    )
    meta = {
        "note": (
            "Approximate PIT HS300 via 510300 ETF quarterly holdings "
            "(not official daily cons). Sparse quarters (n<200) dropped; "
            "membership carries forward prior complete snapshot."
        ),
        "snapshot_file": str(OUT_SNAP),
        "membership_file": str(OUT_MEM),
        "min_period_size": MIN_PERIOD_SIZE,
        "n_periods_raw": int(len(sizes_all)),
        "n_periods": int(len(sizes_used)),
        "n_unique_codes": int(snaps["code"].nunique()),
        "period_sizes_raw": {
            str(pd.Timestamp(k).date()): int(v) for k, v in sizes_all.items()
        },
        "period_sizes": {
            str(pd.Timestamp(k).date()): int(v) for k, v in sizes_used.items()
        },
    }
    OUT_MEM.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    frames = []
    for year in range(2017, 2027):
        for month in (3, 6, 9, 12):
            if year == 2026 and month > 6:
                continue
            df = fetch_quarter(year, month)
            print(f"[{year}-{month:02d}] n={len(df)}", flush=True)
            if not df.empty:
                frames.append(df)
            time.sleep(0.35)
    if not frames:
        raise SystemExit("no ETF holdings fetched")
    write_outputs(pd.concat(frames, ignore_index=True))


if __name__ == "__main__":
    main()
