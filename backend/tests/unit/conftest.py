"""单元测试基座（US-006）：外部 HTTP 拦截 + 独立库 + FK 逆序清理。"""
from __future__ import annotations

from pathlib import Path

import pytest
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
SPIKE_URL = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike"
SCHEMA_SQL = BACKEND.parent / "scripts" / "prd_schema.sql"


@pytest.fixture(autouse=True)
def block_external_http():
    """默认禁止任何真实外部 HTTP；本机回环放行（smoke 的真实 uvicorn 需要）。"""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
        mock.route(host="127.0.0.1").pass_through()
        mock.route(host="localhost").pass_through()
        yield mock


async def apply_spike_schema_async() -> None:
    import asyncpg

    async def _apply():
        conn = await asyncpg.connect(host="127.0.0.1", port=5432, user="aicr",
                                     password="spikepass", database="ai_chatroom_spike")
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        finally:
            await conn.close()
    await _apply()


def apply_spike_schema() -> None:
    import asyncio

    asyncio.run(apply_spike_schema_async())


@pytest.fixture(scope="session", autouse=True)
def _ensure_spike_schema():
    apply_spike_schema()


@pytest.fixture(autouse=True)
def _cipher_key(monkeypatch):
    """单元测试统一使用固定的测试加密密钥，避免依赖外部环境。"""
    from cryptography.fernet import Fernet

    from app.core import crypto

    monkeypatch.setenv("CHANNEL_CIPHER_KEY",
                       Fernet.generate_key().decode())
    crypto.reset_cipher()
    yield
    crypto.reset_cipher()


@pytest.fixture(autouse=True)
def _app_uses_spike_db():
    """单元测试期间把应用会话指向 spike 库，保证 API 与 fixture 读写同一个库。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app import db

    original = db._factory
    engine = create_async_engine(SPIKE_URL, pool_size=3, max_overflow=2)
    db.set_session_factory(async_sessionmaker(engine, expire_on_commit=False))
    yield
    db.set_session_factory(original)


@pytest.fixture
async def spike_session():
    engine = create_async_engine(SPIKE_URL, pool_size=2, max_overflow=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
