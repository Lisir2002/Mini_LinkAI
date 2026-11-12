"""EXT-024 WebSocket 房间广播：真实 uvicorn + 双客户端 + Redis pub/sub。"""
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
from cryptography.fernet import Fernet
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
PORT = 8099

FIXED_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _fixed_cipher(monkeypatch):
    """子进程与测试进程共用同一把渠道密钥，保证加密的 Key 可被子进程解密。"""
    from app.core import crypto
    monkeypatch.setenv("CHANNEL_CIPHER_KEY", FIXED_KEY)
    crypto.reset_cipher()
    yield
    crypto.reset_cipher()
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def server():
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike"
    env["REDIS_URL"] = "redis://:spikepass@127.0.0.1:6379/15"
    env["JWT_SECRET"] = "spike-secret-not-for-production-0123456789"
    env["ENVIRONMENT"] = "development"
    env["CHANNEL_CIPHER_KEY"] = FIXED_KEY
    env["PYTHONPATH"] = str(BACKEND)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.interfaces.app:app", "--host", "127.0.0.1",
         "--port", str(PORT)],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                break
        except Exception:        # noqa: BLE001 - 启动轮询
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
async def room_ctx(spike_session):
    from app.core.security import create_access_token
    from tests.factories import add_member, make_room, make_user

    a = await make_user(spike_session, nickname="成员A")
    b = await make_user(spike_session, nickname="成员B")
    outsider = await make_user(spike_session, nickname="外人")
    rid = await make_room(spike_session, owner_id=a)
    await add_member(spike_session, room_id=rid, user_id=b)
    ta, _ = create_access_token(a, "member")
    tb, _ = create_access_token(b, "member")
    tx, _ = create_access_token(outsider, "member")
    return {"rid": rid, "a": a, "ta": ta, "tb": tb, "tx": tx,
            "ha": {"Authorization": f"Bearer {ta}"}}


async def _recv_msg(ws, timeout=6.0):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        d = json.loads(raw)
        if d.get("type") == "message":
            return d


async def test_two_clients_receive_same_broadcast(server, room_ctx):
    rid, ha = room_ctx["rid"], room_ctx["ha"]
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['ta']}") as wa, \
               websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['tb']}") as wb:
        assert json.loads(await wa.recv())["type"] == "hello"
        assert json.loads(await wb.recv())["type"] == "hello"
        r = await httpx.AsyncClient().post(
            f"{BASE}/api/rooms/{rid}/messages", json={"content": "广播测试消息"}, headers=ha)
        assert r.status_code == 200
        ma, mb = await _recv_msg(wa), await _recv_msg(wb)
        assert ma["message"]["content"] == "广播测试消息"
        assert ma["message"]["id"] == mb["message"]["id"], "两客户端必须收到同一条"
        assert ma["message"]["nickname"] == "成员A"


async def test_non_member_and_bad_token_rejected(server, room_ctx):
    rid = room_ctx["rid"]
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['tx']}") as ws:
        with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
            await asyncio.wait_for(ws.recv(), timeout=5)
        assert ei.value.rcvd.code == 4403
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token=invalid.jwt") as ws:
        with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
            await asyncio.wait_for(ws.recv(), timeout=5)
        assert ei.value.rcvd.code == 4401


async def test_heartbeat_ping_pong(server, room_ctx):
    rid = room_ctx["rid"]
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['ta']}") as ws:
        await ws.recv()  # hello
        await ws.send("ping")
        while True:
            d = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if d["type"] == "pong":
                break


async def test_disconnect_cleanup_and_remaining_client(server, room_ctx):
    rid, ha = room_ctx["rid"], room_ctx["ha"]
    wa = await websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['ta']}")
    wb = await websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['tb']}")
    await wa.recv()
    await wb.recv()
    await wa.close()
    await asyncio.sleep(0.5)
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE}/api/rooms/{rid}/messages",
                         json={"content": "断线后广播"}, headers=ha)
        assert r.status_code == 200
    m = await _recv_msg(wb)
    assert m["message"]["content"] == "断线后广播", "剩余客户端必须继续收到广播"
    await wb.close()


async def test_ai_reply_broadcast(server, room_ctx, spike_session):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from tests.factories import make_channel, make_model

    sse = ('data: {"choices":[{"delta":{"content":"广播回复"}}]}\n\n'
           'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
           '"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
           'data: [DONE]\n\n')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = sse.encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rid, ha = room_ctx["rid"], room_ctx["ha"]
    ch = await make_channel(spike_session,
                            base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1")
    mid = await make_model(spike_session, public_name="ws-model")
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.execute(text("UPDATE rooms SET model_id=:m WHERE id=:r"),
                                {"m": mid, "r": rid})
    await spike_session.commit()
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['ta']}") as ws:
        await ws.recv()
        async with httpx.AsyncClient() as c:
            async with c.stream("POST", f"{BASE}/api/rooms/{rid}/ai/ask",
                                json={"content": "@AI 你好"}, headers=ha) as r:
                assert r.status_code == 200
                async for _ in r.aiter_lines():
                    pass
        got, ai_seen = [], False
        for _ in range(2):
            m = await _recv_msg(ws)
            got.append(m["message"]["role"])
            if m["message"]["role"] == "assistant":
                assert m["message"]["content"] == "广播回复"
                ai_seen = True
        assert ai_seen and "user" in got, f"应广播用户消息与 AI 回复: {got}"
    srv.shutdown()

async def test_online_count_broadcast(server, room_ctx):
    rid = room_ctx["rid"]
    wa = await websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['ta']}")
    hello = json.loads(await wa.recv())
    assert hello["type"] == "hello"
    counts = []
    wb = await websockets.connect(f"{WS}/ws/rooms/{rid}?token={room_ctx['tb']}")
    await wb.recv()  # hello
    for ws in (wa, wb):
        while True:
            d = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if d.get("type") == "online":
                counts.append(d["count"])
                break
    assert max(counts) == 2, f"两连接在线数应为 2: {counts}"
    while True:  # 把 wa 队列里 wb 加入产生的 count=2 事件消费掉
        d = json.loads(await asyncio.wait_for(wa.recv(), timeout=5))
        if d.get("type") == "online" and d["count"] == 2:
            break
    await wb.close()
    while True:
        d = json.loads(await asyncio.wait_for(wa.recv(), timeout=5))
        if d.get("type") == "online":
            assert d["count"] == 1, "断开后在线数应回落到 1"
            break
    await wa.close()
