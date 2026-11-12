"""US-037 选路：优先级、权重、冷却跳过、失败计数与自动禁用。"""
from __future__ import annotations

import pytest
from sqlalchemy import text


async def _mk(spike_session, name, priority=0, weight=100, status="enabled"):
    from tests.factories import make_channel
    cid = await make_channel(spike_session, name=name, priority=priority,
                             weight=weight, status=status)
    return cid


async def _model_with(spike_session, name, cids):
    from tests.factories import make_model
    mid = await make_model(spike_session, public_name=name)
    for c in cids:
        await spike_session.execute(
            text("INSERT INTO model_channels (model_id,channel_id,upstream_model) "
                 "VALUES (:m,:c,'up')"), {"m": mid, "c": c})
    await spike_session.commit()
    return mid


async def test_highest_priority_wins(spike_session):
    from app.llm.services.router_service import select_channel

    lo = await _mk(spike_session, "lo", priority=0)
    hi = await _mk(spike_session, "hi", priority=10)
    await _model_with(spike_session, "prio", [lo, hi])
    for _ in range(5):
        assert (await select_channel(spike_session, "prio"))["id"] == hi


async def test_cooldown_and_disabled_are_skipped(spike_session):
    from app.llm.services.router_service import select_channel

    bad = await _mk(spike_session, "bad", priority=10)
    good = await _mk(spike_session, "good", priority=0)
    await spike_session.execute(
        text("UPDATE channels SET cooldown_until=now()+interval '60 s' WHERE id=:i"), {"i": bad})
    await spike_session.commit()
    await _model_with(spike_session, "cool", [bad, good])
    assert (await select_channel(spike_session, "cool"))["id"] == good


async def test_no_channel_raises(spike_session):
    from app.llm.services.router_service import NoChannelAvailable, select_channel

    with pytest.raises(NoChannelAvailable):
        await select_channel(spike_session, "not-exist")


async def test_three_failures_auto_disable(spike_session):
    from app.llm.services.router_service import record_failure

    cid = await _mk(spike_session, "flaky")
    for _ in range(3):
        await record_failure(spike_session, cid, kind="upstream")
    row = (await spike_session.execute(
        text("SELECT status, fail_count, cooldown_until FROM channels WHERE id=:i"),
        {"i": cid})).mappings().one()
    assert row["status"] == "auto_disabled" and row["fail_count"] >= 3
    assert row["cooldown_until"] is not None


async def test_auth_failure_disables_immediately(spike_session):
    from app.llm.services.router_service import record_failure

    cid = await _mk(spike_session, "badauth")
    await record_failure(spike_session, cid, kind="auth")
    st = (await spike_session.execute(
        text("SELECT status FROM channels WHERE id=:i"), {"i": cid})).scalar_one()
    assert st == "auto_disabled", "鉴权失败应立即禁用，不做无谓重试"
