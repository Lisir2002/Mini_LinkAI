"""US-017 审计服务 / US-019 邀请码原子核销。"""
from __future__ import annotations

import pytest
from sqlalchemy import text


async def test_audit_record_writes_row_without_secrets(spike_session):
    from app.services.audit_service import record
    from tests.factories import make_user

    uid = await make_user(spike_session)
    await record(spike_session, actor_id=uid, action="channel.create",
                 target_type="channel", target_id="9",
                 detail={"name": "c1", "api_key": "sk-should-not-persist",
                         "password": "p@ss"})
    row = (await spike_session.execute(
        text("SELECT action, detail FROM audit_logs ORDER BY id DESC LIMIT 1"))).one()
    assert row.action == "channel.create"
    assert "sk-should-not-persist" not in str(row.detail)
    assert "p@ss" not in str(row.detail)
    assert row.detail["name"] == "c1"


async def _make_code(session, max_uses: int = 1) -> str:
    from tests.factories import make_user
    uid = await make_user(session)
    code = "RM-TEST-" + str(max_uses) + "-" + str(id(session))[-6:]
    await session.execute(
        text("INSERT INTO invite_codes (code,created_by,max_uses) VALUES (:c,:u,:m)"),
        {"c": code, "u": uid, "m": max_uses})
    await session.commit()
    return code


async def test_invite_redeem_increments_used_count(spike_session):
    from app.services.invite_service import redeem

    code = await _make_code(spike_session, max_uses=2)
    await redeem(spike_session, code)
    n = (await spike_session.execute(
        text("SELECT used_count FROM invite_codes WHERE code=:c"), {"c": code})).scalar_one()
    assert n == 1


async def test_invite_invalid_code_raises(spike_session):
    from app.services.invite_service import InviteCodeInvalid, redeem

    with pytest.raises(InviteCodeInvalid):
        await redeem(spike_session, "RM-NOT-EXIST")


async def test_invite_exhausted_raises(spike_session):
    from app.services.invite_service import InviteCodeInvalid, redeem

    code = await _make_code(spike_session, max_uses=1)
    await redeem(spike_session, code)
    with pytest.raises(InviteCodeInvalid):
        await redeem(spike_session, code)


async def test_invite_concurrent_redeem_only_one_wins(spike_session):
    """max_uses=1 的邀请码，10 个并发核销只能成功 1 次。"""
    import asyncio

    import asyncpg

    from tests.factories import make_user

    uid = await make_user(spike_session)
    code = "RM-RACE-" + str(uid)
    await spike_session.execute(
        text("INSERT INTO invite_codes (code,created_by,max_uses) VALUES (:c,:u,1)"),
        {"c": code, "u": uid})
    await spike_session.commit()

    dsn = dict(host="127.0.0.1", port=5432, user="aicr",
               password="spikepass", database="ai_chatroom_spike")

    async def one() -> bool:
        conn = await asyncpg.connect(**dsn)
        try:
            r = await conn.fetchrow(
                "UPDATE invite_codes SET used_count=used_count+1 "
                "WHERE code=$1 AND used_count<max_uses "
                "AND (expires_at IS NULL OR expires_at>now()) RETURNING id", code)
            return r is not None
        finally:
            await conn.close()

    results = await asyncio.gather(*[one() for _ in range(10)])
    assert sum(results) == 1, f"并发核销成功 {sum(results)} 次，应为 1"
    n = (await spike_session.execute(
        text("SELECT used_count FROM invite_codes WHERE code=:c"), {"c": code})).scalar_one()
    assert n == 1
