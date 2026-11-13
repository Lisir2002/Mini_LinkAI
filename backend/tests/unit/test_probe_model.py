"""连通测试探测模型：probe_model 应贯穿到实际请求体。"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.llm.adapter.anthropic import AnthropicAdapter
from app.llm.adapter.openai_compat import OpenAICompatAdapter


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_probe_uses_probe_model():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "m"})

    respx.post("https://api.ant/v1/messages").mock(side_effect=handler)
    a = AnthropicAdapter(base_url="https://api.ant", api_key="k", probe_model="spark-x2.6")
    res = await a.test_connectivity()
    assert res.ok
    assert captured["body"]["model"] == "spark-x2.6"


@respx.mock
@pytest.mark.asyncio
async def test_openai_probe_defaults_to_probe():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": []})

    respx.post("https://api-o.test/v1/chat/completions").mock(side_effect=handler)
    a = OpenAICompatAdapter(base_url="https://api-o.test/v1", api_key="k")
    res = await a.test_connectivity()
    assert res.ok
    assert captured["body"]["model"] == "probe"