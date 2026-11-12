"""W2 核心：会话 CRUD + SSE 流式对话 + 配额结算 + 会话级串行。"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

SSE = ('data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
       'data: [DONE]\n\n')


@pytest.fixture
async def ctx(spike_session, admin_headers):
    from tests.factories import make_channel, make_model

    cid = await make_channel(spike_session, name="conv-ch", base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"chat-{uuid.uuid4().hex[:8]}")
    await spike_session.execute(
        text("INSERT INTO model_channels (model_id,channel_id,upstream_model) "
             "VALUES (:m,:c,'up')"), {"m": mid, "c": cid})
    await spike_session.commit()
    return {"h": admin_headers, "model_id": mid, "channel_id": cid}


@pytest.fixture
async def admin_headers(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, role="admin", daily_token_limit=100000)
    token, _ = create_access_token(uid, "admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _conv(client, ctx, **kw):
    r = await client.post("/api/conversations",
                          json={"title": "测试会话", "model_id": ctx["model_id"]} | kw,
                          headers=ctx["h"])
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


async def test_conversation_crud_and_ownership(client, ctx, spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    cid = await _conv(client, ctx)
    lst = await client.get("/api/conversations", headers=ctx["h"])
    assert any(c["id"] == cid for c in lst.json()["data"]["items"])
    patch = await client.patch(f"/api/conversations/{cid}",
                               json={"title": "改名"}, headers=ctx["h"])
    assert patch.status_code == 200
    other = await make_user(spike_session)
    tok, _ = create_access_token(other, "member")
    steal = await client.get(f"/api/conversations/{cid}",
                             headers={"Authorization": f"Bearer {tok}"})
    assert steal.status_code == 404, "越权统一 404"
    assert (await client.delete(f"/api/conversations/{cid}", headers=ctx["h"])).status_code == 200


async def test_sse_streams_persists_and_settles(client, ctx, spike_session, block_external_http):
    cid = await _conv(client, ctx)
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    events = []
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "你好"}, headers=ctx["h"]) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    deltas = [e for e in events if "content" in e]
    assert "".join(d["content"] for d in deltas) == "你好"
    assert any("message_id" in e for e in events), "必须有 done 事件带 message_id"
    msgs = (await spike_session.execute(
        text("SELECT role,content FROM messages WHERE conversation_id=:c ORDER BY id"),
        {"c": cid})).all()
    assert [m[0] for m in msgs] == ["user", "assistant"]
    st = (await spike_session.execute(
        text("SELECT status,total_tokens FROM usage_logs ORDER BY id DESC LIMIT 1"))).one()
    assert st[0] == "settled" and st[1] == 14
    used = (await spike_session.execute(
        text("SELECT total_tokens FROM daily_usage WHERE room_id IS NULL "
             "ORDER BY quota_date DESC LIMIT 1"))).scalar_one()
    assert used == 14, "结算后用量应等于实际 token，而非预扣值"


async def test_upstream_failure_refunds(client, ctx, spike_session, block_external_http):
    before = (await spike_session.execute(
        text("SELECT coalesce(sum(total_tokens),0) FROM daily_usage"))).scalar_one()
    cid = await _conv(client, ctx)
    block_external_http.post("https://api.test/v1/chat/completions").respond(500, json={})
    events = []
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "hi"}, headers=ctx["h"]) as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    assert any(e.get("code") for e in events), "必须发出 error 事件"
    st = (await spike_session.execute(
        text("SELECT status FROM usage_logs ORDER BY id DESC LIMIT 1"))).scalar_one()
    assert st == "refunded"
    after = (await spike_session.execute(
        text("SELECT coalesce(sum(total_tokens),0) FROM daily_usage"))).scalar_one()
    assert after == before, f"失败必须全额退回：{before} → {after}"


async def test_quota_exceeded_blocks_before_upstream(client, ctx, spike_session,
                                                     block_external_http):
    uid = (await spike_session.execute(
        text("SELECT id FROM users WHERE role='admin' ORDER BY id DESC LIMIT 1"))).scalar_one()
    await spike_session.execute(
        text("UPDATE users SET daily_token_limit=1 WHERE id=:i"), {"i": uid})
    await spike_session.commit()
    from app.core.security import decode_token
    token_uid = int(decode_token(ctx["h"]["Authorization"][7:])["sub"])
    lim = (await spike_session.execute(
        text("SELECT daily_token_limit FROM users WHERE id=:i"), {"i": token_uid})).scalar_one()
    assert uid == token_uid and lim == 1, f"uid={uid} token_uid={token_uid} limit={lim}"
    route = block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    cid = await _conv(client, ctx)
    events = []
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "hi"}, headers=ctx["h"]) as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    assert any(e.get("code") == "QUOTA_EXCEEDED" for e in events), f"实际事件: {events}"
    assert len(route.calls) == 0, "超限时不得调用上游"


async def test_first_call_of_day_also_respects_limit(spike_session):
    """回归：当天首次调用走纯 INSERT 分支，同样必须受限额约束。"""
    from datetime import date

    from app.llm.services.quota_service import freeze_tokens
    from tests.factories import make_user

    uid = await make_user(spike_session)
    d = date(2031, 1, 1)
    assert await freeze_tokens(spike_session, quota_date=d, owner_id=uid,
                               room_id=None, tokens=5000, limit=100) is False
    n = (await spike_session.execute(
        text("SELECT coalesce(sum(total_tokens),0) FROM daily_usage "
             "WHERE owner_id=:u AND quota_date=:d"), {"u": uid, "d": d})).scalar_one()
    assert n == 0, "首次调用超限不得写入任何用量"
    assert await freeze_tokens(spike_session, quota_date=d, owner_id=uid,
                               room_id=None, tokens=100, limit=100) is True


async def test_no_channel_refunds_and_leaves_no_pending(client, ctx, spike_session):
    """无可用渠道时必须退回预扣，不得留下 pending 悬挂。"""
    cid = await _conv(client, ctx)
    await spike_session.execute(text("UPDATE channels SET status='disabled' WHERE id=:i"),
                                {"i": ctx["channel_id"]})
    await spike_session.commit()
    events = []
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "hi"}, headers=ctx["h"]) as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    assert any(e.get("code") == "NO_CHANNEL_AVAILABLE" for e in events), events
    pend = (await spike_session.execute(
        text("SELECT count(*) FROM usage_logs WHERE conversation_id=:c AND status='pending'"),
        {"c": cid})).scalar_one()
    assert pend == 0, "无渠道分支不得留下 pending"
    ref = (await spike_session.execute(
        text("SELECT status FROM usage_logs WHERE conversation_id=:c ORDER BY id DESC LIMIT 1"),
        {"c": cid})).scalar_one()
    assert ref == "refunded"
