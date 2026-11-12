"""EXT-016 房间模板市场：房主发布成熟配置，他人一键克隆开房。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import get_session
from app.core.errors import AppError
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/api/room-templates", tags=["room-templates"])
User = Depends(get_current_user)


class PublishIn(BaseModel):
    room_id: int


@router.post("")
async def publish_template(body: PublishIn, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        room = (await s.execute(text(
            "SELECT * FROM rooms WHERE id=:i AND NOT archived"),
            {"i": body.room_id})).mappings().first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "房间不存在")
        if room["owner_id"] != user["id"] and user["role"] != "admin":
            raise AppError(403, "FORBIDDEN", "只有房主可以发布模板")
        if room["access_type"] != "public":
            raise AppError(422, "TEMPLATE_PRIVATE_ROOM", "私密房间不能发布为模板")
        row = (await s.execute(text(
            "INSERT INTO room_templates (name,description,system_prompt,model_id,access_type,"
            "max_members,daily_token_budget,ai_trigger,context_window,published_by,source_room_id) "
            "VALUES (:n,:d,:sp,:m,:a,:mx,:b,:t,:w,:u,:r) RETURNING id"),
            {"n": room["name"], "d": room["description"] or "", "sp": room["system_prompt"],
             "m": room["model_id"], "a": room["access_type"], "mx": room["max_members"],
             "b": room["daily_token_budget"], "t": room["ai_trigger"],
             "w": room["context_window"], "u": user["id"], "r": room["id"]})).mappings().one()
        await s.commit()
    return {"code": 0, "data": {"template_id": row["id"]}}


@router.get("")
async def list_templates(q: str = "", offset: int = Query(default=0, ge=0),
                         limit: int = Query(default=20, ge=1, le=50),
                         user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT t.id,t.name,t.description,t.access_type,t.max_members,t.use_count,"
            "t.created_at,m.display_name AS model_name,u.nickname AS publisher "
            "FROM room_templates t "
            "LEFT JOIN models m ON m.id=t.model_id "
            "LEFT JOIN users u ON u.id=t.published_by "
            "WHERE :q = '' OR t.name ILIKE :pat OR t.description ILIKE :pat "
            "ORDER BY t.use_count DESC, t.id DESC LIMIT :lim OFFSET :off"),
            {"q": q, "pat": f"%{q}%", "lim": limit, "off": offset})).mappings().all()
    items = [dict(r) for r in rows]
    next_offset = offset + limit if len(items) == limit else None
    return {"code": 0, "data": {"items": items, "next_offset": next_offset}}


@router.post("/{tid}/clone")
async def clone_template(tid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        tpl = (await s.execute(text("SELECT * FROM room_templates WHERE id=:i"),
                               {"i": tid})).mappings().first()
        if tpl is None:
            raise AppError(404, "TEMPLATE_NOT_FOUND", "模板不存在")
        room = (await s.execute(text(
            "INSERT INTO rooms (name,description,owner_id,system_prompt,model_id,access_type,"
            "max_members,daily_token_budget,ai_trigger,context_window) "
            "VALUES (:n,:d,:o,:sp,:m,:a,:mx,:b,:t,:w) RETURNING id,name"),
            {"n": tpl["name"], "d": tpl["description"], "o": user["id"],
             "sp": tpl["system_prompt"], "m": tpl["model_id"], "a": tpl["access_type"],
             "mx": tpl["max_members"], "b": tpl["daily_token_budget"],
             "t": tpl["ai_trigger"], "w": tpl["context_window"]})).mappings().one()
        await s.execute(text(
            "INSERT INTO room_members (room_id,user_id,role) VALUES (:r,:u,'owner')"),
            {"r": room["id"], "u": user["id"]})
        await s.execute(text("UPDATE rooms SET member_count=1 WHERE id=:r"), {"r": room["id"]})
        await s.execute(text(
            "INSERT INTO messages (scope,room_id,role,content) VALUES ('room',:r,'system',:c)"),
            {"r": room["id"], "c": f"房间由模板「{tpl['name']}」创建"})
        await s.execute(text(
            "UPDATE room_templates SET use_count=use_count+1 WHERE id=:i"), {"i": tid})
        await s.commit()
    return {"code": 0, "data": {"room_id": room["id"], "name": room["name"]}}


@router.delete("/{tid}")
async def delete_template(tid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        tpl = (await s.execute(text(
            "SELECT published_by FROM room_templates WHERE id=:i"),
            {"i": tid})).mappings().first()
        if tpl is None:
            raise AppError(404, "TEMPLATE_NOT_FOUND", "模板不存在")
        if tpl["published_by"] != user["id"] and user["role"] != "admin":
            raise AppError(403, "FORBIDDEN", "只能删除自己发布的模板")
        await s.execute(text("DELETE FROM room_templates WHERE id=:i"), {"i": tid})
        await s.commit()
    return {"code": 0, "data": {"deleted": True}}