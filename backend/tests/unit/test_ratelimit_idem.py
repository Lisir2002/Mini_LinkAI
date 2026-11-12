"""US-018：滑动窗口限流与幂等。"""
from __future__ import annotations

import asyncio


async def test_rate_limit_window_boundary():
    from app.core.ratelimit import check_rate_limit

    key = "rl-test-boundary"
    for _ in range(3):
        ok, _wait = await check_rate_limit(key, limit=3, window_sec=60)
        assert ok is True
    ok, wait = await check_rate_limit(key, limit=3, window_sec=60)
    assert ok is False and wait > 0


async def test_rate_limit_recovers_after_window():
    from app.core.ratelimit import check_rate_limit

    key = "rl-test-recover"
    assert (await check_rate_limit(key, limit=1, window_sec=1))[0] is True
    assert (await check_rate_limit(key, limit=1, window_sec=1))[0] is False
    await asyncio.sleep(1.15)
    assert (await check_rate_limit(key, limit=1, window_sec=1))[0] is True


async def test_idempotency_executes_once_for_same_key():
    from app.core.idempotency import run_idempotent

    calls = {"n": 0}

    async def work() -> dict:
        calls["n"] += 1
        return {"value": calls["n"]}

    a = await run_idempotent("idem-1", 60, work)
    b = await run_idempotent("idem-1", 60, work)
    assert a == b == {"value": 1}
    assert calls["n"] == 1


async def test_idempotency_concurrent_executes_once():
    from app.core.idempotency import run_idempotent

    calls = {"n": 0}

    async def work() -> dict:
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"value": calls["n"]}

    res = await asyncio.gather(*[run_idempotent("idem-2", 60, work) for _ in range(5)])
    assert calls["n"] == 1
    assert all(r == {"value": 1} for r in res)
