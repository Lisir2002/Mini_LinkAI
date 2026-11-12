"""认证接口（PRD 8.1 / 5.1）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.idempotency import run_idempotent
from app.core.logging import mask_email, mask_phone
from app.core.ratelimit import check_rate_limit
from app.core.security import (
    blacklist_token,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.interfaces.deps import get_current_user, get_db
from app.users.services import audit_service
from app.users.services.invite_service import InviteCodeInvalid, redeem

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{7,15}$")
    password: str = Field(min_length=8, max_length=72)
    nickname: str = Field(min_length=1, max_length=32)
    invite_code: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> RegisterIn:
        if bool(self.email) == bool(self.phone):
            raise ValueError("email 与 phone 必须且只能填一个")
        return self


class LoginIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    password: str

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> LoginIn:
        if bool(self.email) == bool(self.phone):
            raise ValueError("email 与 phone 必须且只能填一个")
        return self


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


def _user_out(row: dict[str, Any], token: str, exp: Any) -> dict[str, Any]:
    ident = mask_email(row["email"]) if row.get("email") else mask_phone(row.get("phone") or "")
    return {"token": token, "expires_at": exp.isoformat(),
            "user": {"id": row["id"], "nickname": row["nickname"],
                     "email": ident, "role": row["role"],
                     "must_change_password": row.get("must_change_password", False),
                     "daily_msg_limit": row["daily_msg_limit"],
                     "daily_token_limit": row["daily_token_limit"]}}


@router.post("/register")
async def register(body: RegisterIn, request: Request,
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    ip = request.client.host if request.client else None
    ok, wait = await check_rate_limit(f"register:{ip}", limit=5, window_sec=86400)
    if not ok:
        raise AppError(429, "RATE_LIMITED", f"注册过于频繁，请 {wait} 秒后再试")

    async def _do_register() -> dict[str, Any]:
        if settings.REGISTRATION_MODE == "closed":
            raise AppError(403, "REGISTRATION_CLOSED", "当前仅管理员可创建账号")
        if settings.REGISTRATION_MODE == "invite_code":
            if not body.invite_code:
                raise AppError(422, "INVITE_CODE_INVALID", "请填写邀请码")
            try:
                await redeem(db, body.invite_code)
            except InviteCodeInvalid:
                raise AppError(422, "INVITE_CODE_INVALID", "邀请码无效或已被使用") from None
        try:
            row = (await db.execute(
                text("INSERT INTO users (email,phone,password_hash,nickname,role,invite_code_used) "
                     "VALUES (:e,:ph,:p,:n,'member',:c) "
                     "RETURNING id,email,phone,nickname,role,must_change_password,"
                     "daily_msg_limit,daily_token_limit"),
                {"e": str(body.email) if body.email else None, "ph": body.phone,
                 "p": hash_password(body.password),
                 "n": body.nickname.strip(), "c": body.invite_code})).mappings().one()
            await audit_service.record(db, actor_id=row["id"], action="user.register",
                                       target_type="user", target_id=str(row["id"]), ip=ip)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise AppError(409, "EMAIL_EXISTS", "该邮箱已注册，去登录？") from None
        token, exp = create_access_token(row["id"], row["role"])
        return _user_out(dict(row), token, exp)

    idem = body.idempotency_key or request.headers.get("Idempotency-Key")
    if idem:
        data = await run_idempotent(f"register:{idem}", 600, _do_register)
    else:
        data = await _do_register()
    return {"code": 0, "data": data}


@router.post("/login")
async def login(body: LoginIn, request: Request,
                db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    ident = str(body.email) if body.email else str(body.phone)
    column = "email" if body.email else "phone"
    key = f"login-fail:{ident}"
    ok, wait = await check_rate_limit(key, limit=5, window_sec=900, consume=False)
    if not ok:
        raise AppError(423, "ACCOUNT_LOCKED", f"尝试过于频繁，请 {wait} 秒后重试")
    row = (await db.execute(
        text("SELECT id,email,phone,nickname,role,status,password_hash,must_change_password,"
             f"daily_msg_limit,daily_token_limit FROM users WHERE {column}=:e"),
        {"e": ident})).mappings().first()
    if row is None or not verify_password(row["password_hash"], body.password):
        from app.core.ratelimit import record_rate_limit
        await record_rate_limit(key, 900)
        raise AppError(401, "AUTH_FAILED", "邮箱或密码错误")
    if row["status"] == "banned":
        raise AppError(403, "ACCOUNT_BANNED", "账号已被停用，请联系管理员")
    ip = request.client.host if request.client else None
    await db.execute(text("UPDATE users SET last_login_at=now(), last_login_ip=CAST(:ip AS inet) "
                          "WHERE id=:i"), {"i": row["id"], "ip": ip})
    await audit_service.record(db, actor_id=row["id"], action="user.login",
                               target_type="user", target_id=str(row["id"]), ip=ip)
    await db.commit()
    token, exp = create_access_token(row["id"], row["role"])
    return {"code": 0, "data": _user_out(dict(row), token, exp)}


@router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"code": 0, "data": {
        "id": user["id"], "nickname": user["nickname"],
        "email": mask_email(user["email"]), "role": user["role"],
        "must_change_password": user["must_change_password"],
        "daily_msg_limit": user["daily_msg_limit"],
        "daily_token_limit": user["daily_token_limit"],
    }}


@router.post("/password")
async def change_password(body: PasswordIn, request: Request,
                          user: dict[str, Any] = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(text("SELECT password_hash FROM users WHERE id=:i"),
                            {"i": user["id"]})).scalar_one()
    if not verify_password(row, body.old_password):
        raise AppError(401, "AUTH_FAILED", "原密码不正确")
    await db.execute(text("UPDATE users SET password_hash=:p, must_change_password=false "
                          "WHERE id=:i"),
                     {"p": hash_password(body.new_password), "i": user["id"]})
    await audit_service.record(db, actor_id=user["id"], action="user.password_change",
                               target_type="user", target_id=str(user["id"]))
    await db.commit()
    await revoke_other_tokens(request, user["id"])
    return {"code": 0, "data": {"changed": True}}


@router.post("/logout")
async def logout(request: Request,
                 user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    payload = decode_token(request.headers["Authorization"][7:])
    ttl = int(payload["exp"]) - int(__import__("time").time())
    await blacklist_token(str(payload["jti"]), max(ttl, 1))
    return {"code": 0, "data": {"logged_out": True}}


async def revoke_other_tokens(request: Request, user_id: int) -> None:
    """改密后吊销其他 token，保留当前会话（US-023）。"""
    import json as _json
    import time as _time

    from app.core.redis_client import get_redis

    payload = decode_token(request.headers["Authorization"][7:])
    await get_redis().set(
        f"pwd_changed:{user_id}",
        _json.dumps({"ts": int(_time.time()),
                     "ts_ms": int(_time.time() * 1000),
                     "keep_jti": payload["jti"]}),
        ex=settings.JWT_EXPIRE_DAYS * 86400,
    )
