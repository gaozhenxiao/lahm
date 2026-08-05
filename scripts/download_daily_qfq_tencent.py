"""用腾讯 fqkline 下载前复权(qfq)日线，覆盖 data/factors/_shared/daily。

约定（全项目因子回测统一前复权）:
- 路径: data/factors/_shared/daily/{sh_600519}.parquet（与既有一致）
- OHLC 一律前复权；列 adjust='qfq'；旁路 meta: daily_price_meta.json
- 全量重拉时 **整文件覆盖** OHLC，禁止与未复权/他源混写；估值 peTTM/pbMRQ 可按日保留旧非空
- 新浪 getKLineData 无复权参数，禁止再写入本缓存 OHLC
- BaoStock 黑名单：本脚本不调用

腾讯单次最多约 640 根，按 end 向前翻页拼到 --start。

用法:
  # HS300 + 基准冒烟
  python scripts/download_daily_qfq_tencent.py --universe hs300 --force-codes sh.605117,sz.300896
  # HS300 全覆盖
  python scripts/download_daily_qfq_tencent.py --universe hs300 --force
  # HS300+CSI500+CSI1000 并集（全历史重拉）
  python scripts/download_daily_qfq_tencent.py --universe hs300_csi500_csi1000 --force
  # 增量：只拉最近若干根，合并写入已有 parquet（不重刷全历史）
  python scripts/download_daily_qfq_tencent.py --universe hs300_csi500_csi1000 --incremental
  # 全 A
  python scripts/download_daily_qfq_tencent.py --universe all_a --resume
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

# web.ifzq 易被 WAF/501；优先直连 ifzq，其次 proxy
TENCENT_FQ_URLS = (
    "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
)
PAGE_SIZE = 640
ADJUST = "qfq"
SOURCE = "tencent_fqkline"
META_NAME = "daily_price_meta.json"
PROGRESS_NAME = "download_daily_qfq_tencent_progress.jsonl"
STATUS_NAME = "download_daily_qfq_tencent_status.json"
DONE_NAME = "download_daily_qfq_tencent_done.json"
JUMP_WARN = 0.50


def _bs_to_tencent_symbol(code: str) -> str:
    s = str(code).strip().replace("_", ".")
    if "." in s:
        mkt, num = s.split(".", 1)
        return f"{mkt.lower()}{num}"
    if s.isdigit() and len(s) == 6:
        prefix = "sh" if s.startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{s}"
    return s.lower()


def _parquet_path(cache_dir: Path, code: str) -> Path:
    return cache_dir / "daily" / f"{code.replace('.', '_')}.parquet"


def _sleep(base: float, jitter: float) -> None:
    time.sleep(random.uniform(max(0.05, base - jitter), base + jitter))


def fetch_tencent_qfq_page(
    symbol: str,
    *,
    end: str,
    session: requests.Session,
    datalen: int = PAGE_SIZE,
    timeout: float = 30,
) -> pd.DataFrame:
    """单页前复权；字段: date,open,close,high,low,volume(手)。"""
    param = f"{symbol},day,,{end},{int(datalen)},qfq"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://gu.qq.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    last_exc: Optional[Exception] = None
    payload: Dict[str, Any] = {}
    for url in TENCENT_FQ_URLS:
        try:
            r = session.get(url, params={"param": param}, timeout=timeout, headers=headers)
            if r.status_code >= 400:
                last_exc = RuntimeError(f"HTTP {r.status_code} {url}")
                continue
            payload = r.json() or {}
            if payload.get("data"):
                break
            last_exc = RuntimeError(f"empty data from {url}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            payload = {}
    if not payload.get("data"):
        raise last_exc or RuntimeError("tencent qfq fetch failed")
    data = (payload.get("data") or {})
    if not data:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    key = next(iter(data.keys()))
    block = data.get(key) or {}
    # 股票只接受 qfqday；指数无 qfqday 时用 day（指数无公司行为混写问题）
    rows = block.get("qfqday") or []
    is_index = symbol.startswith(("sh000", "sz399"))
    if not rows and is_index:
        rows = block.get("day") or []
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    return _rows_to_ohlcv(rows)


def fetch_tencent_qfq_page_range(
    symbol: str,
    *,
    start: str,
    end: str,
    session: requests.Session,
    datalen: int = PAGE_SIZE,
    timeout: float = 30,
) -> pd.DataFrame:
    """显式起止日期的前复权窗口（按年拼接时用，避免 end 翻页锚点漂移）。"""
    param = f"{symbol},day,{start},{end},{int(datalen)},qfq"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://gu.qq.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    last_exc: Optional[Exception] = None
    payload: Dict[str, Any] = {}
    for url in TENCENT_FQ_URLS:
        try:
            r = session.get(url, params={"param": param}, timeout=timeout, headers=headers)
            if r.status_code >= 400:
                last_exc = RuntimeError(f"HTTP {r.status_code} {url}")
                continue
            payload = r.json() or {}
            if payload.get("data"):
                break
            last_exc = RuntimeError(f"empty data from {url}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            payload = {}
    if not payload.get("data"):
        raise last_exc or RuntimeError("tencent qfq fetch failed")
    data = payload.get("data") or {}
    key = next(iter(data.keys()))
    block = data.get(key) or {}
    rows = block.get("qfqday") or []
    is_index = symbol.startswith(("sh000", "sz399"))
    if not rows and is_index:
        rows = block.get("day") or []
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    return _rows_to_ohlcv(rows)


def _rows_to_ohlcv(rows: Sequence) -> pd.DataFrame:
    parsed = []
    for r in rows:
        if not r or len(r) < 6:
            continue
        parsed.append(
            {
                "date": r[0],
                "open": r[1],
                "close": r[2],
                "high": r[3],
                "low": r[4],
                "volume": r[5],
            }
        )
    if not parsed:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    out = pd.DataFrame(parsed)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["volume"] = out["volume"] * 100.0
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def fetch_tencent_qfq_range(
    code: str,
    *,
    start: str,
    session: requests.Session,
    interval: float,
    jitter: float,
    max_pages: int = 24,
) -> pd.DataFrame:
    """按自然年窗口拉前复权再拼接（比 end 向前翻页口径更稳）。"""
    del max_pages  # 兼容旧签名
    sym = _bs_to_tencent_symbol(code)
    start_ts = pd.Timestamp(start)
    y0 = int(start_ts.year)
    y1 = int(datetime.now().year)
    chunks: List[pd.DataFrame] = []
    for year in range(y0, y1 + 1):
        _sleep(interval, jitter)
        y_start = f"{year}-01-01"
        y_end = f"{year}-12-31"
        try:
            page = fetch_tencent_qfq_page_range(sym, start=y_start, end=y_end, session=session)
        except Exception:
            # 年份失败再试 end=today 的近期页（仅当年）
            if year == y1:
                page = fetch_tencent_qfq_page(sym, end=datetime.now().strftime("%Y-%m-%d"), session=session)
            else:
                raise
        if page.empty:
            continue
        page = page[(page["date"] >= pd.Timestamp(y_start)) & (page["date"] <= pd.Timestamp(y_end))]
        chunks.append(page)
    if not chunks:
        return pd.DataFrame(
            columns=[
                "date",
                "code",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turn",
                "pctChg",
                "peTTM",
                "pbMRQ",
                "adjust",
            ]
        )
    df = (
        pd.concat(chunks, ignore_index=True)
        .dropna(subset=["date", "close"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
    )
    df = df[df["date"] >= start_ts - pd.Timedelta(days=5)].copy()
    # 腾讯极早期 qfq 偶发非正/负价，丢弃无效 OHLC
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    before = len(df)
    df = df[
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["high"] >= df["low"])
    ].copy()
    dropped_bad = before - len(df)
    df["code"] = code
    df["adjust"] = ADJUST
    for c in ("amount", "turn", "pctChg", "peTTM", "pbMRQ"):
        if c not in df.columns:
            df[c] = pd.NA
    cols = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turn",
        "pctChg",
        "peTTM",
        "pbMRQ",
        "adjust",
    ]
    out = df[cols].reset_index(drop=True)
    out.attrs["dropped_bad_ohlc"] = int(dropped_bad)
    return out


def _jump_stats(df: pd.DataFrame, *, thresh: float = JUMP_WARN) -> Dict[str, Any]:
    if df is None or df.empty or "close" not in df.columns:
        return {"n_ret_gt_50pct": 0, "max_abs_ret": 0.0, "jump_dates": []}
    s = df.sort_values("date")
    ret = s["close"].astype(float).pct_change()
    # 跳过首根（上市/序列起点常不可比）
    ret = ret.iloc[1:]
    bad = ret[ret.abs() > thresh]
    jump_dates = []
    if not bad.empty:
        dates = s["date"].iloc[1:].loc[bad.index]
        for d, r in zip(dates, bad):
            jump_dates.append({"date": str(pd.Timestamp(d).date()), "ret": float(r)})
    return {
        "n_ret_gt_50pct": int(len(bad)),
        "max_abs_ret": float(ret.abs().max()) if len(ret) else 0.0,
        "jump_dates": jump_dates[:10],
    }


def trim_leading_jumps(
    df: pd.DataFrame,
    *,
    thresh: float = JUMP_WARN,
    max_jumps: int = 2,
) -> pd.DataFrame:
    """裁掉序列前部复权断裂，使剩余 |ret|>thresh 次数 <= max_jumps。"""
    if df is None or df.empty:
        return df
    s = df.sort_values("date").reset_index(drop=True)
    for _ in range(200):
        js = _jump_stats(s, thresh=thresh)
        if int(js.get("n_ret_gt_50pct") or 0) <= max_jumps:
            break
        jumps = js.get("jump_dates") or []
        if not jumps:
            break
        cut = pd.Timestamp(jumps[0]["date"])
        s2 = s[s["date"] > cut].reset_index(drop=True)
        if len(s2) < 60 or len(s2) >= len(s):
            break
        s = s2
    return s


def write_qfq_cache(
    code: str,
    fresh: pd.DataFrame,
    cache_dir: Path,
    *,
    keep_valuation: bool = True,
    incremental: bool = False,
) -> Dict[str, Any]:
    """写入前复权日线。

    - 默认：整文件覆盖 OHLC（全量重拉）；可选保留旧估值列。
    - incremental=True：保留已有历史 OHLC，仅用 fresh 按 date 覆盖/追加最近若干根。
    """
    path = _parquet_path(cache_dir, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = fresh.copy()
    fresh["date"] = pd.to_datetime(fresh["date"], errors="coerce")
    fresh = fresh.dropna(subset=["date"])
    fresh["adjust"] = ADJUST
    fresh["code"] = code
    ohlc_cols = ["open", "high", "low", "close", "volume"]
    val_cols_all = ("peTTM", "pbMRQ", "turn", "pctChg", "amount")
    old_rows = 0
    old: Optional[pd.DataFrame] = None
    if path.exists():
        try:
            old = pd.read_parquet(path)
            old["date"] = pd.to_datetime(old["date"], errors="coerce")
            old = old.dropna(subset=["date"])
            old_rows = int(len(old))
        except Exception:  # noqa: BLE001
            old = None

    if incremental and old is not None and not old.empty:
        # 历史保留；同日以腾讯 fresh OHLC 覆盖
        base = old.copy()
        for c in ohlc_cols:
            if c not in base.columns:
                base[c] = pd.NA
        if "adjust" not in base.columns:
            base["adjust"] = ADJUST
        base["code"] = code
        overlay = fresh[["date"] + [c for c in ohlc_cols if c in fresh.columns]].copy()
        overlay["adjust"] = ADJUST
        overlay["code"] = code
        # 去掉 base 中将被覆盖的日期，再 concat
        cut = set(overlay["date"].tolist())
        base = base[~base["date"].isin(cut)]
        out = pd.concat([base, overlay], ignore_index=True, sort=False)
        # 估值列：保留旧值；新日无估值则 NA
        for c in val_cols_all:
            if c not in out.columns:
                out[c] = pd.NA
        if keep_valuation:
            old_v_cols = [c for c in val_cols_all if c in old.columns]
            if old_v_cols:
                old_v = old[["date"] + old_v_cols].drop_duplicates("date", keep="last")
                out = out.drop(columns=old_v_cols, errors="ignore")
                out = out.merge(old_v, on="date", how="left")
    else:
        out = trim_leading_jumps(fresh)
        out["adjust"] = ADJUST
        out["code"] = code
        if keep_valuation and old is not None and not old.empty:
            val_cols = [c for c in val_cols_all if c in old.columns]
            if val_cols:
                old_v = old[["date"] + val_cols].drop_duplicates("date", keep="last")
                out = out.drop(columns=[c for c in val_cols if c in out.columns], errors="ignore")
                out = out.merge(old_v, on="date", how="left")

    for c in val_cols_all:
        if c not in out.columns:
            out[c] = pd.NA
    cols = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turn",
        "pctChg",
        "peTTM",
        "pbMRQ",
        "adjust",
    ]
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    out = (
        out[cols]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    # 全量路径才裁前部跳变；增量不改历史序列
    if not incremental:
        out = trim_leading_jumps(out)
        out["adjust"] = ADJUST
        out["code"] = code
    out.to_parquet(path, index=False)
    js = _jump_stats(out)
    return {
        "code": code,
        "rows": int(len(out)),
        "rows_before": old_rows,
        "first": str(out["date"].min().date()) if not out.empty else None,
        "last": str(out["date"].max().date()) if not out.empty else None,
        "adjust": ADJUST,
        "source": SOURCE,
        "incremental": bool(incremental),
        **js,
    }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_progress(path: Path, rec: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


_UNIVERSE_BENCH = {
    "hs300": ("sh.000300",),
    "csi500": ("sh.000905",),
    "csi1000": ("sh.000852",),
    "csi_core": ("sh.000300", "sh.000905", "sh.000852"),
    "hs300_csi500_csi1000": ("sh.000300", "sh.000905", "sh.000852"),
}


def _read_universe_parquet(cache: Path, name: str) -> List[str]:
    uni = cache / f"universe_{name}.parquet"
    if not uni.exists():
        raise SystemExit(f"missing {uni}")
    return pd.read_parquet(uni)["code"].astype(str).tolist()


def _universe_codes(cache: Path, universe: str, force_codes: str, limit: int) -> List[str]:
    if force_codes.strip():
        return [c.strip().replace("_", ".") for c in force_codes.split(",") if c.strip()]
    if universe == "hs300":
        codes = _read_universe_parquet(cache, "hs300") if (cache / "universe_hs300.parquet").exists() else []
        codes = list(_UNIVERSE_BENCH["hs300"]) + codes
    elif universe in ("csi500", "csi1000", "csi_core"):
        codes = _read_universe_parquet(cache, universe)
        codes = list(_UNIVERSE_BENCH[universe]) + codes
    elif universe == "hs300_csi500_csi1000":
        seen = set()
        codes: List[str] = []
        for b in _UNIVERSE_BENCH[universe]:
            if b not in seen:
                seen.add(b)
                codes.append(b)
        for name in ("hs300", "csi500", "csi1000"):
            for c in _read_universe_parquet(cache, name):
                if c not in seen:
                    seen.add(c)
                    codes.append(c)
    elif universe == "all_a":
        codes = _read_universe_parquet(cache, "all_a")
    else:
        raise SystemExit(f"unknown universe {universe}")
    if limit and limit > 0:
        codes = codes[:limit]
    return codes


def process_one(
    code: str,
    *,
    cache: Path,
    session: requests.Session,
    start: str,
    interval: float,
    jitter: float,
    incremental: bool = False,
    datalen: int = 10,
) -> Tuple[str, Dict[str, Any]]:
    try:
        if incremental:
            _sleep(interval, jitter)
            sym = _bs_to_tencent_symbol(code)
            end = datetime.now().strftime("%Y-%m-%d")
            fresh = fetch_tencent_qfq_page(sym, end=end, session=session, datalen=datalen)
            if not fresh.empty:
                # 只保留最近 datalen 根（接口可能多返回）
                fresh = fresh.sort_values("date").tail(int(datalen)).copy()
                fresh["code"] = code
                fresh["adjust"] = ADJUST
                for c in ("amount", "turn", "pctChg", "peTTM", "pbMRQ"):
                    if c not in fresh.columns:
                        fresh[c] = pd.NA
        else:
            fresh = fetch_tencent_qfq_range(
                code, start=start, session=session, interval=interval, jitter=jitter
            )
    except Exception as exc:  # noqa: BLE001
        return "error", {"err": str(exc)}
    if fresh.empty:
        return "empty", {"err": "empty tencent qfq"}
    # 无本地缓存时增量退化成写入这段近期数据（不拉全历史）
    path = _parquet_path(cache, code)
    use_inc = bool(incremental and path.exists())
    info = write_qfq_cache(
        code, fresh, cache, keep_valuation=True, incremental=use_inc
    )
    return "updated", info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--universe",
        default="hs300",
        choices=["hs300", "csi500", "csi1000", "csi_core", "hs300_csi500_csi1000", "all_a"],
    )
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--interval", type=float, default=0.12)
    ap.add_argument("--jitter", type=float, default=0.04)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force-codes", default="")
    ap.add_argument("--force", action="store_true", help="忽略 done，全部重拉")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--incremental",
        action="store_true",
        help="只拉最近若干根并合并进已有 parquet，不重刷全历史",
    )
    ap.add_argument(
        "--datalen",
        type=int,
        default=10,
        help="增量模式拉取根数（默认 10，覆盖今日及近几日）",
    )
    ap.add_argument("--backoff-base", type=float, default=6.0)
    args = ap.parse_args()

    kit.clear_proxy()
    cache = kit.shared_cache_dir()
    (cache / "daily").mkdir(parents=True, exist_ok=True)
    codes = _universe_codes(cache, args.universe, args.force_codes, args.limit)

    progress_path = cache / PROGRESS_NAME
    status_path = cache / STATUS_NAME
    done_path = cache / DONE_NAME
    # 增量始终重拉近期 bar；resume 仅用于全量模式
    done_map = (
        _load_json(done_path)
        if args.resume and not args.force and not args.incremental
        else {}
    )

    status: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source": SOURCE,
        "adjust": ADJUST,
        "universe": args.universe,
        "start": args.start,
        "incremental": bool(args.incremental),
        "datalen": int(args.datalen) if args.incremental else None,
        "total": len(codes),
        "updated": 0,
        "empty": 0,
        "errors": 0,
        "skip": 0,
        "n_with_jump_gt_50pct": 0,
        "error_samples": [],
        "jump_samples": [],
    }
    _save_json(status_path, status)

    sess = requests.Session()
    sess.trust_env = False
    t0 = time.time()
    consecutive_fail = 0
    print(
        f"[qfq-tencent] n={len(codes)} universe={args.universe} "
        f"incremental={args.incremental} datalen={args.datalen if args.incremental else '-'} "
        f"start={args.start} cache={cache}",
        flush=True,
    )

    for i, code in enumerate(codes, 1):
        if (
            args.resume
            and not args.force
            and not args.incremental
            and done_map.get(code, {}).get("ok")
        ):
            status["skip"] += 1
            if i % 50 == 0:
                print(f"[{i}/{len(codes)}] SKIP(done) {code}", flush=True)
            continue

        action, detail = "error", {}
        try:
            action, detail = process_one(
                code,
                cache=cache,
                session=sess,
                start=args.start,
                interval=args.interval,
                jitter=args.jitter,
                incremental=args.incremental,
                datalen=args.datalen,
            )
        except Exception as exc:  # noqa: BLE001
            action, detail = "error", {"err": str(exc)}

        if action == "error":
            consecutive_fail += 1
            # 501/限流：拉长冷却，最多重试 3 次
            for attempt in range(3):
                backoff = args.backoff_base * (2 ** min(consecutive_fail + attempt, 5)) + random.uniform(2, 6)
                print(
                    f"[{i}/{len(codes)}] ERROR {code} {detail.get('err')} "
                    f"retry={attempt+1}/3 sleep={backoff:.1f}",
                    flush=True,
                )
                time.sleep(backoff)
                try:
                    action, detail = process_one(
                        code,
                        cache=cache,
                        session=sess,
                        start=args.start,
                        interval=max(args.interval, 0.28),
                        jitter=args.jitter,
                        incremental=args.incremental,
                        datalen=args.datalen,
                    )
                except Exception as exc:  # noqa: BLE001
                    action, detail = "error", {"err": str(exc)}
                if action != "error":
                    break

        if action == "updated":
            status["updated"] += 1
            consecutive_fail = 0
            nj = int(detail.get("n_ret_gt_50pct") or 0)
            if nj > 0:
                status["n_with_jump_gt_50pct"] += 1
                if len(status["jump_samples"]) < 30:
                    status["jump_samples"].append(
                        {
                            "code": code,
                            "n_ret_gt_50pct": nj,
                            "max_abs_ret": detail.get("max_abs_ret"),
                            "jump_dates": detail.get("jump_dates"),
                        }
                    )
            done_map[code] = {
                "ok": True,
                "adjust": ADJUST,
                "source": SOURCE,
                "first": detail.get("first"),
                "last": detail.get("last"),
                "rows": detail.get("rows"),
                "n_ret_gt_50pct": nj,
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
        elif action == "empty":
            status["empty"] += 1
            consecutive_fail = 0
        elif action == "error":
            status["errors"] += 1
            if len(status["error_samples"]) < 25:
                status["error_samples"].append({"code": code, "err": detail.get("err")})
            consecutive_fail += 1

        _append_progress(
            progress_path,
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "i": i,
                "n": len(codes),
                "code": code,
                "action": action,
                "detail": {
                    k: detail.get(k)
                    for k in (
                        "first",
                        "last",
                        "rows",
                        "n_ret_gt_50pct",
                        "max_abs_ret",
                        "err",
                    )
                    if k in detail
                },
            },
        )
        if i % 10 == 0 or i == len(codes) or action != "updated":
            status["updated_at"] = datetime.now().isoformat(timespec="seconds")
            status["elapsed_min"] = round((time.time() - t0) / 60, 2)
            _save_json(status_path, status)
            _save_json(done_path, done_map)
            print(
                f"[{i}/{len(codes)}] {action} {code} "
                f"rows={detail.get('rows')} {detail.get('first')}->{detail.get('last')} "
                f"jumps50={detail.get('n_ret_gt_50pct')} err={detail.get('err')}",
                flush=True,
            )

    meta = {
        "adjust": ADJUST,
        "adjust_label": "前复权",
        "source": SOURCE,
        "cache_dir": str(cache / "daily"),
        "filename": "{exchange}_{code6}.parquet  e.g. sh_600519.parquet",
        "ohlc_policy": (
            "incremental: merge recent tencent qfq bars by date onto existing parquet; "
            "full: replace OHLC; never merge raw/sina OHLC into qfq"
        ),
        "valuation_policy": "peTTM/pbMRQ/turn/pctChg/amount kept from prior cache by date when present",
        "volume_unit": "shares (tencent lot * 100)",
        "blacklist": ["baostock", "sina_getKLineData_for_ohlc"],
        "universe_last_run": args.universe,
        "start": args.start,
        "incremental": bool(args.incremental),
        "datalen": int(args.datalen) if args.incremental else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "codes_updated": status["updated"],
    }
    _save_json(cache / META_NAME, meta)
    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
    _save_json(status_path, status)
    _save_json(done_path, done_map)
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    print(f"[meta] -> {cache / META_NAME}", flush=True)


if __name__ == "__main__":
    main()
