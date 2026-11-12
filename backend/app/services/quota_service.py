"""配额账本（PRD 5.6）。预扣必须原子，失败必须退回，绝不留悬挂。"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FREEZE = text(
    "INSERT INTO daily_usage (quota_date, owner_id, room_id, total_tokens, ai_call_count) "
    "SELECT CAST(:d AS date), CAST(:owner AS bigint), CAST(:room AS bigint), "
    "CAST(:tokens AS bigint), 1 WHERE CAST(:tokens AS bigint) <= CAST(:limit AS bigint) "
    "ON CONFLICT (quota_date, owner_id, room_id) "
    "DO UPDATE SET total_tokens = daily_usage.total_tokens + EXCLUDED.total_tokens, "
    "ai_call_count = daily_usage.ai_call_count + 1, updated_at = now() "
    "WHERE daily_usage.total_tokens + EXCLUDED.total_tokens <= :limit "
    "RETURNING total_tokens")


class QuotaExceeded(Exception):
    pass


async def freeze_tokens(session: AsyncSession, *, quota_date: date, owner_id: int,
                        room_id: int | None, tokens: int, limit: int) -> bool:
    row = (await session.execute(_FREEZE, {
        "d": quota_date, "owner": owner_id, "room": room_id,
        "tokens": tokens, "limit": limit})).first()
    return row is not None


async def begin_call(session: AsyncSession, *, user_id: int, owner_id: int,
                     room_id: int | None, conversation_id: int | None,
                     model_id: int | None, channel_id: int | None,
                     frozen: int, quota_date: date, limit: int,
                     model_public_name: str | None = None,
                     model_display_name: str | None = None,
                     channel_name: str | None = None) -> str:
    if not await freeze_tokens(session, quota_date=quota_date, owner_id=owner_id,
                               room_id=room_id, tokens=frozen, limit=limit):
        raise QuotaExceeded(str(owner_id))
    call_id = str(uuid.uuid4())
    await session.execute(text(
        "INSERT INTO usage_logs (call_id,user_id,owner_id,room_id,conversation_id,model_id,"
        "channel_id,model_public_name,model_display_name,channel_name,status,frozen_tokens,"
        "quota_date) VALUES (CAST(:cid AS uuid),:u,:o,:r,:conv,:m,:ch,:mpn,:mdn,:cn,"
        "'pending',:f,:d)"),
        {"cid": call_id, "u": user_id, "o": owner_id, "r": room_id, "conv": conversation_id,
         "m": model_id, "ch": channel_id, "mpn": model_public_name, "mdn": model_display_name,
         "cn": channel_name, "f": frozen, "d": quota_date})
    await session.commit()
    return call_id


async def _adjust(session: AsyncSession, *, quota_date: date, owner_id: int,
                  room_id: int | None, delta: int, prompt: int = 0,
                  completion: int = 0, cost: float = 0.0) -> None:
    await session.execute(text(
        "UPDATE daily_usage SET total_tokens = GREATEST(total_tokens + :delta, 0), "
        "prompt_tokens = prompt_tokens + :p, completion_tokens = completion_tokens + :c, "
        "cost = cost + :cost, updated_at = now() "
        "WHERE quota_date=:d AND owner_id=:o AND room_id IS NOT DISTINCT FROM :r"),
        {"delta": delta, "p": prompt, "c": completion, "cost": cost,
         "d": quota_date, "o": owner_id, "r": room_id})


async def settle_call(session: AsyncSession, *, call_id: str, quota_date: date,
                      owner_id: int, room_id: int | None, frozen: int,
                      prompt_tokens: int, completion_tokens: int, cost: float,
                      first_token_ms: int, total_ms: int) -> None:
    actual = prompt_tokens + completion_tokens
    await _adjust(session, quota_date=quota_date, owner_id=owner_id, room_id=room_id,
                  delta=actual - frozen, prompt=prompt_tokens,
                  completion=completion_tokens, cost=cost)
    await session.execute(text(
        "UPDATE usage_logs SET status='settled', prompt_tokens=:p, completion_tokens=:c, "
        "total_tokens=:t, cost=:cost, first_token_ms=:f, total_ms=:ms, settled_at=now() "
        "WHERE call_id=CAST(:cid AS uuid) AND status='pending'"),
        {"p": prompt_tokens, "c": completion_tokens, "t": actual, "cost": cost,
         "f": first_token_ms, "ms": total_ms, "cid": call_id})
    await session.commit()


async def refund_call(session: AsyncSession, *, call_id: str, quota_date: date,
                      owner_id: int, room_id: int | None, frozen: int, reason: str) -> None:
    await _adjust(session, quota_date=quota_date, owner_id=owner_id, room_id=room_id,
                  delta=-frozen)
    await session.execute(text(
        "UPDATE usage_logs SET status='refunded', fail_reason=:r, settled_at=now() "
        "WHERE call_id=CAST(:cid AS uuid) AND status='pending'"),
        {"r": reason[:255], "cid": call_id})
    await session.commit()


async def freeze(*, quota_date: date, owner_id: int, room_id: int | None,
                 tokens: int, limit: int, dsn: dict[str, Any]) -> bool:
    """独立连接版本，供并发超卖测试使用（与上面同一套 SQL 语义）。"""
    import asyncpg
    conn = await asyncpg.connect(**dsn)
    try:
        row = await conn.fetchrow(
            "INSERT INTO daily_usage (quota_date,owner_id,room_id,total_tokens,ai_call_count) "
            "SELECT $1,$2,$3,$4::bigint,1 WHERE $4::bigint <= $5::bigint "
            "ON CONFLICT (quota_date,owner_id,room_id) "
            "DO UPDATE SET total_tokens=daily_usage.total_tokens+EXCLUDED.total_tokens, "
            "ai_call_count=daily_usage.ai_call_count+1, updated_at=now() "
            "WHERE daily_usage.total_tokens+EXCLUDED.total_tokens <= $5 RETURNING total_tokens",
            quota_date, owner_id, room_id, tokens, limit)
        return row is not None
    finally:
        await conn.close()
