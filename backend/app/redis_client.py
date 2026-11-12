import redis.asyncio as aioredis

from app.config import settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.REDIS_URL, decode_responses=True)
    return _client


async def reset_redis() -> None:
    """测试用：关闭并丢弃客户端，避免连接绑在已关闭的 event loop 上。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
