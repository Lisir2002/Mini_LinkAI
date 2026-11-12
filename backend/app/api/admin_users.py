"""US-017 用户管理：列表、封禁/解封、重置密码，全部留审计痕迹。"""
from __future__ import annotations

import json as _json
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.deps import get_db, require_admin
from app.redis_client import get_redis
from app.services import audit_service

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])
Admin = Depends(require_admin)


class BanIn(BaseModel):
    banned: bool
    reason: str | None = Field(default=None, max_length=200)


@router.get("")
async def list_users(q: str = "", user: dict[str, Any] = Admin,
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    pat = f"%{q}%"
    rows = (await db.execute(text(
        "SELECT id,email,phone,nickname,role,status,must_change_password,created_at "
        "FROM users WHERE :q = '' OR nickname ILIKE :pat OR email ILIKE :pat "
        "ORDER BY id LIMIT 200"), {"q": q, "pat": pat})).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.post("/{uid}/ban")
async def ban_user(uid: int, body: BanIn, user: dict[str, Any] = Admin,
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if uid == user["id"]:
        raise AppError(409, "SELF_PROTECTION", "不能封禁自己的账号")
    target = (await db.execute(text("SELECT id FROM users WHERE id=:i"),
                               {"i": uid})).first()
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    new_status = "banned" if body.banned else "active"
    await db.execute(text("UPDATE users SET status=:s WHERE id=:i"),
                     {"s": new_status, "i": uid})
    await audit_service.record(
        db, actor_id=user["id"], action="user.ban" if body.banned else "user.unban",
        target_type="user", target_id=str(uid),
        detail={"status": new_status, "reason": body.reason})
    await db.commit()
    return {"code": 0, "data": {"status": new_status}}


@router.post("/{uid}/reset-password")
async def reset_password(uid: int, user: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    target = (await db.execute(text("SELECT id FROM users WHERE id=:i"),
                               {"i": uid})).first()
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    temp = secrets.token_urlsafe(9)
    await db.execute(text(
        "UPDATE users SET password_hash=:p, must_change_password=true WHERE id=:i"),
        {"p": hash_password(temp), "i": uid})
    await audit_service.record(
        db, actor_id=user["id"], action="user.reset_password",
        target_type="user", target_id=str(uid), detail={"must_change_password": True})
    await db.commit()
    # 吊销该用户全部已签发 token（无保留 jti）
    await get_redis().set(
        f"pwd_changed:{uid}",
        # 管理员重置须吊销全部会话（含同秒签发），故 ts 取重置时刻 +1s；
        # 临时密码登录属人工动作，正常间隔 >1s。
        _json.dumps({"ts": int(time.time()) + 1,
                     "ts_ms": int(time.time() * 1000) + 1000, "keep_jti": ""}),
        ex=settings.JWT_EXPIRE_DAYS * 86400)
    return {"code": 0, "data": {"temp_password": temp}}