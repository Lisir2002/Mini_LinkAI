"""US-016/020/021/022/023：权限依赖与认证接口。"""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture
async def app_session():
    from app.core.db import get_session

    async with get_session() as s:
        yield s


@pytest.fixture
async def client():
    from app.interfaces.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _invite(session, max_uses: int = 5) -> str:
    code = "RM-" + uuid.uuid4().hex[:8].upper()
    uid = (await session.execute(
        text("SELECT id FROM users WHERE role='admin' LIMIT 1"))).scalar_one_or_none()
    if uid is None:
        uid = (await session.execute(
            text("INSERT INTO users (email,password_hash,nickname,role) "
                 "VALUES (:e,'x','root','admin') RETURNING id"),
            {"e": f"root-{uuid.uuid4().hex[:8]}@x.com"})).scalar_one()
    await session.execute(
        text("INSERT INTO invite_codes (code,created_by,max_uses) VALUES (:c,:u,:m)"),
        {"c": code, "u": uid, "m": max_uses})
    await session.commit()
    return code


def _payload(code: str, **kw) -> dict:
    base = {"email": f"u{uuid.uuid4().hex[:10]}@example.com",
            "password": "Passw0rd2026", "nickname": "tester", "invite_code": code}
    base.update(kw)
    return base


async def test_register_success_returns_token(client, app_session):
    code = await _invite(app_session)
    r = await client.post("/api/auth/register", json=_payload(code))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["token"] and d["user"]["role"] == "member"
    assert "***" in d["user"]["email"], "邮箱应脱敏"


async def test_register_duplicate_email_conflict(client, app_session):
    code = await _invite(app_session)
    p = _payload(code)
    assert (await client.post("/api/auth/register", json=p)).status_code == 200
    r = await client.post("/api/auth/register", json=p)
    assert r.status_code == 409
    assert r.json()["code"] == "EMAIL_EXISTS"


async def test_register_invalid_invite_rejected(client):
    r = await client.post("/api/auth/register", json=_payload("RM-NOPE"))
    assert r.status_code == 422
    assert r.json()["code"] == "INVITE_CODE_INVALID"


async def test_login_success_and_wrong_password(client, app_session):
    code = await _invite(app_session)
    p = _payload(code)
    await client.post("/api/auth/register", json=p)
    ok = await client.post("/api/auth/login", json={"email": p["email"], "password": p["password"]})
    assert ok.status_code == 200 and ok.json()["data"]["token"]
    bad = await client.post("/api/auth/login", json={"email": p["email"], "password": "wrong"})
    assert bad.status_code == 401
    missing = await client.post("/api/auth/login",
                                json={"email": "nobody@x.com", "password": "wrong"})
    assert missing.status_code == 401
    assert missing.json()["message"] == bad.json()["message"], "不得泄露账号是否存在"


async def test_login_locks_after_five_failures(client, app_session):
    code = await _invite(app_session)
    p = _payload(code)
    await client.post("/api/auth/register", json=p)
    for _ in range(5):
        await client.post("/api/auth/login", json={"email": p["email"], "password": "bad"})
    r = await client.post("/api/auth/login", json={"email": p["email"], "password": p["password"]})
    assert r.status_code == 423
    assert r.json()["code"] == "ACCOUNT_LOCKED"


async def test_me_requires_token_and_returns_quota(client, app_session):
    assert (await client.get("/api/auth/me")).status_code == 401
    code = await _invite(app_session)
    reg = await client.post("/api/auth/register", json=_payload(code))
    token = reg.json()["data"]["token"]
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["must_change_password"] is False
    assert d["daily_msg_limit"] == 50


async def test_admin_only_route_rejects_member(client, app_session):
    code = await _invite(app_session)
    reg = await client.post("/api/auth/register", json=_payload(code))
    token = reg.json()["data"]["token"]
    r = await client.get("/api/admin/settings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN_ADMIN_ONLY"


async def test_logout_blacklists_token(client, app_session):
    code = await _invite(app_session)
    reg = await client.post("/api/auth/register", json=_payload(code))
    token = reg.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/auth/logout", headers=h)).status_code == 200
    assert (await client.get("/api/auth/me", headers=h)).status_code == 401


async def test_password_change_clears_flag_and_allows_access(client, app_session):
    code = await _invite(app_session)
    p = _payload(code)
    reg = await client.post("/api/auth/register", json=p)
    token = reg.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    uid = reg.json()["data"]["user"]["id"]
    await app_session.execute(
        text("UPDATE users SET must_change_password=true WHERE id=:i"), {"i": uid})
    await app_session.commit()
    blocked = await client.get("/api/auth/me", headers=h)
    assert blocked.status_code == 200, "me 本身必须可访问"
    other = await client.get("/api/admin/settings", headers=h)
    assert other.status_code == 403 and other.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    chg = await client.post("/api/auth/password", headers=h,
                            json={"old_password": p["password"], "new_password": "NewPass2026x"})
    assert chg.status_code == 200
    after = await client.get("/api/admin/settings", headers=h)
    assert after.json()["code"] == "FORBIDDEN_ADMIN_ONLY"


async def test_register_closed_mode_rejected(client, app_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REGISTRATION_MODE", "closed")
    code = await _invite(app_session)
    r = await client.post("/api/auth/register", json=_payload(code))
    assert r.status_code == 403
    assert r.json()["code"] == "REGISTRATION_CLOSED"


async def test_login_banned_account_rejected(client, app_session):
    code = await _invite(app_session)
    p = _payload(code)
    reg = await client.post("/api/auth/register", json=p)
    uid = reg.json()["data"]["user"]["id"]
    await app_session.execute(text("UPDATE users SET status='banned' WHERE id=:i"), {"i": uid})
    await app_session.commit()
    r = await client.post("/api/auth/login", json={"email": p["email"], "password": p["password"]})
    assert r.status_code == 403
    assert r.json()["code"] == "ACCOUNT_BANNED"


async def test_register_idempotency_key_replays_first_result(client, app_session):
    code = await _invite(app_session, max_uses=5)
    p = _payload(code)
    key = str(uuid.uuid4())
    r1 = await client.post("/api/auth/register", json=p, headers={"Idempotency-Key": key})
    r2 = await client.post("/api/auth/register", json=p, headers={"Idempotency-Key": key})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["user"]["id"] == r2.json()["data"]["user"]["id"]
    n = (await app_session.execute(
        text("SELECT count(*) FROM users WHERE email=:e"), {"e": p["email"]})).scalar_one()
    assert n == 1, "同幂等键不应创建第二个用户"
