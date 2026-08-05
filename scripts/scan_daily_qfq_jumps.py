"""扫描 data/factors/_shared/daily 相邻 |ret|>阈值，检测复权混写。

用法:
  python scripts/scan_daily_qfq_jumps.py --universe hs300 --thresh 0.5
  python scripts/scan_daily_qfq_jumps.py --codes sh.605117,sz.300896
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="", choices=["", "hs300", "all_a"])
    ap.add_argument("--codes", default="")
    ap.add_argument("--thresh", type=float, default=0.5)
    ap.add_argument("--min-jumps", type=int, default=1)
    ap.add_argument(
        "--out",
        default="",
        help="输出 csv；默认 data/factors/daily_qfq_jump_scan.csv",
    )
    args = ap.parse_args()

    cache = kit.shared_cache_dir()
    daily = cache / "daily"
    if args.codes.strip():
        codes = [c.strip().replace("_", ".") for c in args.codes.split(",") if c.strip()]
    elif args.universe == "hs300":
        uni = cache / "universe_hs300.parquet"
        codes = ["sh.000300"] + pd.read_parquet(uni)["code"].astype(str).tolist()
    elif args.universe == "all_a":
        codes = pd.read_parquet(cache / "universe_all_a.parquet")["code"].astype(str).tolist()
    else:
        codes = [p.stem.replace("_", ".", 1) if p.stem.count("_") >= 1 else p.stem for p in daily.glob("*.parquet")]
        # sh_600519 -> sh.600519
        fixed = []
        for c in codes:
            parts = c.replace(".", "_").split("_")
            if len(parts) >= 2:
                fixed.append(f"{parts[0]}.{'_'.join(parts[1:])}")
            else:
                fixed.append(c)
        codes = fixed

    rows = []
    for code in codes:
        path = kit.daily_parquet_path(cache, code)
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            rows.append({"code": code, "error": str(exc)})
            continue
        js = kit.daily_jump_stats(df, thresh=args.thresh)
        adj = None
        if "adjust" in df.columns and not df.empty:
            adj = ",".join(sorted({str(x) for x in df["adjust"].dropna().unique()}))
        if js["n_ret_gt_thresh"] >= args.min_jumps:
            rows.append(
                {
                    "code": code,
                    "rows": len(df),
                    "adjust": adj,
                    "n_ret_gt_thresh": js["n_ret_gt_thresh"],
                    "max_abs_ret": js["max_abs_ret"],
                    "jump_dates": json.dumps(js["jump_dates"][:5], ensure_ascii=False),
                    "mtime": pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["n_ret_gt_thresh", "max_abs_ret"], ascending=False)
    out_path = Path(args.out) if args.out else ROOT / "data" / "factors" / "daily_qfq_jump_scan.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(
        json.dumps(
            {
                "scanned": len(codes),
                "flagged": int(len(out)),
                "thresh": args.thresh,
                "out": str(out_path),
                "top": out.head(15).to_dict(orient="records") if not out.empty else [],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
