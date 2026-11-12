"""关系设计审查修复：私聊附件权限、房间预算、房主总额、触发/冷却、好友重复行、删友通知。"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

SSE = ('data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
       'data: [DONE]\n\n')
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
async def _clean(spike_session, tmp_path, monkeypatch):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    from app.core.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(settings, "FEATURE_FILE_UPLOAD", True)
    yield


@pytest.fixture
async def actors(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    alice = await make_user(spike_session, nickname="Alice", daily_token_limit=1000000)
    bob = await make_user(spike_session, nickname="Bob", daily_token_limit=1000000)

    def h(uid):
        tok, _ = create_access_token(uid, "member")
        return {"Authorization": f"Bearer {tok}"}

    return {"alice": alice, "bob": bob, "h_a": h(alice), "h_b": h(bob)}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _befriend(client, actors):
    r = await client.post("/api/friends/requests",
                          json={"user_id": actors["bob"]}, headers=actors["h_a"])
    rid = r.json()["data"]["request_id"]
    await client.post(f"/api/friends/requests/{rid}/accept", headers=actors["h_b"])


async def _upload(client, headers):
    r = await client.post("/api/uploads", headers=headers,
                          files={"file": ("a.png", PNG, "image/png")})
    return r.json()["data"]["id"]


async def test_dm_attachment_visible_to_recipient(client, actors):
    await _befriend(client, actors)
    att = await _upload(client, actors["h_a"])
    r = await client.post(f"/api/dm/{actors['bob']}/messages",
                          json={"content": "看图", "attachment_id": att}, headers=actors["h_a"])
    assert r.status_code == 200
    ok = await client.get(f"/api/uploads/{att}/content", headers=actors["h_b"])
    assert ok.status_code == 200, "私聊收件人必须能看图片（当前 can_access 漏了 direct_messages）"
    await client.delete(f"/api/friends/{actors['bob']}", headers=actors["h_a"])
    no = await client.get(f"/api/uploads/{att}/content", headers=actors["h_b"])
    assert no.status_code == 403, "解除好友后应收回附件访问"


@pytest.fixture
async def room_ctx(spike_session, actors):
    from tests.factories import make_channel, make_model, make_room

    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"rv-{uuid.uuid4().hex[:8]}",
                           max_output_tokens=5)
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    rid = await make_room(spike_session, owner_id=actors["alice"], model_id=mid,
                          system_prompt="x")
    await spike_session.commit()
    return {"rid": rid, "mid": mid, "ch": ch}


async def _ask(client, rid, headers, content="@AI 你好"):
    evs = []
    async with client.stream("POST", f"/api/rooms/{rid}/ai/ask",
                             json={"content": content}, headers=headers) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:]))
    return evs


async def test_room_daily_budget_enforced(client, spike_session, actors, room_ctx,
                                          block_external_http):
    await spike_session.execute(text(
        "UPDATE rooms SET daily_token_budget=5 WHERE id=:r"), {"r": room_ctx["rid"]})
    await spike_session.commit()
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    evs = await _ask(client, room_ctx["rid"], actors["h_a"])
    codes = [e.get("code") for e in evs if "code" in e]
    assert "QUOTA_EXCEEDED" in codes, f"冻结额超房间日预算必须拒绝: {evs}"


async def test_owner_global_cap_across_rooms(client, spike_session, actors, room_ctx,
                                             block_external_http):
    from tests.factories import make_room

    await spike_session.execute(text("UPDATE users SET daily_token_limit=20 WHERE id=:i"),
                                {"i": actors["alice"]})
    rid2 = await make_room(spike_session, owner_id=actors["alice"], model_id=room_ctx["mid"],
                           system_prompt="x")
    await spike_session.commit()
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    evs1 = await _ask(client, room_ctx["rid"], actors["h_a"])
    assert not any(e.get("code") == "QUOTA_EXCEEDED" for e in evs1), f"首呼应成功: {evs1}"
    evs2 = await _ask(client, rid2, actors["h_a"])
    codes = [e.get("code") for e in evs2 if "code" in e]
    assert "QUOTA_EXCEEDED" in codes, f"房主跨房间总额超限必须拒绝: {evs2}"


async def test_ai_trigger_off_and_mention(client, spike_session, actors, room_ctx,
                                          block_external_http):
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    await spike_session.execute(text("UPDATE rooms SET ai_trigger='off' WHERE id=:r"),
                                {"r": room_ctx["rid"]})
    await spike_session.commit()
    evs = await _ask(client, room_ctx["rid"], actors["h_a"])
    assert any(e.get("code") == "ROOM_AI_DISABLED" for e in evs), "off 模式必须拒绝 AI"
    await spike_session.execute(text("UPDATE rooms SET ai_trigger='mention' WHERE id=:r"),
                                {"r": room_ctx["rid"]})
    await spike_session.commit()
    evs2 = await _ask(client, room_ctx["rid"], actors["h_a"], content="没有提到机器人")
    assert any(e.get("code") == "AI_MENTION_REQUIRED" for e in evs2), "mention 模式必须含 @AI"


async def test_room_ai_cooldown(client, spike_session, actors, room_ctx, block_external_http):
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    evs1 = await _ask(client, room_ctx["rid"], actors["h_a"])
    assert any("message_id" in e for e in evs1), f"首呼应成功: {evs1}"
    evs2 = await _ask(client, room_ctx["rid"], actors["h_a"])
    assert any(e.get("code") == "COOLDOWN" for e in evs2), f"冷却期内第二呼必须拒绝: {evs2}"


async def test_mutual_requests_no_duplicate_friends(client, spike_session, actors):
    a, b = actors["alice"], actors["bob"]
    await spike_session.execute(text(
        "INSERT INTO friendships (requester_id,addressee_id,status) VALUES "
        "(:a,:b,'pending'),(:b,:a,'pending')"), {"a": a, "b": b})
    await spike_session.commit()
    reqs = (await spike_session.execute(text(
        "SELECT id FROM friendships WHERE requester_id=:b AND addressee_id=:a"),
        {"a": a, "b": b})).scalar_one()
    r = await client.post(f"/api/friends/requests/{reqs}/accept", headers=actors["h_a"])
    assert r.status_code == 200
    fl = await client.get("/api/friends", headers=actors["h_a"])
    assert len(fl.json()["data"]["items"]) == 1, "好友列表不得重复"
    left = (await spike_session.execute(text(
        "SELECT count(*) FROM friendships WHERE status='pending' AND "
        "((requester_id=:a AND addressee_id=:b) OR (requester_id=:b AND addressee_id=:a))"),
        {"a": a, "b": b})).scalar_one()
    assert left == 0, "接受后不得残留反向 pending"


async def test_unfriend_notifies_other(client, actors, monkeypatch):
    await _befriend(client, actors)
    from app.users.services import dm_bus
    calls = []
    orig = dm_bus.publish

    async def spy(uid, payload):
        calls.append((uid, payload))
        await orig(uid, payload)

    monkeypatch.setattr(dm_bus, "publish", spy)
    await client.delete(f"/api/friends/{actors['bob']}", headers=actors["h_a"])
    assert any(uid == actors["bob"] and p.get("type") == "friend_removed"
               for uid, p in calls), "删除好友必须通知对方刷新"