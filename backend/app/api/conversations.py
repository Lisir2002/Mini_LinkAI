"""单聊会话与 SSE 流式对话（PRD 5.4 / 8.3）。"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.timeutil import quota_date
from app.db import get_session
from app.deps import get_current_user, get_db, scope_conversation
from app.services.adapter.base import UnifiedRequest, UpstreamError
from app.services.adapter.openai_compat import estimate_usage
from app.services.channel_service import build_adapter
from app.services.drift_service import apply_drift, update_drift
from app.services.export_service import render_export
from app.services.live_metrics import record_call
from app.services.quota_service import QuotaExceeded, begin_call, refund_call, settle_call
from app.services.quote_service import (
    QUOTE_COLS,
    QUOTE_JOIN,
    attach_quote,
    build_quote,
    validate_quote,
)
from app.services.router_service import (
    NoChannelAvailable,
    record_failure,
    record_success,
    route_channel,
)
from app.services.upload_service import assemble_content, validate_attachment

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
User = Depends(get_current_user)


class ConvIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    title: str = "新会话"
    model_id: int | None = None
    system_prompt: str | None = None


class ConvPatch(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    title: str | None = None
    pinned: bool | None = None
    model_id: int | None = None
    system_prompt: str | None = None


class MsgIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reply_to_msg_id: int | None = None
    attachment_id: int | None = None


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = None
    reply_to_msg_id: int | None = None
    attachment_id: int | None = None


@router.get("")
async def list_convs(user: dict[str, Any] = User,
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(text(
        "SELECT id,title,model_id,pinned,notify_muted,context_tokens,message_count,"
        "last_message_at,created_at FROM conversations WHERE user_id=:u "
        "ORDER BY pinned DESC, last_message_at DESC NULLS LAST, id DESC"),
        {"u": user["id"]})).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.post("")
async def create_conv(body: ConvIn, user: dict[str, Any] = User,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(text(
        "INSERT INTO conversations (user_id,title,model_id,system_prompt) "
        "VALUES (:u,:t,:m,:sp) RETURNING id,title,model_id,created_at"),
        {"u": user["id"], "t": body.title, "m": body.model_id,
         "sp": body.system_prompt})).mappings().one()
    await db.commit()
    return {"code": 0, "data": dict(row)}


@router.get("/{cid}")
async def get_conv(cid: int, user: dict[str, Any] = User,
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await scope_conversation(user, cid)
    row = (await db.execute(text("SELECT * FROM conversations WHERE id=:i"),
                            {"i": cid})).mappings().one()
    return {"code": 0, "data": dict(row)}


@router.patch("/{cid}")
async def patch_conv(cid: int, body: ConvPatch, user: dict[str, Any] = User,
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await scope_conversation(user, cid)
    sets = {k: v for k, v in body.model_dump().items() if v is not None}
    if not sets:
        raise AppError(422, "VALIDATION_ERROR", "没有需要修改的字段")
    clause = ", ".join(f"{k}=:{k}" for k in sets)
    await db.execute(text(f"UPDATE conversations SET {clause}, updated_at=now() WHERE id=:i"),
                     {**sets, "i": cid})
    await db.commit()
    return {"code": 0, "data": {"updated": True}}


@router.delete("/{cid}")
async def delete_conv(cid: int, user: dict[str, Any] = User,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await scope_conversation(user, cid)
    await db.execute(text("DELETE FROM conversations WHERE id=:i"), {"i": cid})
    await db.commit()
    return {"code": 0, "data": {"deleted": True}}


@router.get("/{cid}/messages")
async def list_messages(cid: int, user: dict[str, Any] = User,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await scope_conversation(user, cid)
    rows = (await db.execute(text(
        "SELECT m.id,m.role,m.content,m.status,m.total_tokens,m.created_at,"
        "m.attachment_id," + QUOTE_COLS +
        " FROM messages m " + QUOTE_JOIN +
        " WHERE m.conversation_id=:c ORDER BY m.id"), {"c": cid})).mappings().all()
    items = []
    for r in rows:
        d = {k: r[k] for k in ("id", "role", "content", "status", "total_tokens",
                               "created_at", "attachment_id")}
        d["reply_to_msg_id"] = r["reply_to_msg_id"]
        d["quote"] = build_quote(dict(r))
        items.append(d)
    return {"code": 0, "data": {"items": items}}


@router.post("/{cid}/messages")
async def send_message(cid: int, body: MsgIn, user: dict[str, Any] = User,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await scope_conversation(user, cid)
    await validate_quote(db, body.reply_to_msg_id, conversation_id=cid)
    await validate_attachment(db, user, body.attachment_id)
    row = (await db.execute(text(
        "INSERT INTO messages (scope,conversation_id,sender_id,role,content,reply_to_msg_id,"
        "attachment_id) VALUES ('dm',:c,:u,'user',:t,:q,:a) RETURNING id"),
        {"c": cid, "u": user["id"], "t": body.content,
         "q": body.reply_to_msg_id, "a": body.attachment_id})).mappings().one()
    await db.execute(text("UPDATE conversations SET last_message_at=now(), "
                          "message_count=message_count+1 WHERE id=:c"), {"c": cid})
    await db.commit()
    return {"code": 0, "data": {"message_id": row["id"]}}


@router.get("/{cid}/export")
async def export_conv(cid: int, format: str = "md", user: dict[str, Any] = User,
                      db: AsyncSession = Depends(get_db)) -> Any:
    await scope_conversation(user, cid)
    conv = (await db.execute(text("SELECT title FROM conversations WHERE id=:i"),
                             {"i": cid})).mappings().one()
    msgs = (await db.execute(text(
        "SELECT m.role,m.content,m.created_at,u.nickname FROM messages m "
        "LEFT JOIN users u ON u.id=m.sender_id "
        "WHERE m.conversation_id=:c ORDER BY m.id"), {"c": cid})).mappings().all()
    return render_export(conv["title"], [dict(m) for m in msgs], format)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{cid}/ai/completions")
async def ai_completions(cid: int, body: AskIn,
                         user: dict[str, Any] = User) -> StreamingResponse:
    await scope_conversation(user, cid)
    async with get_session() as s:
        await validate_quote(s, body.reply_to_msg_id, conversation_id=cid)
        await validate_attachment(s, user, body.attachment_id)
    call_id = str(uuid.uuid4())

    async def gen() -> AsyncIterator[str]:
        async with get_session() as s:
            locked = (await s.execute(text(
                "UPDATE conversations SET active_call_id=CAST(:k AS uuid) "
                "WHERE id=:c AND active_call_id IS NULL RETURNING id"),
                {"k": call_id, "c": cid})).first()
            await s.commit()
            if locked is None:
                yield _sse("error", {"code": "AI_IN_PROGRESS", "message": "该会话已有回复在生成"})
                return
            conv = (await s.execute(text("SELECT * FROM conversations WHERE id=:i"),
                                    {"i": cid})).mappings().one()
            model = None
            if conv["model_id"]:
                model = (await s.execute(text("SELECT * FROM models WHERE id=:i AND enabled"),
                                         {"i": conv["model_id"]})).mappings().first()
            if model is None:
                await _release(s, cid, call_id)
                yield _sse("error", {"code": "NO_MODEL", "message": "会话未绑定可用模型"})
                return
            await s.execute(text(
                "INSERT INTO messages (scope,conversation_id,sender_id,role,content,"
                "reply_to_msg_id,attachment_id) VALUES ('dm',:c,:u,'user',:t,:q,:a)"),
                {"c": cid, "u": user["id"], "t": body.content, "q": body.reply_to_msg_id,
                 "a": body.attachment_id})
            hist = (await s.execute(text(
                "SELECT id,role,content FROM messages WHERE conversation_id=:c "
                "ORDER BY id DESC LIMIT 20"), {"c": cid})).all()
            messages = [{"role": r[1], "content": r[2]} for r in reversed(hist)]
            await attach_quote(s, messages, [r[0] for r in hist], body.reply_to_msg_id)
            if body.attachment_id is not None:
                messages[-1]["content"] = await assemble_content(
                    s, body.attachment_id, body.content, bool(model["supports_vision"]))
            if conv["system_prompt"]:
                messages.insert(0, {"role": "system", "content": conv["system_prompt"]})
            await s.commit()

            prompt_est = estimate_usage(messages, "")["prompt_tokens"]
            prompt_adj = await apply_drift(s, model["id"], prompt_est)
            frozen = prompt_adj + int(model["max_output_tokens"])
            qd = quota_date()
            try:
                real_call = await begin_call(
                    s, user_id=user["id"], owner_id=user["id"], room_id=None,
                    conversation_id=cid, model_id=model["id"], channel_id=None,
                    frozen=frozen, quota_date=qd,
                    limit=int(user["daily_token_limit"]),
                    model_public_name=model["public_name"],
                    model_display_name=model["display_name"])
            except QuotaExceeded:
                await _release(s, cid, call_id)
                yield _sse("error", {"code": "QUOTA_EXCEEDED", "message": "今日额度已用完"})
                return
            try:
                chan = await route_channel(s, model["public_name"], model["id"], user["id"])
            except NoChannelAvailable:
                await refund_call(s, call_id=real_call, quota_date=qd,
                                  owner_id=user["id"], room_id=None, frozen=frozen,
                                  reason="no_channel")
                await _release(s, cid, call_id)
                yield _sse("error", {"code": "NO_CHANNEL_AVAILABLE", "message": "该模型暂不可用"})
                return
            await s.execute(text("UPDATE usage_logs SET channel_id=:ch, channel_name=:cn, "
                                 "experiment_id=:eid, bucket=:bk "
                                 "WHERE call_id=CAST(:k AS uuid)"),
                            {"ch": chan["id"], "cn": chan["name"], "k": real_call,
                             "eid": chan.get("_experiment_id"), "bk": chan.get("_bucket")})
            await s.commit()
            yield _sse("meta", {"call_id": real_call, "model": model["public_name"],
                                "channel_id": chan["id"]})

            adapter = build_adapter(chan)
            req = UnifiedRequest(model=chan["upstream_model"], messages=messages,
                                 max_tokens=int(model["max_output_tokens"]))
            pieces: list[str] = []
            usage: dict[str, Any] | None = None
            t0 = time.perf_counter()
            first_ms = 0
            try:
                async for ev in adapter.stream_chat(req):
                    if ev.type == "delta":
                        if not first_ms:
                            first_ms = int((time.perf_counter() - t0) * 1000)
                        pieces.append(ev.data["content"])
                        yield _sse("delta", ev.data)
                    elif ev.type == "usage":
                        usage = ev.data
            except UpstreamError as exc:
                await record_failure(s, chan["id"], kind=exc.kind)
                await refund_call(s, call_id=real_call, quota_date=qd,
                                  owner_id=user["id"], room_id=None, frozen=frozen,
                                  reason=exc.kind)
                await _release(s, cid, call_id)
                yield _sse("error", {"code": "UPSTREAM_ERROR",
                                     "message": "模型服务异常，已退回额度",
                                     "kind": exc.kind, "refund": True})
                return

            usage = usage or estimate_usage(messages, "".join(pieces))
            cost = (usage["prompt_tokens"] / 1e6 * float(model["price_input"])
                    + usage["completion_tokens"] / 1e6 * float(model["price_output"]))
            total_ms = int((time.perf_counter() - t0) * 1000)
            msg = (await s.execute(text(
                "INSERT INTO messages (scope,conversation_id,role,content,model_id,channel_id,"
                "prompt_tokens,completion_tokens,total_tokens,cost,first_token_ms,total_ms) "
                "VALUES ('dm',:c,'assistant',:t,:m,:ch,:p,:co,:tt,:cost,:f,:ms) RETURNING id"),
                {"c": cid, "t": "".join(pieces), "m": model["id"], "ch": chan["id"],
                 "p": usage["prompt_tokens"], "co": usage["completion_tokens"],
                 "tt": usage["prompt_tokens"] + usage["completion_tokens"], "cost": cost,
                 "f": first_ms, "ms": total_ms})).mappings().one()
            await settle_call(s, call_id=real_call, quota_date=qd, owner_id=user["id"],
                              room_id=None, frozen=frozen,
                              prompt_tokens=usage["prompt_tokens"],
                              completion_tokens=usage["completion_tokens"], cost=cost,
                              first_token_ms=first_ms, total_ms=total_ms)
            await record_success(s, chan["id"])
            if not usage.get("estimated"):
                await update_drift(s, model["id"], estimated=prompt_est,
                                   actual=usage["prompt_tokens"])
            try:
                await record_call(chan["id"], total_ms)
            except Exception:    # noqa: BLE001 - 指标采集失败不得影响对话
                pass
            await s.execute(text("UPDATE conversations SET last_message_at=now(), "
                                 "message_count=message_count+2 WHERE id=:c"), {"c": cid})
            await s.commit()
            await _release(s, cid, call_id)
            yield _sse("usage", usage)
            yield _sse("done", {"message_id": msg["id"], "first_token_ms": first_ms,
                                "total_ms": total_ms})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _release(s: AsyncSession, cid: int, call_id: str) -> None:
    await s.execute(text("UPDATE conversations SET active_call_id=NULL "
                         "WHERE id=:c AND active_call_id=CAST(:k AS uuid)"),
                    {"c": cid, "k": call_id})
    await s.commit()
