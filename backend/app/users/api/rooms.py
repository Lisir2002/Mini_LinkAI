"""房间与多人 + AI 群聊（PRD 5.5）。V1 用轮询获取新消息，WebSocket 留待后续。"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.redis_client import get_redis
from app.core.timeutil import quota_date
from app.files.services.export_service import render_export
from app.files.services.upload_service import assemble_content, validate_attachment
from app.interfaces.deps import get_current_user, room_perm, scope_room
from app.llm.adapter.base import UnifiedRequest, UpstreamError
from app.llm.adapter.openai_compat import estimate_usage
from app.llm.services.channel_service import build_adapter
from app.llm.services.drift_service import apply_drift, update_drift
from app.llm.services.output_mode import MODES, constraint_prompt, validate_output
from app.llm.services.quota_service import QuotaExceeded, begin_call, refund_call, settle_call
from app.llm.services.router_service import (
    NoChannelAvailable,
    record_failure,
    record_success,
    route_channel,
)
from app.stats.services.live_metrics import record_call
from app.users.services import room_bus
from app.users.services.quote_service import (
    QUOTE_COLS,
    QUOTE_JOIN,
    attach_quote,
    build_quote,
    validate_quote,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
User = Depends(get_current_user)


class RoomIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    system_prompt: str = ""
    model_id: int | None = None
    access_type: str = "public"
    max_members: int = 50


class RoomPatch(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    system_prompt: str | None = None
    model_id: int | None = None
    output_mode: str | None = None
    output_schema: str | None = None
    max_members: int | None = Field(default=None, ge=2, le=500)
    daily_token_budget: int | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, ge=1, le=100)


class RoomMsgIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reply_to_msg_id: int | None = None
    attachment_id: int | None = None


@router.get("/{rid}/export")
async def export_room(rid: int, format: str = "md", user: dict[str, Any] = User) -> Any:
    await scope_room(user, rid)
    async with get_session() as s:
        room = (await s.execute(text("SELECT name FROM rooms WHERE id=:i"),
                                {"i": rid})).mappings().one()
        msgs = (await s.execute(text(
            "SELECT m.role,m.content,m.created_at,u.nickname FROM messages m "
            "LEFT JOIN users u ON u.id=m.sender_id "
            "WHERE m.room_id=:r ORDER BY m.id"), {"r": rid})).mappings().all()
    return render_export(room["name"], [dict(m) for m in msgs], format)


async def _msg_payload(s: Any, mid: int) -> dict[str, Any]:
    """广播载荷与 REST 列表同构，前端可直接增量渲染。"""
    row = (await s.execute(text(
        "SELECT m.id,m.role,m.content,m.total_tokens,m.created_at,u.nickname,m.attachment_id,"
        "m.output_mode,m.output_downgraded," + QUOTE_COLS +
        " FROM messages m LEFT JOIN users u ON u.id=m.sender_id " + QUOTE_JOIN +
        " WHERE m.id=:i"), {"i": mid})).mappings().one()
    d: dict[str, Any] = {k: row[k] for k in ("id", "role", "content", "total_tokens",
                                             "nickname", "output_mode", "output_downgraded",
                                             "attachment_id")}
    d["created_at"] = row["created_at"].isoformat()
    d["reply_to_msg_id"] = row["reply_to_msg_id"]
    d["quote"] = build_quote(dict(row))
    return d


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("")
async def list_rooms(user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT r.id,r.name,r.description,r.access_type,r.member_count,r.max_members,"
            "r.ai_status,r.ai_trigger,r.created_at,m.public_name AS model_name,"
            "(SELECT count(*) FROM room_members rm "
            " WHERE rm.room_id=r.id AND rm.user_id=:u) AS joined,"
            "(SELECT content FROM messages WHERE room_id=r.id "
            " ORDER BY id DESC LIMIT 1) AS last_msg "
            "FROM rooms r LEFT JOIN models m ON m.id=r.model_id "
            "WHERE NOT r.archived ORDER BY r.member_count DESC, r.id DESC"),
            {"u": user["id"]})).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.post("")
async def create_room(body: RoomIn, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        row = (await s.execute(text(
            "INSERT INTO rooms (name,description,owner_id,system_prompt,model_id,"
            "access_type,max_members) "
            "VALUES (:n,:d,:o,:sp,:m,:a,:mx) RETURNING id,name"),
            {"n": body.name, "d": body.description, "o": user["id"], "sp": body.system_prompt,
             "m": body.model_id, "a": body.access_type, "mx": body.max_members})).mappings().one()
        await s.execute(text(
            "INSERT INTO room_members (room_id,user_id,role) VALUES (:r,:u,'owner')"),
            {"r": row["id"], "u": user["id"]})
        await s.execute(text("UPDATE rooms SET member_count=1 WHERE id=:r"), {"r": row["id"]})
        await s.commit()
    return {"code": 0, "data": dict(row)}


@router.patch("/{rid}")
async def patch_room(rid: int, body: RoomPatch, user: dict[str, Any] = User) -> dict[str, Any]:
    """EXT-018 房间设置：房主/管理员可改，含结构化输出模式与 Schema。"""
    if not await room_perm(user, rid, "owner"):
        raise AppError(403, "FORBIDDEN", "只有房主或管理员可以修改房间设置")
    sets = {k: v for k, v in body.model_dump().items() if v is not None}
    if not sets:
        raise AppError(422, "VALIDATION_ERROR", "没有需要修改的字段")
    if "output_mode" in sets and sets["output_mode"] not in MODES:
        raise AppError(422, "OUTPUT_MODE_INVALID", "output_mode 仅支持 free/json/table/code")
    if "output_schema" in sets:
        try:
            json.loads(sets["output_schema"])
        except ValueError:
            raise AppError(422, "OUTPUT_SCHEMA_INVALID", "output_schema 必须是合法 JSON") from None
    clause = ", ".join(f"{k}=:{k}" for k in sets)
    async with get_session() as s:
        await s.execute(text(f"UPDATE rooms SET {clause}, updated_at=now() WHERE id=:i"),
                        {**sets, "i": rid})
        await s.commit()
    return {"code": 0, "data": {"updated": True}}


@router.post("/{rid}/join")
async def join_room(rid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        room = (await s.execute(text("SELECT * FROM rooms WHERE id=:i AND NOT archived"),
                                {"i": rid})).mappings().first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "房间不存在")
        if room["access_type"] != "public" and user["role"] != "admin":
            raise AppError(403, "ROOM_INVITE_ONLY", "该房间需要邀请码或房主审批")
        added = (await s.execute(text(
            "UPDATE rooms SET member_count=member_count+1 "
            "WHERE id=:i AND member_count < max_members RETURNING member_count"),
            {"i": rid})).first()
        if added is None:
            raise AppError(409, "ROOM_FULL",
                           f"房间已满 {room['max_members']}/{room['max_members']}")
        await s.execute(text(
            "INSERT INTO room_members (room_id,user_id,role) VALUES (:r,:u,'member') "
            "ON CONFLICT DO NOTHING"), {"r": rid, "u": user["id"]})
        sysrow = (await s.execute(text(
            "INSERT INTO messages (scope,room_id,role,content) VALUES ('room',:r,'system',:c) "
            "RETURNING id"),
            {"r": rid, "c": f"{user['nickname']} 加入了房间"})).mappings().one()
        await s.commit()
        await room_bus.publish(rid, {"type": "message",
                                     "message": await _msg_payload(s, sysrow["id"])})
    return {"code": 0, "data": {"joined": True}}


@router.post("/{rid}/leave")
async def leave_room(rid: int, user: dict[str, Any] = User) -> dict[str, Any]:
    async with get_session() as s:
        if await room_perm(user, rid, "owner"):
            raise AppError(409, "OWNER_CANNOT_LEAVE", "房主不能退出，请先转让或归档房间")
        await s.execute(text("DELETE FROM room_members WHERE room_id=:r AND user_id=:u"),
                        {"r": rid, "u": user["id"]})
        await s.execute(text(
            "UPDATE rooms SET member_count=GREATEST(member_count-1,0) WHERE id=:r"), {"r": rid})
        await s.commit()
    return {"code": 0, "data": {"left": True}}


@router.get("/{rid}/messages")
async def room_messages(rid: int, after: int = 0, user: dict[str, Any] = User) -> dict[str, Any]:
    await scope_room(user, rid)
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT m.id,m.role,m.content,m.total_tokens,m.created_at,u.nickname,m.attachment_id,"
        "m.output_mode,m.output_downgraded," + QUOTE_COLS +
            " FROM messages m LEFT JOIN users u ON u.id=m.sender_id " + QUOTE_JOIN +
            " WHERE m.room_id=:r AND m.id > :a ORDER BY m.id LIMIT 200"),
            {"r": rid, "a": after})).mappings().all()
        room = (await s.execute(text(
            "SELECT r.name,r.description,r.ai_status,r.owner_id,m.public_name AS model_name "
            "FROM rooms r LEFT JOIN models m ON m.id=r.model_id WHERE r.id=:i"),
            {"i": rid})).mappings().one()
    items = []
    for r in rows:
        d = dict(r)
        for k in ("q_content", "q_role", "q_nickname"):
            d.pop(k, None)
        d["quote"] = build_quote(dict(r))
        items.append(d)
    return {"code": 0, "data": {"items": items, "room": dict(room)}}


@router.post("/{rid}/messages")
async def send_room_message(rid: int, body: RoomMsgIn,
                            user: dict[str, Any] = User) -> dict[str, Any]:
    await scope_room(user, rid)
    async with get_session() as s:
        await validate_quote(s, body.reply_to_msg_id, room_id=rid)
        await validate_attachment(s, user, body.attachment_id)
        row = (await s.execute(text(
            "INSERT INTO messages (scope,room_id,sender_id,role,content,reply_to_msg_id,"
            "attachment_id) VALUES ('room',:r,:u,'user',:c,:q,:a) RETURNING id"),
            {"r": rid, "u": user["id"], "c": body.content,
             "q": body.reply_to_msg_id, "a": body.attachment_id})).mappings().one()
        await s.commit()
        await room_bus.publish(rid, {"type": "message",
                                     "message": await _msg_payload(s, row["id"])})
    return {"code": 0, "data": {"message_id": row["id"]}}


@router.post("/{rid}/ai/ask")
async def room_ai(rid: int, body: RoomMsgIn, user: dict[str, Any] = User) -> StreamingResponse:
    await scope_room(user, rid)
    async with get_session() as s:
        await validate_quote(s, body.reply_to_msg_id, room_id=rid)
        await validate_attachment(s, user, body.attachment_id)

    async def gen() -> AsyncIterator[str]:
        async with get_session() as s:
            room = (await s.execute(text(
                "SELECT r.*, m.public_name, m.display_name, m.id AS mid, m.max_output_tokens, "
                "m.supports_vision, "
                "m.price_input, m.price_output FROM rooms r LEFT JOIN models m ON m.id=r.model_id "
                "WHERE r.id=:i"), {"i": rid})).mappings().one()
            if room["ai_status"] in ("suspended", "closed") or not room["mid"]:
                yield _sse("error", {"code": "ROOM_AI_UNAVAILABLE",
                                     "message": "该房间当前不可使用 AI"})
                return
            if room["ai_trigger"] == "off":
                yield _sse("error", {"code": "ROOM_AI_DISABLED",
                                     "message": "该房间已关闭 AI 触发"})
                return
            if room["ai_trigger"] == "mention" and "@ai" not in body.content.lower():
                yield _sse("error", {"code": "AI_MENTION_REQUIRED",
                                     "message": "该房间需要 @AI 才会触发模型"})
                return
            cd_key = f"room:{rid}:ai_cd"
            if not await get_redis().set(cd_key, "1", nx=True,
                                         ex=settings.ROOM_AI_COOLDOWN_SEC):
                yield _sse("error", {
                    "code": "COOLDOWN",
                    "message": f"AI 冷却中，请 {settings.ROOM_AI_COOLDOWN_SEC} 秒后再试"})
                return
            trig = (await s.execute(text(
                "INSERT INTO messages (scope,room_id,sender_id,role,content,reply_to_msg_id,"
                "attachment_id) VALUES ('room',:r,:u,'user',:c,:q,:a) RETURNING id"),
                {"r": rid, "u": user["id"], "c": body.content,
                 "q": body.reply_to_msg_id, "a": body.attachment_id})).mappings().one()
            hist = (await s.execute(text(
                "SELECT m.id,m.role,m.content,u.nickname FROM messages m "
                "LEFT JOIN users u ON u.id=m.sender_id "
                "WHERE m.room_id=:r AND m.role<>'system' ORDER BY m.id DESC LIMIT :n"),
                {"r": rid, "n": int(room["context_window"])})).all()
            messages = [{"role": h[1], "content": (f"{h[3]}：" if h[3] else "") + h[2]}
                        for h in reversed(hist)]
            await attach_quote(s, messages, [h[0] for h in hist], body.reply_to_msg_id,
                               with_nickname=True)
            if body.attachment_id is not None:
                messages[-1]["content"] = await assemble_content(
                    s, body.attachment_id, messages[-1]["content"],
                    bool(room["supports_vision"]))
            sys_prompt = room["system_prompt"] or "这是一个多人讨论房间，请面向全体简洁作答。"
            sys_prompt += constraint_prompt(room["output_mode"], room["output_schema"])
            messages.insert(0, {"role": "system", "content": sys_prompt})
            await s.commit()
            await room_bus.publish(rid, {"type": "message",
                                         "message": await _msg_payload(s, trig["id"])})

            owner = (await s.execute(text("SELECT daily_token_limit FROM users WHERE id=:i"),
                                     {"i": room["owner_id"]})).scalar_one()
            prompt_est = estimate_usage(messages, "")["prompt_tokens"]
            prompt_adj = await apply_drift(s, room["mid"], prompt_est)
            frozen = prompt_adj + int(room["max_output_tokens"])
            qd = quota_date()
            # 房主日总额（跨房间+单聊聚合）预检；原子冻结仍按行保证不超卖
            owner_used = (await s.execute(text(
                "SELECT coalesce(sum(total_tokens),0) FROM daily_usage "
                "WHERE owner_id=:o AND quota_date=:d"),
                {"o": room["owner_id"], "d": qd})).scalar_one()
            if int(owner_used) + frozen > int(owner):
                yield _sse("error", {"code": "QUOTA_EXCEEDED", "message": "房主今日额度已用完"})
                return
            budget = int(room["daily_token_budget"])
            room_limit = budget if budget > 0 else 10**12
            try:
                call = await begin_call(
                    s, user_id=user["id"], owner_id=room["owner_id"], room_id=rid,
                    conversation_id=None, model_id=room["mid"], channel_id=None,
                    frozen=frozen, quota_date=qd, limit=room_limit,
                    model_public_name=room["public_name"],
                    model_display_name=room["display_name"])
            except QuotaExceeded:
                yield _sse("error", {"code": "QUOTA_EXCEEDED", "message": "房间今日预算已用完"})
                return
            try:
                chan = await route_channel(s, room["public_name"], room["mid"], user["id"])
            except NoChannelAvailable:
                await refund_call(s, call_id=call, quota_date=qd, owner_id=room["owner_id"],
                                  room_id=rid, frozen=frozen, reason="no_channel")
                yield _sse("error", {"code": "NO_CHANNEL_AVAILABLE", "message": "该模型暂不可用"})
                return
            await s.execute(text("UPDATE usage_logs SET channel_id=:ch, channel_name=:cn, "
                                 "experiment_id=:eid, bucket=:bk "
                                 "WHERE call_id=CAST(:k AS uuid)"),
                            {"ch": chan["id"], "cn": chan["name"], "k": call,
                             "eid": chan.get("_experiment_id"), "bk": chan.get("_bucket")})
            await s.commit()
            yield _sse("meta", {"call_id": call, "model": room["public_name"],
                                "trigger": user["nickname"]})
            pieces: list[str] = []
            usage: dict[str, Any] | None = None
            usage_sum = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            t0 = time.perf_counter()
            first = 0
            out_mode = room["output_mode"]
            final_mode = out_mode if out_mode != "free" else None
            downgraded = False
            attempts = 2 if out_mode == "json" else 1
            for attempt in range(attempts):
                pieces = []
                usage = None
                try:
                    async for ev in build_adapter(chan).stream_chat(UnifiedRequest(
                            model=chan["upstream_model"], messages=messages,
                            max_tokens=int(room["max_output_tokens"]),
                            cache_key=f"room:{rid}")):
                        if ev.type == "delta":
                            if not first:
                                first = int((time.perf_counter() - t0) * 1000)
                            pieces.append(ev.data["content"])
                            yield _sse("delta", ev.data)
                        elif ev.type == "usage":
                            usage = ev.data
                except UpstreamError as exc:
                    await record_failure(s, chan["id"], kind=exc.kind)
                    await refund_call(s, call_id=call, quota_date=qd,
                                      owner_id=room["owner_id"], room_id=rid,
                                      frozen=frozen, reason=exc.kind)
                    yield _sse("error", {"code": "UPSTREAM_ERROR",
                                         "message": "模型异常，已退回额度", "refund": True})
                    return
                usage = usage or estimate_usage(messages, "".join(pieces))
                for k in usage_sum:
                    usage_sum[k] += int(usage.get(k, 0))
                if validate_output(out_mode, "".join(pieces), room["output_schema"]):
                    break
                if attempt == 0:
                    messages.append({
                        "role": "user",
                        "content": "上次输出不符合 JSON 约束，请重新只输出合法 JSON。"})
                    yield _sse("retry", {"attempt": 2, "reason": "OUTPUT_INVALID"})
                    continue
                downgraded = True
                final_mode = "free"
            usage = usage_sum
            cost = (usage["prompt_tokens"] / 1e6 * float(room["price_input"])
                    + usage["completion_tokens"] / 1e6 * float(room["price_output"]))
            total_ms = int((time.perf_counter() - t0) * 1000)
            msg = (await s.execute(text(
                "INSERT INTO messages (scope,room_id,role,content,model_id,channel_id,"
                "prompt_tokens,"
                "completion_tokens,total_tokens,cost,first_token_ms,total_ms,"
                "output_mode,output_downgraded) "
                "VALUES ('room',:r,'assistant',:c,:m,:ch,:p,:co,:tt,:cost,:f,:ms,:om,:od) "
                "RETURNING id"),
                {"r": rid, "c": "".join(pieces), "m": room["mid"], "ch": chan["id"],
                 "p": usage["prompt_tokens"], "co": usage["completion_tokens"],
                 "tt": usage["prompt_tokens"] + usage["completion_tokens"], "cost": cost,
                 "f": first, "ms": total_ms, "om": final_mode,
                 "od": downgraded})).mappings().one()
            await settle_call(s, call_id=call, quota_date=qd, owner_id=room["owner_id"],
                              room_id=rid, frozen=frozen, prompt_tokens=usage["prompt_tokens"],
                              completion_tokens=usage["completion_tokens"], cost=cost,
                              first_token_ms=first, total_ms=total_ms)
            await record_success(s, chan["id"])
            await s.commit()
            await room_bus.publish(rid, {"type": "message",
                                         "message": await _msg_payload(s, msg["id"])})
            if not usage.get("estimated"):
                await update_drift(s, room["mid"], estimated=prompt_est,
                                   actual=usage["prompt_tokens"])
            try:
                await record_call(chan["id"], total_ms)
            except Exception:    # noqa: BLE001 - 指标采集失败不得影响对话
                pass
            yield _sse("usage", usage)
            yield _sse("done", {"message_id": msg["id"], "first_token_ms": first,
                                "total_ms": total_ms, "output_mode": final_mode,
                                "output_downgraded": downgraded})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
