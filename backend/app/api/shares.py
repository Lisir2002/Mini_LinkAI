"""EXT-010 只读分享：HMAC 签名令牌 + 有效期 + 可撤销，免登录查看。"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.deps import get_current_user, get_db, scope_conversation, scope_room

router = APIRouter(prefix="/api/shares", tags=["shares"])
public = APIRouter(prefix="/api/share", tags=["share-public"])
User = Depends(get_current_user)


class ShareIn(BaseModel):
    scope: str
    conversation_id: int | None = None
    room_id: int | None = None
    days: int = Field(default=7, ge=1, le=30)


def _sign(share_id: int) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), str(share_id).encode(),
                    hashlib.sha256).hexdigest()[:32]


@router.post("")
async def create_share(body: ShareIn, user: dict[str, Any] = User,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.scope == "dm" and body.conversation_id:
        await scope_conversation(user, body.conversation_id)
    elif body.scope == "room" and body.room_id:
        await scope_room(user, body.room_id)
    else:
        raise AppError(422, "SHARE_TARGET_INVALID", "scope 与目标 id 不匹配")
    expires = datetime.now(UTC) + timedelta(days=body.days)
    row = (await db.execute(text(
        "INSERT INTO shares (scope,conversation_id,room_id,created_by,expires_at) "
        "VALUES (:s,:c,:r,:u,:e) RETURNING id"),
        {"s": body.scope, "c": body.conversation_id, "r": body.room_id,
         "u": user["id"], "e": expires})).mappings().one()
    await db.commit()
    sid = int(row["id"])
    return {"code": 0, "data": {"share_id": sid, "token": f"{sid}.{_sign(sid)}",
                                "expires_at": expires.isoformat()}}


@router.get("")
async def list_shares(user: dict[str, Any] = User,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(text(
        "SELECT id,scope,conversation_id,room_id,expires_at,revoked,created_at "
        "FROM shares WHERE created_by=:u ORDER BY id DESC LIMIT 100"),
        {"u": user["id"]})).mappings().all()
    items = [dict(r) | {"token": f"{r['id']}.{_sign(int(r['id']))}"} for r in rows]
    return {"code": 0, "data": {"items": items}}


@router.delete("/{sid}")
async def revoke_share(sid: int, user: dict[str, Any] = User,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(text("SELECT created_by FROM shares WHERE id=:i"),
                            {"i": sid})).mappings().first()
    if row is None:
        raise AppError(404, "SHARE_NOT_FOUND", "分享不存在")
    if row["created_by"] != user["id"] and user["role"] != "admin":
        raise AppError(403, "FORBIDDEN", "只能撤销自己创建的分享")
    await db.execute(text("UPDATE shares SET revoked=true WHERE id=:i"), {"i": sid})
    await db.commit()
    return {"code": 0, "data": {"revoked": True}}


@public.get("/{token}")
async def view_share(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 2 or not parts[0].isdigit():
        raise AppError(403, "SHARE_TAMPERED", "分享链接无效")
    sid = int(parts[0])
    if not hmac.compare_digest(parts[1], _sign(sid)):
        raise AppError(403, "SHARE_TAMPERED", "分享链接签名校验失败")
    share = (await db.execute(text(
        "SELECT s.*, COALESCE(c.title, r.name) AS title "
        "FROM shares s LEFT JOIN conversations c ON c.id=s.conversation_id "
        "LEFT JOIN rooms r ON r.id=s.room_id WHERE s.id=:i"),
        {"i": sid})).mappings().first()
    if share is None:
        raise AppError(404, "SHARE_NOT_FOUND", "分享不存在")
    if share["revoked"]:
        raise AppError(410, "SHARE_REVOKED", "分享已被撤销")
    if share["expires_at"] < datetime.now(UTC):
        raise AppError(410, "SHARE_EXPIRED", "分享已过期")
    if share["scope"] == "dm":
        msgs = (await db.execute(text(
            "SELECT m.role,m.content,m.created_at,u.nickname FROM messages m "
            "LEFT JOIN users u ON u.id=m.sender_id "
            "WHERE m.conversation_id=:c ORDER BY m.id"),
            {"c": share["conversation_id"]})).mappings().all()
    else:
        msgs = (await db.execute(text(
            "SELECT m.role,m.content,m.created_at,u.nickname FROM messages m "
            "LEFT JOIN users u ON u.id=m.sender_id "
            "WHERE m.room_id=:r ORDER BY m.id"),
            {"r": share["room_id"]})).mappings().all()
    return {"code": 0, "data": {
        "title": share["title"], "scope": share["scope"],
        "expires_at": share["expires_at"].isoformat(),
        "messages": [{"role": m["role"], "content": m["content"],
                      "nickname": m["nickname"], "created_at": m["created_at"].isoformat()}
                     for m in msgs]}}