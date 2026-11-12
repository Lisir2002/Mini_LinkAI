"""EXT-005 全文搜索：pg_trgm GIN 索引 + 数据范围隔离 + 游标分页。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ratelimit import check_rate_limit
from app.deps import get_current_user, get_db

router = APIRouter(prefix="/api/search", tags=["search"])
User = Depends(get_current_user)


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(content: str, q: str) -> tuple[str, str]:
    pos = content.lower().find(q.lower())
    if pos < 0:
        return content[:120], q
    start, end = max(0, pos - 40), min(len(content), pos + len(q) + 60)
    snip = content[start:end]
    if start > 0:
        snip = "…" + snip
    if end < len(content):
        snip = snip + "…"
    return snip, content[pos:pos + len(q)]


@router.get("")
async def search(q: str = Query(default=""), scope: str = Query(default="all"),
                 cursor: int = 0, limit: int = Query(default=20, ge=1, le=50),
                 user: dict[str, Any] = User,
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = q.strip()
    if not q or len(q) > 100:
        raise AppError(422, "SEARCH_QUERY_INVALID", "搜索词需为 1–100 个字符")
    if scope not in ("all", "dm", "room"):
        raise AppError(422, "SEARCH_SCOPE_INVALID", "scope 仅支持 all/dm/room")
    ok, wait = await check_rate_limit(f"search:{user['id']}", limit=30, window_sec=60)
    if not ok:
        raise AppError(429, "RATE_LIMITED", f"搜索过于频繁，请 {wait} 秒后再试")

    is_admin = user["role"] == "admin"
    dm_ok = "TRUE" if is_admin else "c.user_id = :u"
    room_ok = ("TRUE" if is_admin else
               "EXISTS (SELECT 1 FROM room_members rm "
               "WHERE rm.room_id=m.room_id AND rm.user_id=:u)")
    scope_clause = {
        "all": f"((m.conversation_id IS NOT NULL AND {dm_ok}) "
               f"OR (m.room_id IS NOT NULL AND {room_ok}))",
        "dm": f"(m.conversation_id IS NOT NULL AND {dm_ok})",
        "room": f"(m.room_id IS NOT NULL AND {room_ok})",
    }[scope]
    rows = (await db.execute(text(
        "SELECT m.id, m.scope, m.conversation_id, m.room_id, m.content, m.created_at, "
        "COALESCE(c.title, r.name) AS title "
        "FROM messages m "
        "LEFT JOIN conversations c ON c.id=m.conversation_id "
        "LEFT JOIN rooms r ON r.id=m.room_id "
        "WHERE m.content ILIKE :pat ESCAPE '\\' AND m.role <> 'system' "
        f"AND {scope_clause} AND (:cursor = 0 OR m.id < :cursor) "
        "ORDER BY m.id DESC LIMIT :lim"),
        {"pat": f"%{_escape_like(q)}%", "u": user["id"], "cursor": cursor,
         "lim": limit})).mappings().all()
    items = []
    for r in rows:
        snip, match = _snippet(r["content"], q)
        items.append({"message_id": r["id"], "scope": r["scope"],
                      "conversation_id": r["conversation_id"], "room_id": r["room_id"],
                      "title": r["title"], "snippet": snip, "match": match,
                      "created_at": r["created_at"]})
    next_cursor = items[-1]["message_id"] if len(items) == limit else None
    return {"code": 0, "data": {"items": items, "next_cursor": next_cursor}}