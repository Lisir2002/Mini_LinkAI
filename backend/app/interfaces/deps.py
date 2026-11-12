"""FastAPI 依赖注入。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.redis_client import get_redis as _get_redis
from app.core.security import TokenInvalid, decode_token, is_blacklisted


def get_settings() -> Settings:
    return settings


def get_redis() -> Redis:
    return _get_redis()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


_PASSWORD_GATE_ALLOW = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


async def get_current_user(request: Request) -> dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AppError(401, "TOKEN_EXPIRED", "请先登录")
    try:
        payload = decode_token(auth[7:])
    except TokenInvalid:
        raise AppError(401, "TOKEN_EXPIRED", "登录已过期，请重新登录") from None
    if await is_blacklisted(str(payload.get("jti", ""))):
        raise AppError(401, "TOKEN_EXPIRED", "登录已失效，请重新登录")

    async with get_session() as s:
        row = (await s.execute(
            text("SELECT id,email,nickname,role,status,must_change_password,"
                 "daily_msg_limit,daily_token_limit FROM users WHERE id=:i"),
            {"i": int(payload["sub"])})).mappings().first()
    if row is None:
        raise AppError(401, "TOKEN_EXPIRED", "登录已失效，请重新登录")
    if row["status"] == "banned":
        raise AppError(403, "ACCOUNT_BANNED", "账号已被停用，请联系管理员")
    if row["must_change_password"] and request.url.path not in _PASSWORD_GATE_ALLOW:
        raise AppError(403, "PASSWORD_CHANGE_REQUIRED", "请先修改初始密码")
    if await _token_revoked_by_password_change(payload):
        raise AppError(401, "TOKEN_EXPIRED", "密码已修改，请重新登录")
    try:
        from app.stats.services.live_metrics import touch_active
        await touch_active(int(row["id"]))
    except Exception:        # noqa: BLE001 - 指标采集失败不得影响认证
        pass
    return dict(row)


async def _token_revoked_by_password_change(payload: dict[str, Any]) -> bool:
    """改密后使其他 token 失效，但保留发起改密的那一个（PRD US-023）。"""
    import json as _json

    raw = await get_redis().get(f"pwd_changed:{payload['sub']}")
    if not raw:
        return False
    info = _json.loads(raw)
    if "ts_ms" in info:
        token_ms = int(payload.get("iat_ms", int(payload.get("iat", 0)) * 1000))
        revoked = token_ms < int(info["ts_ms"])
    else:
        revoked = int(payload.get("iat", 0)) < int(info["ts"])
    return revoked and payload.get("jti") != info["keep_jti"]


async def scope_conversation(user: dict[str, Any], conv_id: int) -> dict[str, Any]:
    async with get_session() as s:
        row = (await s.execute(
            text("SELECT id,user_id FROM conversations WHERE id=:i"),
            {"i": conv_id})).mappings().first()
    if row is None or (user["role"] != "admin" and row["user_id"] != user["id"]):
        raise AppError(404, "CONVERSATION_NOT_FOUND", "会话不存在")
    return dict(row)


async def scope_room(user: dict[str, Any], room_id: int) -> dict[str, Any]:
    async with get_session() as s:
        room = (await s.execute(
            text("SELECT id,owner_id,archived FROM rooms WHERE id=:i"),
            {"i": room_id})).mappings().first()
        if room is None or room["archived"]:
            raise AppError(404, "ROOM_NOT_FOUND", "房间不存在")
        if user["role"] == "admin":
            return dict(room)
        member = (await s.execute(
            text("SELECT 1 FROM room_members WHERE room_id=:r AND user_id=:u"),
            {"r": room_id, "u": user["id"]})).first()
    if member is None:
        raise AppError(403, "NOT_ROOM_MEMBER", "你不是该房间成员")
    return dict(room)


async def room_perm(user: dict[str, Any], room_id: int, need: str) -> bool:
    if user["role"] == "admin":
        return True
    order = {"member": 0, "manager": 1, "owner": 2}
    async with get_session() as s:
        role = (await s.execute(
            text("SELECT role FROM room_members WHERE room_id=:r AND user_id=:u"),
            {"r": room_id, "u": user["id"]})).scalar_one_or_none()
    return role is not None and order[role] >= order[need]


async def scope_usage(user: dict[str, Any], room_id: int | None = None) -> dict[str, Any]:
    if user["role"] == "admin":
        return {"level": "all"}
    if room_id is not None:
        if await room_perm(user, room_id, "owner"):
            return {"level": "room_all", "room_id": room_id}
        if await room_perm(user, room_id, "manager"):
            return {"level": "room_summary", "room_id": room_id}
    return {"level": "own", "user_id": user["id"]}


async def guard_admin_target(actor: dict[str, Any], target_id: int) -> None:
    """禁止封禁/降级自己，禁止动最后一个管理员（PRD 5.2）。"""
    if actor["id"] == target_id:
        raise AppError(409, "LAST_ADMIN_PROTECTED", "不能对自己执行该操作")
    async with get_session() as s:
        role = (await s.execute(text("SELECT role FROM users WHERE id=:i"),
                                {"i": target_id})).scalar_one_or_none()
        if role == "admin":
            n = (await s.execute(
                text("SELECT count(*) FROM users WHERE role='admin'"))).scalar_one()
            if n <= 1:
                raise AppError(409, "LAST_ADMIN_PROTECTED", "系统必须保留至少一个管理员")


async def require_admin(request: Request) -> dict[str, Any]:
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise AppError(403, "FORBIDDEN_ADMIN_ONLY", "仅管理员可访问")
    return user
