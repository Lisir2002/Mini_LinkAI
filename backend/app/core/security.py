"""密码哈希（PRD 10.1 第三层）：argon2id，不可逆。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.redis_client import get_redis

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class TokenInvalid(Exception):
    """JWT 无效、过期或签名不匹配。"""


def create_access_token(user_id: int, role: str) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id), "role": role,
        "iat": int(now.timestamp()), "iat_ms": int(now.timestamp() * 1000),
        "exp": exp, "jti": uuid.uuid4().hex,
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256"), exp


def decode_token(token: str) -> dict[str, Any]:
    """先用当前密钥，再用过渡期旧密钥（PRD 10.1 第五层密钥轮换）。"""
    secrets = [settings.JWT_SECRET]
    if settings.JWT_SECRET_PREV:
        secrets.append(settings.JWT_SECRET_PREV)
    last: Exception | None = None
    for sec in secrets:
        try:
            return dict(pyjwt.decode(token, sec, algorithms=["HS256"]))
        except pyjwt.PyJWTError as exc:
            last = exc
    raise TokenInvalid(str(last))


async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    await get_redis().set(f"token_bl:{jti}", "1", ex=max(ttl_seconds, 1))


async def is_blacklisted(jti: str) -> bool:
    return bool(await get_redis().exists(f"token_bl:{jti}"))
