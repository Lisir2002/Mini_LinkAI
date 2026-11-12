from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.logging import log_event

T = TypeVar("T")

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=10,
)
_factory = async_sessionmaker(engine, expire_on_commit=False)


def get_session() -> AsyncSession:
    """统一会话入口。测试可切换工厂指向独立库，避免跨库读写不一致。"""
    return _factory()


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _factory
    _factory = factory


_read_engine = None
_read_factory: async_sessionmaker[AsyncSession] | None = None


def read_factory() -> async_sessionmaker[AsyncSession] | None:
    """配置了 READ_REPLICA_URL 才建立独立只读引擎；否则 None（走主库）。"""
    global _read_engine, _read_factory
    if not settings.READ_REPLICA_URL:
        return None
    if _read_factory is None:
        _read_engine = create_async_engine(
            settings.READ_REPLICA_URL, pool_size=2, max_overflow=2,
            pool_pre_ping=True, pool_recycle=1800, pool_timeout=5)
        _read_factory = async_sessionmaker(_read_engine, expire_on_commit=False)
    return _read_factory


def reset_read_factory() -> None:
    global _read_engine, _read_factory
    _read_factory = None
    _read_engine = None


async def run_read(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """统计读路径：优先副本，连接级故障自动回退主库（EXT-026）。"""
    f = read_factory()
    if f is not None:
        try:
            async with f() as s:
                return await fn(s)
        except (OperationalError, InterfaceError, SATimeoutError, OSError, TimeoutError):
            log_event("db.replica_fallback", status="failure", level="warning")
    async with get_session() as s:
        return await fn(s)


async def dispose_engine() -> None:
    """释放连接池，避免连接绑在已关闭的 event loop 上。"""
    await engine.dispose()


async def reset_singletons() -> None:
    """测试用：释放 engine 并重建 Redis 客户端（PRD 12.4 全局副作用清理）。"""
    from app.redis_client import reset_redis

    await engine.dispose()
    if _read_engine is not None:
        await _read_engine.dispose()
    reset_read_factory()
    await reset_redis()
