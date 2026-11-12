"""EXT-001 引用回复：校验、quote 快照、AI 上下文组装与去重（单聊 + 房间）。"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

SSE = ('data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
       'data: [DONE]\n\n')
MARKER = "QUOTE-MARKER-被引用的独特内容"


@pytest.fixture
async def admin_uid(spike_session):
    from tests.factories import make_user

    return await make_user(spike_session, role="admin", daily_token_limit=1000000,
                           nickname="引用测试员")


@pytest.fixture
async def admin_headers(admin_uid):
    from app.core.security import create_access_token

    token, _ = create_access_token(admin_uid, "admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


@pytest.fixture
async def ctx(spike_session, admin_headers):
    from tests.factories import make_channel, make_model

    cid = await make_channel(spike_session, name="quote-ch", base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"q-{uuid.uuid4().hex[:8]}")
    await spike_session.execute(
        text("INSERT INTO model_channels (model_id,channel_id,upstream_model) "
             "VALUES (:m,:c,'up')"), {"m": mid, "c": cid})
    await spike_session.commit()
    return {"h": admin_headers, "model_id": mid}


async def _conv(client, ctx):
    r = await client.post("/api/conversations",
                          json={"title": "引用会话", "model_id": ctx["model_id"]},
                          headers=ctx["h"])
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


async def _send(client, cid, content, headers, reply=None):
    body = {"content": content}
    if reply is not None:
        body["reply_to_msg_id"] = reply
    return await client.post(f"/api/conversations/{cid}/messages", json=body, headers=headers)


def _capture(block_external_http):
    captured: dict = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    block_external_http.post("https://api.test/v1/chat/completions").mock(side_effect=handler)
    return captured


async def test_quote_send_and_snapshot(client, ctx):
    cid = await _conv(client, ctx)
    a = (await _send(client, cid, MARKER + "·" + "长" * 120, ctx["h"])).json()["data"]["message_id"]
    r = await _send(client, cid, "针对上面那条追问", ctx["h"], reply=a)
    assert r.status_code == 200, r.text
    items = (await client.get(f"/api/conversations/{cid}/messages",
                              headers=ctx["h"])).json()["data"]["items"]
    b = next(m for m in items if m["content"] == "针对上面那条追问")
    assert b["reply_to_msg_id"] == a
    q = b["quote"]
    assert q["id"] == a and q["nickname"] == "引用测试员"
    assert len(q["excerpt"]) <= 80 and MARKER in q["excerpt"]
    assert items[0]["quote"] is None


async def test_quote_cross_conversation_rejected(client, ctx):
    c1, c2 = await _conv(client, ctx), await _conv(client, ctx)
    other = (await _send(client, c2, "别的会话的消息", ctx["h"])).json()["data"]["message_id"]
    r = await _send(client, c1, "跨会话引用", ctx["h"], reply=other)
    assert r.status_code == 422
    assert r.json()["code"] == "QUOTE_INVALID"


async def test_quote_missing_rejected(client, ctx):
    cid = await _conv(client, ctx)
    r = await _send(client, cid, "引用不存在的消息", ctx["h"], reply=99999999)
    assert r.status_code == 422
    assert r.json()["code"] == "QUOTE_INVALID"


async def test_quote_deleted_placeholder(client, ctx, spike_session):
    cid = await _conv(client, ctx)
    a = (await _send(client, cid, "即将被删除", ctx["h"])).json()["data"]["message_id"]
    await _send(client, cid, "引用它", ctx["h"], reply=a)
    await spike_session.execute(text("DELETE FROM messages WHERE id=:i"), {"i": a})
    await spike_session.commit()
    items = (await client.get(f"/api/conversations/{cid}/messages",
                              headers=ctx["h"])).json()["data"]["items"]
    q = next(m for m in items if m["content"] == "引用它")["quote"]
    assert q["deleted"] is True and q["id"] == a


async def test_ai_context_includes_quote_outside_window(client, ctx, spike_session,
                                                        block_external_http):
    cid = await _conv(client, ctx)
    first = (await _send(client, cid, MARKER, ctx["h"])).json()["data"]["message_id"]
    for i in range(25):
        await _send(client, cid, f"填充消息 {i}", ctx["h"])
    captured = _capture(block_external_http)
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "追问那条", "reply_to_msg_id": first},
                             headers=ctx["h"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    contents = [m["content"] for m in captured["body"]["messages"]]
    assert contents.count(MARKER) == 1, "窗口外的被引用消息必须注入且仅一次"
    assert contents.index(MARKER) == len(contents) - 2, "必须插在触发消息之前"


async def test_ai_context_quote_in_window_not_duplicated(client, ctx, block_external_http):
    cid = await _conv(client, ctx)
    a = (await _send(client, cid, MARKER, ctx["h"])).json()["data"]["message_id"]
    captured = _capture(block_external_http)
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "追问", "reply_to_msg_id": a},
                             headers=ctx["h"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    contents = [m["content"] for m in captured["body"]["messages"]]
    assert contents.count(MARKER) == 1, "窗口内已有则不得重复注入"


async def test_room_quote_validation_and_context(client, ctx, spike_session, admin_uid,
                                                 block_external_http):
    from tests.factories import make_room

    r1 = await make_room(spike_session, owner_id=admin_uid, model_id=ctx["model_id"])
    r2 = await make_room(spike_session, owner_id=admin_uid, model_id=ctx["model_id"])
    h = ctx["h"]
    a = (await client.post(f"/api/rooms/{r1}/messages", json={"content": MARKER},
                           headers=h)).json()["data"]["message_id"]
    cross = await client.post(f"/api/rooms/{r2}/messages",
                              json={"content": "跨房间", "reply_to_msg_id": a}, headers=h)
    assert cross.status_code == 422 and cross.json()["code"] == "QUOTE_INVALID"
    ok = await client.post(f"/api/rooms/{r1}/messages",
                           json={"content": "房间内引用", "reply_to_msg_id": a}, headers=h)
    assert ok.status_code == 200
    items = (await client.get(f"/api/rooms/{r1}/messages", headers=h)).json()["data"]["items"]
    q = next(m for m in items if m["content"] == "房间内引用")["quote"]
    assert q["id"] == a and q["excerpt"] == MARKER
    captured = _capture(block_external_http)
    evs = []
    async with client.stream("POST", f"/api/rooms/{r1}/ai/ask",
                             json={"content": "@AI 追问", "reply_to_msg_id": a},
                             headers=h) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                evs.append(line)
    assert "body" in captured, f"上游未被调用，SSE 事件: {evs}"
    contents = [m["content"] for m in captured["body"]["messages"]]
    assert sum(MARKER in c for c in contents) == 1