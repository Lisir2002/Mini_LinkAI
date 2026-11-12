"""US-024：健康检查需反映真实依赖状态与耗时。"""
from __future__ import annotations

import httpx


async def test_health_reports_dependencies_and_latency():
    from app.interfaces.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["db"] == "ok" and d["redis"] == "ok"
    assert "environment" in d and "version" in d
    assert isinstance(d["db_ms"], int) and isinstance(d["redis_ms"], int)


async def test_health_503_names_failed_dependency(monkeypatch):
    from app.interfaces import app as main

    async def boom() -> None:
        raise OSError("redis down")

    monkeypatch.setattr(main, "_probe_redis_health", boom)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="http://t") as c:
        r = await c.get("/api/health")
    assert r.status_code == 503
    assert r.json()["detail"]["failed"] == "redis"
