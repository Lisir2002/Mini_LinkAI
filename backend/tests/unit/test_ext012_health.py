"""EXT-012 渠道健康：采样落库、7 天清理、熔断/失败率告警与去重、健康接口。"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

WEBHOOK = "https://hooks.test/alert"


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def admin_h(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, role="admin")
    tok, _ = create_access_token(uid, "admin")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _set_webhook(spike_session, enabled=True):
    import json
    await spike_session.execute(text(
        "INSERT INTO settings (key,value,version) VALUES ('alert_webhook',CAST(:v AS jsonb),1) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"),
        {"v": json.dumps({"url": WEBHOOK, "type": "dingtalk", "enabled": enabled})})
    await spike_session.commit()
    from app.core.redis_client import get_redis
    await get_redis().delete("settings:alert_webhook")


async def test_sample_writes_row(spike_session, block_external_http):
    from app.stats.services.health_service import sample_all
    from tests.factories import make_channel

    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, json={"choices": [{"message": {"content": "pong"}}]})
    n = await sample_all(spike_session)
    assert n == 1
    row = (await spike_session.execute(text(
        "SELECT success,latency_ms FROM channel_health_samples WHERE channel_id=:c"),
        {"c": ch})).mappings().one()
    assert row["success"] is True and row["latency_ms"] >= 0


async def test_cleanup_keeps_7_days(spike_session):
    from app.stats.services.health_service import cleanup_samples
    from tests.factories import make_channel

    ch = await make_channel(spike_session)
    await spike_session.execute(text(
        "INSERT INTO channel_health_samples (channel_id,success,sampled_at) VALUES "
        "(:c,true,now()-interval '8 days'),(:c,false,now()-interval '1 hour')"), {"c": ch})
    await spike_session.commit()
    removed = await cleanup_samples(spike_session)
    assert removed == 1
    left = (await spike_session.execute(text(
        "SELECT count(*) FROM channel_health_samples"))).scalar_one()
    assert left == 1


async def test_disable_alert_with_dedupe(spike_session, block_external_http):
    from app.llm.services.router_service import record_failure
    from tests.factories import make_channel

    ch = await make_channel(spike_session)
    await _set_webhook(spike_session)
    hook = block_external_http.post(WEBHOOK).respond(200, json={"errcode": 0})
    for _ in range(3):
        await record_failure(spike_session, ch, kind="timeout")
    status = (await spike_session.execute(text("SELECT status FROM channels WHERE id=:i"),
                                          {"i": ch})).scalar_one()
    assert status == "auto_disabled"
    assert hook.call_count == 1, "熔断必须触发一次告警"
    await record_failure(spike_session, ch, kind="timeout")
    assert hook.call_count == 1, "10 分钟去重窗口内不得重复告警"


async def test_no_alert_without_config(spike_session, block_external_http):
    from app.llm.services.router_service import record_failure
    from tests.factories import make_channel

    ch = await make_channel(spike_session)
    hook = block_external_http.post(WEBHOOK).respond(200, json={})
    for _ in range(3):
        await record_failure(spike_session, ch, kind="timeout")
    assert hook.call_count == 0


async def test_failure_rate_alert(spike_session, block_external_http):
    from app.stats.services.health_service import check_failure_rates
    from tests.factories import make_channel

    ch = await make_channel(spike_session)
    await _set_webhook(spike_session)
    await spike_session.execute(text(
        "INSERT INTO channel_health_samples (channel_id,success,sampled_at) "
        "SELECT :c, g <= 1, now()-interval '2 minutes' FROM generate_series(1,5) g"),
        {"c": ch})
    await spike_session.commit()
    hook = block_external_http.post(WEBHOOK).respond(200, json={})
    fired = await check_failure_rates(spike_session)
    assert fired == 1 and hook.call_count == 1, "5 样本 4 失败（80%）必须告警"


async def test_health_api(client, spike_session, admin_h):
    from tests.factories import make_channel

    ch = await make_channel(spike_session)
    await spike_session.execute(text(
        "INSERT INTO channel_health_samples (channel_id,success,latency_ms) "
        "VALUES (:c,true,42),(:c,false,NULL)"), {"c": ch})
    await spike_session.commit()
    r = await client.get(f"/api/admin/channels/{ch}/health", headers=admin_h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert len(d["samples"]) == 2
    assert d["fail_rate"] == 0.5
    assert (await client.get(f"/api/admin/channels/{ch}/health")).status_code == 401


async def test_webhook_setting_validation(client, admin_h):
    ok = await client.put("/api/admin/settings/alert_webhook",
                          json={"value": {"url": WEBHOOK, "type": "feishu", "enabled": True},
                                "version": 0}, headers=admin_h)
    assert ok.status_code == 200, ok.text
    bad = await client.put("/api/admin/settings/alert_webhook",
                           json={"value": {"url": "not-a-url", "type": "feishu"},
                                 "version": 1}, headers=admin_h)
    assert bad.status_code == 422

async def test_alert_test_send(client, spike_session, admin_h, block_external_http):
    await _set_webhook(spike_session)
    hook = block_external_http.post(WEBHOOK).respond(200, json={})
    r = await client.post("/api/admin/alerts/test", headers=admin_h)
    assert r.status_code == 200, r.text
    assert hook.call_count == 1
    r2 = await client.post("/api/admin/alerts/test", headers=admin_h)
    assert r2.status_code == 200 and hook.call_count == 2, "测试发送不受去重限制"
