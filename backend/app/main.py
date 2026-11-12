from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text

from app.api import admin as admin_api
from app.api import admin_users as admin_users_api
from app.api import auth as auth_api
from app.api import conversations as conv_api
from app.api import dm as dm_api
from app.api import experiments as experiments_api
from app.api import feedback as feedback_api
from app.api import friends as friends_api
from app.api import models as models_api
from app.api import quota as quota_api
from app.api import rooms as rooms_api
from app.api import search as search_api
from app.api import shares as shares_api
from app.api import stats as stats_api
from app.api import templates as templates_api
from app.api import uploads as uploads_api
from app.core.errors import AppError
from app.core.logging import configure_logging, log_event
from app.core.startup import wait_for_dependencies
from app.db import get_session
from app.redis_client import get_redis

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动期校验依赖，重试耗尽即退出，绝不无限等待（PRD 2.4）。"""
    await wait_for_dependencies()
    from app.services import dm_bus, room_bus
    bus_task = asyncio.create_task(room_bus.listener())
    dm_task = asyncio.create_task(dm_bus.listener())
    yield
    bus_task.cancel()
    dm_task.cancel()
    for t in (bus_task, dm_task):
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(auth_api.router)
app.include_router(admin_api.router)
app.include_router(admin_users_api.router)
app.include_router(models_api.router)
app.include_router(conv_api.router)
app.include_router(friends_api.router)
app.include_router(dm_api.router)
app.include_router(feedback_api.router)
app.include_router(experiments_api.router)
app.include_router(stats_api.router)
app.include_router(search_api.router)
app.include_router(shares_api.router)
app.include_router(shares_api.public)
app.include_router(quota_api.router)
app.include_router(rooms_api.router)
app.include_router(templates_api.router)
app.include_router(uploads_api.router)


@app.middleware("http")
async def trace_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    return response


async def _audit_denial(request: Request, exc: AppError, trace_id: str) -> None:
    """权限被拒必须留痕（PRD 10.3）。审计失败不得影响错误响应。"""
    try:
        from app.core.security import decode_token
        from app.services import audit_service

        actor = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                actor = int(decode_token(auth[7:])["sub"])
            except Exception:    # noqa: BLE001
                actor = None
        async with get_session() as s:
            await audit_service.record(
                s, actor_id=actor, action="auth.permission_denied",
                target_type="route", target_id=request.url.path,
                detail={"code": exc.code}, trace_id=trace_id)
            await s.commit()
    except Exception:            # noqa: BLE001
        pass


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    if exc.code in {"FORBIDDEN_ADMIN_ONLY", "NOT_ROOM_MEMBER"}:
        await _audit_denial(request, exc, trace_id)
    return JSONResponse(status_code=exc.status, content={
        "code": exc.code, "message": exc.message,
        "detail": exc.detail, "trace_id": trace_id})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常统一转通用文案，堆栈只进日志（PRD 10.1 第四层）。"""
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    log_event("http.unhandled_error", status="failure", trace_id=trace_id,
              error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL", "message": "服务器开小差了", "trace_id": trace_id},
    )


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 0, "data": data}


async def _probe_db_health() -> None:
    async with get_session() as s:
        await s.execute(text("SELECT 1"))


async def _probe_redis_health() -> None:
    await get_redis().ping()


@app.get("/api/health")
async def health() -> Any:
    from time import perf_counter

    from app.config import settings

    failed: list[str] = []
    timings: dict[str, int] = {}
    for name, probe in (("db", _probe_db_health), ("redis", _probe_redis_health)):
        t0 = perf_counter()
        try:
            await probe()
        except Exception:        # noqa: BLE001 - 健康检查需吞掉探测异常并如实上报
            failed.append(name)
        timings[f"{name}_ms"] = int((perf_counter() - t0) * 1000)
    if failed:
        return JSONResponse(status_code=503, content={
            "code": "DEPENDENCY_UNAVAILABLE", "message": "依赖不可用",
            "detail": {"failed": failed[0]}, **timings})
    return _ok({"db": "ok", "redis": "ok", "environment": settings.ENVIRONMENT,
                "version": "0.1.0", **timings})


@app.get("/api/_smoke/db")
async def smoke_db() -> dict[str, Any]:
    async with get_session() as s:
        value = (await s.execute(text("SELECT 1"))).scalar_one()
    return _ok({"value": value})


@app.get("/api/_smoke/redis")
async def smoke_redis() -> dict[str, Any]:
    key = f"smoke:{uuid.uuid4()}"
    await get_redis().set(key, "pong", ex=30)
    got = await get_redis().get(key)
    await get_redis().delete(key)
    return _ok({"written": "pong", "roundtrip": got})


@app.get("/api/_smoke/sse")
async def smoke_sse() -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        for i in range(3):
            yield f"event: delta\ndata: {json.dumps({'i': i})}\n\n"
            await asyncio.sleep(0.06)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws/_smoke")
async def smoke_ws(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"type": "push", "msg": "server initiated"})
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        return


@app.websocket("/ws/rooms/{rid}")
async def ws_room(websocket: WebSocket, rid: int, token: str = "") -> None:
    """EXT-024 房间实时广播：query token 鉴权，30s 心跳，断开即清理。"""
    from app.core.security import TokenInvalid, decode_token
    from app.services import room_bus

    await websocket.accept()
    try:
        payload = decode_token(token)
    except TokenInvalid:
        await websocket.close(code=4401)
        return
    async with get_session() as s:
        user = (await s.execute(text(
            "SELECT id,role,status,must_change_password FROM users WHERE id=:i"),
            {"i": int(payload["sub"])})).mappings().first()
        room = (await s.execute(text("SELECT archived FROM rooms WHERE id=:i"),
                                {"i": rid})).mappings().first()
        member = None
        if user is not None and room is not None:
            member = user["role"] == "admin" or (await s.execute(text(
                "SELECT 1 FROM room_members WHERE room_id=:r AND user_id=:u"),
                {"r": rid, "u": user["id"]})).first() is not None
    if user is None or user["status"] == "banned":
        await websocket.close(code=4401)
        return
    if user["must_change_password"]:
        await websocket.close(code=4403)
        return
    if room is None or room["archived"]:
        await websocket.close(code=4404)
        return
    if not member:
        await websocket.close(code=4403)
        return
    room_bus.register(rid, websocket, int(user["id"]))
    await room_bus.presence_changed(rid, int(user["id"]), joined=True)
    try:
        await websocket.send_json({"type": "hello", "room_id": rid})
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if raw == "ping":
                    await websocket.send_json({"type": "pong"})
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        room_bus.unregister(rid, websocket)
        await room_bus.presence_changed(rid, int(user["id"]), joined=False)


@app.websocket("/ws/dm")
async def ws_dm(websocket: WebSocket, token: str = "") -> None:
    """FR-004 个人事件频道：私聊消息 / 好友申请 / 同意 / 已读回执。"""
    from app.core.security import TokenInvalid, decode_token
    from app.services import dm_bus

    await websocket.accept()
    try:
        payload = decode_token(token)
    except TokenInvalid:
        await websocket.close(code=4401)
        return
    async with get_session() as s:
        user = (await s.execute(text(
            "SELECT id,status,must_change_password FROM users WHERE id=:i"),
            {"i": int(payload["sub"])})).mappings().first()
    if user is None or user["status"] == "banned":
        await websocket.close(code=4401)
        return
    if user["must_change_password"]:
        await websocket.close(code=4403)
        return
    uid = int(user["id"])
    dm_bus.register(uid, websocket)
    try:
        await websocket.send_json({"type": "hello", "user_id": uid})
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if raw == "ping":
                    await websocket.send_json({"type": "pong"})
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        dm_bus.unregister(uid, websocket)
