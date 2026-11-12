"""全局测试基座（US-006）。

每个测试后清理全部全局副作用：Redis FLUSHDB、engine 与 Redis 客户端重建、
临时文件由 tmp_path 自动回收。数据库按 FK 逆序清理由 unit 层负责（需全量 schema）。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def clean_state():
    yield
    from app.core.db import reset_singletons
    from app.core.redis_client import get_redis

    try:
        await get_redis().flushdb()
    except Exception:        # noqa: BLE001 - 清理阶段的连接异常不应掩盖测试结论
        pass
    await reset_singletons()
