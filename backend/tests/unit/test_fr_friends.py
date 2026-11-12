"""FR-001/002/003 好友与私聊：申请流、双向关系、门禁、已读未读。"""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def actors(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    alice = await make_user(spike_session, nickname="Alice", email="alice@ex.com")
    bob = await make_user(spike_session, nickname="Bob", email="bob@ex.com")
    carol = await make_user(spike_session, nickname="Carol", email="carol@ex.com")

    def h(uid):
        tok, _ = create_access_token(uid, "member")
        return {"Authorization": f"Bearer {tok}"}

    return {"alice": alice, "bob": bob, "carol": carol,
            "h_a": h(alice), "h_b": h(bob), "h_c": h(carol)}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _request(client, h, uid):
    return await client.post("/api/friends/requests", json={"user_id": uid}, headers=h)


async def _accept(client, h, rid):
    return await client.post(f"/api/friends/requests/{rid}/accept", headers=h)


async def _befriend(client, actors, a="alice", b="bob"):
    r = await _request(client, actors[f"h_{a[0]}"], actors[b])
    rid = r.json()["data"]["request_id"]
    await _accept(client, actors[f"h_{b[0]}"], rid)


async def test_user_search_privacy(client, actors):
    r = await client.get("/api/users/search", params={"q": "Bob"}, headers=actors["h_a"])
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 1 and items[0]["id"] == actors["bob"]
    assert "*" in items[0]["email"] and "bob@ex.com" not in r.text
    me = await client.get("/api/users/search", params={"q": "Alice"}, headers=actors["h_a"])
    assert all(i["id"] != actors["alice"] for i in me.json()["data"]["items"])


async def test_request_accept_flow(client, actors):
    r = await _request(client, actors["h_a"], actors["bob"])
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["request_id"]
    inc = await client.get("/api/friends/requests", headers=actors["h_b"])
    incoming = inc.json()["data"]["incoming"]
    assert len(incoming) == 1 and incoming[0]["nickname"] == "Alice"
    wrong = await _accept(client, actors["h_c"], rid)
    assert wrong.status_code == 403
    ok = await _accept(client, actors["h_b"], rid)
    assert ok.status_code == 200
    fa = await client.get("/api/friends", headers=actors["h_a"])
    fb = await client.get("/api/friends", headers=actors["h_b"])
    assert [x["user_id"] for x in fa.json()["data"]["items"]] == [actors["bob"]]
    assert [x["user_id"] for x in fb.json()["data"]["items"]] == [actors["alice"]]


async def test_request_reject_and_guards(client, actors):
    r = await _request(client, actors["h_a"], actors["bob"])
    rid = r.json()["data"]["request_id"]
    assert (await client.post(f"/api/friends/requests/{rid}/reject",
                              headers=actors["h_b"])).status_code == 200
    assert (await client.get("/api/friends", headers=actors["h_a"])).json()["data"]["items"] == []
    self_r = await _request(client, actors["h_a"], actors["alice"])
    assert self_r.status_code == 422
    await _befriend(client, actors)
    dup = await _request(client, actors["h_a"], actors["bob"])
    assert dup.status_code == 409


async def test_reverse_pending_auto_accepts(client, actors):
    await _request(client, actors["h_a"], actors["bob"])
    r = await _request(client, actors["h_b"], actors["alice"])
    assert r.status_code == 200
    assert r.json()["data"].get("auto_accepted") is True
    fa = await client.get("/api/friends", headers=actors["h_a"])
    assert len(fa.json()["data"]["items"]) == 1


async def test_dm_friend_gate_and_history(client, actors):
    no = await client.post(f"/api/dm/{actors['bob']}/messages",
                           json={"content": "hi"}, headers=actors["h_a"])
    assert no.status_code == 403 and no.json()["code"] == "NOT_FRIEND"
    await _befriend(client, actors)
    ok = await client.post(f"/api/dm/{actors['bob']}/messages",
                           json={"content": "你好 Bob"}, headers=actors["h_a"])
    assert ok.status_code == 200, ok.text
    mid = ok.json()["data"]["message_id"]
    await client.post(f"/api/dm/{actors['alice']}/messages",
                      json={"content": "你好 Alice"}, headers=actors["h_b"])
    hist = await client.get(f"/api/dm/{actors['bob']}/messages", headers=actors["h_a"])
    items = hist.json()["data"]["items"]
    assert [m["content"] for m in items] == ["你好 Bob", "你好 Alice"]
    inc = await client.get(f"/api/dm/{actors['bob']}/messages",
                           params={"after": mid}, headers=actors["h_a"])
    assert [m["content"] for m in inc.json()["data"]["items"]] == ["你好 Alice"]
    stranger = await client.get(f"/api/dm/{actors['bob']}/messages", headers=actors["h_c"])
    assert stranger.status_code == 403


async def test_unread_and_read_mark(client, actors):
    await _befriend(client, actors)
    await client.post(f"/api/dm/{actors['bob']}/messages",
                      json={"content": "1"}, headers=actors["h_a"])
    await client.post(f"/api/dm/{actors['bob']}/messages",
                      json={"content": "2"}, headers=actors["h_a"])
    fl = await client.get("/api/friends", headers=actors["h_b"])
    row = fl.json()["data"]["items"][0]
    assert row["unread_count"] == 2 and row["last_msg"] == "2"
    rd = await client.post(f"/api/dm/{actors['alice']}/read", headers=actors["h_b"])
    assert rd.status_code == 200 and rd.json()["data"]["marked"] == 2
    fl2 = await client.get("/api/friends", headers=actors["h_b"])
    assert fl2.json()["data"]["items"][0]["unread_count"] == 0


async def test_unfriend_blocks_dm(client, actors):
    await _befriend(client, actors)
    r = await client.delete(f"/api/friends/{actors['bob']}", headers=actors["h_a"])
    assert r.status_code == 200
    assert (await client.get("/api/friends", headers=actors["h_b"])).json()["data"]["items"] == []
    no = await client.post(f"/api/dm/{actors['bob']}/messages",
                           json={"content": "x"}, headers=actors["h_a"])
    assert no.status_code == 403
    assert (await client.delete(f"/api/friends/{actors['carol']}",
                                headers=actors["h_a"])).status_code == 404


async def test_dm_attachment_ownership(client, spike_session, actors):
    await _befriend(client, actors)
    import tempfile

    from app.config import settings
    from app.services.upload_service import save_upload
    with tempfile.TemporaryDirectory() as td:
        settings.UPLOAD_DIR = td
        settings.FEATURE_FILE_UPLOAD = True
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        up = await save_upload(spike_session, owner_id=actors["alice"], filename="a.png", data=png)
        ok = await client.post(f"/api/dm/{actors['bob']}/messages",
                               json={"content": "看图", "attachment_id": up["id"]},
                               headers=actors["h_a"])
        assert ok.status_code == 200
        steal = await client.post(f"/api/dm/{actors['alice']}/messages",
                                  json={"content": "x", "attachment_id": up["id"]},
                                  headers=actors["h_b"])
        assert steal.status_code == 422