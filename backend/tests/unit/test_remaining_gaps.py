"""补齐 US-031/032/033/040 的剩余分支。"""
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


async def _channel(client, admin, name):
    r = await client.post("/api/admin/channels", headers=admin["h"], json={
        "name": name, "type": "openai_compatible",
        "base_url": "https://api.test/v1", "api_key": "sk-x-abcd1234"})
    return r.json()["data"]["id"]


# ── US-031 ────────────────────────────────────────────────
async def test_sync_models_upstream_404_returns_clear_error(client, admin, block_external_http):
    cid = await _channel(client, admin, "sync404")
    block_external_http.get("https://api.test/v1/models").respond(404, json={})
    r = await client.post(f"/api/admin/channels/{cid}/sync-models", headers=admin["h"])
    assert r.status_code == 502
    assert r.json()["code"] == "UPSTREAM_ERROR"
    assert "拉取模型列表失败" in r.json()["message"]


async def test_sync_models_empty_list_is_ok(client, admin, block_external_http):
    cid = await _channel(client, admin, "syncempty")
    block_external_http.get("https://api.test/v1/models").respond(200, json={"data": []})
    r = await client.post(f"/api/admin/channels/{cid}/sync-models", headers=admin["h"])
    assert r.status_code == 200 and r.json()["data"]["models"] == []


# ── US-032 ────────────────────────────────────────────────
async def test_reenable_auto_disabled_requires_confirm(client, admin, spike_session):
    cid = await _channel(client, admin, "autodis")
    await spike_session.execute(
        text("UPDATE channels SET status='auto_disabled', fail_count=3 WHERE id=:i"), {"i": cid})
    await spike_session.commit()
    no = await client.post(f"/api/admin/channels/{cid}/toggle",
                           json={"enabled": True}, headers=admin["h"])
    assert no.status_code == 409 and no.json()["code"] == "CONFIRM_REQUIRED"
    yes = await client.post(f"/api/admin/channels/{cid}/toggle",
                            json={"enabled": True, "confirm": True}, headers=admin["h"])
    assert yes.status_code == 200
    row = (await spike_session.execute(
        text("SELECT status,fail_count FROM channels WHERE id=:i"), {"i": cid})).mappings().one()
    assert row["status"] == "enabled" and row["fail_count"] == 0


# ── US-033 ────────────────────────────────────────────────
async def test_model_patch_version_lock_and_delete_keeps_snapshot(client, admin, spike_session):
    m = (await client.post("/api/admin/models", headers=admin["h"],
                           json={"public_name": "patchme", "display_name": "P"})).json()["data"]
    ok = await client.patch(f"/api/admin/models/{m['id']}", headers=admin["h"],
                            json={"display_name": "新名", "version": m["version"]})
    assert ok.status_code == 200
    stale = await client.patch(f"/api/admin/models/{m['id']}", headers=admin["h"],
                               json={"display_name": "再改", "version": m["version"]})
    assert stale.status_code == 409 and stale.json()["code"] == "CONFLICT_STALE"

    await spike_session.execute(text(
        "INSERT INTO usage_logs (call_id,user_id,owner_id,model_id,model_public_name,"
        "model_display_name,status,frozen_tokens,quota_date) "
        "VALUES (gen_random_uuid(),:u,:u,:m,'patchme','P','settled',10,current_date)"),
        {"u": admin["id"], "m": m["id"]})
    await spike_session.commit()
    d = await client.delete(f"/api/admin/models/{m['id']}", headers=admin["h"])
    assert d.status_code == 200
    snap = (await spike_session.execute(text(
        "SELECT model_id, model_public_name, model_display_name FROM usage_logs "
        "WHERE model_public_name='patchme'"))).mappings().one()
    assert snap["model_id"] is None, "外键应置 NULL"
    assert snap["model_public_name"] == "patchme" and snap["model_display_name"] == "P", \
        "快照必须保留，历史统计才可归维度"


# ── US-040 ────────────────────────────────────────────────
async def test_stale_pending_is_refunded(spike_session):
    from app.stats.tasks.pending_refund import refund_stale_pending
    from tests.factories import make_user

    uid = await make_user(spike_session)
    await spike_session.execute(text(
        "INSERT INTO daily_usage (quota_date,owner_id,room_id,total_tokens,ai_call_count) "
        "VALUES (current_date,:u,NULL,500,1)"), {"u": uid})
    await spike_session.execute(text(
        "INSERT INTO usage_logs (call_id,user_id,owner_id,status,frozen_tokens,quota_date,"
        "created_at) VALUES (gen_random_uuid(),:u,:u,'pending',500,current_date,"
        "now()-interval '11 minutes')"), {"u": uid})
    await spike_session.commit()
    n = await refund_stale_pending(spike_session)
    assert n >= 1
    left = (await spike_session.execute(text(
        "SELECT count(*) FROM usage_logs WHERE owner_id=:u AND status='pending'"),
        {"u": uid})).scalar_one()
    assert left == 0
    used = (await spike_session.execute(text(
        "SELECT total_tokens FROM daily_usage WHERE owner_id=:u AND room_id IS NULL"),
        {"u": uid})).scalar_one()
    assert used == 0, "悬挂预扣必须被退回"


async def test_recent_pending_is_not_touched(spike_session):
    from app.stats.tasks.pending_refund import refund_stale_pending
    from tests.factories import make_user

    uid = await make_user(spike_session)
    await spike_session.execute(text(
        "INSERT INTO usage_logs (call_id,user_id,owner_id,status,frozen_tokens,quota_date,"
        "created_at) VALUES (gen_random_uuid(),:u,:u,'pending',500,current_date,"
        "now()-interval '9 minutes')"), {"u": uid})
    await spike_session.commit()
    await refund_stale_pending(spike_session)
    st = (await spike_session.execute(text(
        "SELECT status FROM usage_logs WHERE owner_id=:u"), {"u": uid})).scalar_one()
    assert st == "pending", "9 分钟前的不得误退"


def test_scheduler_registers_jobs():
    from app.stats.scheduler import build_scheduler

    sch = build_scheduler()
    ids = {j.id for j in sch.get_jobs()}
    assert "pending_refund" in ids and "channel_health" in ids
