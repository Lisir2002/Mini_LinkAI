"""EXT-003 消息反馈：每人每条消息一票，可改可取消。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.deps import get_current_user, get_db

router = APIRouter(prefix="/api/messages", tags=["feedback"])
User = Depends(get_current_user)


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/{mid}/feedback")
async def vote(mid: int, body: FeedbackIn, user: dict[str, Any] = User,
               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    msg = (await db.execute(text(
        "SELECT m.id, m.conversation_id, m.room_id, c.user_id AS conv_owner "
        "FROM messages m LEFT JOIN conversations c ON c.id=m.conversation_id "
        "WHERE m.id=:i"), {"i": mid})).mappings().first()
    if msg is None:
        raise AppError(404, "MESSAGE_NOT_FOUND", "消息不存在")
    if user["role"] != "admin":
        if msg["conversation_id"] is not None:
            allowed = msg["conv_owner"] == user["id"]
        else:
            allowed = (await db.execute(text(
                "SELECT 1 FROM room_members WHERE room_id=:r AND user_id=:u"),
                {"r": msg["room_id"], "u": user["id"]})).first() is not None
        if not allowed:
            raise AppError(403, "FORBIDDEN", "只能评价自己会话或所在房间的消息")
    existing = (await db.execute(text(
        "SELECT rating FROM message_feedbacks WHERE message_id=:m AND user_id=:u"),
        {"m": mid, "u": user["id"]})).scalar_one_or_none()
    if existing == body.rating:
        await db.execute(text(
            "DELETE FROM message_feedbacks WHERE message_id=:m AND user_id=:u"),
            {"m": mid, "u": user["id"]})
        state = "none"
    else:
        await db.execute(text(
            "INSERT INTO message_feedbacks (message_id,user_id,rating,reason) "
            "VALUES (:m,:u,:r,:reason) "
            "ON CONFLICT (message_id,user_id) "
            "DO UPDATE SET rating=EXCLUDED.rating, reason=EXCLUDED.reason, created_at=now()"),
            {"m": mid, "u": user["id"], "r": body.rating, "reason": body.reason})
        state = body.rating
    await db.commit()
    return {"code": 0, "data": {"state": state}}