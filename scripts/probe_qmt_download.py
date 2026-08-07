"""经国金 QMT 完整交易端(端口58600)下载日线样本。"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "qmt_probe"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    from xtquant import xtdata

    print("connect 127.0.0.1:58600 …", flush=True)
    client = xtdata.connect("127.0.0.1", 58600)
    print("client", client, flush=True)

    codes = ["600036.SH", "601988.SH", "000001.SZ"]
    for code in codes:
        print(f"\n=== {code} ===", flush=True)
        try:
            xtdata.download_history_data(code, period="1d", start_time="20240101", end_time="20260807")
            print("download ok", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("download err:", exc, flush=True)
            traceback.print_exc()

        try:
            data = xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume", "amount"],
                stock_list=[code],
                period="1d",
                start_time="20240101",
                end_time="20260807",
                count=-1,
            )
            df = data.get(code) if isinstance(data, dict) else None
            if df is None or (hasattr(df, "empty") and df.empty):
                print("empty", type(data), data if not isinstance(data, dict) else list(data.keys()))
                continue
            print("rows", len(df))
            print(df.tail(3))
            fp = OUT / f"{code.replace('.', '_')}_1d.csv"
            df.to_csv(fp)
            print("saved", fp)
        except Exception as exc:  # noqa: BLE001
            print("get err:", exc, flush=True)
            traceback.print_exc()

    # also try a tick/1m briefly
    code = "600036.SH"
    print(f"\n=== {code} 1m sample ===", flush=True)
    try:
        xtdata.download_history_data(code, period="1m", start_time="20260801", end_time="20260807")
        data = xtdata.get_market_data_ex(
            field_list=["open", "high", "low", "close", "volume"],
            stock_list=[code],
            period="1m",
            start_time="20260801",
            end_time="20260807",
            count=-1,
        )
        df = data.get(code) if isinstance(data, dict) else None
        if df is not None and len(df):
            print("1m rows", len(df))
            print(df.tail(3))
            df.to_csv(OUT / f"{code.replace('.', '_')}_1m.csv")
        else:
            print("1m empty")
    except Exception as exc:  # noqa: BLE001
        print("1m err:", exc)
        traceback.print_exc()

    meta = {"port": 58600, "codes": codes, "out": str(OUT)}
    (OUT / "download_ok.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
