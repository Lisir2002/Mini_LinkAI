"""渠道与模型的缓存失效与适配器构造（PRD 5.2/5.3）。"""
from __future__ import annotations

from typing import Any

from app.core.crypto import decrypt_api_key
from app.core.redis_client import get_redis
from app.llm.adapter.base import ProtocolAdapter
from app.llm.adapter.registry import get_adapter


async def invalidate_model_cache() -> None:
    r = get_redis()
    await r.delete("models:enabled")
    async for key in r.scan_iter(match="route:*", count=100):
        await r.delete(key)


def build_adapter(row: dict[str, Any]) -> ProtocolAdapter:
    cls = get_adapter(row["type"])
    return cls(base_url=row["base_url"], api_key=decrypt_api_key(row["api_key_enc"]),
               supported_params=row.get("supported_params"),
               timeout_first_token_ms=row.get("timeout_first_token_ms", 15000),
               timeout_total_ms=row.get("timeout_total_ms", 60000))


CHANNEL_COLS = ("id,name,type,base_url,api_key_hint,preset,supported_params,weight,priority,"
                "status,fail_count,cooldown_until,last_check_at,last_latency_ms,"
                "discovered_models,version")
