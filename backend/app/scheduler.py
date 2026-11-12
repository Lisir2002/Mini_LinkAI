"""周期任务入口（PRD 9.5）。独立容器运行，且必须 replicas=1。

多副本会重复执行定时任务；每个任务另加 Redis 锁作为第二道保险。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import configure_logging, log_event
from app.db import get_session
from app.redis_client import get_redis
from app.services.health_service import check_failure_rates, cleanup_samples, sample_all
from app.tasks.channel_health import check_channels
from app.tasks.pending_refund import refund_stale_pending
from app.tasks.stats_precompute import precompute_stats


async def with_lock(name: str, ttl: int, fn: Callable[..., Awaitable[Any]]) -> None:
    r = get_redis()
    if not await r.set(f"job-lock:{name}", "1", nx=True, ex=ttl):
        return
    try:
        async with get_session() as s:
            await fn(s)
    except Exception as exc:                      # noqa: BLE001 - 任务失败不得拖垮调度器
        log_event("scheduler.job_failed", status="failure", job=name, error=str(exc)[:200])
    finally:
        await r.delete(f"job-lock:{name}")


def build_scheduler() -> AsyncIOScheduler:
    sch = AsyncIOScheduler(timezone="UTC")
    sch.add_job(with_lock, "interval", minutes=10, id="pending_refund",
                args=["pending_refund", 540, refund_stale_pending],
                max_instances=1, coalesce=True)
    sch.add_job(with_lock, "interval", minutes=5, id="channel_health",
                args=["channel_health", 270, check_channels],
                max_instances=1, coalesce=True)
    sch.add_job(with_lock, "interval", minutes=1, id="health_sample",
                args=["health_sample", 55, sample_all],
                max_instances=1, coalesce=True)
    sch.add_job(with_lock, "interval", minutes=5, id="fail_rate_alert",
                args=["fail_rate_alert", 270, check_failure_rates],
                max_instances=1, coalesce=True)
    sch.add_job(with_lock, "interval", minutes=10, id="stats_precompute",
                args=["stats_precompute", 540, precompute_stats],
                max_instances=1, coalesce=True)
    sch.add_job(with_lock, "cron", hour=3, id="health_cleanup",
                args=["health_cleanup", 300, cleanup_samples],
                max_instances=1, coalesce=True)
    return sch


async def main() -> None:
    configure_logging()
    sch = build_scheduler()
    sch.start()
    log_event("scheduler.started", status="success",
              jobs=[j.id for j in sch.get_jobs()])
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
