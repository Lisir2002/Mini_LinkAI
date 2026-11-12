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
        body: dict[str, Any] = {
            "model": req.model, "messages": rest, "stream": True,
            "max_tokens": req.max_tokens or 1024,      # anthropic 必填
        }
        if system:
            body["system"] = system                    # 顶层，不在 messages 内
        body.update(self.pick({"temperature": req.temperature, "top_p": req.top_p,
                               "stop_sequences": req.stop}))
        prompt_tokens = completion_tokens = 0
        async with httpx.AsyncClient(timeout=self.total_timeout) as c:
            async with c.stream("POST", f"{self.base_url}/v1/messages", json=body,
                                headers=self.build_headers(self.api_key)) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise self.normalize_error(r.status_code, {})
                async for ev, data in iter_sse(r):
                    obj = json.loads(data)
                    if ev == "message_start":
                        prompt_tokens = (obj.get("message", {})
                                         .get("usage", {}).get("input_tokens", 0))
                    elif ev == "content_block_delta":
                        piece = (obj.get("delta") or {}).get("text")
                        if piece:
                            yield StreamEvent("delta", {"content": piece})
                    elif ev == "message_delta":
                        completion_tokens = obj.get("usage", {}).get("output_tokens", 0)
                        yield StreamEvent("usage", {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens})
        yield StreamEvent("done", {})

    async def test_connectivity(self) -> TestResult:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/v1/messages",
                                 headers=self.build_headers(self.api_key),
                                 json={"model": "probe", "max_tokens": 8,
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
