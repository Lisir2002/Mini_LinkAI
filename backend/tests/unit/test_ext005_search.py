"""EXT-005 全文搜索：权限隔离、中文命中、游标分页、校验与性能。"""
from __future__ import annotations

import time

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

    alice = await make_user(spike_session, nickname="Alice")
    bob = await make_user(spike_session, nickname="Bob")

    def hdr(uid):
        tok, _ = create_access_token(uid, "member")
        return {"Authorization": f"Bearer {tok}"}

    return {"alice": alice, "bob": bob, "h_a": hdr(alice), "h_b": hdr(bob)}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=60) as c:
        yield c


@pytest.fixture
async def seeded(spike_session, users):
    from tests.factories import add_member, make_conversation, make_room

    ca = await make_conversation(spike_session, user_id=users["alice"], title="Alice 的会话")
    cb = await make_conversation(spike_session, user_id=users["bob"], title="Bob 的会话")
    rid = await make_room(spike_session, owner_id=users["alice"], name="公开讨论室")
    await add_member(spike_session, room_id=rid, user_id=users["alice"])
    await spike_session.execute(text(
        "INSERT INTO messages (scope,conversation_id,role,content) VALUES "
        "('dm',:ca,'user','今天讨论量子计算的最新进展'),"
        "('dm',:ca,'assistant','量子计算利用叠加态进行并行运算'),"
        "('dm',:cb,'user','Bob 私密：量子密钥分发不该被搜到')"),
        {"ca": ca, "cb": cb})
    await spike_session.execute(text(
        "INSERT INTO messages (scope,room_id,sender_id,role,content) VALUES "
        "('room',:r,:u,'user','房间里也聊到了量子纠缠')"), {"r": rid, "u": users["alice"]})
    await spike_session.commit()
    return {"ca": ca, "cb": cb, "rid": rid}


async def test_search_permission_isolation(client, seeded, users):
    r = await client.get("/api/search", params={"q": "量子"}, headers=users["h_a"])
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 3, "Alice 应搜到自己的 2 条单聊 + 1 条房间"
    assert all("Bob 私密" not in i["snippet"] for i in items)
    rb = await client.get("/api/search", params={"q": "量子"}, headers=users["h_b"])
    assert len(rb.json()["data"]["items"]) == 1, "Bob 只能搜到自己的会话"
    assert rb.json()["data"]["items"][0]["title"] == "Bob 的会话"


async def test_search_scope_and_highlight(client, seeded, users):
    r = await client.get("/api/search", params={"q": "量子", "scope": "room"},
                         headers=users["h_a"])
    items = r.json()["data"]["items"]
    assert len(items) == 1 and items[0]["scope"] == "room"
    assert items[0]["title"] == "公开讨论室"
    assert items[0]["match"] == "量子" and "量子" in items[0]["snippet"]
    r2 = await client.get("/api/search", params={"q": "量子", "scope": "dm"},
                          headers=users["h_a"])
    assert all(i["scope"] == "dm" for i in r2.json()["data"]["items"])


async def test_search_cursor_pagination(client, spike_session, seeded, users):
    await spike_session.execute(text(
        "INSERT INTO messages (scope,conversation_id,role,content) "
        "SELECT 'dm',:c,'user','分页样本 '||g FROM generate_series(1,30) g"),
        {"c": seeded["ca"]})
    await spike_session.commit()
    r1 = await client.get("/api/search", params={"q": "分页样本", "limit": 10},
                          headers=users["h_a"])
    d1 = r1.json()["data"]
    assert len(d1["items"]) == 10 and d1["next_cursor"] is not None
    r2 = await client.get("/api/search",
                          params={"q": "分页样本", "limit": 10, "cursor": d1["next_cursor"]},
                          headers=users["h_a"])
    d2 = r2.json()["data"]
    ids1 = {i["message_id"] for i in d1["items"]}
    ids2 = {i["message_id"] for i in d2["items"]}
    assert not ids1 & ids2, "分页不得重叠"
    assert max(ids2) < min(ids1), "按 id 倒序翻页"


async def test_search_validation(client, users):
    assert (await client.get("/api/search", params={"q": ""},
                             headers=users["h_a"])).status_code == 422
    assert (await client.get("/api/search", params={"q": "长" * 101},
                             headers=users["h_a"])).status_code == 422
    assert (await client.get("/api/search", params={"q": "任意"})).status_code == 401


async def test_search_performance_10k(client, spike_session, seeded, users):
    await spike_session.execute(text(
        "INSERT INTO messages (scope,conversation_id,role,content) "
        "SELECT 'dm',:c,'user','性能测试消息 '||g||' 中文搜索样本' "
        "FROM generate_series(1,10000) g"), {"c": seeded["ca"]})
    await spike_session.commit()
    await client.get("/api/search", params={"q": "预热"}, headers=users["h_a"])
    t0 = time.perf_counter()
    r = await client.get("/api/search", params={"q": "中文搜索样本"}, headers=users["h_a"])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    assert len(r.json()["data"]["items"]) == 20
    assert elapsed_ms < 100, f"1 万条消息搜索耗时 {elapsed_ms:.1f}ms，应 <100ms"