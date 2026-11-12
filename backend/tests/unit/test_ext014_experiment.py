"""EXT-014 A/B 路由实验：分桶稳定性、比例、路由集成、回退、聚合报告。"""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

SSE = ('data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
       'data: [DONE]\n\n')


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def ctx(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_channel, make_model, make_user

    uid = await make_user(spike_session, role="admin", daily_token_limit=10000000)
    tok, _ = create_access_token(uid, "admin")
    ca = await make_channel(spike_session, name="exp-A", base_url="https://api-a.test/v1")
    cb = await make_channel(spike_session, name="exp-B", base_url="https://api-b.test/v1")
    mid = await make_model(spike_session, public_name=f"exp-{uuid.uuid4().hex[:8]}")
    for ch in (ca, cb):
        await spike_session.execute(text(
            "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
            "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.commit()
    return {"h": {"Authorization": f"Bearer {tok}"}, "uid": uid,
            "mid": mid, "ca": ca, "cb": cb}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def _mk(client, ctx, ratio=50):
    return await client.post("/api/admin/experiments",
                             json={"model_id": ctx["mid"], "channel_a": ctx["ca"],
                                   "channel_b": ctx["cb"], "ratio_a": ratio},
                             headers=ctx["h"])


async def test_create_and_validation(client, ctx):
    r = await _mk(client, ctx)
    assert r.status_code == 200, r.text
    eid = r.json()["data"]["experiment_id"]
    dup = await _mk(client, ctx)
    assert dup.status_code == 409 and dup.json()["code"] == "EXPERIMENT_RUNNING"
    same = await client.post("/api/admin/experiments",
                             json={"model_id": ctx["mid"], "channel_a": ctx["ca"],
                                   "channel_b": ctx["ca"], "ratio_a": 50},
                             headers=ctx["h"])
    assert same.status_code in (409, 422)
    bad = await client.post("/api/admin/experiments",
                            json={"model_id": ctx["mid"], "channel_a": ctx["ca"],
                                  "channel_b": ctx["cb"], "ratio_a": 0},
                            headers=ctx["h"])
    assert bad.status_code == 422
    await client.post(f"/api/admin/experiments/{eid}/end", headers=ctx["h"])


async def test_unbound_channel_rejected(client, ctx, spike_session):
    from tests.factories import make_channel

    stray = await make_channel(spike_session, name="stray")
    r = await client.post("/api/admin/experiments",
                          json={"model_id": ctx["mid"], "channel_a": stray,
                                "channel_b": ctx["cb"], "ratio_a": 50},
                          headers=ctx["h"])
    assert r.status_code == 422


async def test_bucket_stability_and_ratio(spike_session, ctx):
    from app.services.router_service import bucket_of

    for uid in (1, 42, 999, 123456):
        picks = {bucket_of(uid, 50) for _ in range(20)}
        assert len(picks) == 1, "同一用户必须恒同桶"
    a_count = sum(1 for uid in range(10000) if bucket_of(uid, 30) == "a")
    assert 2500 <= a_count <= 3500, f"30% 比例偏差过大: {a_count}/10000"


async def test_routing_uses_bucket_and_logs(client, ctx, spike_session, block_external_http):
    from app.services.router_service import bucket_of

    eid = (await _mk(client, ctx, ratio=50)).json()["data"]["experiment_id"]
    bucket = bucket_of(ctx["uid"], 50)
    hit = {"a": 0, "b": 0}

    def make_handler(tag):
        def handler(request):
            hit[tag] += 1
            return httpx.Response(200, text=SSE,
                                  headers={"content-type": "text/event-stream"})
        return handler

    block_external_http.post("https://api-a.test/v1/chat/completions").mock(
        side_effect=make_handler("a"))
    block_external_http.post("https://api-b.test/v1/chat/completions").mock(
        side_effect=make_handler("b"))
    cid = (await client.post("/api/conversations", json={"model_id": ctx["mid"]},
                             headers=ctx["h"])).json()["data"]["id"]
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "实验路由"}, headers=ctx["h"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    assert hit[bucket] == 1 and hit["a" if bucket == "b" else "b"] == 0
    row = (await spike_session.execute(text(
        "SELECT experiment_id,bucket,channel_id FROM usage_logs "
        "WHERE conversation_id=:c ORDER BY id DESC LIMIT 1"),
        {"c": cid})).mappings().one()
    assert row["experiment_id"] == eid and row["bucket"] == bucket
    assert row["channel_id"] == (ctx["ca"] if bucket == "a" else ctx["cb"])


async def test_end_experiment_falls_back(client, ctx, spike_session):
    eid = (await _mk(client, ctx)).json()["data"]["experiment_id"]
    r = await client.post(f"/api/admin/experiments/{eid}/end", headers=ctx["h"])
    assert r.status_code == 200
    from app.services.router_service import pick_experiment
    assert await pick_experiment(spike_session, ctx["mid"], ctx["uid"]) is None


async def test_disabled_bucket_channel_falls_back(client, ctx, spike_session):
    await _mk(client, ctx, ratio=99)
    from app.services.router_service import bucket_of, pick_experiment
    bucket = bucket_of(ctx["uid"], 99)
    dead = ctx["ca"] if bucket == "a" else ctx["cb"]
    await spike_session.execute(text("UPDATE channels SET status='disabled' WHERE id=:i"),
                                {"i": dead})
    await spike_session.commit()
    assert await pick_experiment(spike_session, ctx["mid"], ctx["uid"]) is None


async def test_report_aggregation(client, ctx, spike_session):
    from tests.factories import make_conversation

    await make_conversation(spike_session, user_id=ctx["uid"])
    eid = (await _mk(client, ctx)).json()["data"]["experiment_id"]
    for bucket, ch, ms, cost in (("a", ctx["ca"], 100, 0.5), ("b", ctx["cb"], 200, 0.2)):
        for i in range(3):
            call = str(uuid.uuid4())
            await spike_session.execute(text(
                "INSERT INTO usage_logs (call_id,user_id,owner_id,model_id,channel_id,"
                "model_public_name,status,frozen_tokens,quota_date,total_ms,cost,"
                "experiment_id,bucket,settled_at) "
                "VALUES (CAST(:cid AS uuid),:u,:u,:m,:ch,'exp','settled',10,CURRENT_DATE,"
                ":ms,:cost,:e,:b,now())"),
                {"cid": call, "u": ctx["uid"], "m": ctx["mid"], "ch": ch,
                 "ms": ms + i, "cost": cost, "e": eid, "b": bucket})
            mid_msg = (await spike_session.execute(text(
                "INSERT INTO messages (scope,conversation_id,role,content,usage_log_id) "
                "SELECT 'dm',c.id,'assistant','x',ul.id FROM conversations c, usage_logs ul "
                "WHERE ul.call_id=CAST(:cid AS uuid) LIMIT 1 RETURNING id"),
                {"cid": call})).scalar_one_or_none()
            if mid_msg and i == 0:
                await spike_session.execute(text(
                    "INSERT INTO message_feedbacks (message_id,user_id,rating) "
                    "VALUES (:m,:u,:r)"),
                    {"m": mid_msg, "u": ctx["uid"], "r": "up" if bucket == "b" else "down"})
    await spike_session.commit()
    r = await client.get(f"/api/admin/experiments/{eid}/report", headers=ctx["h"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    by = {b["bucket"]: b for b in d["buckets"]}
    assert by["a"]["calls"] == 3 and by["b"]["calls"] == 3
    assert by["a"]["avg_total_ms"] == 101 and by["b"]["avg_total_ms"] == 201
    assert abs(by["a"]["cost"] - 1.5) < 1e-6 and abs(by["b"]["cost"] - 0.6) < 1e-6
    assert by["a"]["down"] == 1 and by["b"]["up"] == 1
    assert d["recommendation"], "必须给出切换建议文案"


async def test_member_forbidden(client, ctx, spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    m = await make_user(spike_session)
    tok, _ = create_access_token(m, "member")
    h = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/api/admin/experiments", headers=h)).status_code == 403
    assert (await _mk(client, ctx)).status_code == 200  # admin 仍可建（清理后）

async def test_admin_models_include_bindings(client, ctx):
    r = await client.get("/api/admin/models", headers=ctx["h"])
    assert r.status_code == 200
    m = next(x for x in r.json()["data"]["items"] if x["id"] == ctx["mid"])
    assert {c["channel_id"] for c in m["channels"]} == {ctx["ca"], ctx["cb"]}
    assert all("channel_name" in c and "upstream_model" in c for c in m["channels"])
