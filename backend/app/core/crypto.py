"""渠道 API Key 字段级加密（PRD 10.1 第三层 / US-025）。

密钥直接读 env 而非 settings 快照，便于轮换脚本与测试注入。
明文永不落库、永不出接口；对外只给 key_hint（末 4 位）。
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

_cipher: Fernet | None = None


def _get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        key = os.environ.get("CHANNEL_CIPHER_KEY", "")
        if not key:
            raise RuntimeError("CHANNEL_CIPHER_KEY 未配置，无法加解密渠道密钥")
        _cipher = Fernet(key.encode())
    return _cipher


def reset_cipher() -> None:
    """密钥轮换或测试切换后丢弃缓存实例。"""
    global _cipher
    _cipher = None


def encrypt_api_key(plain: str) -> str:
    return _get_cipher().encrypt(plain.encode()).decode()


def decrypt_api_key(token: str) -> str:
    return _get_cipher().decrypt(token.encode()).decode()


def key_hint(plain: str) -> str:
    return "****" + plain[-4:] if len(plain) >= 4 else "****"
