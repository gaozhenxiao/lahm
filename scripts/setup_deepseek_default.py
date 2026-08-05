# -*- coding: utf-8 -*-
"""把 DeepSeek 配成默认厂家/模型，并写入 Mongo llm_providers + system_config。"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 避免 Windows 控制台 GBK 打印 emoji 崩掉
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main() -> None:
    from pymongo import MongoClient
    from app.core.config import settings
    from app.utils.api_key_utils import is_valid_api_key, truncate_api_key
    from app.core.unified_config import unified_config
    from app.services.llm_call_log_service import log_llm_call

    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not is_valid_api_key(key):
        raise SystemExit("DEEPSEEK_API_KEY invalid")

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[settings.MONGO_DB]
    now = datetime.now().isoformat(timespec="seconds")

    db.llm_providers.update_one(
        {"name": "deepseek"},
        {
            "$set": {
                "api_key": key,
                "is_active": True,
                "default_base_url": os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                "test_model": "deepseek-chat",
                "display_name": "DeepSeek",
                "updated_at": now,
                "extra_config": {"source": "environment", "has_api_key": True},
            },
            "$setOnInsert": {
                "description": "DeepSeek",
                "website": "https://www.deepseek.com",
                "api_doc_url": "https://platform.deepseek.com/api-docs",
                "supported_features": ["chat", "completion", "function_calling", "streaming"],
                "created_at": now,
            },
        },
        upsert=True,
    )
    print("[provider] deepseek", truncate_api_key(key))

    cfg = db.system_configs.find_one(sort=[("version", -1)]) or db.system_config.find_one()
    coll_name = "system_configs"
    if cfg is None:
        # try alternate collection names used historically
        for name in ("system_configs", "system_config", "configs"):
            cfg = db[name].find_one()
            if cfg:
                coll_name = name
                break
    if cfg is None:
        # create minimal
        coll_name = "system_configs"
        cfg = {
            "config_name": "default",
            "config_type": "system",
            "llm_configs": [],
            "system_settings": {},
            "version": 1,
            "created_at": now,
        }
        db[coll_name].insert_one(cfg)
        cfg = db[coll_name].find_one({"config_name": "default"}) or db[coll_name].find_one()

    llm_configs = list(cfg.get("llm_configs") or [])
    found = False
    for m in llm_configs:
        if m.get("provider") == "deepseek" and m.get("model_name") == "deepseek-chat":
            m["enabled"] = True
            found = True
    if not found:
        llm_configs.append(
            {
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "model_display_name": "DeepSeek Chat",
                "api_base": "https://api.deepseek.com",
                "max_tokens": 4096,
                "temperature": 0.1,
                "timeout": 300,
                "retry_times": 2,
                "enabled": True,
                "description": "default deepseek",
                "input_price_per_1k": 0.001,
                "output_price_per_1k": 0.002,
                "currency": "CNY",
                "suitable_roles": ["both"],
                "capability_level": 4,
            }
        )
        print("[llm_config] inserted deepseek-chat")
    else:
        print("[llm_config] deepseek-chat enabled")

    ss = dict(cfg.get("system_settings") or {})
    ss.update(
        {
            "default_provider": "deepseek",
            "default_model": "deepseek-chat",
            "quick_analysis_model": "deepseek-chat",
            "deep_analysis_model": "deepseek-chat",
            "default_llm": "deepseek-chat",
        }
    )
    db[coll_name].update_one(
        {"_id": cfg["_id"]},
        {
            "$set": {
                "llm_configs": llm_configs,
                "default_llm": "deepseek-chat",
                "system_settings": ss,
                "updated_at": now,
            }
        },
    )
    print("[mongo]", coll_name, "default -> deepseek-chat")

    unified_config.save_system_settings(
        {
            **unified_config.get_system_settings(),
            **ss,
        }
    )
    print("[settings.json] ok")

    from openai import OpenAI

    client_ai = OpenAI(
        api_key=key,
        base_url=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    )
    try:
        resp = client_ai.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        print("[smoke]", text, "tokens", getattr(usage, "total_tokens", None))
        log_llm_call(
            provider="deepseek",
            model="deepseek-chat",
            input_text="[smoke] Reply with exactly: ok",
            output_text=text,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            meta={"adapter": "setup_deepseek_default"},
        )
    except Exception as exc:  # noqa: BLE001
        print("[smoke] FAILED:", exc)
        log_llm_call(
            provider="deepseek",
            model="deepseek-chat",
            input_text="[smoke] Reply with exactly: ok",
            error=str(exc),
            meta={"adapter": "setup_deepseek_default"},
        )
        if "402" in str(exc) or "Insufficient Balance" in str(exc):
            print("[warn] DeepSeek balance empty — top up at https://platform.deepseek.com/")
    print("[log] llm_api_call_logs wrote")
    client.close()


if __name__ == "__main__":
    main()
