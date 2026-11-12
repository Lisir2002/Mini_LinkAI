"""US-016：数据范围过滤与管理员自我保护。"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.errors import AppError


async def _u(session, role="member"):
    from tests.factories import make_user
    uid = await make_user(session, role=role)
    return {"id": uid, "role": role}


async def test_conversation_scope_owner_ok_others_404(spike_session):
    from app.deps import scope_conversation
    from tests.factories import make_conversation

    a, b = await _u(spike_session), await _u(spike_session)
    cid = await make_conversation(spike_session, user_id=a["id"])
    assert (await scope_conversation(a, cid))["id"] == cid
    with pytest.raises(AppError) as ei:
        await scope_conversation(b, cid)
    assert ei.value.status == 404, "越权必须统一 404，不泄露资源存在性"


async def test_room_scope_member_ok_outsider_403_archived_404(spike_session):
    from app.deps import scope_room
    from tests.factories import add_member, make_room

    owner, outsider = await _u(spike_session), await _u(spike_session)
    rid = await make_room(spike_session, owner_id=owner["id"])
    assert (await scope_room(owner, rid))["id"] == rid
    with pytest.raises(AppError) as ei:
        await scope_room(outsider, rid)
    assert ei.value.status == 403
    await add_member(spike_session, room_id=rid, user_id=outsider["id"])
    assert (await scope_room(outsider, rid))["id"] == rid
    await spike_session.execute(text("UPDATE rooms SET archived=true WHERE id=:r"), {"r": rid})
    await spike_session.commit()
    with pytest.raises(AppError) as ei2:
        await scope_room(owner, rid)
    assert ei2.value.status == 404


async def test_room_perm_hierarchy(spike_session):
    from app.deps import room_perm
    from tests.factories import add_member, make_room

    owner, mgr, mem, outsider = [await _u(spike_session) for _ in range(4)]
    rid = await make_room(spike_session, owner_id=owner["id"])
    await add_member(spike_session, room_id=rid, user_id=mgr["id"], role="manager")
    await add_member(spike_session, room_id=rid, user_id=mem["id"])
    assert await room_perm(owner, rid, "owner") is True
    assert await room_perm(mgr, rid, "owner") is False
    assert await room_perm(mgr, rid, "manager") is True
    assert await room_perm(mem, rid, "manager") is False
    assert await room_perm(mem, rid, "member") is True
    assert await room_perm(outsider, rid, "member") is False


async def test_usage_scope_grading(spike_session):
    from app.deps import scope_usage
    from tests.factories import add_member, make_room

    owner, mgr, mem = [await _u(spike_session) for _ in range(3)]
    admin = await _u(spike_session, role="admin")
    rid = await make_room(spike_session, owner_id=owner["id"])
    await add_member(spike_session, room_id=rid, user_id=mgr["id"], role="manager")
    await add_member(spike_session, room_id=rid, user_id=mem["id"])
    assert (await scope_usage(admin, rid))["level"] == "all"
    assert (await scope_usage(owner, rid))["level"] == "room_all"
    assert (await scope_usage(mgr, rid))["level"] == "room_summary"
    assert (await scope_usage(mem, rid))["level"] == "own"


async def test_admin_cannot_ban_self_or_last_admin(spike_session):
    from app.deps import guard_admin_target

    admin = await _u(spike_session, role="admin")
    with pytest.raises(AppError) as ei:
        await guard_admin_target(admin, admin["id"])
    assert ei.value.status == 409 and ei.value.code == "LAST_ADMIN_PROTECTED"
