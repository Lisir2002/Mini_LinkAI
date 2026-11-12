"""测试数据工厂与 FK 逆序清理（US-006）。属测试工具，不进生产代码路径。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 按 PRD 12.3 的 FK 依赖逆序
CLEANUP_ORDER = (
    "direct_messages", "friendships", "stats_daily", "daily_usage", "usage_logs",
    "route_experiments", "notifications", "audit_logs",
    "message_feedbacks",
    "messages", "uploads",
    "room_join_requests", "room_members", "room_templates", "rooms", "model_channels",
    "models",
    "model_tokenizer_drift", "shares", "channel_health_samples", "channels",
    "conversations", "invite_codes", "settings",
    "users",
)


def _rand(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _insert(table: str, data: dict[str, Any]) -> Any:
    cols = ",".join(data)
    binds = ",".join(f":{k}" for k in data)
    return text(f"INSERT INTO {table} ({cols}) VALUES ({binds}) RETURNING id")  # noqa: S608


async def make_user(session: AsyncSession, **overrides: Any) -> int:
    data = {
        "email": f"{_rand('u')}@example.com",
        "password_hash": "x",
        "nickname": "tester",
        "role": "member",
    } | overrides
    row = await session.execute(_insert("users", data), data)
    uid = int(row.scalar_one())
    await session.commit()
    return uid


async def make_channel(session: AsyncSession, **overrides: Any) -> int:
    from app.core.crypto import encrypt_api_key, key_hint

    plain = "sk-test-default-1234"
    data = {
        "name": _rand("ch"),
        "type": "openai_compatible",
        "base_url": "https://example.invalid/v1",
        "api_key_enc": encrypt_api_key(plain),
        "api_key_hint": key_hint(plain),
    } | overrides
    row = await session.execute(_insert("channels", data), data)
    cid = int(row.scalar_one())
    await session.commit()
    return cid


async def make_model(session: AsyncSession, **overrides: Any) -> int:
    name = _rand("m")
    data = {"public_name": name, "display_name": name} | overrides
    row = await session.execute(_insert("models", data), data)
    mid = int(row.scalar_one())
    await session.commit()
    return mid


async def make_room(session: AsyncSession, *, owner_id: int, **overrides: Any) -> int:
    data = {"name": _rand("room"), "owner_id": owner_id} | overrides
    row = await session.execute(_insert("rooms", data), data)
    rid = int(row.scalar_one())
    await session.execute(
        text("INSERT INTO room_members (room_id,user_id,role) VALUES (:r,:u,'owner')"),
        {"r": rid, "u": owner_id})
    await session.execute(
        text("UPDATE rooms SET member_count=1 WHERE id=:r"), {"r": rid})
    await session.commit()
    return rid


async def cleanup_all(session: AsyncSession) -> None:
    """按 FK 逆序清空。只清理实际存在的表，兼容仅有部分表的 smoke 库。"""
    rows = await session.execute(
        text("SELECT table_name FROM information_schema.tables "
             "WHERE table_schema='public' AND table_type='BASE TABLE'"))
    existing = {r[0] for r in rows}
    for table in CLEANUP_ORDER:
        if table in existing:
            await session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - 固定白名单
    await session.commit()


async def make_conversation(session: AsyncSession, *, user_id: int, **overrides: Any) -> int:
    data = {"user_id": user_id, "title": _rand("conv")} | overrides
    row = await session.execute(_insert("conversations", data), data)
    cid = int(row.scalar_one())
    await session.commit()
    return cid


async def add_member(session: AsyncSession, *, room_id: int, user_id: int,
                     role: str = "member") -> None:
    await session.execute(
        text("INSERT INTO room_members (room_id,user_id,role) VALUES (:r,:u,:ro) "
             "ON CONFLICT DO NOTHING"), {"r": room_id, "u": user_id, "ro": role})
    await session.commit()
