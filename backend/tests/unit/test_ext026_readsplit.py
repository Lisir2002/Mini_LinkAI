"""EXT-026 读写分离与统计预聚合：副本路由、故障回退、预计算一致性。"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import text

SPIKE = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike"


@pytest.fixture(autouse=True)
async def _clean(spike_session, monkeypatch):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    from app.core import db
    from app.core.config import settings
    monkeypatch.setattr(settings, "READ_REPLICA_URL", "")
    db.reset_read_factory()
    yield
    db.reset_read_factory()


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


async def test_read_uses_replica_when_configured(spike_session, monkeypatch):
    from app.core import db
    from app.core.config import settings

    monkeypatch.setattr(settings, "READ_REPLICA_URL", SPIKE)

    async def q(s):
        return (await s.execute(text("SELECT 1"))).scalar_one()

    assert await db.run_read(q) == 1
    assert db.read_factory() is not None, "配置副本后必须建立独立只读引擎"


async def test_read_fallback_when_replica_down(spike_session, monkeypatch):
    from app.core import db
    from app.core.config import settings

    monkeypatch.setattr(settings, "READ_REPLICA_URL",
                        "postgresql+asyncpg://aicr:spikepass@127.0.0.1:59999/nodb")

    async def q(s):
        return (await s.execute(text("SELECT 42"))).scalar_one()

    assert await db.run_read(q) == 42, "副本不可达必须自动回退主库"


async def test_no_replica_uses_primary(spike_session):
    from app.core import db

    async def q(s):
        return (await s.execute(text("SELECT 7"))).scalar_one()

    assert await db.run_read(q) == 7
    assert db.read_factory() is None


async def _seed_usage(spike_session, day: date, user_id: int, n: int, tokens: int, cost: float):
    for _ in range(n):
        await spike_session.execute(text(
            "INSERT INTO usage_logs (call_id,user_id,owner_id,model_public_name,status,"
            "frozen_tokens,quota_date,total_tokens,cost,settled_at) "
            "VALUES (CAST(:cid AS uuid),:u,:u,'m','settled',10,:d,:t,:c,now())"),
            {"cid": str(uuid.uuid4()), "u": user_id, "d": day, "t": tokens, "c": cost})
    await spike_session.commit()


async def test_precompute_matches_realtime(spike_session):
    from app.stats.tasks.stats_precompute import precompute_stats
    from tests.factories import make_user

    u1 = await make_user(spike_session)
    u2 = await make_user(spike_session)
    today = date.today()
    await _seed_usage(spike_session, today, u1, 3, 100, 0.5)
    await _seed_usage(spike_session, today, u2, 2, 200, 0.25)
    await _seed_usage(spike_session, today - timedelta(days=1), u1, 1, 50, 0.1)
    await precompute_stats(spike_session)
    rows = (await spike_session.execute(text(
        "SELECT stat_date,ai_calls,total_tokens,cost,active_users FROM stats_daily "
        "ORDER BY stat_date"))).mappings().all()
    assert len(rows) == 2
    t = rows[-1]
    assert t["ai_calls"] == 5 and t["total_tokens"] == 700
    assert abs(float(t["cost"]) - 2.0) < 1e-6 and t["active_users"] == 2
    y = rows[0]
    assert y["ai_calls"] == 1 and y["active_users"] == 1
    direct = (await spike_session.execute(text(
        "SELECT count(*) AS n, sum(total_tokens) AS t FROM usage_logs "
        "WHERE status='settled' AND quota_date=:d"), {"d": today})).mappings().one()
    assert int(direct["n"]) == t["ai_calls"] and int(direct["t"]) == t["total_tokens"]


async def test_precompute_idempotent(spike_session):
    from app.stats.tasks.stats_precompute import precompute_stats
    from tests.factories import make_user

    u = await make_user(spike_session)
    await _seed_usage(spike_session, date.today(), u, 2, 100, 0.5)
    await precompute_stats(spike_session)
    await precompute_stats(spike_session)
    row = (await spike_session.execute(text(
        "SELECT ai_calls,total_tokens FROM stats_daily WHERE stat_date=CURRENT_DATE")
        )).mappings().one()
    assert row["ai_calls"] == 2 and row["total_tokens"] == 200


async def test_overview_and_recompute_api(client, spike_session, admin_h):
    from tests.factories import make_user

    u = await make_user(spike_session)
    await _seed_usage(spike_session, date.today(), u, 2, 100, 0.5)
    r = await client.post("/api/admin/stats/recompute", headers=admin_h)
    assert r.status_code == 200, r.text
    ov = await client.get("/api/admin/stats/overview", params={"days": 7}, headers=admin_h)
    assert ov.status_code == 200
    items = ov.json()["data"]["items"]
    assert len(items) == 1 and items[0]["ai_calls"] == 2
    assert items[0]["total_tokens"] == 200


async def test_stats_member_forbidden(client, spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    m = await make_user(spike_session)
    tok, _ = create_access_token(m, "member")
    h = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/api/admin/stats/overview", headers=h)).status_code == 403
    assert (await client.post("/api/admin/stats/recompute", headers=h)).status_code == 403


async def test_feedback_stats_via_read_path(client, spike_session, admin_h, monkeypatch):
    """副本配置下满意度统计仍正确（走 run_read）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "READ_REPLICA_URL", SPIKE)
    r = await client.get("/api/admin/stats/feedback", headers=admin_h)
    assert r.status_code == 200
    assert r.json()["data"]["total"]["up"] == 0