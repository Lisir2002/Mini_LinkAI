"""EXT-016 房间模板市场：发布权限、列表搜索、原子克隆与计数。"""
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
async def actors(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    owner = await make_user(spike_session, nickname="房主")
    other = await make_user(spike_session, nickname="克隆者")
    to, _ = create_access_token(owner, "member")
    tx, _ = create_access_token(other, "member")
    return {"owner": owner, "other": other,
            "h_owner": {"Authorization": f"Bearer {to}"},
            "h_other": {"Authorization": f"Bearer {tx}"}}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


@pytest.fixture
async def room(spike_session, actors):
    from tests.factories import make_model, make_room

    mid = await make_model(spike_session, public_name="tpl-model", display_name="模板模型")
    rid = await make_room(spike_session, owner_id=actors["owner"], name="翻译室",
                          description="贴原文即译", system_prompt="你是专业翻译",
                          model_id=mid, max_members=30, daily_token_budget=123456,
                          context_window=15)
    return {"rid": rid, "mid": mid}


async def _publish(client, rid, headers):
    return await client.post("/api/room-templates", json={"room_id": rid}, headers=headers)


async def test_publish_copies_config(client, spike_session, actors, room):
    r = await _publish(client, room["rid"], actors["h_owner"])
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["template_id"]
    row = (await spike_session.execute(text(
        "SELECT * FROM room_templates WHERE id=:i"), {"i": tid})).mappings().one()
    assert row["name"] == "翻译室" and row["system_prompt"] == "你是专业翻译"
    assert row["model_id"] == room["mid"] and row["max_members"] == 30
    assert row["daily_token_budget"] == 123456 and row["context_window"] == 15
    assert row["published_by"] == actors["owner"] and row["use_count"] == 0


async def test_publish_permission_and_private(client, spike_session, actors, room):
    assert (await _publish(client, room["rid"], actors["h_other"])).status_code == 403
    await spike_session.execute(text(
        "UPDATE rooms SET access_type='invite_code' WHERE id=:i"), {"i": room["rid"]})
    await spike_session.commit()
    r = await _publish(client, room["rid"], actors["h_owner"])
    assert r.status_code == 422 and r.json()["code"] == "TEMPLATE_PRIVATE_ROOM"


async def test_list_search_and_order(client, spike_session, actors, room):
    await _publish(client, room["rid"], actors["h_owner"])
    from tests.factories import make_room
    r2 = await make_room(spike_session, owner_id=actors["owner"], name="代码审查室",
                         description="review 代码")
    await _publish(client, r2, actors["h_owner"])
    lst = await client.get("/api/room-templates", headers=actors["h_other"])
    assert lst.status_code == 200
    items = lst.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["model_name"] in ("模板模型", None)
    q = await client.get("/api/room-templates", params={"q": "翻译"},
                         headers=actors["h_other"])
    assert len(q.json()["data"]["items"]) == 1
    assert q.json()["data"]["items"][0]["name"] == "翻译室"


async def test_clone_copies_config_and_counts(client, spike_session, actors, room):
    tid = (await _publish(client, room["rid"], actors["h_owner"])).json()["data"]["template_id"]
    r = await client.post(f"/api/room-templates/{tid}/clone", headers=actors["h_other"])
    assert r.status_code == 200, r.text
    new_rid = r.json()["data"]["room_id"]
    row = (await spike_session.execute(text("SELECT * FROM rooms WHERE id=:i"),
                                       {"i": new_rid})).mappings().one()
    assert row["name"] == "翻译室" and row["system_prompt"] == "你是专业翻译"
    assert row["model_id"] == room["mid"] and row["max_members"] == 30
    assert row["daily_token_budget"] == 123456 and row["context_window"] == 15
    assert row["owner_id"] == actors["other"] and row["member_count"] == 1
    member = (await spike_session.execute(text(
        "SELECT role FROM room_members WHERE room_id=:r AND user_id=:u"),
        {"r": new_rid, "u": actors["other"]})).scalar_one()
    assert member == "owner"
    cnt = (await spike_session.execute(text(
        "SELECT use_count FROM room_templates WHERE id=:i"), {"i": tid})).scalar_one()
    assert cnt == 1
    await client.post(f"/api/room-templates/{tid}/clone", headers=actors["h_other"])
    cnt2 = (await spike_session.execute(text(
        "SELECT use_count FROM room_templates WHERE id=:i"), {"i": tid})).scalar_one()
    assert cnt2 == 2


async def test_clone_survives_deleted_model(client, spike_session, actors, room):
    tid = (await _publish(client, room["rid"], actors["h_owner"])).json()["data"]["template_id"]
    await spike_session.execute(text("DELETE FROM models WHERE id=:i"), {"i": room["mid"]})
    await spike_session.commit()
    r = await client.post(f"/api/room-templates/{tid}/clone", headers=actors["h_other"])
    assert r.status_code == 200
    new_rid = r.json()["data"]["room_id"]
    mid = (await spike_session.execute(text("SELECT model_id FROM rooms WHERE id=:i"),
                                       {"i": new_rid})).scalar_one()
    assert mid is None


async def test_delete_permission(client, actors, room):
    tid = (await _publish(client, room["rid"], actors["h_owner"])).json()["data"]["template_id"]
    assert (await client.delete(f"/api/room-templates/{tid}",
                                headers=actors["h_other"])).status_code == 403
    assert (await client.delete(f"/api/room-templates/{tid}",
                                headers=actors["h_owner"])).status_code == 200

async def test_room_payload_exposes_owner(client, actors, room):
    r = await client.get(f"/api/rooms/{room['rid']}/messages", headers=actors["h_owner"])
    assert r.status_code == 200
    assert r.json()["data"]["room"]["owner_id"] == actors["owner"]
