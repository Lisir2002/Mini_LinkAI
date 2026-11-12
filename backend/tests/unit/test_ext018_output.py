"""EXT-018 结构化输出：约束注入、JSON 校验、重试一次、降级标注、房间设置。"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text


def sse(content: str) -> str:
    payload = json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
    return (f"data: {payload}\n\n"
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
            'data: [DONE]\n\n')


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def ctx(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_channel, make_model, make_room, make_user

    uid = await make_user(spike_session, role="admin", daily_token_limit=1000000)
    tok, _ = create_access_token(uid, "admin")
    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"out-{uuid.uuid4().hex[:8]}")
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    rid = await make_room(spike_session, owner_id=uid, model_id=mid)
    await spike_session.commit()
    return {"h": {"Authorization": f"Bearer {tok}"}, "rid": rid, "uid": uid}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


def _mock_seq(block_external_http, contents: list[str]):
    calls = {"n": 0}
    bodies: list[dict] = []

    def handler(request):
        bodies.append(json.loads(request.content))
        i = min(calls["n"], len(contents) - 1)
        calls["n"] += 1
        return httpx.Response(200, text=sse(contents[i]),
                              headers={"content-type": "text/event-stream"})

    block_external_http.post("https://api.test/v1/chat/completions").mock(side_effect=handler)
    return calls, bodies


async def _ask(client, ctx):
    async with client.stream("POST", f"/api/rooms/{ctx['rid']}/ai/ask",
                             json={"content": "@AI 回答"}, headers=ctx["h"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass


async def _set_mode(spike_session, rid, mode, schema=None):
    await spike_session.execute(text(
        "UPDATE rooms SET output_mode=:m, output_schema=:s WHERE id=:r"),
        {"m": mode, "s": schema, "r": rid})
    await spike_session.commit()


async def test_json_constraint_injected(client, spike_session, ctx, block_external_http):
    schema = json.dumps({"type": "object", "required": ["answer"]})
    await _set_mode(spike_session, ctx["rid"], "json", schema)
    calls, bodies = _mock_seq(block_external_http, ['{"answer":"ok"}'])
    await _ask(client, ctx)
    sysmsg = bodies[0]["messages"][0]["content"]
    assert "JSON" in sysmsg and schema in sysmsg
    row = (await spike_session.execute(text(
        "SELECT output_mode,output_downgraded FROM messages "
        "WHERE room_id=:r AND role='assistant' ORDER BY id DESC LIMIT 1"),
        {"r": ctx["rid"]})).mappings().one()
    assert row["output_mode"] == "json" and row["output_downgraded"] is False
    assert calls["n"] == 1


async def test_invalid_json_retries_once_then_succeeds(client, spike_session, ctx,
                                                       block_external_http):
    await _set_mode(spike_session, ctx["rid"], "json")
    calls, _ = _mock_seq(block_external_http, ["这不是 JSON", '{"answer":"第二次对了"}'])
    await _ask(client, ctx)
    assert calls["n"] == 2, "校验失败必须重试一次"
    row = (await spike_session.execute(text(
        "SELECT content,output_mode,output_downgraded FROM messages "
        "WHERE room_id=:r AND role='assistant' ORDER BY id DESC LIMIT 1"),
        {"r": ctx["rid"]})).mappings().one()
    assert "第二次对了" in row["content"]
    assert row["output_mode"] == "json" and row["output_downgraded"] is False


async def test_twice_invalid_downgrades(client, spike_session, ctx, block_external_http):
    await _set_mode(spike_session, ctx["rid"], "json")
    calls, _ = _mock_seq(block_external_http, ["坏输出一", "坏输出二"])
    await _ask(client, ctx)
    assert calls["n"] == 2, "最多重试一次，不得无限重试"
    row = (await spike_session.execute(text(
        "SELECT output_mode,output_downgraded FROM messages "
        "WHERE room_id=:r AND role='assistant' ORDER BY id DESC LIMIT 1"),
        {"r": ctx["rid"]})).mappings().one()
    assert row["output_mode"] == "free" and row["output_downgraded"] is True


async def test_schema_violation_counts_as_invalid(client, spike_session, ctx,
                                                  block_external_http):
    schema = json.dumps({"type": "object", "required": ["answer"],
                         "properties": {"answer": {"type": "string"}}})
    await _set_mode(spike_session, ctx["rid"], "json", schema)
    calls, _ = _mock_seq(block_external_http, ['{"wrong":1}', '{"answer":"合格"}'])
    await _ask(client, ctx)
    assert calls["n"] == 2, "合法 JSON 但不符合 Schema 也应触发重试"


async def test_table_and_code_constraints(client, spike_session, ctx, block_external_http):
    from app.core.redis_client import get_redis
    for mode, kw in (("table", "表格"), ("code", "代码")):
        await get_redis().delete(f"room:{ctx['rid']}:ai_cd")  # 冷却与本测试意图正交
        await _set_mode(spike_session, ctx["rid"], mode)
        calls, bodies = _mock_seq(block_external_http, ["输出内容"])
        await _ask(client, ctx)
        assert kw in bodies[0]["messages"][0]["content"], f"{mode} 约束未注入"
        assert calls["n"] == 1, "非 JSON 模式不做校验重试"


async def test_patch_room_output_settings(client, spike_session, ctx):
    r = await client.patch(f"/api/rooms/{ctx['rid']}",
                           json={"output_mode": "json",
                                 "output_schema": '{"type":"object"}'},
                           headers=ctx["h"])
    assert r.status_code == 200, r.text
    row = (await spike_session.execute(text(
        "SELECT output_mode,output_schema FROM rooms WHERE id=:r"),
        {"r": ctx["rid"]})).mappings().one()
    assert row["output_mode"] == "json"
    bad = await client.patch(f"/api/rooms/{ctx['rid']}",
                             json={"output_mode": "yaml"}, headers=ctx["h"])
    assert bad.status_code == 422
    badschema = await client.patch(f"/api/rooms/{ctx['rid']}",
                                   json={"output_schema": "{不是JSON"}, headers=ctx["h"])
    assert badschema.status_code == 422


async def test_patch_room_permission(client, spike_session, ctx):
    from app.core.security import create_access_token
    from tests.factories import make_user

    other = await make_user(spike_session)
    tok, _ = create_access_token(other, "member")
    r = await client.patch(f"/api/rooms/{ctx['rid']}", json={"output_mode": "json"},
                           headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403