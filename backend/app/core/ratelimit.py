"""Redis 滑动窗口限流（PRD 9.7）。被拒的请求不占用窗口名额。"""
from __future__ import annotations

import math
import time
import uuid

from app.redis_client import get_redis


async def check_rate_limit(key: str, *, limit: int, window_sec: int,
                           consume: bool = True) -> tuple[bool, int]:
    """返回 (是否放行, 建议等待秒数)。consume=False 只查不记账（登录成功不耗失败预算）。"""
    r = get_redis()
    k = f"rl:{key}"
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(k, 0, now - window_sec)
    pipe.zcard(k)
    _, count = await pipe.execute()
    if int(count) >= limit:
        oldest = await r.zrange(k, 0, 0, withscores=True)
        wait = math.ceil(oldest[0][1] + window_sec - now) if oldest else window_sec
        return False, max(int(wait), 1)
    if consume:
        await record_rate_limit(key, window_sec)
    return True, 0


async def record_rate_limit(key: str, window_sec: int) -> None:
    """记一次尝试（仅失败时调用）。"""
    r = get_redis()
    k = f"rl:{key}"
    now = time.time()
    pipe = r.pipeline()
    pipe.zadd(k, {f"{now}-{uuid.uuid4().hex[:8]}": now})
    pipe.expire(k, window_sec + 1)
    await pipe.execute()
