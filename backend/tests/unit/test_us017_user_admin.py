"""US-017 收尾：用户管理 API（封禁/解封/重置密码）+ 审计事件。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def actors(spike_session):
    from app.core.security import create_access_token, hash_password
    from tests.factories import make_user

    admin = await make_user(spike_session, role="admin", nickname="管理员")
    victim = await make_user(spike_session, nickname="被封者", email="victim@example.com",
                             password_hash=hash_password("VictimPass2026"))
    ta, _ = create_access_token(admin, "admin")
    tv, _ = create_access_token(victim, "member")
    return {"admin": admin, "victim": victim,
            "h_admin": {"Authorization": f"Bearer {ta}"},
            "h_victim": {"Authorization": f"Bearer {tv}"}}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _audit(spike_session, action):
    return (await spike_session.execute(text(
        "SELECT actor_id,target_id,detail FROM audit_logs WHERE action=:a ORDER BY id DESC"),
        {"a": action})).mappings().all()


async def test_ban_unban_with_audit(client, spike_session, actors):
    v = actors["victim"]
    r = await client.post(f"/api/admin/users/{v}/ban",
                          json={"banned": True, "reason": "刷屏"}, headers=actors["h_admin"])
    assert r.status_code == 200, r.text
    status = (await spike_session.execute(text("SELECT status FROM users WHERE id=:i"),
                                          {"i": v})).scalar_one()
    assert status == "banned"
    login = await client.post("/api/auth/login",
                              json={"email": "victim@example.com", "password": "VictimPass2026"})
    assert login.status_code == 403 and login.json()["code"] == "ACCOUNT_BANNED"
    rows = await _audit(spike_session, "user.ban")
    assert len(rows) == 1 and rows[0]["target_id"] == str(v)
    assert rows[0]["detail"].get("reason") == "刷屏"
    r = await client.post(f"/api/admin/users/{v}/ban",
                          json={"banned": False}, headers=actors["h_admin"])
    assert r.status_code == 200
    assert (await spike_session.execute(text("SELECT status FROM users WHERE id=:i"),
                                        {"i": v})).scalar_one() == "active"
    assert len(await _audit(spike_session, "user.unban")) == 1


async def test_cannot_ban_self(client, actors):
    r = await client.post(f"/api/admin/users/{actors['admin']}/ban",
                          json={"banned": True}, headers=actors["h_admin"])
    assert r.status_code == 409


async def test_reset_password_flow(client, spike_session, actors):
    v = actors["victim"]
    r = await client.post(f"/api/admin/users/{v}/reset-password", headers=actors["h_admin"])
    assert r.status_code == 200, r.text
    temp = r.json()["data"]["temp_password"]
    assert len(temp) >= 8
    row = (await spike_session.execute(text(
        "SELECT must_change_password FROM users WHERE id=:i"), {"i": v})).mappings().one()
    assert row["must_change_password"] is True
    me = await client.get("/api/auth/me", headers=actors["h_victim"])
    assert me.status_code == 401, "重置后旧 token 必须全部失效"
    login = await client.post("/api/auth/login",
                              json={"email": "victim@example.com", "password": temp})
    assert login.status_code == 200, login.text
    rows = await _audit(spike_session, "user.reset_password")
    assert len(rows) == 1
    assert temp not in str(rows[0]["detail"]), "审计 detail 不得含临时密码"


async def test_non_admin_forbidden(client, actors):
    v = actors["victim"]
    h = actors["h_victim"]
    assert (await client.get("/api/admin/users", headers=h)).status_code == 403
    assert (await client.post(f"/api/admin/users/{v}/ban",
                              json={"banned": True}, headers=h)).status_code == 403
    assert (await client.post(f"/api/admin/users/{v}/reset-password",
                              headers=h)).status_code == 403


async def test_user_list_and_search(client, actors):
    r = await client.get("/api/admin/users", headers=actors["h_admin"])
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 2
    r2 = await client.get("/api/admin/users", params={"q": "被封者"},
                          headers=actors["h_admin"])
    assert len(r2.json()["data"]["items"]) == 1

async def test_login_immediately_after_password_change(client, spike_session):
    """改密后同一秒内重新登录，新 token 不得被误吊销。"""
    from app.core.security import hash_password
    from tests.factories import make_user

    await make_user(spike_session, email="fast@example.com",
                    password_hash=hash_password("OldPass2026x"), nickname="快手")
    r1 = await client.post("/api/auth/login",
                           json={"email": "fast@example.com", "password": "OldPass2026x"})
    assert r1.status_code == 200
    tok1 = r1.json()["data"]["token"]
    ch = await client.post("/api/auth/password",
                           json={"old_password": "OldPass2026x", "new_password": "NewPass2026x"},
                           headers={"Authorization": f"Bearer {tok1}"})
    assert ch.status_code == 200
    r2 = await client.post("/api/auth/login",
                           json={"email": "fast@example.com", "password": "NewPass2026x"})
    assert r2.status_code == 200
    tok2 = r2.json()["data"]["token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok2}"})
    assert me.status_code == 200, "改密后立即登录的新 token 必须可用"


async def test_successful_logins_do_not_consume_fail_budget(client, spike_session):
    from app.core.security import hash_password
    from tests.factories import make_user

    await make_user(spike_session, email="many@example.com",
                    password_hash=hash_password("Pass2026xyz"), nickname="多次")
    for i in range(6):
        r = await client.post("/api/auth/login",
                              json={"email": "many@example.com", "password": "Pass2026xyz"})
        assert r.status_code == 200, f"第 {i+1} 次成功登录不应被限流"


async def test_five_failures_then_lock(client, spike_session):
    from app.core.security import hash_password
    from tests.factories import make_user

    await make_user(spike_session, email="brute@example.com",
                    password_hash=hash_password("Pass2026xyz"), nickname="爆破")
    for _ in range(5):
        r = await client.post("/api/auth/login",
                              json={"email": "brute@example.com", "password": "wrong-pass"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login",
                          json={"email": "brute@example.com", "password": "Pass2026xyz"})
    assert r.status_code == 423, "5 次失败后即使密码正确也应锁定"


async def test_reset_revokes_all_tokens_including_same_second(
        client, spike_session, actors, monkeypatch):
    """管理员重置必须吊销全部会话：ts=重置时刻+1s，同秒签发的旧 token 也失效。"""
    import json as _json
    import time

    from app.redis_client import get_redis

    monkeypatch.setattr(time, "time", lambda: 1_000_000_000.0)
    r = await client.post(f"/api/admin/users/{actors['victim']}/reset-password",
                          headers=actors["h_admin"])
    assert r.status_code == 200
    raw = await get_redis().get(f"pwd_changed:{actors['victim']}")
    assert _json.loads(raw)["ts"] == 1_000_000_001
