"""【已弃用写入 OHLC】新浪 getKLineData 无复权参数，写入会与前复权缓存混写。

因子回测日线统一前复权(qfq)，请改用:
  python scripts/download_daily_qfq_tencent.py --universe all_a --force

本脚本默认拒绝写入；仅在显式 --allow-raw-ohlc 时保留旧行为（调试用，禁止用于回测缓存）。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402

SINA_KLINE = (
    "https://quotes.sina.cn/cn/api/openapi.php/"
    "CN_MarketDataService.getKLineData"
)
# 实测 openapi 上限约 1970；留余量用 1960
SINA_DATALEN_MAX = 1960
TARGET_START = "2018-01-01"
PROGRESS_NAME = "download_all_a_daily_sina_progress.jsonl"
STATUS_NAME = "download_all_a_daily_sina_status.json"
DONE_NAME = "download_all_a_daily_sina_done.json"


def _bs_to_sina_symbol(code: str) -> str:
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


def _read_local(cache_dir: Path, code: str) -> Optional[pd.DataFrame]:
    path = _parquet_path(cache_dir, code)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df if not df.empty else None


def _coverage(
    df: Optional[pd.DataFrame],
    *,
    start: str,
    end_slack_days: int = 10,
) -> Dict[str, Any]:
    """评估本地是否已覆盖目标区间。"""
    today = pd.Timestamp(datetime.now().date())
    start_ts = pd.Timestamp(start)
    need_end = today - pd.Timedelta(days=end_slack_days)
    if df is None or df.empty:
        return {
            "ok": False,
            "need_history": True,
            "need_recent": True,
            "first": None,
            "last": None,
            "rows": 0,
        }
    first = df["date"].min()
    last = df["date"].max()
    # 上市晚于 start 时，起点以本地 earliest 为准（无法验证上市日，宽松：首日 <= start+40 或首日已很早）
    start_ok = pd.notna(first) and first <= start_ts + pd.Timedelta(days=40)
    # 若本地已有很长历史（>=1600 根且首日接近新浪极限），也视为 history 够
    long_enough = len(df) >= 1600 and pd.notna(first) and first <= pd.Timestamp("2019-01-01")
    end_ok = pd.notna(last) and last >= need_end
    return {
        "ok": bool((start_ok or long_enough) and end_ok),
        "need_history": not bool(start_ok or long_enough),
        "need_recent": not bool(end_ok),
        "first": str(first.date()) if pd.notna(first) else None,
        "last": str(last.date()) if pd.notna(last) else None,
        "rows": int(len(df)),
    }


def fetch_sina_daily(
    symbol: str,
    *,
    datalen: int,
    session: requests.Session,
    timeout: float = 25,
) -> pd.DataFrame:
    r = session.get(
        SINA_KLINE,
        params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)},
        timeout=timeout,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    if r.status_code == 429:
        raise RuntimeError("HTTP 429")
    r.raise_for_status()
    payload = r.json()
    rows = (((payload or {}).get("result") or {}).get("data")) or []
    if not rows:
        # json_v2 形态：直接 list
        if isinstance(payload, list):
            rows = payload
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
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
            ]
        )
    df = pd.DataFrame(rows)
    df = df.rename(columns={"day": "date"})
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("amount", "turn", "pctChg", "peTTM", "pbMRQ"):
        if c not in df.columns:
            df[c] = pd.NA
    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def merge_into_cache(code: str, fresh: pd.DataFrame, cache_dir: Path) -> Dict[str, Any]:
    path = _parquet_path(cache_dir, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = fresh.copy()
    fresh["code"] = code
    before_first = before_last = None
    old_rows = 0
    if path.exists():
        try:
            old = pd.read_parquet(path)
        except Exception:  # noqa: BLE001
            old = pd.DataFrame()
        if not old.empty:
            old["date"] = pd.to_datetime(old["date"], errors="coerce")
            old = old.dropna(subset=["date"])
            old_rows = int(len(old))
            if old_rows:
                before_first = str(old["date"].min().date())
                before_last = str(old["date"].max().date())
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
            merged = merged.drop_duplicates("date", keep="last")
            for c in ("peTTM", "pbMRQ", "turn", "pctChg", "amount"):
                if c in merged.columns:
                    merged[c] = pd.to_numeric(merged[c], errors="coerce")
                    # 估值等优先保留旧非空：同日 keep=last 后对空值用旧序列回填不完美，
                    # 这里仅 ffill 填近期空估值，避免破坏历史。
                    merged[c] = merged[c].ffill()
            out = merged.reset_index(drop=True)
        else:
            out = fresh.reset_index(drop=True)
    else:
        out = fresh.reset_index(drop=True)
    out.to_parquet(path, index=False)
    after_first = str(out["date"].min().date()) if not out.empty else None
    after_last = str(out["date"].max().date()) if not out.empty else None
    return {
        "code": code,
        "before_first": before_first,
        "before_last": before_last,
        "after_first": after_first,
        "after_last": after_last,
        "rows_before": old_rows,
        "rows": int(len(out)),
        "extended": before_last != after_last or before_first != after_first,
    }


def _sleep_interval(base: float, jitter: float) -> None:
    lo = max(0.05, base - jitter)
    hi = base + jitter
    time.sleep(random.uniform(lo, hi))


def _load_done(path: Path) -> Dict[str, Any]:
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


def process_one(
    code: str,
    *,
    cache: Path,
    session: requests.Session,
    start: str,
    interval: float,
    jitter: float,
    force: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """返回 (action, detail)。action: skip|updated|empty|error"""
    local = _read_local(cache, code)
    cov = _coverage(local, start=start)
    if cov["ok"] and not force:
        return "skip", cov

    # 智能选择 datalen：缺历史用上限；只缺最近用较小窗口
    if cov["need_history"] or local is None:
        datalen = SINA_DATALEN_MAX
    else:
        # 只补最近：约 60 根足够覆盖假期/停牌
        datalen = 80

    _sleep_interval(interval, jitter)
    sym = _bs_to_sina_symbol(code)
    try:
        fresh = fetch_sina_daily(sym, datalen=datalen, session=session)
    except Exception as exc:  # noqa: BLE001
        return "error", {"err": str(exc), **cov}

    if fresh.empty:
        return "empty", {"err": "empty sina bars", "datalen": datalen, **cov}

    # 裁掉目标起点之前（保留上市后全部；起点过滤仅丢弃更早）
    start_ts = pd.Timestamp(start)
    # 若本地已有更早历史，合并时会保留；这里对 fresh 不做强制裁切，避免丢掉可用 bar
    info = merge_into_cache(code, fresh, cache)
    after = _read_local(cache, code)
    cov2 = _coverage(after, start=start)
    info.update(
        {
            "datalen": datalen,
            "coverage_ok": cov2["ok"],
            "first": cov2["first"],
            "last": cov2["last"],
            "sina_first": str(fresh["date"].min().date()),
            "sina_last": str(fresh["date"].max().date()),
            "sina_bars": int(len(fresh)),
            # 标注：是否达到目标起点（新浪硬上限时常达不到 2018-01-01）
            "reached_target_start": bool(
                cov2["first"] and pd.Timestamp(cov2["first"]) <= start_ts + pd.Timedelta(days=40)
            ),
        }
    )
    return "updated", info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=TARGET_START, help="目标历史起点 YYYY-MM-DD")
    ap.add_argument("--interval", type=float, default=0.18, help="请求基础间隔秒")
    ap.add_argument("--jitter", type=float, default=0.05, help="间隔随机抖动秒")
    ap.add_argument("--limit", type=int, default=0, help="调试截断，0=全量")
    ap.add_argument(
        "--force-codes",
        default="",
        help="逗号分隔代码，仅处理这些（冒烟用）；覆盖 universe 截取",
    )
    ap.add_argument("--resume", action="store_true", help="跳过 done 清单中已完整的票")
    ap.add_argument("--force", action="store_true", help="忽略本地完整标记强制重拉")
    ap.add_argument(
        "--backoff-base",
        type=float,
        default=8.0,
        help="遇 429/异常时基础退避秒",
    )
    ap.add_argument(
        "--allow-raw-ohlc",
        action="store_true",
        help="危险：允许写入未复权新浪 OHLC（默认禁止，回测请用 download_daily_qfq_tencent.py）",
    )
    args = ap.parse_args()

    if not args.allow_raw_ohlc:
        raise SystemExit(
            "refused: Sina getKLineData has no qfq; writing raw OHLC corrupts "
            "data/factors/_shared/daily. Use:\n"
            "  python scripts/download_daily_qfq_tencent.py --universe all_a --force\n"
            "Or pass --allow-raw-ohlc only for non-backtest debugging."
        )

    kit.clear_proxy()
    cache = kit.shared_cache_dir()
    daily_dir = cache / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    uni = cache / "universe_all_a.parquet"
    if not uni.exists():
        raise SystemExit(f"missing {uni}; cannot proceed without universe_all_a")

    codes: List[str] = pd.read_parquet(uni)["code"].astype(str).tolist()
    if args.force_codes.strip():
        codes = [c.strip().replace("_", ".") for c in args.force_codes.split(",") if c.strip()]
    elif args.limit and args.limit > 0:
        codes = codes[: args.limit]

    progress_path = cache / PROGRESS_NAME
    status_path = cache / STATUS_NAME
    done_path = cache / DONE_NAME
    done_map = _load_done(done_path) if args.resume else {}

    status: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source": "sina_kline",
        "universe": "all_a",
        "start": args.start,
        "sina_datalen_max": SINA_DATALEN_MAX,
        "note": (
            f"Sina getKLineData max ~{SINA_DATALEN_MAX} bars "
            "(~2018-06 to latest for old names); "
            "no date-range paging; cannot reach earlier than API window"
        ),
        "total": len(codes),
        "skip": 0,
        "updated": 0,
        "empty": 0,
        "errors": 0,
        "done_ok": 0,
        "cursor": 0,
        "error_samples": [],
    }
    _save_json(status_path, status)

    sess = requests.Session()
    t0 = time.time()
    consecutive_fail = 0
    print(
        f"[sina-all-a] n={len(codes)} cache={cache} "
        f"interval={args.interval}+/-{args.jitter} max_datalen={SINA_DATALEN_MAX}",
        flush=True,
    )

    for i, code in enumerate(codes, 1):
        status["cursor"] = i
        # resume：done 清单且本地仍完整
        if args.resume and not args.force and code in done_map and done_map[code].get("ok"):
            local = _read_local(cache, code)
            cov = _coverage(local, start=args.start)
            if cov["ok"]:
                status["skip"] += 1
                status["done_ok"] += 1
                if i % 100 == 0 or i == len(codes):
                    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
                    _save_json(status_path, status)
                    print(f"[{i}/{len(codes)}] SKIP(done) {code}", flush=True)
                continue

        action = "error"
        detail: Dict[str, Any] = {}
        try:
            action, detail = process_one(
                code,
                cache=cache,
                session=sess,
                start=args.start,
                interval=args.interval,
                jitter=args.jitter,
                force=args.force,
            )
            if action == "error" and "429" in str(detail.get("err", "")):
                consecutive_fail += 1
                backoff = args.backoff_base * (2 ** min(consecutive_fail, 5)) + random.uniform(0, 3)
                print(
                    f"[{i}/{len(codes)}] BACKOFF {code} 429 sleep={backoff:.1f}s",
                    flush=True,
                )
                _save_json(status_path, status)
                time.sleep(backoff)
                # 重试一次
                action, detail = process_one(
                    code,
                    cache=cache,
                    session=sess,
                    start=args.start,
                    interval=args.interval,
                    jitter=args.jitter,
                    force=True,
                )
        except Exception as exc:  # noqa: BLE001
            action = "error"
            detail = {"err": str(exc)}
            consecutive_fail += 1
            backoff = args.backoff_base * (2 ** min(consecutive_fail, 5)) + random.uniform(0, 3)
            print(
                f"[{i}/{len(codes)}] BACKOFF {code} exc={exc} sleep={backoff:.1f}s",
                flush=True,
            )
            _save_json(status_path, status)
            time.sleep(backoff)

        if action == "skip":
            status["skip"] += 1
            status["done_ok"] += 1
            done_map[code] = {
                "ok": True,
                "first": detail.get("first"),
                "last": detail.get("last"),
                "rows": detail.get("rows"),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            consecutive_fail = 0
        elif action == "updated":
            status["updated"] += 1
            consecutive_fail = 0
            # 覆盖达标 或 已拉满新浪窗口（尽力）都记 done，避免 resume 反复重下
            ok = bool(detail.get("coverage_ok") or detail.get("sina_bars", 0) >= SINA_DATALEN_MAX - 5)
            done_map[code] = {
                "ok": ok,
                "first": detail.get("first") or detail.get("after_first"),
                "last": detail.get("last") or detail.get("after_last"),
                "rows": detail.get("rows"),
                "sina_bars": detail.get("sina_bars"),
                "reached_target_start": detail.get("reached_target_start"),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            if ok:
                status["done_ok"] += 1
        elif action == "empty":
            status["empty"] += 1
            consecutive_fail = 0
            if len(status["error_samples"]) < 20:
                status["error_samples"].append({"code": code, "err": "empty"})
        else:
            status["errors"] += 1
            consecutive_fail += 1
            if len(status["error_samples"]) < 20:
                status["error_samples"].append(
                    {"code": code, "err": str(detail.get("err", "error"))}
                )

        rec = {
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
                    "datalen",
                    "sina_bars",
                    "sina_first",
                    "sina_last",
                    "reached_target_start",
                    "coverage_ok",
                    "err",
                )
                if k in detail
            },
            "elapsed_min": round((time.time() - t0) / 60, 2),
        }
        _append_progress(progress_path, rec)

        if i % 20 == 0 or i == len(codes) or action in ("updated", "empty", "error"):
            status["updated_at"] = rec["ts"]
            status["elapsed_min"] = rec["elapsed_min"]
            _save_json(status_path, status)
            # 每 20 只落盘 done，防中断丢进度
            if i % 20 == 0 or i == len(codes):
                _save_json(done_path, done_map)
            d = rec["detail"]
            print(
                f"[{i}/{len(codes)}] {action} {code} "
                f"rows={d.get('rows')} {d.get('first')}->{d.get('last')} "
                f"sina_bars={d.get('sina_bars')} err={d.get('err')}",
                flush=True,
            )

        # 连续失败过多：加长休眠
        if consecutive_fail >= 5:
            cool = args.backoff_base * 4 + random.uniform(0, 10)
            print(f"[cool] consecutive_fail={consecutive_fail} sleep={cool:.1f}s", flush=True)
            _save_json(status_path, status)
            _save_json(done_path, done_map)
            time.sleep(cool)

    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["elapsed_min"] = round((time.time() - t0) / 60, 2)
    _save_json(status_path, status)
    _save_json(done_path, done_map)
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    print(f"[done] status -> {status_path}", flush=True)
    print(f"[done] progress -> {progress_path}", flush=True)


if __name__ == "__main__":
    main()
