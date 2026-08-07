"""试连国金 MiniQMT：下载并读取一只股票日线。"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UD = r"D:\国金证券QMT交易端\userdata_mini"
OUT = ROOT / "data" / "qmt_probe"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("xtquant import …", flush=True)
    from xtquant import xtdata

    print("xtdata module:", getattr(xtdata, "__file__", None), flush=True)

    # 部分版本支持指定 data_dir / 连接
    for fn_name in ("connect", "reconnect"):
        fn = getattr(xtdata, fn_name, None)
        if callable(fn):
            try:
                print(f"call {fn_name}() …", flush=True)
                r = fn()
                print(f"  -> {r}", flush=True)
            except TypeError:
                try:
                    print(f"call {fn_name}(UD) …", flush=True)
                    r = fn(UD)
                    print(f"  -> {r}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"  fail: {exc}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  fail: {exc}", flush=True)

    code = "600036.SH"
    print(f"download_history_data {code} 1d …", flush=True)
    try:
        xtdata.download_history_data(code, period="1d", start_time="20240101", end_time="20251231")
        print("download ok", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("download fail:", exc, flush=True)
        traceback.print_exc()

    print("get_market_data_ex …", flush=True)
    try:
        data = xtdata.get_market_data_ex(
            field_list=["open", "high", "low", "close", "volume", "amount"],
            stock_list=[code],
            period="1d",
            start_time="20240101",
            end_time="20251231",
            count=-1,
        )
        df = data.get(code) if isinstance(data, dict) else data
        print("type", type(data), "keys" if isinstance(data, dict) else "", list(data)[:5] if isinstance(data, dict) else "")
        if df is not None:
            print(df.tail(5) if hasattr(df, "tail") else df)
            if hasattr(df, "to_csv"):
                fp = OUT / f"{code.replace('.', '_')}_1d.csv"
                df.to_csv(fp)
                print("saved", fp, "rows", len(df))
        else:
            print("empty data", data)
    except Exception as exc:  # noqa: BLE001
        print("get fail:", exc, flush=True)
        traceback.print_exc()

    # 写状态
    status = {
        "userdata_mini": UD,
        "code": code,
        "ok": True,
    }
    (OUT / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
