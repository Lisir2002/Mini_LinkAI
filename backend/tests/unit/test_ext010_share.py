"""EXT-010 导出与分享：格式、权限、HMAC 签名、过期与撤销。"""
from __future__ import annotations

import json

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

    owner = await make_user(spike_session, nickname="属主")
    other = await make_user(spike_session, nickname="路人")
    to, _ = create_access_token(owner, "member")
    tx, _ = create_access_token(other, "member")
    return {"owner": owner, "other": other,
            "h_owner": {"Authorization": f"Bearer {to}"},
            "h_other": {"Authorization": f"Bearer {tx}"}}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


@pytest.fixture
async def conv(spike_session, actors):
    from tests.factories import make_conversation

    cid = await make_conversation(spike_session, user_id=actors["owner"], title="导出会话")
    await spike_session.execute(text(
        "INSERT INTO messages (scope,conversation_id,sender_id,role,content) VALUES "
        "('dm',:c,:u,'user','你好，导出测试'),('dm',:c,NULL,'assistant','收到，这是回复')"),
        {"c": cid, "u": actors["owner"]})
    await spike_session.commit()
    return cid


async def test_export_md_and_json(client, conv, actors):
    r = await client.get(f"/api/conversations/{conv}/export", params={"format": "md"},
                         headers=actors["h_owner"])
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "导出会话" in r.text and "你好，导出测试" in r.text and "收到，这是回复" in r.text
    r2 = await client.get(f"/api/conversations/{conv}/export", params={"format": "json"},
                          headers=actors["h_owner"])
    d = json.loads(r2.text)
    assert d["title"] == "导出会话" and len(d["messages"]) == 2
    assert d["messages"][0]["content"] == "你好，导出测试"


async def test_export_permission(client, conv, actors):
    r = await client.get(f"/api/conversations/{conv}/export", headers=actors["h_other"])
    assert r.status_code == 404


async def test_room_export_member_only(client, spike_session, actors):
    from tests.factories import make_room

    rid = await make_room(spike_session, owner_id=actors["owner"], name="导出房间")
    await spike_session.execute(text(
        "INSERT INTO messages (scope,room_id,sender_id,role,content) "
        "VALUES ('room',:r,:u,'user','房间消息')"), {"r": rid, "u": actors["owner"]})
    await spike_session.commit()
    ok = await client.get(f"/api/rooms/{rid}/export", params={"format": "md"},
                          headers=actors["h_owner"])
    assert ok.status_code == 200 and "房间消息" in ok.text
    no = await client.get(f"/api/rooms/{rid}/export", headers=actors["h_other"])
    assert no.status_code in (403, 404)


async def _mk_share(client, conv, actors, days=7):
    return await client.post("/api/shares",
                             json={"scope": "dm", "conversation_id": conv, "days": days},
                             headers=actors["h_owner"])


async def test_share_create_and_anonymous_read(client, conv, actors):
    r = await _mk_share(client, conv, actors)
    assert r.status_code == 200, r.text
    token = r.json()["data"]["token"]
    anon = await client.get(f"/api/share/{token}")
    assert anon.status_code == 200, anon.text
    d = anon.json()["data"]
    assert d["title"] == "导出会话" and len(d["messages"]) == 2
    assert "email" not in json.dumps(d), "分享不得泄露邮箱等隐私字段"


async def test_share_tampered_signature(client, conv, actors):
    token = (await _mk_share(client, conv, actors)).json()["data"]["token"]
    sid, sig = token.split(".")
    bad = f"{sid}.{'0' * len(sig)}"
    r = await client.get(f"/api/share/{bad}")
    assert r.status_code == 403


async def test_share_expired(client, conv, actors, spike_session):
    d = (await _mk_share(client, conv, actors)).json()["data"]
    await spike_session.execute(text(
        "UPDATE shares SET expires_at = now() - interval '1 hour' WHERE id=:i"),
        {"i": d["share_id"]})
    await spike_session.commit()
    r = await client.get(f"/api/share/{d['token']}")
    assert r.status_code == 410


async def test_share_revoke(client, conv, actors):
    d = (await _mk_share(client, conv, actors)).json()["data"]
    rv = await client.delete(f"/api/shares/{d['share_id']}", headers=actors["h_owner"])
    assert rv.status_code == 200
    assert (await client.get(f"/api/share/{d['token']}")).status_code == 410
    mine = await client.get("/api/shares", headers=actors["h_owner"])
    assert mine.json()["data"]["items"][0]["revoked"] is True


async def test_share_permission_and_validation(client, conv, actors):
    steal = await client.post("/api/shares",
                              json={"scope": "dm", "conversation_id": conv, "days": 7},
                              headers=actors["h_other"])
    assert steal.status_code in (403, 404)
    assert (await _mk_share(client, conv, actors, days=0)).status_code == 422
    assert (await _mk_share(client, conv, actors, days=31)).status_code == 422