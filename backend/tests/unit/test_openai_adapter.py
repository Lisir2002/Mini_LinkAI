"""US-028：openai_compatible 适配器（全部用 respx 模拟上游）。"""
from __future__ import annotations

import json

import httpx
import pytest

SSE = (
    'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    'data: [DONE]\n\n'
)


def _adapter(**kw):
    from app.llm.adapter.openai_compat import OpenAICompatAdapter

    return OpenAICompatAdapter(base_url="https://api.test/v1", api_key="sk-test", **kw)


async def test_stream_chat_parses_deltas_usage_and_done(block_external_http):
    from app.llm.adapter.base import UnifiedRequest

    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    events = [e async for e in _adapter().stream_chat(
        UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    types = [e.type for e in events]
    assert types.count("delta") == 2
    assert "usage" in types and types[-1] == "done"
    assert "".join(e.data["content"] for e in events if e.type == "delta") == "你好"
    usage = next(e.data for e in events if e.type == "usage")
    assert usage["prompt_tokens"] == 10 and usage["completion_tokens"] == 2


async def test_stream_requests_include_usage_option(block_external_http):
    from app.llm.adapter.base import UnifiedRequest

    route = block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    _ = [e async for e in _adapter().stream_chat(
        UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    body = json.loads(route.calls[0].request.content)
    assert body["stream"] is True
    assert body["stream_options"]["include_usage"] is True, "不带此选项流式拿不到 usage"
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"


async def test_param_whitelist_filters_unsupported(block_external_http):
    from app.llm.adapter.base import UnifiedRequest

    route = block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    ad = _adapter(supported_params=["temperature", "max_tokens", "stream"])
    _ = [e async for e in ad.stream_chat(UnifiedRequest(
        model="m", messages=[{"role": "user", "content": "hi"}],
        temperature=0.7, top_p=0.9, max_tokens=100))]
    body = json.loads(route.calls[0].request.content)
    assert "temperature" in body and "max_tokens" in body
    assert "top_p" not in body, "白名单外的参数不得发送"


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "rate_limit"),
                                         (400, "bad_param"), (500, "upstream")])
def test_error_normalization(status, kind):
    assert _adapter().normalize_error(status, {}).kind == kind


async def test_connectivity_success_and_auth_failure(block_external_http):
    ad = _adapter()
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, json={"choices": [{"message": {"content": "ok"}}]})
    ok = await ad.test_connectivity()
    assert ok.ok is True and isinstance(ok.latency_ms, int)

    block_external_http.post("https://api.test/v1/chat/completions").respond(401, json={})
    bad = await ad.test_connectivity()
    assert bad.ok is False and bad.error_kind == "auth"


async def test_list_models(block_external_http):
    block_external_http.get("https://api.test/v1/models").respond(
        200, json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})
    assert await _adapter().list_models() == ["gpt-4o", "gpt-4o-mini"]


async def test_missing_usage_falls_back_to_estimation(block_external_http):
    from app.llm.adapter.base import UnifiedRequest

    no_usage = ('data: {"choices":[{"delta":{"content":"你好世界"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: [DONE]\n\n')
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=no_usage, headers={"content-type": "text/event-stream"})
    events = [e async for e in _adapter().stream_chat(
        UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    u = next(e.data for e in events if e.type == "usage")
    assert u["estimated"] is True, "usage 缺失必须标记为估算"
    assert u["completion_tokens"] > 0 and u["prompt_tokens"] > 0


async def test_finish_reason_length_is_surfaced(block_external_http):
    from app.llm.adapter.base import UnifiedRequest

    body = ('data: {"choices":[{"delta":{"content":"部分"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"length"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":9,"total_tokens":14}}\n\n'
            'data: [DONE]\n\n')
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=body, headers={"content-type": "text/event-stream"})
    events = [e async for e in _adapter().stream_chat(
        UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    assert events[-1].type == "done"
    assert events[-1].data["finish_reason"] == "length"


async def test_upstream_401_raises_normalized_error(block_external_http):
    from app.llm.adapter.base import UnifiedRequest, UpstreamError

    block_external_http.post("https://api.test/v1/chat/completions").respond(401, json={})
    with pytest.raises(UpstreamError) as ei:
        _ = [e async for e in _adapter().stream_chat(
            UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    assert ei.value.kind == "auth"


async def test_read_timeout_raises_timeout_kind(block_external_http):
    from app.llm.adapter.base import UnifiedRequest, UpstreamError

    block_external_http.post("https://api.test/v1/chat/completions").mock(
        side_effect=httpx.ReadTimeout("too slow"))
    with pytest.raises(UpstreamError) as ei:
        _ = [e async for e in _adapter().stream_chat(
            UnifiedRequest(model="m", messages=[{"role": "user", "content": "hi"}]))]
    assert ei.value.kind == "timeout"
