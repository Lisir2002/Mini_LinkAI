"""结构化日志与脱敏（PRD 10.3）。

禁止输出：密码、Token、API Key（含密文）、消息正文全文。
邮箱与手机在输出前脱敏。
"""
from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEYS = frozenset({
    "password", "password_hash", "token", "jwt", "authorization",
    "api_key", "api_key_enc", "secret", "content", "prompt", "completion",
})


def mask_email(value: str) -> str:
    local, sep, domain = value.partition("@")
    if not sep:
        return "***"
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return digits[:3] + "****" + digits[-4:]


def _sanitize(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict.pop(key)
    if isinstance(event_dict.get("email"), str):
        event_dict["email"] = mask_email(event_dict["email"])
    if isinstance(event_dict.get("phone"), str):
        event_dict["phone"] = mask_phone(event_dict["phone"])
    return event_dict


class _StdoutLoggerFactory:
    """每次创建 logger 时动态取 sys.stdout。

    固定绑定 file=sys.stdout 会在 pytest 的 capsys 切换后持有已关闭句柄，
    导致异常处理器内写日志再次抛错、退化成纯文本 500（已实测踩到）。
    """

    def __call__(self, *args: Any) -> structlog.PrintLogger:
        return structlog.PrintLogger(file=sys.stdout)


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _sanitize,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=_StdoutLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def log_event(action: str, **fields: Any) -> None:
    structlog.get_logger().info(action, action=action, **fields)
