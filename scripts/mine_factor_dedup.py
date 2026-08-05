"""挖掘去重：枚举 Mongo / FACTOR_IMPL / mine_* / overnight_keep，生成指纹。

去重键：signal + universe + 关键 params 指纹
关键字段：margin/np/gp/roe/lag/brk/hold/sl/tp 及 *_by_mkv 等。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

KEY_PARAM_NAMES: Tuple[str, ...] = (
    "margin_improve",
    "margin_min",
    "np_min",
    "np_improve",
    "gp_improve",
    "gp_min",
    "roe_improve",
    "roe_min",
    "funda_lag",
    "break_days",
    "hold_days",
    "stop_loss",
    "take_profit",
    "dd_need",
    "ret20_max",
    "pullback_min",
    "base_window",
    "amp_max",
    "explosive_chg",
    "prior_yoy_max",
    "qoq_gap_min",
    "require_ma20",
    "net_profit_min",
    "mktcap_min",
    "ma_days",
    "yoy_min",
    "pe_pct_max",
    "pb_pct_max",
    "amt_dry_ratio",
    "brk_soft",
    "margin_min_by_mkv",
    "break_days_by_mkv",
    "ipo_age_lo",
    "ipo_age_hi",
    "growth_min",
    "growth_accel",
    "accel_min",
    "entry",
    "yoy_col",
    "turn_from",
    "turn_to",
    "opex_improve",
    "opex_max",
    "inv_improve",
    "inv_max",
    "ar_improve",
    "ar_max",
    "cl_accel",
    "rev_yoy_min",
    "gp_improve",
    "lev_improve",
    "lev_max",
    "roa_improve",
    "roa_min",
    "cfo_min",
    "cfo_improve",
    "asset_turn_min",
    "asset_turn_improve",
)

# 已知重点因子（即使 Mongo 已删也视为已覆盖，勿当新发现反复报）
KNOWN_ANCHORS: List[Dict[str, Any]] = [
    {
        "factor_id": "gross_expand_m16_tp35",  # #168
        "signal": "signal_gross_expand_break",
        "universe": "hs300",
        "params": {
            "margin_improve": 0.006,
            "margin_min": 0.16,
            "np_min": 0.10,
            "funda_lag": 29,
            "break_days": 60,
            "hold_days": 51,
            "stop_loss": 0.12,
            "take_profit": 0.35,
        },
        "note": "#168",
    },
    {
        "factor_id": "gross_expand_lag28_tp35",  # #166
        "signal": "signal_gross_expand_break",
        "universe": "hs300",
        "params": {
            "margin_improve": 0.006,
            "margin_min": 0.17,
            "np_min": 0.10,
            "funda_lag": 28,
            "break_days": 60,
            "hold_days": 51,
            "stop_loss": 0.12,
            "take_profit": 0.35,
        },
        "note": "#166",
    },
    {
        "factor_id": "dual_improve_hs300_mine_r1",  # #171
        "signal": "signal_dual_improve_breakout",
        "universe": "hs300",
        "params": {
            "margin_improve": 0.005,
            "margin_min": 0.15,
            "np_improve": 0.004,
            "funda_lag": 28,
            "break_days": 60,
            "hold_days": 50,
            "stop_loss": 0.12,
            "take_profit": 0.35,
        },
        "note": "#171 breakout",
    },
    {
        "factor_id": "dual_improve_meanrev",
        "signal": "signal_dual_improve_meanrev",
        "universe": "hs300",
        "params": {
            "margin_improve": 0.003,
            "break_days": 60,
            "hold_days": 25,
            "stop_loss": 0.12,
            "pullback_min": 0.06,
            "dd_need": 0.04,
        },
        "note": "meanrev deleted/known",
    },
    {
        "factor_id": "dual_improve_hs300_meanrev_r1",
        "signal": "signal_dual_improve_meanrev",
        "universe": "hs300",
        "params": {
            "margin_improve": 0.005,
            "margin_min": 0.15,
            "np_improve": 0.004,
            "funda_lag": 28,
            "break_days": 60,
            "hold_days": 50,
            "stop_loss": 0.12,
            "take_profit": 0.35,
            "pullback_min": 0.06,
            "dd_need": 0.04,
        },
        "note": "meanrev r1 known/parallel",
    },
]


def _norm_num(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        fv = float(v)
        if abs(fv - round(fv)) < 1e-12:
            return int(round(fv))
        return round(fv, 8)
    if isinstance(v, dict):
        return {str(k): _norm_num(v[k]) for k in sorted(v.keys(), key=str)}
    if isinstance(v, (list, tuple)):
        return [_norm_num(x) for x in v]
    return v


def key_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    p = params or {}
    out: Dict[str, Any] = {}
    for k in KEY_PARAM_NAMES:
        if k in p and p[k] is not None:
            out[k] = _norm_num(p[k])
    return out


def signal_name(signal: Any) -> str:
    if signal is None:
        return ""
    if callable(signal):
        return getattr(signal, "__name__", str(signal))
    s = str(signal)
    return s if s.startswith("signal_") or not s else f"signal_{s}"


def fingerprint(signal: Any, universe: str, params: Optional[Dict[str, Any]]) -> str:
    payload = {
        "signal": signal_name(signal),
        "universe": str(universe or "hs300").lower(),
        "params": key_params(params),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def soft_family_key(signal: Any, universe: str, params: Optional[Dict[str, Any]]) -> str:
    """粗粒度参数族：信号+宇宙+主要门槛/滞后/持有/突破/关键过滤器。"""
    p = key_params(params)
    coarse = {
        "signal": signal_name(signal),
        "universe": str(universe or "hs300").lower(),
        "margin_min": p.get("margin_min"),
        "margin_improve": p.get("margin_improve"),
        "np_min": p.get("np_min"),
        "np_improve": p.get("np_improve"),
        "funda_lag": p.get("funda_lag"),
        "break_days": p.get("break_days"),
        "hold_days": p.get("hold_days"),
        "margin_min_by_mkv": p.get("margin_min_by_mkv"),
        "break_days_by_mkv": p.get("break_days_by_mkv"),
        "explosive_chg": p.get("explosive_chg"),
        "pullback_min": p.get("pullback_min"),
        "dd_need": p.get("dd_need"),
        "net_profit_min": p.get("net_profit_min"),
        "mktcap_min": p.get("mktcap_min"),
        "yoy_min": p.get("yoy_min"),
        "pe_pct_max": p.get("pe_pct_max"),
        "pb_pct_max": p.get("pb_pct_max"),
        "amt_dry_ratio": p.get("amt_dry_ratio"),
        "brk_soft": p.get("brk_soft"),
        "base_window": p.get("base_window"),
        "ipo_age_lo": p.get("ipo_age_lo"),
        "ipo_age_hi": p.get("ipo_age_hi"),
    }
    raw = json.dumps(coarse, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _record(
    *,
    source: str,
    factor_id: str,
    signal: Any,
    universe: str,
    params: Dict[str, Any],
    note: str = "",
) -> Dict[str, Any]:
    sig = signal_name(signal)
    uni = str(universe or (params or {}).get("universe") or "hs300").lower()
    return {
        "source": source,
        "factor_id": factor_id,
        "signal": sig,
        "universe": uni,
        "params": key_params(params),
        "fp": fingerprint(sig, uni, params),
        "family": soft_family_key(sig, uni, params),
        "note": note,
    }


def load_mongo_records() -> List[Dict[str, Any]]:
    try:
        from pymongo import MongoClient
        from app.core.config import settings

        client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=4000)
        db = client[settings.MONGO_DB]
        rows: List[Dict[str, Any]] = []
        for doc in db.factors.find({}, {"factor_id": 1, "name": 1, "params": 1, "signal": 1}):
            fid = str(doc.get("factor_id") or "")
            params = dict(doc.get("params") or {})
            uni = params.get("universe") or "hs300"
            sig = doc.get("signal")
            if not sig:
                try:
                    from app.services.factors.factor_registry import FACTOR_IMPL

                    meta = FACTOR_IMPL.get(fid) or {}
                    sig = meta.get("signal")
                    if meta.get("params"):
                        params = {**meta["params"], **params}
                except Exception:  # noqa: BLE001
                    pass
            if not sig:
                if "gross_expand" in fid and "ma60" in fid:
                    sig = "signal_gross_expand_ma60"
                elif "gross_expand" in fid and "base" in fid:
                    sig = "signal_gross_expand_base_break"
                elif "gross_expand" in fid:
                    sig = "signal_gross_expand_break"
                elif "dual_improve_meanrev" in fid or fid.endswith("meanrev") or "meanrev" in fid:
                    sig = "signal_dual_improve_meanrev"
                elif "dual_improve" in fid:
                    sig = "signal_dual_improve_breakout"
                elif "q_np_gap" in fid:
                    sig = "signal_q_np_gap"
                elif "gp_np_tight" in fid:
                    sig = "signal_gp_np_tight_break"
                elif "gp_np" in fid and "reclaim" in fid:
                    sig = "signal_gp_np_expand_reclaim"
                elif "gp_np" in fid:
                    sig = "signal_gp_np_expand_break"
            rows.append(
                _record(
                    source="mongo",
                    factor_id=fid,
                    signal=sig,
                    universe=str(uni),
                    params=params,
                    note=str(doc.get("name") or ""),
                )
            )
        return rows
    except Exception as exc:  # noqa: BLE001
        return [
            _record(
                source="mongo_error",
                factor_id="",
                signal="",
                universe="hs300",
                params={},
                note=str(exc),
            )
        ]


def load_impl_records() -> List[Dict[str, Any]]:
    from app.services.factors.factor_registry import FACTOR_IMPL

    rows: List[Dict[str, Any]] = []
    for fid, meta in FACTOR_IMPL.items():
        params = dict(meta.get("params") or {})
        uni = params.get("universe") or "hs300"
        rows.append(
            _record(
                source="factor_impl",
                factor_id=fid,
                signal=meta.get("signal"),
                universe=str(uni),
                params=params,
            )
        )
    return rows


def load_overnight_keep_records() -> List[Dict[str, Any]]:
    path = ROOT / "data" / "factors" / "overnight_keep.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    from app.services.factors.factor_registry import FACTOR_IMPL

    rows: List[Dict[str, Any]] = []
    for bucket in ("good", "keep", "champions", "accepted"):
        ids = data.get(bucket) or []
        if not isinstance(ids, list):
            continue
        for fid in ids:
            fid = str(fid)
            meta = FACTOR_IMPL.get(fid)
            if not meta:
                rows.append(
                    _record(
                        source="overnight_keep_id_only",
                        factor_id=fid,
                        signal="",
                        universe="hs300",
                        params={},
                        note="no FACTOR_IMPL",
                    )
                )
                continue
            params = dict(meta.get("params") or {})
            rows.append(
                _record(
                    source="overnight_keep",
                    factor_id=fid,
                    signal=meta.get("signal"),
                    universe=str(params.get("universe") or "hs300"),
                    params=params,
                    note=bucket,
                )
            )
    return rows


def load_mine_dir_records(glob_pat: str = "mine_*") -> List[Dict[str, Any]]:
    root = ROOT / "data" / "factors"
    rows: List[Dict[str, Any]] = []
    if not root.exists():
        return rows
    for d in root.glob(glob_pat):
        if not d.is_dir():
            continue
        for jf in d.rglob("results.json"):
            try:
                payload = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            universe = payload.get("universe") or jf.parent.name
            for r in payload.get("all") or payload.get("ranked") or []:
                params = dict(r.get("params") or {})
                uni = params.get("universe") or universe
                sig = r.get("signal") or ""
                rows.append(
                    _record(
                        source=f"mine:{d.name}",
                        factor_id=str(r.get("cfg_id") or ""),
                        signal=sig,
                        universe=str(uni),
                        params=params,
                        note=str(jf.relative_to(root)),
                    )
                )
    return rows


def build_inventory() -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    for rec in KNOWN_ANCHORS:
        records.append(
            _record(
                source="known_anchor",
                factor_id=rec["factor_id"],
                signal=rec["signal"],
                universe=rec["universe"],
                params=rec["params"],
                note=rec.get("note") or "",
            )
        )
    records.extend(load_mongo_records())
    records.extend(load_impl_records())
    records.extend(load_overnight_keep_records())
    records.extend(load_mine_dir_records("mine_*"))

    fps: Dict[str, Dict[str, Any]] = {}
    families: Dict[str, Dict[str, Any]] = {}
    for r in records:
        if not r.get("signal") and not r.get("params"):
            continue
        fp = r["fp"]
        if fp not in fps:
            fps[fp] = r
        fam = r["family"]
        if fam not in families:
            families[fam] = r

    return {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_records": len(records),
        "n_unique_fp": len(fps),
        "n_unique_family": len(families),
        "fps": fps,
        "families": families,
        "anchors": [r for r in records if r.get("source") == "known_anchor"],
        "mongo_factor_ids": sorted(
            {r["factor_id"] for r in records if r.get("source") == "mongo" and r.get("factor_id")}
        ),
    }


class DedupIndex:
    def __init__(self, inventory: Optional[Dict[str, Any]] = None):
        self.inventory = inventory or build_inventory()
        self.fps: Set[str] = set(self.inventory.get("fps") or {})
        self.families: Set[str] = set(self.inventory.get("families") or {})

    def check(
        self, signal: Any, universe: str, params: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        fp = fingerprint(signal, universe, params)
        if fp in self.fps:
            hit = (self.inventory.get("fps") or {}).get(fp)
            return True, f"exact_fp:{hit.get('source')}:{hit.get('factor_id')}", hit
        fam = soft_family_key(signal, universe, params)
        if fam in self.families:
            hit = (self.inventory.get("families") or {}).get(fam)
            return True, f"family:{hit.get('source')}:{hit.get('factor_id')}", hit
        return False, "", None

    def add_seen(
        self,
        signal: Any,
        universe: str,
        params: Optional[Dict[str, Any]],
        factor_id: str = "",
    ) -> None:
        fp = fingerprint(signal, universe, params)
        fam = soft_family_key(signal, universe, params)
        rec = _record(
            source="session",
            factor_id=factor_id,
            signal=signal,
            universe=universe,
            params=params or {},
        )
        self.fps.add(fp)
        self.families.add(fam)
        self.inventory.setdefault("fps", {})[fp] = rec
        self.inventory.setdefault("families", {})[fam] = rec


def write_inventory_markdown(inv: Dict[str, Any], path: Path) -> Path:
    lines = [
        "# 已有因子库存（挖掘去重）",
        "",
        f"- 时间：{inv.get('built_at')}",
        f"- 记录数：{inv.get('n_records')}；唯一指纹：{inv.get('n_unique_fp')}；参数族：{inv.get('n_unique_family')}",
        "- 去重键：`signal + universe + 关键 params`（精确指纹）+ 粗粒度参数族",
        "",
        "## 锚点（#166/#168/#171 / meanrev）",
        "",
    ]
    for a in inv.get("anchors") or []:
        lines.append(
            f"- `{a.get('factor_id')}` {a.get('note')} | {a.get('signal')} | "
            f"{a.get('universe')} | fp=`{a.get('fp')}` | {a.get('params')}"
        )
    lines.append("")
    mongo_ids = inv.get("mongo_factor_ids") or []
    focus = [
        x
        for x in mongo_ids
        if any(
            k in x
            for k in ("gross_expand", "dual_improve", "gp_np", "q_np", "meanrev", "fmkv", "mkv")
        )
    ]
    lines.append(f"## Mongo 重点子集（n={len(focus)} / total={len(mongo_ids)}）")
    lines.append("")
    for x in focus:
        lines.append(f"- `{x}`")
    lines.append("")
    lines.append("## 用法")
    lines.append("挖掘脚本：`DedupIndex().check(signal, universe, params)`；命中则 skip。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (path.parent / "existing_inventory.json").write_text(
        json.dumps(
            {
                "built_at": inv.get("built_at"),
                "n_records": inv.get("n_records"),
                "n_unique_fp": inv.get("n_unique_fp"),
                "n_unique_family": inv.get("n_unique_family"),
                "mongo_factor_ids": inv.get("mongo_factor_ids"),
                "anchors": inv.get("anchors"),
                "fps": inv.get("fps"),
                "families": {
                    k: {
                        "factor_id": v.get("factor_id"),
                        "signal": v.get("signal"),
                        "universe": v.get("universe"),
                        "source": v.get("source"),
                        "params": v.get("params"),
                    }
                    for k, v in (inv.get("families") or {}).items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    inv = build_inventory()
    out = ROOT / "data" / "factors" / "mine_csi300_500_1000_round2" / "EXISTING_INVENTORY.md"
    p = write_inventory_markdown(inv, out)
    print(f"n_records={inv['n_records']} fps={inv['n_unique_fp']} families={inv['n_unique_family']}")
    print(f"wrote {p}")
