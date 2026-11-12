"""FR-003 私聊：仅好友可发，增量拉取、已读标记、实时推送。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.errors import AppError
from app.db import get_session
from app.deps import get_current_user
from app.services import dm_bus
from app.services.upload_service import validate_attachment

router = APIRouter(prefix="/api/dm", tags=["dm"])
User = Depends(get_current_user)


class DmIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    attachment_id: int | None = None


async def _gate(s: Any, me: int, other: int) -> None:
    from app.api.friends import are_friends

    if not await are_friends(s, me, other):
        raise AppError(403, "NOT_FRIEND", "你们还不是好友，先添加好友吧")


@router.post("/{uid}/messages")
async def send_dm(uid: int, body: DmIn, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        await _gate(s, user["id"], uid)
        await validate_attachment(s, user, body.attachment_id)
        row = (await s.execute(text(
            "INSERT INTO direct_messages (sender_id,recipient_id,content,attachment_id) "
            "VALUES (:a,:b,:c,:att) RETURNING id,created_at"),
            {"a": user["id"], "b": uid, "c": body.content,
             "att": body.attachment_id})).mappings().one()
        await s.commit()
    payload = {"id": row["id"], "sender_id": user["id"], "recipient_id": uid,
               "content": body.content, "attachment_id": body.attachment_id,
               "read_at": None, "created_at": row["created_at"].isoformat(),
               "sender_nickname": user["nickname"]}
    await dm_bus.publish(uid, {"type": "dm", "message": payload})
    return {"code": 0, "data": {"message_id": row["id"]}}


@router.get("/{uid}/messages")
async def list_dm(uid: int, after: int = 0, limit: int = Query(default=100, ge=1, le=200),
                  user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        await _gate(s, user["id"], uid)
        rows = (await s.execute(text(
            "SELECT id,sender_id,recipient_id,content,attachment_id,read_at,created_at "
            "FROM direct_messages WHERE "
            "((sender_id=:a AND recipient_id=:b) OR (sender_id=:b AND recipient_id=:a)) "
            "AND id > :after ORDER BY id LIMIT :lim"),
            {"a": user["id"], "b": uid, "after": after, "lim": limit})).mappings().all()
    items = [dict(r) | {"created_at": r["created_at"].isoformat(),
                        "read_at": r["read_at"].isoformat() if r["read_at"] else None}
             for r in rows]
    return {"code": 0, "data": {"items": items}}


@router.post("/{uid}/read")
async def mark_read(uid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        await _gate(s, user["id"], uid)
        rows = (await s.execute(text(
            "UPDATE direct_messages SET read_at=now() "
            "WHERE sender_id=:other AND recipient_id=:me AND read_at IS NULL RETURNING id"),
            {"other": uid, "me": user["id"]})).all()
        await s.commit()
    await dm_bus.publish(uid, {"type": "dm_read", "reader_id": user["id"],
                               "count": len(rows)})
    return {"code": 0, "data": {"marked": len(rows)}}
