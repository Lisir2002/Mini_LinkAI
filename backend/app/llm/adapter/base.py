"""协议适配器抽象（PRD 5.2.1）。上层只认 UnifiedRequest 与 StreamEvent。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx


@dataclass
class UnifiedRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    stream: bool = True
    cache_key: str | None = None


@dataclass
class StreamEvent:
    type: str                       # meta | delta | usage | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    ok: bool
    latency_ms: int = 0
    error_kind: str | None = None
    message: str = ""


class UpstreamError(Exception):
    def __init__(self, kind: str, message: str = "", status: int | None = None) -> None:
        super().__init__(message or kind)
        self.kind = kind
        self.status = status


def error_kind(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status in (400, 404, 422):
        return "bad_param"
    return "upstream"


async def iter_sse(response: httpx.Response) -> AsyncIterator[tuple[str | None, str]]:
    """统一解析 SSE：返回 (event 名, data 字符串)。"""
    event: str | None = None
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            yield event, line[5:].strip()
        elif not line:
            event = None


def split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    sys_parts = [m["content"] for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    return "\n".join(sys_parts), rest


class ProtocolAdapter(ABC):
    protocol: ClassVar[str] = ""
    default_params: ClassVar[list[str]] = []

    def __init__(self, *, base_url: str, api_key: str,
                 supported_params: list[str] | None = None,
                 timeout_first_token_ms: int = 15000,
                 timeout_total_ms: int = 60000,
                 probe_model: str = "probe",
                 options: dict[str, Any] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.probe_model = probe_model
        self.options = options or {}
        self.api_key = api_key
        self.supported_params = list(supported_params or self.default_params)
        self.timeout = httpx.Timeout(timeout_total_ms / 1000,
                                     connect=5.0, read=timeout_first_token_ms / 1000)
        self.total_timeout = timeout_total_ms / 1000
        self.first_token_timeout = timeout_first_token_ms / 1000

    def pick(self, values: dict[str, Any]) -> dict[str, Any]:
        """按参数白名单过滤，避免把上游不支持的参数发过去导致 400。"""
        return {k: v for k, v in values.items()
                if v is not None and k in self.supported_params}

    @abstractmethod
    def stream_chat(self, req: UnifiedRequest) -> AsyncIterator[StreamEvent]: ...
    @abstractmethod
    async def test_connectivity(self) -> TestResult: ...
    @abstractmethod
    async def list_models(self) -> list[str]: ...
    @abstractmethod
    def build_headers(self, key: str) -> dict[str, str]: ...
    @abstractmethod
    def normalize_error(self, status: int, body: dict[str, Any]) -> UpstreamError: ...
