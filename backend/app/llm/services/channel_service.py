"""渠道与模型的缓存失效与适配器构造（PRD 5.2/5.3）。"""
from __future__ import annotations

import re
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


_SUFFIXES = {
    "openai_compatible": r"/(chat/completions|responses)$",
    "anthropic": r"/(v1/messages|v1|messages)$",
    "gemini": r"/(v1beta(/interactions|/models(/[\w.-]+)?(:streamGenerateContent"
              r"|:generateContent)?)?|v1(/interactions)?|interactions)$",
}


def normalize_base_url(proto: str, url: str, auto_complete: bool = True) -> str:
    """自动补全开关开启时，把用户误填的端点后缀剥掉、补齐协议必需段。

    开启：openai 系补齐 /v1；anthropic 剥掉误填的 /v1/messages；gemini 只留根地址。
    关闭：仅去尾部斜杠，完全按用户输入使用。
    """
    u = (url or "").strip().rstrip("/")
    if not auto_complete:
        return u
    pattern = _SUFFIXES.get(proto)
    if pattern:
        u = re.sub(pattern, "", u).rstrip("/")
    if proto == "openai_compatible" and not u.endswith("/v1"):
        u += "/v1"
    return u


def build_adapter(row: dict[str, Any],
                  probe_model: str | None = None) -> ProtocolAdapter:
    cls = get_adapter(row["type"])
    # 构造期再归一一次：历史脏数据（误存完整端点）在开关开启时自动纠正
    base = normalize_base_url(row["type"], row["base_url"],
                              row.get("auto_complete_url", True))
    return cls(base_url=base, api_key=decrypt_api_key(row["api_key_enc"]),
               probe_model=probe_model or "probe",
               options=row.get("options") or {},
               supported_params=row.get("supported_params"),
               timeout_first_token_ms=row.get("timeout_first_token_ms", 15000),
               timeout_total_ms=row.get("timeout_total_ms", 60000))


CHANNEL_COLS = ("id,name,type,base_url,api_key_hint,preset,supported_params,weight,priority,"
                "status,fail_count,cooldown_until,last_check_at,last_latency_ms,"
                "discovered_models,version,auto_complete_url,options")
