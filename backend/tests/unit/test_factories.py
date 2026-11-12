"""US-006：测试数据工厂、外部调用拦截、FK 逆序清理。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text


async def test_make_user_applies_defaults_and_overrides(spike_session):
    from tests.factories import make_user

    uid = await make_user(spike_session)
    row = (await spike_session.execute(
        text("SELECT role, nickname FROM users WHERE id=:i"), {"i": uid})).one()
    assert row.role == "member"
    uid2 = await make_user(spike_session, role="admin", nickname="老板",
                           email="boss@x.com")
    row2 = (await spike_session.execute(
        text("SELECT role, nickname FROM users WHERE id=:i"), {"i": uid2})).one()
    assert (row2.role, row2.nickname) == ("admin", "老板")


async def test_factories_build_room_with_owner(spike_session):
    from tests.factories import make_room, make_user

    owner = await make_user(spike_session)
    rid = await make_room(spike_session, owner_id=owner, name="测试室")
    cnt = (await spike_session.execute(
        text("SELECT count(*) FROM room_members WHERE room_id=:r AND role='owner'"),
        {"r": rid})).scalar_one()
    assert cnt == 1


async def test_cleanup_removes_all_rows_in_fk_order(spike_session):
    from tests.factories import cleanup_all, make_channel, make_model, make_room, make_user

    u = await make_user(spike_session)
    await make_room(spike_session, owner_id=u)
    await make_channel(spike_session)
    await make_model(spike_session)
    await cleanup_all(spike_session)
    for t in ("users", "rooms", "room_members", "channels", "models",
              "messages", "usage_logs", "daily_usage"):
        n = (await spike_session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
        assert n == 0, f"{t} 未清空: {n}"


async def test_external_http_is_blocked_by_default():
    with pytest.raises(Exception) as ei:
        async with httpx.AsyncClient() as c:
            await c.get("https://api.deepseek.com/v1/models")
    assert "respx" in str(type(ei.value)).lower() or "mock" in str(ei.value).lower()


async def test_cleanup_tolerates_tables_that_do_not_exist(spike_session):
    """smoke 库只有 users 表，清理不能因缺表而报错。"""
    from sqlalchemy import text

    from tests.factories import cleanup_all
    from tests.unit.conftest import apply_spike_schema_async

    try:
        await spike_session.execute(text("DROP TABLE IF EXISTS daily_usage CASCADE"))
        await spike_session.commit()
        await cleanup_all(spike_session)      # 不应抛异常
    finally:
        await apply_spike_schema_async()
