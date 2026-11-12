"""FR-004 个人事件总线：Redis pub/sub → 本地连接池（私聊/好友通知）。"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.redis_client import get_redis

CHANNEL_PATTERN = "dm:*:events"
_local: dict[int, set[WebSocket]] = defaultdict(set)


def register(user_id: int, ws: WebSocket) -> None:
    _local[user_id].add(ws)


def unregister(user_id: int, ws: WebSocket) -> None:
    _local[user_id].discard(ws)
    if not _local[user_id]:
        _local.pop(user_id, None)


async def publish(user_id: int, payload: dict[str, Any]) -> None:
    try:
        await get_redis().publish(f"dm:{user_id}:events",
                                  json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:            # noqa: BLE001 - 推送失败不影响主链路
        pass


async def fanout(user_id: int, payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in list(_local.get(user_id, ())):
        try:
            await ws.send_json(payload)
        except Exception:        # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        unregister(user_id, ws)


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
                user_id = int(channel.split(":")[1])
                payload = json.loads(msg["data"])
            except (ValueError, IndexError, KeyError):
                continue
            await fanout(user_id, payload)
    finally:
        await pubsub.close()