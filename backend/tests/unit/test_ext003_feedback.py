"""EXT-003 消息反馈：upsert 改票/取消、权限、管理员聚合。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def users(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    owner = await make_user(spike_session, nickname="属主", daily_token_limit=100000)
    member = await make_user(spike_session, nickname="成员")
    stranger = await make_user(spike_session, nickname="路人")
    admin = await make_user(spike_session, role="admin", nickname="管理员")

    def hdr(uid, role="member"):
        tok, _ = create_access_token(uid, role)
        return {"Authorization": f"Bearer {tok}"}

    return {"owner": owner, "member": member, "stranger": stranger, "admin": admin,
            "h_owner": hdr(owner), "h_member": hdr(member),
            "h_stranger": hdr(stranger), "h_admin": hdr(admin, "admin")}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


@pytest.fixture
async def dm_msg(spike_session, users):
    from tests.factories import make_conversation

    cid = await make_conversation(spike_session, user_id=users["owner"])
    mid = int((await spike_session.execute(text(
        "INSERT INTO messages (scope,conversation_id,role,content) "
        "VALUES ('dm',:c,'assistant','AI 的回答') RETURNING id"),
        {"c": cid})).scalar_one())
    await spike_session.commit()
    return mid


async def _vote(client, mid, headers, rating="up", reason=None):
    body = {"rating": rating}
    if reason is not None:
        body["reason"] = reason
    return await client.post(f"/api/messages/{mid}/feedback", json=body, headers=headers)


async def test_vote_change_cancel(client, dm_msg, users, spike_session):
    r = await _vote(client, dm_msg, users["h_owner"], "up")
    assert r.status_code == 200 and r.json()["data"]["state"] == "up"
    r = await _vote(client, dm_msg, users["h_owner"], "down", reason="答非所问")
    assert r.json()["data"]["state"] == "down"
    row = (await spike_session.execute(text(
        "SELECT rating,reason FROM message_feedbacks WHERE message_id=:m"),
        {"m": dm_msg})).mappings().one()
    assert row["rating"] == "down" and row["reason"] == "答非所问"
    r = await _vote(client, dm_msg, users["h_owner"], "down")
    assert r.json()["data"]["state"] == "none", "投相同评价应取消"
    n = (await spike_session.execute(text(
        "SELECT count(*) FROM message_feedbacks WHERE message_id=:m"),
        {"m": dm_msg})).scalar_one()
    assert n == 0


async def test_dm_permission(client, dm_msg, users):
    assert (await _vote(client, dm_msg, users["h_stranger"])).status_code == 403
    assert (await _vote(client, dm_msg, users["h_admin"])).status_code == 200
    assert (await _vote(client, 99999999, users["h_owner"])).status_code == 404


async def test_room_permission(client, spike_session, users):
    from tests.factories import add_member, make_room

    rid = await make_room(spike_session, owner_id=users["owner"])
    await add_member(spike_session, room_id=rid, user_id=users["member"])
    mid = int((await spike_session.execute(text(
        "INSERT INTO messages (scope,room_id,role,content) "
        "VALUES ('room',:r,'assistant','房间 AI 回答') RETURNING id"),
        {"r": rid})).scalar_one())
    await spike_session.commit()
    assert (await _vote(client, mid, users["h_member"])).status_code == 200
    assert (await _vote(client, mid, users["h_stranger"])).status_code == 403


async def test_invalid_rating(client, dm_msg, users):
    r = await client.post(f"/api/messages/{dm_msg}/feedback",
                          json={"rating": "maybe"}, headers=users["h_owner"])
    assert r.status_code == 422


async def test_admin_feedback_stats(client, spike_session, users, dm_msg):
    from tests.factories import make_model, make_room

    m1 = await make_model(spike_session, display_name="模型甲")
    m2 = await make_model(spike_session, display_name="模型乙")
    rid = await make_room(spike_session, owner_id=users["owner"], name="差评房间")
    msgs = []
    for model, scope, ref in ((m1, "dm", dm_msg), (m2, "room", None)):
        if scope == "dm":
            await spike_session.execute(text(
                "UPDATE messages SET model_id=:m WHERE id=:i"), {"m": model, "i": ref})
            msgs.append(ref)
        else:
            for _ in range(3):
                mid = int((await spike_session.execute(text(
                    "INSERT INTO messages (scope,room_id,role,content,model_id) "
                    "VALUES ('room',:r,'assistant','x',:m) RETURNING id"),
                    {"r": rid, "m": model})).scalar_one())
                msgs.append(mid)
    await spike_session.commit()
    await _vote(client, dm_msg, users["h_owner"], "up")
    await _vote(client, msgs[1], users["h_owner"], "down")
    await _vote(client, msgs[2], users["h_owner"], "down")
    await _vote(client, msgs[3], users["h_owner"], "up")

    assert (await client.get("/api/admin/stats/feedback",
                             headers=users["h_member"])).status_code == 403
    r = await client.get("/api/admin/stats/feedback", headers=users["h_admin"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["total"]["up"] == 2 and d["total"]["down"] == 2
    assert d["total"]["rate"] == 0.5
    by_model = {x["display_name"]: x for x in d["by_model"]}
    assert by_model["模型甲"]["up"] == 1 and by_model["模型甲"]["down"] == 0
    assert by_model["模型乙"]["up"] == 1 and by_model["模型乙"]["down"] == 2
    assert d["top_rooms"][0]["name"] == "差评房间"
    assert d["top_rooms"][0]["down"] == 2