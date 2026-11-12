"""FR-004 私聊 WS：真实 uvicorn 双客户端，DM/好友事件推送、心跳、鉴权。"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import websockets

BACKEND = Path(__file__).resolve().parents[2]
PORT = 8098
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def server():
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike"
    env["REDIS_URL"] = "redis://:spikepass@127.0.0.1:6379/15"
    env["JWT_SECRET"] = "spike-secret-not-for-production-0123456789"
    env["ENVIRONMENT"] = "development"
    env["PYTHONPATH"] = str(BACKEND)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(PORT)],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                break
        except Exception:        # noqa: BLE001
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("uvicorn 未能在 30s 内启动")
    yield proc
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(autouse=True)
async def _clean(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    yield


@pytest.fixture
async def actors(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    alice = await make_user(spike_session, nickname="Alice")
    bob = await make_user(spike_session, nickname="Bob")
    ta, _ = create_access_token(alice, "member")
    tb, _ = create_access_token(bob, "member")
    return {"alice": alice, "bob": bob, "ta": ta, "tb": tb,
            "ha": {"Authorization": f"Bearer {ta}"},
            "hb": {"Authorization": f"Bearer {tb}"}}


async def _befriend(actors):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(BASE + "/api/friends/requests",
                         json={"user_id": actors["bob"]}, headers=actors["ha"])
        rid = r.json()["data"]["request_id"]
        await c.post(BASE + f"/api/friends/requests/{rid}/accept", headers=actors["hb"])


async def _recv_type(ws, typ, timeout=6.0):
    while True:
        d = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if d.get("type") == typ:
            return d


async def test_dm_push_to_recipient_only(server, actors):
    await _befriend(actors)
    async with websockets.connect(f"{WS}/ws/dm?token={actors['ta']}") as wa, \
               websockets.connect(f"{WS}/ws/dm?token={actors['tb']}") as wb:
        assert json.loads(await wa.recv())["type"] == "hello"
        assert json.loads(await wb.recv())["type"] == "hello"
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(BASE + f"/api/dm/{actors['bob']}/messages",
                             json={"content": "实时私聊"}, headers=actors["ha"])
            assert r.status_code == 200
        d = await _recv_type(wb, "dm")
        assert d["message"]["content"] == "实时私聊"
        assert d["message"]["sender_id"] == actors["alice"]
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(wa.recv(), timeout=1.5)  # 发送者不收自己的推送


async def test_friend_request_and_accepted_push(server, actors):
    async with websockets.connect(f"{WS}/ws/dm?token={actors['ta']}") as wa, \
               websockets.connect(f"{WS}/ws/dm?token={actors['tb']}") as wb:
        await wa.recv()
        await wb.recv()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(BASE + "/api/friends/requests",
                             json={"user_id": actors["alice"]}, headers=actors["hb"])
            rid = r.json()["data"]["request_id"]
            req = await _recv_type(wa, "friend_request")
            assert req["nickname"] == "Bob" and req["request_id"] == rid
            await c.post(BASE + f"/api/friends/requests/{rid}/accept", headers=actors["ha"])
        acc = await _recv_type(wb, "friend_accepted")
        assert acc["nickname"] == "Alice"


async def test_read_receipt_push(server, actors):
    await _befriend(actors)
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(BASE + f"/api/dm/{actors['bob']}/messages",
                     json={"content": "待读"}, headers=actors["ha"])
    async with websockets.connect(f"{WS}/ws/dm?token={actors['ta']}") as wa:
        await wa.recv()
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(BASE + f"/api/dm/{actors['alice']}/read", headers=actors["hb"])
        d = await _recv_type(wa, "dm_read")
        assert d["reader_id"] == actors["bob"] and d["count"] == 1


async def test_heartbeat_and_bad_token(server, actors):
    async with websockets.connect(f"{WS}/ws/dm?token={actors['ta']}") as ws:
        await ws.recv()
        await ws.send("ping")
        d = await _recv_type(ws, "pong")
        assert d["type"] == "pong"
    async with websockets.connect(f"{WS}/ws/dm?token=bad.token") as ws:
        with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
            await asyncio.wait_for(ws.recv(), timeout=5)
        assert ei.value.rcvd.code == 4401

async def test_ws_rejects_before_password_change(server, spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    uid = await make_user(spike_session, must_change_password=True)
    tok, _ = create_access_token(uid, "member")
    async with websockets.connect(f"{WS}/ws/dm?token={tok}") as ws:
        with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
            await asyncio.wait_for(ws.recv(), timeout=5)
        assert ei.value.rcvd.code == 4403, "未改初始密码不得建立 WS"
