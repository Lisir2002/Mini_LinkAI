"""三协议差异点：鉴权头、系统提示词位置、角色命名、流式分片与 usage 位置。"""
from __future__ import annotations

import json

import pytest

ANT_SSE = (
    'event: message_start\n'
    'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
    'event: content_block_delta\n'
    'data: {"type":"content_block_delta","delta":{"text":"你"}}\n\n'
    'event: message_delta\n'
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    '"usage":{"output_tokens":2}}\n\n'
    'event: message_stop\n'
    'data: {"type":"message_stop"}\n\n'
)
GEM_SSE = (
    'data: {"candidates":[{"content":{"parts":[{"text":"你"}]}}]}\n\n'
    'data: {"candidates":[{"content":{"parts":[{"text":"好"}]},"finishReason":"STOP"}],'
    '"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":2,"totalTokenCount":12}}\n\n'
)


def _req():
    from app.services.adapter.base import UnifiedRequest
    return UnifiedRequest(model="m", messages=[
        {"role": "system", "content": "你是助手"}, {"role": "user", "content": "hi"}])


async def test_anthropic_headers_and_body(block_external_http):
    from app.services.adapter.anthropic import AnthropicAdapter

    route = block_external_http.post("https://api.ant/v1/messages").respond(
        200, text=ANT_SSE, headers={"content-type": "text/event-stream"})
    ad = AnthropicAdapter(base_url="https://api.ant", api_key="sk-ant")
    events = [e async for e in ad.stream_chat(_req())]
    req = route.calls[0].request
    assert req.headers["x-api-key"] == "sk-ant"
    assert req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["system"] == "你是助手", "system 必须在顶层"
    assert all(m["role"] != "system" for m in body["messages"])
    assert "max_tokens" in body, "anthropic 的 max_tokens 必填"
    assert "".join(e.data["content"] for e in events if e.type == "delta") == "你"
    u = next(e.data for e in events if e.type == "usage")
    assert u["prompt_tokens"] == 10 and u["completion_tokens"] == 2
    assert events[-1].type == "done"


async def test_gemini_headers_body_and_no_done_marker(block_external_http):
    from app.services.adapter.gemini import GeminiAdapter

    route = block_external_http.post(
        "https://api.gem/v1beta/models/m:streamGenerateContent").respond(
        200, text=GEM_SSE, headers={"content-type": "text/event-stream"})
    ad = GeminiAdapter(base_url="https://api.gem", api_key="gk")
    events = [e async for e in ad.stream_chat(_req())]
    req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == "gk"
    assert "key=" not in str(req.url), "禁止用 query 传 key"
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "你是助手"
    assert body["contents"][0]["role"] == "user"
    assert "generationConfig" in body
    assert "".join(e.data["content"] for e in events if e.type == "delta") == "你好"
    u = next(e.data for e in events if e.type == "usage")
    assert u["prompt_tokens"] == 10 and u["completion_tokens"] == 2
    assert events[-1].type == "done", "gemini 无终止标记，靠流结束判定"


@pytest.mark.parametrize("proto,cls_path,status,kind", [
    ("anthropic", "app.services.adapter.anthropic:AnthropicAdapter", 401, "auth"),
    ("anthropic", "app.services.adapter.anthropic:AnthropicAdapter", 429, "rate_limit"),
    ("gemini", "app.services.adapter.gemini:GeminiAdapter", 403, "auth"),
    ("gemini", "app.services.adapter.gemini:GeminiAdapter", 400, "bad_param"),
])
def test_other_protocol_error_mapping(proto, cls_path, status, kind):
    import importlib
    mod, name = cls_path.split(":")
    cls = getattr(importlib.import_module(mod), name)
    ad = cls(base_url="https://x", api_key="k")
    assert ad.normalize_error(status, {}).kind == kind
