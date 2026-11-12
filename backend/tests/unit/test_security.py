"""US-015（部分）：argon2id 密码哈希。"""
from __future__ import annotations


def test_hash_is_argon2id_and_verifies():
    from app.core.security import hash_password, verify_password

    h = hash_password("Passw0rd2026")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Passw0rd2026") is True


def test_wrong_password_does_not_verify():
    from app.core.security import hash_password, verify_password

    h = hash_password("Passw0rd2026")
    assert verify_password(h, "wrong-password") is False


def test_same_password_hashes_differ_due_to_salt():
    from app.core.security import hash_password

    assert hash_password("Passw0rd2026") != hash_password("Passw0rd2026")
