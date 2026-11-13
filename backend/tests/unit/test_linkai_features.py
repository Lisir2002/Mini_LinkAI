"""LinkAI 渠道增强：URL 补全 / Responses API / 缓存键 / 缓存断点 / Interactions。"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.llm.adapter.anthropic import AnthropicAdapter
from app.llm.adapter.base import UnifiedRequest
from app.llm.adapter.gemini import GeminiAdapter
from app.llm.adapter.openai_compat import OpenAICompatAdapter
from app.llm.services.channel_service import normalize_base_url


def test_normalize_openai_appends_v1_and_strips_endpoints():
    assert normalize_base_url("openai_compatible", "https://api.deepseek.com") \
        == "https://api.deepseek.com/v1"
    assert normalize_base_url("openai_compatible", "https://api.deepseek.com/v1/chat/completions") \
        == "https://api.deepseek.com/v1"
    assert normalize_base_url("openai_compatible", "https://x/compatible-mode/v1") \
        == "https://x/compatible-mode/v1"


def test_normalize_anthropic_strips_messages_suffix():
    assert normalize_base_url("anthropic", "https://maas.xf-yun.com/anthropic/v1/messages") \
        == "https://maas.xf-yun.com/anthropic"
    assert normalize_base_url("anthropic", "https://api.anthropic.com") \
        == "https://api.anthropic.com"


def test_normalize_gemini_keeps_root():
    assert normalize_base_url("gemini", "https://generativelanguage.googleapis.com/v1beta/models") \
        == "https://generativelanguage.googleapis.com"
    assert normalize_base_url(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/interactions") \
        == "https://generativelanguage.googleapis.com"


def test_normalize_off_keeps_user_input():
    assert normalize_base_url("openai_compatible", "https://gw.internal/custom", False) \
        == "https://gw.internal/custom"


@respx.mock
@pytest.mark.asyncio
async def test_openai_prompt_cache_key():
    route = respx.post("https://api.test/v1/chat/completions").mock(return_value=httpx.Response(
        200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"}))
    a = OpenAICompatAdapter(base_url="https://api.test/v1", api_key="k",
                            options={"prompt_cache_key": True})
    _ = [e async for e in a.stream_chat(UnifiedRequest(
        model="m", messages=[{"role": "user", "content": "hi"}], cache_key="conv:7"))]
    body = json.loads(route.calls[0].request.content)
    assert body["prompt_cache_key"] == "conv:7"


@respx.mock
@pytest.mark.asyncio
async def test_openai_prompt_cache_key_off_by_default():
    route = respx.post("https://api.test/v1/chat/completions").mock(return_value=httpx.Response(
        200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"}))
    a = OpenAICompatAdapter(base_url="https://api.test/v1", api_key="k")
    _ = [e async for e in a.stream_chat(UnifiedRequest(
        model="m", messages=[{"role": "user", "content": "hi"}], cache_key="conv:7"))]
    body = json.loads(route.calls[0].request.content)
    assert "prompt_cache_key" not in body


@respx.mock
@pytest.mark.asyncio
async def test_openai_responses_api_stream():
    sse = ("data: " + json.dumps({"type": "response.output_text.delta", "delta": "你好"})
           + "\n\n"
           + "data: " + json.dumps({"type": "response.completed",
                                    "response": {"usage": {"input_tokens": 7,
                                                           "output_tokens": 3,
                                                           "total_tokens": 10}}}) + "\n\n")
    route = respx.post("https://api.test/v1/responses").mock(return_value=httpx.Response(
        200, text=sse, headers={"content-type": "text/event-stream"}))
    a = OpenAICompatAdapter(base_url="https://api.test/v1", api_key="k",
                            options={"responses_api": True})
    events = [e async for e in a.stream_chat(UnifiedRequest(
        model="m", messages=[{"role": "system", "content": "sys"},
                             {"role": "user", "content": "hi"}], max_tokens=99))]
    body = json.loads(route.calls[0].request.content)
    assert body["instructions"] == "sys"
    assert body["input"][0]["content"][0]["type"] == "input_text"
    assert body["max_output_tokens"] == 99
    usage = [e for e in events if e.type == "usage"][0].data
    assert usage["prompt_tokens"] == 7 and usage["estimated"] is False
    deltas = [e.data["content"] for e in events if e.type == "delta"]
    assert deltas == ["你好"]


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_cache_breakpoints_and_usage():
    start = {"type": "message_start", "message": {"usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 800,
        "cache_read_input_tokens": 0}}}
    delta = {"type": "content_block_delta", "delta": {"text": "hi"}}
    mdelta = {"type": "message_delta", "usage": {"output_tokens": 5}}
    sse = (f"event: message_start\ndata: {json.dumps(start)}\n\n"
           f"event: content_block_delta\ndata: {json.dumps(delta)}\n\n"
           f"event: message_delta\ndata: {json.dumps(mdelta)}\n\n")
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(
        200, text=sse, headers={"content-type": "text/event-stream"}))
    a = AnthropicAdapter(base_url="https://api.anthropic.com", api_key="k",
                         options={"prompt_cache": True})
    events = [e async for e in a.stream_chat(UnifiedRequest(
        model="claude-x", messages=[{"role": "system", "content": "rule"},
                                    {"role": "user", "content": "问"}]))]
    body = json.loads(route.calls[0].request.content)
    assert body["system"][0]["cache_control"]["type"] == "ephemeral"
    assert body["messages"][-1]["content"][0]["cache_control"]["type"] == "ephemeral"
    usage = [e for e in events if e.type == "usage"][0].data
    assert usage["prompt_tokens"] == 810  # 10 普通 + 800 缓存写入，配额口径完整


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_no_cache_control_when_off():
    sse = ("event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"usage\":"
           "{\"input_tokens\":1}}}\n\n"
           "event: message_delta\ndata: {\"type\":\"message_delta\",\"usage\":"
           "{\"output_tokens\":1}}\n\n")
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(
        200, text=sse, headers={"content-type": "text/event-stream"}))
    a = AnthropicAdapter(base_url="https://api.anthropic.com", api_key="k")
    _ = [e async for e in a.stream_chat(UnifiedRequest(
        model="claude-x", messages=[{"role": "system", "content": "rule"},
                                    {"role": "user", "content": "问"}]))]
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "rule"
    assert body["messages"][-1]["content"] == "问"


@respx.mock
@pytest.mark.asyncio
async def test_gemini_interactions_mode():
    sse = ('data: ' + json.dumps({"type": "step.delta", "delta": {"text": "OK"}}) + '\n\n'
           'data: ' + json.dumps({"type": "interaction.completed",
                                  "usage": {"input_tokens": 4, "output_tokens": 2,
                                            "total_tokens": 6}}) + '\n\n')
    route = respx.post("https://generativelanguage.googleapis.com/v1beta/interactions").mock(
        return_value=httpx.Response(200, text=sse,
                                    headers={"content-type": "text/event-stream"}))
    a = GeminiAdapter(base_url="https://generativelanguage.googleapis.com", api_key="k",
                      options={"interactions_api": True})
    events = [e async for e in a.stream_chat(UnifiedRequest(
        model="gemini-3.5", messages=[{"role": "user", "content": "hi"}]))]
    body = json.loads(route.calls[0].request.content)
    assert body["input"][0]["type"] == "user_input"
    assert body["stream"] is True
    deltas = [e.data["content"] for e in events if e.type == "delta"]
    assert deltas == ["OK"]
    usage = [e for e in events if e.type == "usage"][0].data
    assert usage["total_tokens"] == 6


# ───────────── 管理端接口：标记落库 + 归一化 ─────────────

@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def h(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, role="admin")
    tok, _ = create_access_token(uid, "admin")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
async def client():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        yield c


async def test_create_normalizes_and_saves_flags(client, h):
    r = await client.post("/api/admin/channels", headers=h, json={
        "name": "讯飞", "type": "anthropic",
        "base_url": "https://maas-api.cn-huabei-1.xf-yun.com/anthropic/v1/messages",
        "api_key": "ak-x", "options": {"prompt_cache": True}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["base_url"] == "https://maas-api.cn-huabei-1.xf-yun.com/anthropic"
    assert d["auto_complete_url"] is True
    assert d["options"] == {"prompt_cache": True}
    r2 = await client.patch(f"/api/admin/channels/{d['id']}", headers=h, json={
        "version": d["version"], "auto_complete_url": False,
        "base_url": "https://custom.gateway.internal/llm"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["base_url"] == "https://custom.gateway.internal/llm"


def test_build_adapter_normalizes_legacy_suffixed_url():
    """存量脏数据兜底：开关开启时构造适配器即自动纠正误存的完整端点。"""
    from app.core.crypto import encrypt_api_key
    from app.llm.services.channel_service import build_adapter

    row = {"type": "anthropic", "base_url": "https://x/anthropic/v1/messages",
           "api_key_enc": encrypt_api_key("k"), "auto_complete_url": True}
    assert build_adapter(row).base_url == "https://x/anthropic"
    assert build_adapter({**row, "auto_complete_url": False}).base_url \
        == "https://x/anthropic/v1/messages"
