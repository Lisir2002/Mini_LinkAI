"""US-027：厂商预设。"""
from __future__ import annotations


def test_each_protocol_has_presets():
    from app.llm.adapter.presets import PRESETS

    for proto in ("openai_compatible", "anthropic", "gemini"):
        assert len(PRESETS[proto]) >= 1


def test_openai_compat_covers_major_vendors():
    from app.llm.adapter.presets import PRESETS

    names = {p.name for p in PRESETS["openai_compatible"]}
    for expect in ("DeepSeek", "阿里百炼", "OpenRouter", "OpenAI", "Ollama"):
        assert expect in names, f"缺少预设 {expect}"


def test_base_urls_have_no_trailing_slash():
    from app.llm.adapter.presets import PRESETS

    for items in PRESETS.values():
        for p in items:
            assert not p.base_url.endswith("/"), p.name


def test_presets_carry_default_param_whitelist():
    from app.llm.adapter.presets import PRESETS

    p = PRESETS["openai_compatible"][0]
    assert "stream" in p.supported_params and "max_tokens" in p.supported_params
