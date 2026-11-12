"""EXT-007 实时指标采集：Redis 滚动计数，采集失败不影响主链路。"""
from __future__ import annotations

import math
import time
from collections.abc import Awaitable
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import get_redis

ACTIVE_KEY = "stats:active"
ACTIVE_WINDOW = 300


def p95(samples: list[int]) -> int | None:
    if not samples:
        return None
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


async def touch_active(user_id: int) -> None:
    r = get_redis()
    now = time.time()
    pipe = r.pipeline()
    pipe.zadd(ACTIVE_KEY, {str(user_id): now})
    pipe.zremrangebyscore(ACTIVE_KEY, 0, now - ACTIVE_WINDOW)
    pipe.expire(ACTIVE_KEY, ACTIVE_WINDOW + 60)
    await pipe.execute()


async def record_call(channel_id: int, latency_ms: int) -> None:
    r = get_redis()
    minute = int(time.time() // 60)
    key = f"stats:calls:{minute}"
    lat = f"stats:lat:{channel_id}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 180)
    pipe.lpush(lat, latency_ms)
    pipe.ltrim(lat, 0, 99)
    pipe.expire(lat, 3600)
    await pipe.execute()


async def snapshot(s: AsyncSession) -> dict[str, Any]:
    r = get_redis()
    now = time.time()
    await r.zremrangebyscore(ACTIVE_KEY, 0, now - ACTIVE_WINDOW)
    online = int(await r.zcard(ACTIVE_KEY))
    calls = int(await r.get(f"stats:calls:{int(now // 60)}") or 0)
    chans = (await s.execute(text(
        "SELECT id,name,status,fail_count FROM channels ORDER BY id"))).mappings().all()
    channels = []
    for c in chans:
        raw = await cast(Awaitable[list[str]], r.lrange(f"stats:lat:{c['id']}", 0, 99))
        channels.append({"id": c["id"], "name": c["name"], "status": c["status"],
                         "fail_count": c["fail_count"],
                         "latency_p95": p95([int(x) for x in raw])})
    monthly = (await s.execute(text(
        "SELECT coalesce(sum(cost),0) FROM usage_logs "
        "WHERE status='settled' AND settled_at >= date_trunc('month', now())"))).scalar_one()
    hourly = (await s.execute(text(
        "SELECT coalesce(sum(cost),0) FROM usage_logs "
        "WHERE status='settled' AND settled_at >= now() - interval '1 hour'"))).scalar_one()
    return {"ts": int(now), "online": online, "calls_per_min": calls, "channels": channels,
            "budget": {"monthly_cost": float(monthly),
                       "monthly_budget": float(settings.GLOBAL_MONTHLY_BUDGET),
                       "last_hour_cost": float(hourly)}}