"""幂等执行（PRD 9.9）：同键只执行一次业务，其余等待并复用首次结果。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.redis_client import get_redis


class IdempotencyTimeout(Exception):
    """等待首次执行结果超时。"""


async def run_idempotent(
    key: str, ttl_sec: int, fn: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    r = get_redis()
    result_key, lock_key = f"idem:{key}", f"idem-lock:{key}"
    cached = await r.get(result_key)
    if cached is not None:
        return dict(json.loads(cached))

    acquired = await r.set(lock_key, "1", nx=True, ex=30)
    if not acquired:
        for _ in range(200):
            await asyncio.sleep(0.05)
            cached = await r.get(result_key)
            if cached is not None:
                return dict(json.loads(cached))
        raise IdempotencyTimeout(key)
    try:
        result = await fn()
        await r.set(result_key, json.dumps(result, ensure_ascii=False), ex=ttl_sec)
        return result
    finally:
        await r.delete(lock_key)
