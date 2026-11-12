"""EXT-009 Token 预估校准：EMA 收敛、样本门槛、clamp、预扣应用。"""
from __future__ import annotations

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
async def client():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=30) as c:
        yield c


async def test_ratio_stays_one_before_min_samples(spike_session):
    from app.llm.services.drift_service import apply_drift, update_drift
    from tests.factories import make_model

    mid = await make_model(spike_session)
    for _ in range(4):
        await update_drift(spike_session, mid, estimated=100, actual=200)
    row = (await spike_session.execute(text(
        "SELECT samples,ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": mid})).mappings().one()
    assert row["samples"] == 4 and float(row["ratio"]) == 1.0
    assert await apply_drift(spike_session, mid, 100) == 100


async def test_ratio_converges_and_clamps(spike_session):
    from app.llm.services.drift_service import apply_drift, update_drift
    from tests.factories import make_model

    mid = await make_model(spike_session)
    for _ in range(40):
        await update_drift(spike_session, mid, estimated=100, actual=200)
    ratio = float((await spike_session.execute(text(
        "SELECT ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": mid})).scalar_one())
    assert 1.99 <= ratio <= 2.0, f"应收敛到上界 2.0，实际 {ratio}"
    assert await apply_drift(spike_session, mid, 100) == 200
    for _ in range(60):
        await update_drift(spike_session, mid, estimated=100, actual=10)
    ratio = float((await spike_session.execute(text(
        "SELECT ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": mid})).scalar_one())
    assert ratio >= 0.5, f"不得低于下界 0.5，实际 {ratio}"


async def test_zero_estimate_skipped(spike_session):
    from app.llm.services.drift_service import update_drift
    from tests.factories import make_model

    mid = await make_model(spike_session)
    await update_drift(spike_session, mid, estimated=0, actual=50)
    n = (await spike_session.execute(text(
        "SELECT count(*) FROM model_tokenizer_drift"))).scalar_one()
    assert n == 0


async def test_no_drift_row_returns_original(spike_session):
    from app.llm.services.drift_service import apply_drift
    from tests.factories import make_model

    mid = await make_model(spike_session)
    assert await apply_drift(spike_session, mid, 123) == 123


async def test_settlement_records_drift_sample(client, spike_session, block_external_http):
    from app.core.security import create_access_token
    from tests.factories import make_channel, make_model, make_user

    uid = await make_user(spike_session, role="admin", daily_token_limit=1000000)
    tok, _ = create_access_token(uid, "admin")
    h = {"Authorization": f"Bearer {tok}"}
    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"drift-{uuid.uuid4().hex[:8]}")
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.commit()
    block_external_http.post("https://api.test/v1/chat/completions").respond(
        200, text=SSE, headers={"content-type": "text/event-stream"})
    cid = (await client.post("/api/conversations", json={"model_id": mid},
                             headers=h)).json()["data"]["id"]
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "你好"}, headers=h) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    row = (await spike_session.execute(text(
        "SELECT samples,ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": mid})).mappings().one()
    assert row["samples"] == 1 and float(row["ratio"]) == 1.0