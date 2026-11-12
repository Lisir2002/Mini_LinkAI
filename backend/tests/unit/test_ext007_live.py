"""EXT-007 实时看板：指标采集、P95、SSE 推送与权限。"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

SSE = ('data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
       'data: [DONE]\n\n')


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def headers(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    admin = await make_user(spike_session, role="admin", daily_token_limit=1000000)
    member = await make_user(spike_session)
    ta, _ = create_access_token(admin, "admin")
    tm, _ = create_access_token(member, "member")
    return {"admin": {"Authorization": f"Bearer {ta}"},
            "member": {"Authorization": f"Bearer {tm}"}}


@pytest.fixture
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _first_tick(client, headers, interval=1):
    async with client.stream("GET", "/api/admin/stats/live",
                             params={"interval": interval, "ticks": 2}, headers=headers) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                return json.loads(line[5:])
    raise AssertionError("未收到任何 tick 事件")


def test_p95_calculation():
    from app.stats.services.live_metrics import p95

    assert p95([]) is None
    assert p95([100]) == 100
    assert p95(list(range(1, 101))) == 95


async def test_live_requires_admin(client, headers):
    r = await client.get("/api/admin/stats/live", headers=headers["member"])
    assert r.status_code == 403


async def test_live_tick_shape(client, headers):
    tick = await _first_tick(client, headers["admin"])
    assert set(tick) >= {"online", "calls_per_min", "channels", "budget", "ts"}
    assert isinstance(tick["channels"], list)
    assert set(tick["budget"]) >= {"monthly_cost", "monthly_budget", "last_hour_cost"}


async def test_metrics_recorded_after_ai_call(client, headers, spike_session,
                                              block_external_http):
    from tests.factories import make_channel, make_model

    ch = await make_channel(spike_session, name="live-ch", base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"live-{uuid.uuid4().hex[:8]}",
                           price_input=10, price_output=20)
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.commit()
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    cid = (await client.post("/api/conversations", json={"model_id": mid},
                             headers=headers["admin"])).json()["data"]["id"]
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "你好"}, headers=headers["admin"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    tick = await _first_tick(client, headers["admin"])
    assert tick["calls_per_min"] >= 1, "AI 调用必须计入分钟计数"
    assert tick["online"] >= 1, "活跃用户必须计入在线数"
    chan = next(c for c in tick["channels"] if c["id"] == ch)
    assert chan["latency_p95"] is not None and chan["latency_p95"] >= 0
    assert tick["budget"]["monthly_cost"] > 0, "结算成本必须计入月预算"


async def test_active_touch_updates_online(client, headers):
    from app.stats.services.live_metrics import touch_active

    await touch_active(424242)
    tick = await _first_tick(client, headers["admin"])
    assert tick["online"] >= 1