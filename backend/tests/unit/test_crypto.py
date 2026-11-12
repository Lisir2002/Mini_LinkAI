"""US-025（部分）：渠道 API Key 的 Fernet 字段级加密。"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken


def test_encrypt_decrypt_roundtrip(monkeypatch):
    from app.core import crypto

    monkeypatch.setenv("CHANNEL_CIPHER_KEY", Fernet.generate_key().decode())
    crypto.reset_cipher()
    token = crypto.encrypt_api_key("sk-live-abcdef123456")
    assert "sk-live-abcdef123456" not in token
    assert crypto.decrypt_api_key(token) == "sk-live-abcdef123456"


def test_decrypt_with_wrong_key_fails(monkeypatch):
    from app.core import crypto

    monkeypatch.setenv("CHANNEL_CIPHER_KEY", Fernet.generate_key().decode())
    crypto.reset_cipher()
    token = crypto.encrypt_api_key("sk-secret")
    monkeypatch.setenv("CHANNEL_CIPHER_KEY", Fernet.generate_key().decode())
    crypto.reset_cipher()
    with pytest.raises(InvalidToken):
        crypto.decrypt_api_key(token)


def test_key_hint_shows_only_last_four():
    from app.core.crypto import key_hint

    assert key_hint("sk-live-abcdef123456") == "****3456"
    assert key_hint("ab") == "****"
