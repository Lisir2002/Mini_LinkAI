"""OpenAI 兼容协议适配器：覆盖面最广（PRD 5.2.1）。"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from app.services.adapter.base import (
    ProtocolAdapter,
    StreamEvent,
    TestResult,
    UnifiedRequest,
    UpstreamError,
    error_kind,
    iter_sse,
)


def estimate_usage(messages: list[dict[str, str]], completion: str) -> dict[str, Any]:
    """上游未返回 usage 时的本地估算，结果显式标记 estimated=True。"""
    def _text(content: Any) -> str:
        if isinstance(content, list):
            return "".join(x.get("text", "") for x in content if isinstance(x, dict))
        return str(content or "")

    prompt_text = "".join(_text(m.get("content", "")) for m in messages)
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        p, c = len(enc.encode(prompt_text)), len(enc.encode(completion))
    except Exception:                                  # noqa: BLE001 - 离线环境降级
        p, c = max(len(prompt_text) // 2, 1), max(len(completion) // 2, 1)
    return {"prompt_tokens": p, "completion_tokens": c,
            "total_tokens": p + c, "estimated": True}


class OpenAICompatAdapter(ProtocolAdapter):
    protocol: ClassVar[str] = "openai_compatible"
    default_params: ClassVar[list[str]] = ["temperature", "top_p", "max_tokens", "stream", "stop"]

    def build_headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def normalize_error(self, status: int, body: dict[str, Any]) -> UpstreamError:
        return UpstreamError(error_kind(status), str(body)[:200], status)

    async def stream_chat(self, req: UnifiedRequest) -> AsyncIterator[StreamEvent]:
        body: dict[str, Any] = {
            "model": req.model, "messages": req.messages, "stream": True,
            # 不带此选项，流式响应里拿不到 usage，配额就无法结算
            "stream_options": {"include_usage": True},
        }
        body.update(self.pick({"temperature": req.temperature, "top_p": req.top_p,
                               "max_tokens": req.max_tokens, "stop": req.stop}))
        url = f"{self.base_url}/chat/completions"
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        collected: list[str] = []
        timeout = httpx.Timeout(self.total_timeout, connect=5.0,
                                read=self.first_token_timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                async with c.stream("POST", url, json=body,
                                    headers=self.build_headers(self.api_key)) as r:
                    if r.status_code != 200:
                        await r.aread()
                        raise self.normalize_error(r.status_code, {})
                    async for _ev, data in iter_sse(r):
                        if data == "[DONE]":
                            break
                        obj = json.loads(data)
                        choices = obj.get("choices") or [{}]
                        piece = (choices[0].get("delta") or {}).get("content")
                        if piece:
                            collected.append(piece)
                            yield StreamEvent("delta", {"content": piece})
                        if choices[0].get("finish_reason"):
                            finish_reason = choices[0]["finish_reason"]
                        u = obj.get("usage")
                        if u:
                            usage = {"prompt_tokens": u.get("prompt_tokens", 0),
                                     "completion_tokens": u.get("completion_tokens", 0),
                                     "total_tokens": u.get("total_tokens", 0),
                                     "estimated": False}
        except httpx.TimeoutException as exc:
            raise UpstreamError("timeout", str(exc)[:120]) from exc
        if usage is None:
            # 上游未回 usage：本地估算并显式标记，绝不静默按 0 计费
            usage = estimate_usage(req.messages, "".join(collected))
        yield StreamEvent("usage", usage)
        yield StreamEvent("done", {"finish_reason": finish_reason})

    async def test_connectivity(self) -> TestResult:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/chat/completions",
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
            r = await c.get(f"{self.base_url}/models", headers=self.build_headers(self.api_key))
        if r.status_code != 200:
            raise self.normalize_error(r.status_code, {})
        return [m["id"] for m in r.json().get("data", [])]
