"""启动期依赖健康检查（PRD 2.4）：重试有限次后退出，绝不无限等待。"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.db import get_session
from app.core.redis_client import get_redis


class DependencyNotReady(RuntimeError):
    """依赖在重试耗尽后仍不可用。"""


async def _probe_db() -> None:
    async with get_session() as s:
        await s.execute(text("SELECT 1"))


async def _probe_redis() -> None:
    await get_redis().ping()


async def wait_for_dependencies(*, attempts: int = 10, delay: float = 3.0) -> None:
    last: Exception | None = None
    for i in range(attempts):
        try:
            await _probe_db()
            await _probe_redis()
            return
        except Exception as exc:        # noqa: BLE001 - 启动期需吞掉所有探测异常后重试
            last = exc
            if i < attempts - 1:
                await asyncio.sleep(delay)
    raise DependencyNotReady(f"依赖在 {attempts} 次重试后仍不可用: {last}")
