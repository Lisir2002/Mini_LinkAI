"""邀请码校验与原子核销（PRD 5.1 / US-019）。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InviteCodeInvalid(Exception):
    """邀请码不存在、已用完或已过期。"""


async def redeem(session: AsyncSession, code: str) -> int:
    """条件 UPDATE 原子核销；返回空即无效。不在此处 commit，交由调用方事务控制。"""
    row = await session.execute(
        text("UPDATE invite_codes SET used_count = used_count + 1 "
             "WHERE code = :c AND used_count < max_uses "
             "AND (expires_at IS NULL OR expires_at > now()) RETURNING id"),
        {"c": code},
    )
    got = row.first()
    if got is None:
        raise InviteCodeInvalid(code)
    return int(got[0])
