"""US-020 手机号注册与 body 幂等键 / US-023 改密后其他 token 失效 / US-017 权限被拒审计。"""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        yield c


@pytest.fixture
async def app_session():
    from app.core.db import get_session
    async with get_session() as s:
        yield s


async def _code(session) -> str:
    code = "RM-" + uuid.uuid4().hex[:8].upper()
    uid = (await session.execute(
        text("SELECT id FROM users WHERE role='admin' LIMIT 1"))).scalar_one()
    await session.execute(text("INSERT INTO invite_codes (code,created_by,max_uses) "
                               "VALUES (:c,:u,9)"), {"c": code, "u": uid})
    await session.commit()
    return code


async def test_register_with_phone_only(client, app_session):
    code = await _code(app_session)
    phone = "+8613" + "".join(str(uuid.uuid4().int % 10) for _ in range(9))
    r = await client.post("/api/auth/register", json={
        "phone": phone, "password": "Passw0rd2026", "nickname": "手机用户", "invite_code": code})
    assert r.status_code == 200, r.text


async def test_register_requires_exactly_one_identifier(client, app_session):
    code = await _code(app_session)
    base = {"password": "Passw0rd2026", "nickname": "x", "invite_code": code}
    r1 = await client.post("/api/auth/register", json=base)
    r2 = await client.post("/api/auth/register",
                           json=base | {"email": "a@b.com", "phone": "+8613800000000"})
    assert r1.status_code == 422 and r2.status_code == 422


async def test_register_body_idempotency_key(client, app_session):
    code = await _code(app_session)
    key = str(uuid.uuid4())
    p = {"email": f"u{uuid.uuid4().hex[:8]}@x.com", "password": "Passw0rd2026",
         "nickname": "x", "invite_code": code, "idempotency_key": key}
    r1 = await client.post("/api/auth/register", json=p)
    r2 = await client.post("/api/auth/register", json=p)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["user"]["id"] == r2.json()["data"]["user"]["id"]


async def test_password_change_invalidates_other_tokens_keeps_current(client, app_session):
    code = await _code(app_session)
    p = {"email": f"u{uuid.uuid4().hex[:8]}@x.com", "password": "Passw0rd2026",
         "nickname": "x", "invite_code": code}
    reg = await client.post("/api/auth/register", json=p)
    t1 = reg.json()["data"]["token"]
    login = await client.post("/api/auth/login",
                              json={"email": p["email"], "password": p["password"]})
    t2 = login.json()["data"]["token"]
    chg = await client.post("/api/auth/password", headers={"Authorization": f"Bearer {t1}"},
                            json={"old_password": p["password"], "new_password": "NewPass2026x"})
    assert chg.status_code == 200
    keep = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {t1}"})
    gone = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"})
    assert keep.status_code == 200, "当前会话 token 应保留"
    assert gone.status_code == 401, "其他 token 应失效"


async def test_permission_denied_is_audited(client, app_session):
    code = await _code(app_session)
    reg = await client.post("/api/auth/register", json={
        "email": f"u{uuid.uuid4().hex[:8]}@x.com", "password": "Passw0rd2026",
        "nickname": "x", "invite_code": code})
    token = reg.json()["data"]["token"]
    uid = reg.json()["data"]["user"]["id"]
    await client.get("/api/admin/settings", headers={"Authorization": f"Bearer {token}"})
    n = (await app_session.execute(
        text("SELECT count(*) FROM audit_logs WHERE action='auth.permission_denied' "
             "AND actor_id=:u"), {"u": uid})).scalar_one()
    assert n >= 1, "权限被拒必须写审计"


async def test_login_with_phone(client, app_session):
    code = await _code(app_session)
    phone = "+86139" + "".join(str(uuid.uuid4().int % 10) for _ in range(8))
    reg = await client.post("/api/auth/register", json={
        "phone": phone, "password": "Passw0rd2026", "nickname": "p", "invite_code": code})
    assert reg.status_code == 200, reg.text
    r = await client.post("/api/auth/login", json={"phone": phone, "password": "Passw0rd2026"})
    assert r.status_code == 200, r.text
