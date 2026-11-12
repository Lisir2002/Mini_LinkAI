"""EXT-001 引用回复：校验、上下文注入与 quote 快照。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError


async def validate_quote(s: AsyncSession, quote_id: int | None, *,
                         conversation_id: int | None = None,
                         room_id: int | None = None) -> None:
    """被引用消息必须存在且属于同一会话/房间，否则 422。"""
    if quote_id is None:
        return
    row = (await s.execute(text(
        "SELECT conversation_id, room_id FROM messages WHERE id=:i"),
        {"i": quote_id})).mappings().first()
    if row is None:
        raise AppError(422, "QUOTE_INVALID", "被引用的消息不存在")
    if conversation_id is not None and row["conversation_id"] != conversation_id:
        raise AppError(422, "QUOTE_INVALID", "不能引用其他会话的消息")
    if room_id is not None and row["room_id"] != room_id:
        raise AppError(422, "QUOTE_INVALID", "不能引用其他房间的消息")


async def attach_quote(s: AsyncSession, messages: list[dict[str, str]],
                       hist_ids: list[int], quote_id: int | None, *,
                       with_nickname: bool = False) -> None:
    """把窗口外的被引用消息插在触发消息之前；已在窗口内则不重复。"""
    if quote_id is None or quote_id in hist_ids:
        return
    row = (await s.execute(text(
        "SELECT m.role, m.content, u.nickname FROM messages m "
        "LEFT JOIN users u ON u.id=m.sender_id WHERE m.id=:i"),
        {"i": quote_id})).mappings().first()
    if row is None:
        return
    content = row["content"]
    if with_nickname and row["nickname"]:
        content = f"{row['nickname']}：{content}"
    messages.insert(len(messages) - 1, {"role": row["role"], "content": content})


def build_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    """由 LEFT JOIN 结果构造 quote 快照；原消息被删时返回 deleted 占位。"""
    rid = row.get("reply_to_msg_id")
    if rid is None:
        return None
    if row.get("q_content") is None:
        return {"id": rid, "deleted": True}
    nickname = row.get("q_nickname") or ("AI" if row.get("q_role") == "assistant" else "成员")
    return {"id": rid, "nickname": nickname, "excerpt": row["q_content"][:80]}


QUOTE_JOIN = ("LEFT JOIN messages q ON q.id=m.reply_to_msg_id "
              "LEFT JOIN users qu ON qu.id=q.sender_id")
QUOTE_COLS = ("m.reply_to_msg_id, q.content AS q_content, "
              "q.role AS q_role, qu.nickname AS q_nickname")