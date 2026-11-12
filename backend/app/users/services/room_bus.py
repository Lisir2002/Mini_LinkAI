"""EXT-024 房间广播：Redis pub/sub → 每实例本地连接池 → 增量推送。

单实例部署下 pub/sub 仍走 Redis 一次往返，为多实例横向扩展预留；
广播失败绝不影响消息主链路，客户端可用 REST after= 补齐。
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import WebSocket

from app.core.redis_client import get_redis

CHANNEL_PATTERN = "room:*:events"
_local: dict[int, set[WebSocket]] = defaultdict(set)
_users: dict[WebSocket, int] = {}


def register(room_id: int, ws: WebSocket, user_id: int) -> None:
    _local[room_id].add(ws)
    _users[ws] = user_id


def unregister(room_id: int, ws: WebSocket) -> None:
    _local[room_id].discard(ws)
    _users.pop(ws, None)
    if not _local[room_id]:
        _local.pop(room_id, None)


async def presence_changed(room_id: int, user_id: int, *, joined: bool) -> None:
    """在线集合增删并广播在线数；失败不影响连接主流程。"""
    try:
        r = get_redis()
        key = f"room:{room_id}:online"
        if joined:
            await cast(Awaitable[int], r.sadd(key, user_id))
        else:
            await cast(Awaitable[int], r.srem(key, user_id))
        await r.expire(key, 86400)
        count = int(await cast(Awaitable[int], r.scard(key)))
        await publish(room_id, {"type": "online", "count": count})
    except Exception:            # noqa: BLE001
        pass


def local_count(room_id: int) -> int:
    return len(_local.get(room_id, ()))


async def publish(room_id: int, payload: dict[str, Any]) -> None:
    try:
        await get_redis().publish(f"room:{room_id}:events",
                                  json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:            # noqa: BLE001 - 广播失败不影响主链路
        pass


async def fanout(room_id: int, payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in list(_local.get(room_id, ())):
        try:
            await ws.send_json(payload)
        except Exception:        # noqa: BLE001 - 连接已死，收集后清理
            dead.append(ws)
    for ws in dead:
        unregister(room_id, ws)


async def listener() -> None:
    pubsub = get_redis().pubsub()
    await pubsub.psubscribe(CHANNEL_PATTERN)
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "pmessage":
                continue
            channel = msg["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()
            try:
                room_id = int(channel.split(":")[1])
                payload = json.loads(msg["data"])
            except (ValueError, IndexError, KeyError):
                continue
            await fanout(room_id, payload)
    finally:
        await pubsub.close()