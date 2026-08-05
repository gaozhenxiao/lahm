"""【已弃用】新浪未复权增量合并会污染前复权日线缓存。

请改用腾讯前复权整文件覆盖:
  python scripts/download_daily_qfq_tencent.py --universe hs300 --force

本脚本默认拒绝执行；仅 --allow-raw-ohlc 保留旧新浪合并（禁止用于回测）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

SINA_KLINE = (
    "https://quotes.sina.cn/cn/api/openapi.php/"
    "CN_MarketDataService.getKLineData"
)


def _clear_proxy() -> None:
    kit.clear_proxy()


def _bs_to_sina_symbol(code: str) -> str:
    """sh.600519 -> sh600519; sh.000300 -> sh000300"""
    s = str(code).strip().replace("_", ".")
    if "." in s:
        mkt, num = s.split(".", 1)
        return f"{mkt.lower()}{num}"
    if s.isdigit() and len(s) == 6:
        prefix = "sh" if s.startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{s}"
    return s.lower()


def fetch_sina_daily(symbol: str, *, datalen: int = 40, session: Optional[requests.Session] = None) -> pd.DataFrame:
    sess = session or requests.Session()
    r = sess.get(
        SINA_KLINE,
        params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)},
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    r.raise_for_status()
    payload = r.json()
    rows = (((payload or {}).get("result") or {}).get("data")) or []
    if not rows:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "amount", "turn", "pctChg", "peTTM", "pbMRQ"]
        )
    df = pd.DataFrame(rows)
    df = df.rename(columns={"day": "date"})
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.NA
    df["turn"] = pd.NA
    df["pctChg"] = pd.NA
    df["peTTM"] = pd.NA
    df["pbMRQ"] = pd.NA
    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def merge_into_cache(code: str, fresh: pd.DataFrame, cache_dir: Path) -> Dict[str, Any]:
    path = cache_dir / "daily" / f"{code.replace('.', '_')}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = fresh.copy()
    fresh["code"] = code
    before_last = None
    if path.exists():
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"], errors="coerce")
        before_last = str(old["date"].max().date()) if old["date"].notna().any() else None
        # 新行补齐列；估值字段优先保留旧值
        for c in ("amount", "turn", "pctChg", "peTTM", "pbMRQ"):
            if c not in fresh.columns:
                fresh[c] = pd.NA
        if "code" not in old.columns:
            old["code"] = code
        merged = (
            pd.concat([old, fresh], ignore_index=True)
            .dropna(subset=["date", "close"])
            .sort_values("date")
        )
        # keep=last 后，同日若新行估值为空则用旧行估值回填
        merged = merged.drop_duplicates("date", keep="last")
        # 对估值 NaN 用同日旧值：已 keep last，再对 pe/pb 做 ffill 仅限增量末日
        for c in ("peTTM", "pbMRQ", "turn", "pctChg", "amount"):
            if c in merged.columns:
                merged[c] = pd.to_numeric(merged[c], errors="coerce")
                merged[c] = merged[c].ffill()
        out = merged.reset_index(drop=True)
    else:
        out = fresh.reset_index(drop=True)
    out.to_parquet(path, index=False)
    after_last = str(out["date"].max().date()) if not out.empty else None
    return {
        "code": code,
        "before_last": before_last,
        "after_last": after_last,
        "rows": int(len(out)),
        "extended": before_last != after_last,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datalen", type=int, default=40, help="新浪拉取近期 bar 数")
    ap.add_argument("--interval", type=float, default=0.12)
    ap.add_argument("--limit", type=int, default=0, help="调试截断，0=全量 HS300")
    ap.add_argument(
        "--allow-raw-ohlc",
        action="store_true",
        help="危险：允许未复权新浪 OHLC 合并进缓存（默认禁止）",
    )
    args = ap.parse_args()

    if not args.allow_raw_ohlc:
        raise SystemExit(
            "refused: Sina bars are unadjusted and must not merge into qfq cache. Use:\n"
            "  python scripts/download_daily_qfq_tencent.py --universe hs300 --force\n"
            "Or pass --allow-raw-ohlc only for non-backtest debugging."
        )

    _clear_proxy()
    cache = kit.shared_cache_dir()
    limiter = kit.RateLimiter(args.interval)
    # 宇宙优先读本地；baostock 挂了也不影响
    uni = cache / "universe_hs300.parquet"
    if not uni.exists():
        raise SystemExit("missing universe_hs300.parquet; cannot refresh without baostock")
    codes: List[str] = pd.read_parquet(uni)["code"].astype(str).tolist()
    if args.limit and args.limit > 0:
        codes = codes[: args.limit]
    targets = ["sh.000300"] + codes

    sess = requests.Session()
    status: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source": "sina_kline",
        "note": "CNINFO daily API requires token; baostock login failed → sina fallback",
        "total": len(targets),
        "ok": 0,
        "extended": 0,
        "errors": 0,
        "error_samples": [],
    }
    t0 = time.time()
    print(f"[sina-daily] n={len(targets)} cache={cache}", flush=True)

    for i, code in enumerate(targets, 1):
        try:
            limiter.wait()
            sym = _bs_to_sina_symbol(code)
            fresh = fetch_sina_daily(sym, datalen=args.datalen, session=sess)
            if fresh.empty:
                raise RuntimeError("empty sina bars")
            info = merge_into_cache(code, fresh, cache)
            status["ok"] += 1
            if info.get("extended"):
                status["extended"] += 1
            if i % 20 == 0 or i == len(targets) or info.get("extended"):
                print(
                    f"[{i}/{len(targets)}] {code} last {info.get('before_last')} -> {info.get('after_last')}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            status["errors"] += 1
            if len(status["error_samples"]) < 12:
                status["error_samples"].append({"code": code, "err": str(exc)})
            print(f"[{i}/{len(targets)}] FAIL {code}: {exc}", flush=True)

    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
    # 汇总末日
    lasts = []
    for code in targets:
        p = cache / "daily" / f"{code.replace('.', '_')}.parquet"
        if p.exists():
            df = pd.read_parquet(p, columns=["date"])
            if not df.empty:
                lasts.append(pd.to_datetime(df["date"], errors="coerce").max())
    if lasts:
        status["latest_date_mode"] = str(pd.Series(lasts).mode().iloc[0].date())
        status["latest_date_max"] = str(pd.Series(lasts).max().date())
        status["latest_date_min"] = str(pd.Series(lasts).min().date())

    out = cache / "update_hs300_daily_sina_status.json"
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    print(f"[done] -> {out}", flush=True)


if __name__ == "__main__":
    main()
