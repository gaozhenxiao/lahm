"""恢复 wave84_tp35_cross 的 gross_expand_m16_tp35（静态 HS300），仅写本地产物，不写 Mongo。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.factors import bs_kit as kit  # noqa: E402
from app.services.factors import signal_specs as sig  # noqa: E402
from app.services.factors import runner as runner  # noqa: E402

FACTOR_ID = "gross_expand_m16_tp35_hs300_restore_wave84"
OUT = ROOT / "data" / "factors" / "gross_expand_m16_tp35_hs300_restore_wave84.json"

# wave84 注册表 params + _COMMON（与 overnight 一致）；无 net_profit_min
PARAMS = {
    "universe": "hs300",
    "price_start": "2016-01-01",
    "price_end": "2026-07-30",  # 对齐 wave84_tp35_cross_full 区间末日
    "max_positions": 8,
    "commission_rate": 0.0001,
    "stamp_tax_sell": 0.001,
    "request_interval_sec": 0.35,
    "bench_code": "sh.000300",
    "margin_improve": 0.006,
    "margin_min": 0.16,
    "np_min": 0.10,
    "funda_lag": 29,
    "break_days": 60,
    "hold_days": 51,
    "stop_loss": 0.12,
    "take_profit": 0.35,
}

TARGET = {"total_return": 35.0207, "sharpe": 1.6029}


def main() -> None:
    # 禁用 BaoStock：登录即失败 → 日线/利润走本地缓存
    def _bs_disabled(*_a, **_k):
        raise RuntimeError("BaoStock disabled (restore wave84 local-cache only)")

    kit.bs_login = _bs_disabled  # type: ignore[assignment]

    cache = kit.shared_cache_dir()
    codes = kit.fetch_universe_codes("hs300", kit.RateLimiter(0.01), cache, force=False)
    print(f"[universe] hs300 cached codes={len(codes)}", flush=True)
    print(f"[params] {json.dumps(PARAMS, ensure_ascii=False)}", flush=True)

    summary = runner.run_factor_pipeline(
        FACTOR_ID,
        "restore wave84 gross_expand_m16_tp35 static hs300",
        sig.signal_gross_expand_break,
        PARAMS,
        need_profit=True,
        need_growth=False,
        limit=0,
        start="2018-01-01",
    )

    ret = summary.get("total_return")
    sharpe = summary.get("sharpe")
    ok = (
        isinstance(ret, (int, float))
        and isinstance(sharpe, (int, float))
        and abs(float(ret) - TARGET["total_return"]) < 0.02
        and abs(float(sharpe) - TARGET["sharpe"]) < 0.01
    )
    payload = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "wave84_tp35_cross / overnight_keep",
        "factor_id_original": "gross_expand_m16_tp35",
        "signal": "signal_gross_expand_break",
        "universe": "hs300",
        "baostock": "disabled_cache_only",
        "mongo_written": False,
        "target": TARGET,
        "reproduced": ok,
        "params": PARAMS,
        "summary": summary,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    print(f"[ok] -> {OUT}", flush=True)
    print(
        f"[verdict] reproduced={ok} ret={ret} sharpe={sharpe} "
        f"(target {TARGET['total_return']}/{TARGET['sharpe']})",
        flush=True,
    )


if __name__ == "__main__":
    main()
