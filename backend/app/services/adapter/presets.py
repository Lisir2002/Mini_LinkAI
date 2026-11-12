"""厂商预设（PRD 5.2.1）：只作便利填充，不参与路由；最终以连通性测试为准。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Preset:
    name: str
    base_url: str
    supported_params: list[str] = field(default_factory=lambda: [
        "temperature", "top_p", "max_tokens", "stream", "stop"])
    timeout_first_token_ms: int = 15000
    timeout_total_ms: int = 60000


_OAI = ["temperature", "top_p", "max_tokens", "stream", "stop"]

PRESETS: dict[str, list[Preset]] = {
    "openai_compatible": [
        Preset("OpenAI", "https://api.openai.com/v1"),
        Preset("DeepSeek", "https://api.deepseek.com/v1"),
        Preset("阿里百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        Preset("SiliconFlow", "https://api.siliconflow.cn/v1"),
        Preset("OpenRouter", "https://openrouter.ai/api/v1"),
        Preset("Groq", "https://api.groq.com/openai/v1"),
        Preset("Moonshot", "https://api.moonshot.cn/v1"),
        Preset("智谱", "https://open.bigmodel.cn/api/paas/v4"),
        Preset("Together", "https://api.together.xyz/v1"),
        Preset("Ollama", "http://127.0.0.1:11434/v1"),
        Preset("vLLM", "http://127.0.0.1:8000/v1"),
    ],
    "anthropic": [
        Preset("Anthropic", "https://api.anthropic.com",
               ["temperature", "top_p", "max_tokens", "stream", "stop_sequences"]),
    ],
    "gemini": [
        Preset("Google AI Studio", "https://generativelanguage.googleapis.com",
               ["temperature", "topP", "maxOutputTokens", "stopSequences"]),
    ],
}
