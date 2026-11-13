"""Anthropic Messages 协议适配器（PRD 5.2.1）。"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from app.llm.adapter.base import (
    ProtocolAdapter,
    StreamEvent,
    TestResult,
    UnifiedRequest,
    UpstreamError,
    error_kind,
    iter_sse,
    split_system,
)


class AnthropicAdapter(ProtocolAdapter):
    protocol: ClassVar[str] = "anthropic"
    default_params: ClassVar[list[str]] = ["temperature", "top_p", "max_tokens",
                                           "stream", "stop_sequences"]

    def build_headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"}

    def normalize_error(self, status: int, body: dict[str, Any]) -> UpstreamError:
        return UpstreamError(error_kind(status), str(body)[:200], status)

    async def stream_chat(self, req: UnifiedRequest) -> AsyncIterator[StreamEvent]:
        system, rest = split_system(req.messages)
        use_cache = bool(self.options.get("prompt_cache"))
        msgs: list[dict[str, Any]] = [dict(m) for m in rest]
        if use_cache and msgs:
            last = msgs[-1]
            content = last.get("content")
            # 断点打在最后一条消息：本轮前缀写入缓存，下轮直接读回（读价约 1 折）
            if isinstance(content, str) and content:
                last["content"] = [{"type": "text", "text": content,
                                    "cache_control": {"type": "ephemeral"}}]
        body: dict[str, Any] = {
            "model": req.model, "messages": msgs, "stream": True,
            "max_tokens": req.max_tokens or 1024,      # anthropic 必填
        }
        if system:
            # 顶层，不在 messages 内；开关开启时系统提示词作为稳定前缀缓存
            if use_cache:
                body["system"] = [{"type": "text", "text": system,
                                   "cache_control": {"type": "ephemeral"}}]
            else:
                body["system"] = system
        body.update(self.pick({"temperature": req.temperature, "top_p": req.top_p,
                               "stop_sequences": req.stop}))
        prompt_tokens = completion_tokens = cache_tokens = 0
        async with httpx.AsyncClient(timeout=self.total_timeout) as c:
            async with c.stream("POST", f"{self.base_url}/v1/messages", json=body,
                                headers=self.build_headers(self.api_key)) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise self.normalize_error(r.status_code, {})
                async for ev, data in iter_sse(r):
                    obj = json.loads(data)
                    if ev == "message_start":
                        u0 = (obj.get("message", {}) or {}).get("usage", {})
                        prompt_tokens = u0.get("input_tokens", 0)
                        # 缓存写入/读取 token 计入配额，保证计费口径完整
                        cache_tokens = (u0.get("cache_creation_input_tokens", 0)
                                        + u0.get("cache_read_input_tokens", 0))
                    elif ev == "content_block_delta":
                        piece = (obj.get("delta") or {}).get("text")
                        if piece:
                            yield StreamEvent("delta", {"content": piece})
                    elif ev == "message_delta":
                        completion_tokens = obj.get("usage", {}).get("output_tokens", 0)
                        yield StreamEvent("usage", {
                            "prompt_tokens": prompt_tokens + cache_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": (prompt_tokens + cache_tokens
                                             + completion_tokens)})
        yield StreamEvent("done", {})

    async def test_connectivity(self) -> TestResult:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/v1/messages",
                                 headers=self.build_headers(self.api_key),
                                 json={"model": self.probe_model, "max_tokens": 8,
                                       "messages": [{"role": "user", "content": "ping"}]})
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(True, ms)
            return TestResult(False, ms, error_kind(r.status_code), f"HTTP {r.status_code}")
        except Exception as exc:                       # noqa: BLE001
            return TestResult(False, int((time.perf_counter() - t0) * 1000),
                              "timeout", str(exc)[:120])

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{self.base_url}/v1/models", headers=self.build_headers(self.api_key))
        if r.status_code != 200:
            raise self.normalize_error(r.status_code, {})
        return [m["id"] for m in r.json().get("data", [])]
