"""Google Gemini generateContent 协议适配器（AI Studio API Key 模式，PRD 5.2.1）。"""
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


class GeminiAdapter(ProtocolAdapter):
    protocol: ClassVar[str] = "gemini"
    default_params: ClassVar[list[str]] = ["temperature", "topP", "maxOutputTokens",
                                           "stopSequences"]

    def build_headers(self, key: str) -> dict[str, str]:
        # 禁用 ?key= 方式：会进访问日志与浏览器历史
        return {"x-goog-api-key": key, "Content-Type": "application/json"}

    def normalize_error(self, status: int, body: dict[str, Any]) -> UpstreamError:
        return UpstreamError(error_kind(status), str(body)[:200], status)

    async def stream_chat(self, req: UnifiedRequest) -> AsyncIterator[StreamEvent]:
        system, rest = split_system(req.messages)
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]} for m in rest]
        gen = self.pick({"temperature": req.temperature, "topP": req.top_p,
                         "maxOutputTokens": req.max_tokens, "stopSequences": req.stop})
        body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        usage: dict[str, int] | None = None
        url = f"{self.base_url}/v1beta/models/{req.model}:streamGenerateContent"
        async with httpx.AsyncClient(timeout=self.total_timeout) as c:
            async with c.stream("POST", url, params={"alt": "sse"}, json=body,
                                headers=self.build_headers(self.api_key)) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise self.normalize_error(r.status_code, {})
                async for _ev, data in iter_sse(r):
                    obj = json.loads(data)
                    for cand in obj.get("candidates", []):
                        for part in (cand.get("content") or {}).get("parts", []):
                            if part.get("text"):
                                yield StreamEvent("delta", {"content": part["text"]})
                    um = obj.get("usageMetadata")
                    if um:
                        usage = {"prompt_tokens": um.get("promptTokenCount", 0),
                                 "completion_tokens": um.get("candidatesTokenCount", 0),
                                 "total_tokens": um.get("totalTokenCount", 0)}
        if usage:
            yield StreamEvent("usage", usage)
        # gemini 无 [DONE] 标记，流结束即完成
        yield StreamEvent("done", {})

    async def test_connectivity(self) -> TestResult:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/v1beta/models/probe:generateContent",
                                 headers=self.build_headers(self.api_key),
                                 json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]})
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(True, ms)
            return TestResult(False, ms, error_kind(r.status_code), f"HTTP {r.status_code}")
        except Exception as exc:                       # noqa: BLE001
            return TestResult(False, int((time.perf_counter() - t0) * 1000),
                              "timeout", str(exc)[:120])

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{self.base_url}/v1beta/models",
                            headers=self.build_headers(self.api_key))
        if r.status_code != 200:
            raise self.normalize_error(r.status_code, {})
        return [m["name"].removeprefix("models/") for m in r.json().get("models", [])]
