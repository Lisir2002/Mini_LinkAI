"""US-035 邀请码管理接口 / US-036 系统设置读写。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture
async def admin(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, role="admin")
    tok, _ = create_access_token(uid, "admin")
    return {"id": uid, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def test_batch_generate_unique_codes_and_masked_list(client, admin):
    r = await client.post("/api/admin/invite-codes", headers=admin["h"],
                          json={"count": 5, "max_uses": 2, "note": "首批"})
    assert r.status_code == 200, r.text
    codes = r.json()["data"]["codes"]
    assert len(codes) == 5 and len(set(codes)) == 5
    lst = (await client.get("/api/admin/invite-codes", headers=admin["h"])).json()["data"]["items"]
    assert all(c["code_masked"] != c.get("code") for c in lst if "code" in c)
    assert all("*" in c["code_masked"] for c in lst)


async def test_generate_count_out_of_range_rejected(client, admin):
    for n in (0, 101):
        r = await client.post("/api/admin/invite-codes", headers=admin["h"], json={"count": n})
        assert r.status_code == 422


async def test_revoke_code_blocks_registration(client, admin, spike_session):
    code = (await client.post("/api/admin/invite-codes", headers=admin["h"],
                              json={"count": 1})).json()["data"]["codes"][0]
    cid = (await spike_session.execute(
        text("SELECT id FROM invite_codes WHERE code=:c"), {"c": code})).scalar_one()
    d = await client.delete(f"/api/admin/invite-codes/{cid}", headers=admin["h"])
    assert d.status_code == 200
    exp = (await spike_session.execute(
        text("SELECT expires_at FROM invite_codes WHERE id=:i"), {"i": cid})).scalar_one()
    assert exp is not None, "作废应置过期时间而非物理删除"
    reg = await client.post("/api/auth/register", json={
        "email": "revoked-test@example.com", "password": "Passw0rd2026",
        "nickname": "x", "invite_code": code})
    assert reg.status_code == 422


async def test_settings_put_updates_and_validates(client, admin, spike_session):
    cur = (await client.get("/api/admin/settings", headers=admin["h"])).json()["data"]["items"]
    quota = next((s for s in cur if s["key"] == "quota"), None)
    ver = quota["version"] if quota else 0
    r = await client.put("/api/admin/settings/quota", headers=admin["h"],
                         json={"value": {"daily_msg_limit": 80}, "version": ver})
    assert r.status_code == 200, r.text
    stale = await client.put("/api/admin/settings/quota", headers=admin["h"],
                             json={"value": {"daily_msg_limit": 90}, "version": ver})
    assert stale.status_code == 409 and stale.json()["code"] == "CONFLICT_STALE"
    bad = await client.put("/api/admin/settings/registration", headers=admin["h"],
                           json={"value": {"mode": "nonsense"}, "version": 0})
    assert bad.status_code == 422
