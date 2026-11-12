"""US-026：协议适配器抽象与分发表。"""
from __future__ import annotations

import pytest


def test_registry_resolves_three_protocols():
    from app.llm.adapter.registry import get_adapter

    for proto in ("openai_compatible", "anthropic", "gemini"):
        cls = get_adapter(proto)
        assert cls.protocol == proto


def test_unknown_protocol_raises():
    from app.llm.adapter.registry import UnknownProtocol, get_adapter

    with pytest.raises(UnknownProtocol):
        get_adapter("no-such-protocol")


def test_unified_request_and_stream_event_shapes():
    from app.llm.adapter.base import StreamEvent, UnifiedRequest

    req = UnifiedRequest(model="smart", messages=[{"role": "user", "content": "hi"}])
    assert req.stream is True
    ev = StreamEvent(type="delta", data={"content": "x"})
    assert ev.type in {"meta", "delta", "usage", "done", "error"}


def test_abstract_adapter_cannot_be_instantiated():
    from app.llm.adapter.base import ProtocolAdapter

    with pytest.raises(TypeError):
        ProtocolAdapter(base_url="https://x", api_key="k")  # type: ignore[abstract]
