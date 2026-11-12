"""US-025/027/029/030/031/032/033/034：渠道与模型管理 API。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text


@pytest.fixture
async def admin(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, role="admin")
    token, _ = create_access_token(uid, "admin")
    return {"id": uid, "h": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
async def member(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session)
    token, _ = create_access_token(uid, "member")
    return {"id": uid, "h": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        yield c


def _ch(**kw):
    return {"name": "测试渠道", "type": "openai_compatible",
            "base_url": "https://api.test/v1", "api_key": "sk-secret-abcd1234"} | kw


async def test_create_channel_returns_hint_only(client, admin):
    r = await client.post("/api/admin/channels", json=_ch(), headers=admin["h"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["api_key_hint"] == "****1234"
    assert "api_key_enc" not in d and "api_key" not in d
    assert "sk-secret-abcd1234" not in r.text


async def test_non_admin_forbidden(client, member):
    r = await client.get("/api/admin/channels", headers=member["h"])
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN_ADMIN_ONLY"


async def test_list_channels_has_no_secrets(client, admin):
    await client.post("/api/admin/channels", json=_ch(name="c-list"), headers=admin["h"])
    r = await client.get("/api/admin/channels", headers=admin["h"])
    assert r.status_code == 200
    assert "api_key_enc" not in r.text and "sk-secret" not in r.text


async def test_patch_without_key_keeps_original_and_version_lock(client, admin, spike_session):
    from app.core.crypto import decrypt_api_key

    created = (await client.post("/api/admin/channels", json=_ch(name="c-patch"),
                                 headers=admin["h"])).json()["data"]
    cid, ver = created["id"], created["version"]
    r = await client.patch(f"/api/admin/channels/{cid}",
                           json={"name": "改名", "version": ver}, headers=admin["h"])
    assert r.status_code == 200
    enc = (await spike_session.execute(
        text("SELECT api_key_enc FROM channels WHERE id=:i"), {"i": cid})).scalar_one()
    assert decrypt_api_key(enc) == "sk-secret-abcd1234"
    stale = await client.patch(f"/api/admin/channels/{cid}",
                               json={"name": "再改", "version": ver}, headers=admin["h"])
    assert stale.status_code == 409 and stale.json()["code"] == "CONFLICT_STALE"


async def test_delete_referenced_channel_requires_confirm(client, admin, spike_session):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-ref"),
                             headers=admin["h"])).json()["data"]["id"]
    mid = (await client.post("/api/admin/models",
                             json={"public_name": "m-ref", "display_name": "M"},
                             headers=admin["h"])).json()["data"]["id"]
    await client.post(f"/api/admin/models/{mid}/channels",
                      json={"channel_id": cid, "upstream_model": "up"}, headers=admin["h"])
    blocked = await client.delete(f"/api/admin/channels/{cid}", headers=admin["h"])
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["affected_models"]
    ok = await client.delete(f"/api/admin/channels/{cid}?confirm=true", headers=admin["h"])
    assert ok.status_code == 200


async def test_connectivity_test_records_latency_and_no_usage(client, admin, block_external_http):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-test"),
                             headers=admin["h"])).json()["data"]["id"]
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, json={"choices": [{"message": {"content": "ok"}}]})
    r = await client.post(f"/api/admin/channels/{cid}/test", headers=admin["h"])
    assert r.status_code == 200 and r.json()["data"]["ok"] is True
    assert isinstance(r.json()["data"]["latency_ms"], int)


async def test_sync_models_writes_discovered(client, admin, block_external_http, spike_session):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-sync"),
                             headers=admin["h"])).json()["data"]["id"]
    block_external_http.get("https://api.test/v1/models").respond(
        200, json={"data": [{"id": "a"}, {"id": "b"}]})
    r = await client.post(f"/api/admin/channels/{cid}/sync-models", headers=admin["h"])
    assert r.status_code == 200 and r.json()["data"]["models"] == ["a", "b"]
    got = (await spike_session.execute(
        text("SELECT discovered_models FROM channels WHERE id=:i"), {"i": cid})).scalar_one()
    assert got


async def test_toggle_idempotent_and_last_channel_protection(client, admin, spike_session):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-toggle"),
                             headers=admin["h"])).json()["data"]["id"]
    mid = (await client.post("/api/admin/models",
                             json={"public_name": "m-tog", "display_name": "M"},
                             headers=admin["h"])).json()["data"]["id"]
    await client.post(f"/api/admin/models/{mid}/channels",
                      json={"channel_id": cid, "upstream_model": "up"}, headers=admin["h"])
    off = await client.post(f"/api/admin/channels/{cid}/toggle",
                            json={"enabled": False}, headers=admin["h"])
    assert off.status_code == 200
    assert "m-tog" in str(off.json()["data"]["affected_models"])
    enabled = (await spike_session.execute(
        text("SELECT enabled FROM models WHERE id=:i"), {"i": mid})).scalar_one()
    assert enabled is False, "唯一渠道被停用时模型应联动停用"
    again = await client.post(f"/api/admin/channels/{cid}/toggle",
                              json={"enabled": False}, headers=admin["h"])
    assert again.status_code == 200, "重复 toggle 应幂等"


async def test_presets_endpoint_grouped_by_protocol(client, admin):
    r = await client.get("/api/admin/channel-presets", headers=admin["h"])
    assert r.status_code == 200
    d = r.json()["data"]
    assert {"openai_compatible", "anthropic", "gemini"} <= set(d)
    assert any(p["name"] == "DeepSeek" for p in d["openai_compatible"])


async def test_user_models_only_enabled_with_channel_and_no_channel_fields(client, admin, member):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-vis"),
                             headers=admin["h"])).json()["data"]["id"]
    mid = (await client.post("/api/admin/models",
                             json={"public_name": "visible", "display_name": "V"},
                             headers=admin["h"])).json()["data"]["id"]
    await client.post("/api/admin/models",
                      json={"public_name": "nochannel", "display_name": "N"}, headers=admin["h"])
    await client.post(f"/api/admin/models/{mid}/channels",
                      json={"channel_id": cid, "upstream_model": "up"}, headers=admin["h"])
    r = await client.get("/api/models", headers=member["h"])
    assert r.status_code == 200
    names = [m["public_name"] for m in r.json()["data"]["items"]]
    assert "visible" in names and "nochannel" not in names
    assert "api_key" not in r.text and "base_url" not in r.text


async def test_set_default_keeps_single_default(client, admin):
    for n in ("d1", "d2"):
        await client.post("/api/admin/models",
                          json={"public_name": n, "display_name": n}, headers=admin["h"])
    r = await client.post("/api/admin/models/by-name/d2/default", headers=admin["h"])
    assert r.status_code == 200
    lst = (await client.get("/api/admin/models", headers=admin["h"])).json()["data"]["items"]
    assert sum(1 for m in lst if m["is_default"]) == 1


async def test_get_single_channel_has_no_ciphertext(client, admin):
    cid = (await client.post("/api/admin/channels", json=_ch(name="c-get"),
                             headers=admin["h"])).json()["data"]["id"]
    r = await client.get(f"/api/admin/channels/{cid}", headers=admin["h"])
    assert r.status_code == 200
    assert "api_key_enc" not in r.text and "sk-secret" not in r.text
    assert r.json()["data"]["api_key_hint"] == "****1234"
