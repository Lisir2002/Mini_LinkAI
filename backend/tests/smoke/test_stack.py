"""US-005 最小异步 smoke test。

目的：在写任何业务代码之前，证明
FastAPI 异步 + asyncpg + Redis + SSE + WebSocket + Alembic 这套组合真实可用。
六项全绿才允许进入业务开发（CLAUDE.md 红线第 1 条）。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_test")
    env.setdefault("REDIS_URL", "redis://:spikepass@127.0.0.1:6379/15")
    env.setdefault("JWT_SECRET", "spike-secret-not-for-production-0123456789")
    env.setdefault("CHANNEL_CIPHER_KEY", "")
    env.setdefault("ENVIRONMENT", "development")
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return env


# ── 1. 异步路由 ────────────────────────────────────────────────
async def test_async_route_returns_200() -> None:
    from app.interfaces.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["db"] == "ok"
    assert body["data"]["redis"] == "ok"
    assert "X-Request-ID" in r.headers


# ── 2. asyncpg 真实查询 ────────────────────────────────────────
async def test_asyncpg_select_one_via_app() -> None:
    from app.interfaces.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/_smoke/db")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["value"] == 1


# ── 3. Redis 读写 ─────────────────────────────────────────────
async def test_redis_set_get_via_app() -> None:
    from app.interfaces.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/_smoke/redis")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["roundtrip"] == data["written"]


# ── 4. SSE 必须分块增量到达 ─────────────────────────────────────
# 注意：httpx 的 ASGITransport 会把整个响应体缓冲后再返回，无法观测流式。
# 因此本项必须起真实 uvicorn 走 TCP，这也是生产链路的真实形态。
async def test_sse_streams_incrementally() -> None:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.interfaces.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND_DIR, env=_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(timeout=15) as c:
            for _ in range(60):
                try:
                    if (await c.get(f"{base}/api/health")).status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.2)
            else:
                pytest.fail("uvicorn 未能在 12 秒内就绪")

            arrivals: list[float] = []
            payloads: list[str] = []
            t0 = time.monotonic()
            async with c.stream("GET", f"{base}/api/_smoke/sse") as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                async for line in r.aiter_lines():
                    if line.startswith("data:"):
                        arrivals.append(time.monotonic() - t0)
                        payloads.append(line[5:].strip())
        assert len(payloads) >= 3, f"事件数不足: {payloads}"
        assert arrivals[-1] - arrivals[0] >= 0.10, f"疑似被缓冲，到达时刻: {arrivals}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ── 5. WebSocket 双向：ping/pong + 服务端主动推送 ────────────────
def test_websocket_ping_pong_and_server_push() -> None:
    from app.interfaces.app import app

    with TestClient(app) as client:
        with client.websocket_connect("/ws/_smoke") as ws:
            pushed = ws.receive_json()          # 服务端主动推送，客户端未先发任何东西
            assert pushed["type"] == "push"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


# ── 6. Alembic 迁移可执行 ──────────────────────────────────────
def test_alembic_upgrade_head_executes() -> None:
    env = _env()
    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert down.returncode == 0, down.stderr[-1500:]
    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert up.returncode == 0, up.stderr[-1500:]

    import asyncpg

    async def _check() -> int:
        conn = await asyncpg.connect(
            host="127.0.0.1", port=5432, user="aicr",
            password="spikepass", database="ai_chatroom_test",
        )
        try:
            return await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='users'"
            )
        finally:
            await conn.close()

    assert asyncio.run(_check()) == 1
