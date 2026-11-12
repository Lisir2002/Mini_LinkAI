"""US-004：依赖注入与启动期依赖健康检查。"""
from __future__ import annotations

import pytest
from sqlalchemy import text


async def test_get_db_yields_working_session_and_closes():
    from app.interfaces.deps import get_db

    gen = get_db()
    session = await gen.__anext__()
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


def test_get_settings_returns_loaded_config():
    from app.interfaces.deps import get_settings

    s = get_settings()
    assert s.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert s.DB_POOL_SIZE == 5


async def test_wait_for_dependencies_succeeds_when_ready():
    from app.core.startup import wait_for_dependencies

    await wait_for_dependencies(attempts=2, delay=0.0)


async def test_wait_for_dependencies_gives_up_after_attempts(monkeypatch):
    from app.core import startup

    async def always_fail() -> None:
        raise OSError("db down")

    monkeypatch.setattr(startup, "_probe_db", always_fail)
    with pytest.raises(startup.DependencyNotReady):
        await startup.wait_for_dependencies(attempts=3, delay=0.0)


async def test_reset_singletons_rebuilds_clients():
    from app.core.db import reset_singletons
    from app.core.startup import _probe_db, _probe_redis
    from app.interfaces.deps import get_redis

    r1 = get_redis()
    await reset_singletons()
    r2 = get_redis()
    assert r1 is not r2
    await _probe_db()
    await _probe_redis()
