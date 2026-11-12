"""protocol → adapter 分发表。新增厂商是加预设一行，不是加代码分支。"""
from __future__ import annotations

from app.services.adapter.anthropic import AnthropicAdapter
from app.services.adapter.base import ProtocolAdapter
from app.services.adapter.gemini import GeminiAdapter
from app.services.adapter.openai_compat import OpenAICompatAdapter


class UnknownProtocol(Exception):
    pass


_ADAPTERS: dict[str, type[ProtocolAdapter]] = {
    OpenAICompatAdapter.protocol: OpenAICompatAdapter,
    AnthropicAdapter.protocol: AnthropicAdapter,
    GeminiAdapter.protocol: GeminiAdapter,
}


def get_adapter(protocol: str) -> type[ProtocolAdapter]:
    if protocol not in _ADAPTERS:
        raise UnknownProtocol(protocol)
    return _ADAPTERS[protocol]
