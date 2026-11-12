"""FR-001/002 好友：搜索用户、申请流、好友列表、删除好友。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.logging import mask_email
from app.interfaces.deps import get_current_user
from app.users.services import dm_bus

router = APIRouter(prefix="/api", tags=["friends"])
User = Depends(get_current_user)


class RequestIn(BaseModel):
    user_id: int


async def are_friends(s: AsyncSession, a: int, b: int) -> bool:
    row = (await s.execute(text(
        "SELECT 1 FROM friendships WHERE status='accepted' AND "
        "((requester_id=:a AND addressee_id=:b) OR (requester_id=:b AND addressee_id=:a)) "
        "LIMIT 1"), {"a": a, "b": b})).first()
    return row is not None


@router.get("/users/search")
async def search_users(q: str = Query(default=""), user: dict[str, Any] = User) -> dict[str, Any]:
    q = q.strip()
    if not q:
        return {"code": 0, "data": {"items": []}}
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT id,nickname,email FROM users "
            "WHERE id <> :me AND status='active' AND (nickname ILIKE :pat OR email ILIKE :pat) "
            "ORDER BY id LIMIT 20"), {"me": user["id"], "pat": f"%{q}%"})).mappings().all()
    items = [{"id": r["id"], "nickname": r["nickname"],
              "email": mask_email(r["email"]) if r["email"] else None} for r in rows]
    return {"code": 0, "data": {"items": items}}


@router.post("/friends/requests")
async def send_request(body: RequestIn, user: dict[str, Any] = User) -> dict[str, Any]:
    me = user["id"]
    if body.user_id == me:
        raise AppError(422, "CANNOT_ADD_SELF", "不能添加自己为好友")
    async with get_session() as s:
        target = (await s.execute(text(
            "SELECT id,nickname FROM users WHERE id=:i AND status='active'"),
            {"i": body.user_id})).mappings().first()
        if target is None:
            raise AppError(404, "USER_NOT_FOUND", "用户不存在")
        if await are_friends(s, me, body.user_id):
            raise AppError(409, "ALREADY_FRIENDS", "你们已经是好友")
        mine = (await s.execute(text(
            "SELECT id,status FROM friendships WHERE requester_id=:a AND addressee_id=:b"),
            {"a": me, "b": body.user_id})).mappings().first()
        if mine is not None and mine["status"] == "pending":
            raise AppError(409, "REQUEST_EXISTS", "已发送过申请，请等待对方处理")
        reverse = (await s.execute(text(
            "SELECT id FROM friendships WHERE requester_id=:b AND addressee_id=:a "
            "AND status='pending'"), {"a": me, "b": body.user_id})).mappings().first()
        if reverse is not None:
            await s.execute(text(
                "UPDATE friendships SET status='accepted', updated_at=now() WHERE id=:i"),
                {"i": reverse["id"]})
            await s.execute(text(
                "DELETE FROM friendships WHERE requester_id=:a AND addressee_id=:b AND id<>:i"),
                {"a": me, "b": body.user_id, "i": reverse["id"]})
            await s.commit()
            await dm_bus.publish(body.user_id, {"type": "friend_accepted",
                                                "user_id": me, "nickname": user["nickname"]})
            return {"code": 0, "data": {"request_id": reverse["id"], "auto_accepted": True}}
        if mine is not None:
            await s.execute(text(
                "UPDATE friendships SET status='pending', updated_at=now() WHERE id=:i"),
                {"i": mine["id"]})
            rid = mine["id"]
        else:
            row = (await s.execute(text(
                "INSERT INTO friendships (requester_id,addressee_id) VALUES (:a,:b) RETURNING id"),
                {"a": me, "b": body.user_id})).mappings().one()
            rid = row["id"]
        await s.commit()
    await dm_bus.publish(body.user_id, {"type": "friend_request",
                                        "request_id": rid, "user_id": me,
                                        "nickname": user["nickname"]})
    return {"code": 0, "data": {"request_id": rid}}


@router.get("/friends/requests")
async def list_requests(user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        incoming = (await s.execute(text(
            "SELECT f.id,f.requester_id AS user_id,u.nickname,f.created_at "
            "FROM friendships f JOIN users u ON u.id=f.requester_id "
            "WHERE f.addressee_id=:me AND f.status='pending' ORDER BY f.id DESC"),
            {"me": user["id"]})).mappings().all()
        outgoing = (await s.execute(text(
            "SELECT f.id,f.addressee_id AS user_id,u.nickname,f.status,f.created_at "
            "FROM friendships f JOIN users u ON u.id=f.addressee_id "
            "WHERE f.requester_id=:me AND f.status IN ('pending','rejected') "
            "ORDER BY f.id DESC"), {"me": user["id"]})).mappings().all()
    return {"code": 0, "data": {"incoming": [dict(r) for r in incoming],
                                "outgoing": [dict(r) for r in outgoing]}}


async def _handle_request(rid: int, user: dict[str, Any], accept: bool) -> dict[str, Any]:
    async with get_session() as s:
        req = (await s.execute(text(
            "SELECT f.*, u.nickname AS addressee_nickname FROM friendships f "
            "JOIN users u ON u.id=f.addressee_id WHERE f.id=:i"),
            {"i": rid})).mappings().first()
        if req is None:
            raise AppError(404, "REQUEST_NOT_FOUND", "申请不存在")
        if req["addressee_id"] != user["id"]:
            raise AppError(403, "FORBIDDEN", "只有收件人可以处理该申请")
        if req["status"] != "pending":
            raise AppError(409, "REQUEST_HANDLED", "该申请已处理")
        new = "accepted" if accept else "rejected"
        await s.execute(text(
            "UPDATE friendships SET status=:s, updated_at=now() WHERE id=:i"),
            {"s": new, "i": rid})
        if accept:
            await s.execute(text(
                "DELETE FROM friendships WHERE requester_id=:a AND addressee_id=:b AND id<>:i"),
                {"a": req["addressee_id"], "b": req["requester_id"], "i": rid})
        await s.commit()
    if accept:
        await dm_bus.publish(req["requester_id"], {
            "type": "friend_accepted", "user_id": user["id"],
            "nickname": req["addressee_nickname"]})
    return {"code": 0, "data": {"status": new}}


@router.post("/friends/requests/{rid}/accept")
async def accept_request(rid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    return await _handle_request(rid, user, accept=True)


@router.post("/friends/requests/{rid}/reject")
async def reject_request(rid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    return await _handle_request(rid, user, accept=False)


@router.get("/friends")
async def list_friends(user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT DISTINCT ON (u.id) u.id AS user_id, u.nickname, "
            "(SELECT content FROM direct_messages dm WHERE "
            " (dm.sender_id=u.id AND dm.recipient_id=:me) "
            " OR (dm.sender_id=:me AND dm.recipient_id=u.id) "
            " ORDER BY dm.id DESC LIMIT 1) AS last_msg, "
            "(SELECT count(*) FROM direct_messages dm WHERE dm.sender_id=u.id "
            " AND dm.recipient_id=:me AND dm.read_at IS NULL) AS unread_count "
            "FROM friendships f "
            "JOIN users u ON u.id = CASE WHEN f.requester_id=:me THEN f.addressee_id "
            " ELSE f.requester_id END "
            "WHERE f.status='accepted' AND (f.requester_id=:me OR f.addressee_id=:me) "
            "ORDER BY u.id, u.nickname"), {"me": user["id"]})).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.delete("/friends/{uid}")
async def unfriend(uid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        row = (await s.execute(text(
            "DELETE FROM friendships WHERE status='accepted' AND "
            "((requester_id=:a AND addressee_id=:b) OR (requester_id=:b AND addressee_id=:a)) "
            "RETURNING id"), {"a": user["id"], "b": uid})).first()
        if row is None:
            raise AppError(404, "NOT_FRIEND", "你们不是好友")
        await s.commit()
    await dm_bus.publish(uid, {"type": "friend_removed", "user_id": user["id"],
                               "nickname": user["nickname"]})
    return {"code": 0, "data": {"removed": True}}