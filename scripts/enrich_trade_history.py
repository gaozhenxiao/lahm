"""为存量 trade_history.csv 补齐 buy_position / nav_pnl，并在卖出备注写入买入日与成本价。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FACTORS = ROOT / "data" / "factors"

_ENTRY_NOTE_RE = re.compile(r"[；;]?\s*买入\d{4}-\d{2}-\d{2}\s*成本价[\d.]+")


def _parse_pct(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _strip_entry_note(note: str) -> str:
    return _ENTRY_NOTE_RE.sub("", str(note or "")).rstrip("；; ").strip()


def _with_entry_note(note: str, entry_date: str, cost: float) -> str:
    base = _strip_entry_note(note)
    extra = f"买入{entry_date} 成本价{cost:.4f}"
    return f"{base}；{extra}" if base else extra


def _max_pos(factor_id: str) -> int:
    path = FACTORS / f"{factor_id}_backtest.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            p = raw.get("params") or {}
            return int(p.get("max_positions") or 8)
        except Exception:  # noqa: BLE001
            pass
    return 8


def enrich_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "buy_position" not in out.columns:
        out["buy_position"] = ""
    if "nav_pnl" not in out.columns:
        out["nav_pnl"] = ""
    if "note" not in out.columns:
        out["note"] = ""
    out["buy_position"] = out["buy_position"].astype(object)
    out["nav_pnl"] = out["nav_pnl"].astype(object)
    out["note"] = out["note"].astype(object)
    entry_eq = None
    entry_pos = None
    entry_date = None
    entry_cost = None
    for i, row in out.iterrows():
        action = str(row.get("action") or "")
        eq = pd.to_numeric(row.get("equity"), errors="coerce")
        p_after = pd.to_numeric(row.get("position_after"), errors="coerce")
        p_before = pd.to_numeric(row.get("position_before"), errors="coerce")
        delta = pd.to_numeric(row.get("delta"), errors="coerce")
        close = pd.to_numeric(row.get("close"), errors="coerce")
        price = pd.to_numeric(row.get("price"), errors="coerce")
        cost = close if pd.notna(close) else price
        dt = str(row.get("date") or "")[:10]
        if action in ("开仓", "加仓"):
            pos = float(p_after) if pd.notna(p_after) else (float(delta) if pd.notna(delta) else None)
            if pos is not None:
                out.at[i, "buy_position"] = f"{pos:.4f}"
            if action == "开仓" or entry_eq is None:
                if pd.notna(eq):
                    entry_eq = float(eq)
                entry_pos = pos
                entry_date = dt
                entry_cost = float(cost) if pd.notna(cost) else None
            out.at[i, "nav_pnl"] = ""
        elif action in ("清仓", "减仓"):
            pos = entry_pos
            if pos is None and pd.notna(p_before):
                pos = float(p_before)
            if pos is not None:
                out.at[i, "buy_position"] = f"{float(pos):.4f}"
            if action == "清仓" and entry_eq and pd.notna(eq) and entry_eq > 0:
                out.at[i, "nav_pnl"] = _fmt_pct(float(eq) / entry_eq - 1.0)
            if action == "清仓" and entry_date and entry_cost is not None:
                out.at[i, "note"] = _with_entry_note(str(row.get("note") or ""), entry_date, entry_cost)
            if action == "清仓":
                entry_eq = None
                entry_pos = None
                entry_date = None
                entry_cost = None
    return out


def enrich_legs(df: pd.DataFrame, weight: float) -> pd.DataFrame:
    out = df.copy()
    if "buy_position" not in out.columns:
        out["buy_position"] = ""
    if "nav_pnl" not in out.columns:
        out["nav_pnl"] = ""
    if "note" not in out.columns:
        out["note"] = ""
    out["buy_position"] = out["buy_position"].astype(object)
    out["nav_pnl"] = out["nav_pnl"].astype(object)
    out["note"] = out["note"].astype(object)
    stacks: dict[str, list] = {}
    order = out.index.tolist()
    dated = sorted(
        order,
        key=lambda i: (str(out.at[i, "date"]), 0 if str(out.at[i, "action"]) == "开仓" else 1),
    )
    for i in dated:
        action = str(out.at[i, "action"] or "")
        code = str(out.at[i, "code"] or "")
        price = pd.to_numeric(out.at[i, "price"], errors="coerce")
        dt = str(out.at[i, "date"] or "")[:10]
        if action == "开仓":
            out.at[i, "buy_position"] = f"{weight:.4f}"
            out.at[i, "nav_pnl"] = ""
            stacks.setdefault(code, []).append(
                {
                    "price": float(price) if pd.notna(price) else None,
                    "w": weight,
                    "date": dt,
                }
            )
        elif action == "清仓":
            out.at[i, "buy_position"] = f"{weight:.4f}"
            ent = stacks.get(code) or []
            entry = ent.pop(0) if ent else None
            ret = _parse_pct(out.at[i, "day_ret"])
            if ret is None and entry and entry["price"] and pd.notna(price) and entry["price"] > 0:
                ret = float(price) / entry["price"] - 1.0
            w = (entry["w"] if entry else weight) or weight
            if ret is not None:
                out.at[i, "nav_pnl"] = _fmt_pct(ret * w)
            if entry and entry.get("date") and entry.get("price") is not None:
                out.at[i, "note"] = _with_entry_note(
                    str(out.at[i, "note"] or ""),
                    entry["date"],
                    float(entry["price"]),
                )
    return out


def enrich_file(path: Path) -> bool:
    name = path.name
    m = re.match(r"(.+)_trade_history(?:_.+)?\.csv$", name)
    if not m:
        return False
    factor_id = m.group(1)
    if path.stat().st_size < 8:
        print("skip empty", path.name)
        return False
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print("skip empty", path.name)
        return False
    if df.empty:
        print("skip empty", path.name)
        return False
    if "code" in df.columns and "price" in df.columns and "position_after" not in df.columns:
        w = 1.0 / _max_pos(factor_id)
        out = enrich_legs(df, w)
    elif "equity" in df.columns or "position_after" in df.columns:
        out = enrich_portfolio(df)
    else:
        return False
    preferred = [
        "date",
        "action",
        "code",
        "buy_position",
        "nav_pnl",
        "side",
        "price",
        "position_before",
        "position_after",
        "delta",
        "equity",
        "day_ret",
        "close",
        "note",
    ]
    cols = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
    out[cols].to_csv(path, index=False, encoding="utf-8-sig")
    return True


def main() -> None:
    n = 0
    for path in sorted(FACTORS.glob("*trade_history*.csv")):
        if enrich_file(path):
            n += 1
            print("ok", path.name)
    print(f"enriched {n} files")


if __name__ == "__main__":
    main()
