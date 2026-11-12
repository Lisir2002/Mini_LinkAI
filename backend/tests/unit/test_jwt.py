"""US-015：JWT 签发校验、双密钥轮换、jti 黑名单。"""
from __future__ import annotations

import time

import pytest


def test_create_and_decode_roundtrip():
    from app.core.security import create_access_token, decode_token

    token, exp = create_access_token(42, "admin")
    p = decode_token(token)
    assert p["sub"] == "42" and p["role"] == "admin" and p["jti"]
    assert exp.timestamp() > time.time()


def test_expired_token_rejected(monkeypatch):
    from app.core import security

    monkeypatch.setattr(security.settings, "JWT_EXPIRE_DAYS", 0)
    token, _ = security.create_access_token(1, "member")
    time.sleep(1.1)
    with pytest.raises(security.TokenInvalid):
        security.decode_token(token)


def test_tampered_token_rejected():
    from app.core.security import TokenInvalid, create_access_token, decode_token

    token, _ = create_access_token(1, "member")
    with pytest.raises(TokenInvalid):
        decode_token(token[:-3] + "aaa")


def test_previous_key_still_valid_during_rotation(monkeypatch):
    from app.core import security

    old = security.settings.JWT_SECRET
    token, _ = security.create_access_token(7, "member")
    monkeypatch.setattr(security.settings, "JWT_SECRET", "brand-new-secret-0123456789abcdef")
    monkeypatch.setattr(security.settings, "JWT_SECRET_PREV", old)
    assert security.decode_token(token)["sub"] == "7"


async def test_blacklist_roundtrip():
    from app.core.security import blacklist_token, is_blacklisted

    assert await is_blacklisted("jti-abc") is False
    await blacklist_token("jti-abc", 30)
    assert await is_blacklisted("jti-abc") is True
