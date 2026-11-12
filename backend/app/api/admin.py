"""管理端接口：渠道、预设、模型注册表（PRD 8.6）。"""
from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_api_key, key_hint
from app.core.errors import AppError
from app.deps import get_db, require_admin
from app.redis_client import get_redis
from app.services import audit_service
from app.services.adapter.base import UpstreamError
from app.services.adapter.presets import PRESETS
from app.services.channel_service import CHANNEL_COLS, build_adapter, invalidate_model_cache

router = APIRouter(prefix="/api/admin", tags=["admin"])
Admin = Depends(require_admin)


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = "openai_compatible"
    base_url: str
    api_key: str
    preset: str | None = None
    supported_params: list[str] | None = None
    weight: int = 100
    priority: int = 0


class ChannelPatch(BaseModel):
    version: int
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    supported_params: list[str] | None = None
    weight: int | None = None
    priority: int | None = None


class ToggleIn(BaseModel):
    enabled: bool
    confirm: bool = False


class ModelIn(BaseModel):
    public_name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    tier: str = "standard"
    context_limit: int = 32768
    price_input: float = 0
    price_output: float = 0


class InviteIn(BaseModel):
    count: int = Field(ge=1, le=100)
    max_uses: int = Field(default=1, ge=1)
    note: str | None = None


class SettingIn(BaseModel):
    value: dict[str, Any]
    version: int = 0


class ModelPatch(BaseModel):
    version: int
    supports_vision: bool | None = None
    display_name: str | None = None
    tier: str | None = None
    context_limit: int | None = None
    max_output_tokens: int | None = None
    price_input: float | None = None
    price_output: float | None = None
    enabled: bool | None = None


class BindIn(BaseModel):
    channel_id: int
    upstream_model: str


@router.get("/settings")
async def list_settings(_: dict[str, Any] = Admin,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(
        text("SELECT key,value,version FROM settings ORDER BY key"))).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.get("/channel-presets")
async def channel_presets(_: dict[str, Any] = Admin) -> dict[str, Any]:
    return {"code": 0, "data": {
        proto: [{"name": p.name, "base_url": p.base_url,
                 "supported_params": p.supported_params,
                 "timeout_first_token_ms": p.timeout_first_token_ms,
                 "timeout_total_ms": p.timeout_total_ms} for p in items]
        for proto, items in PRESETS.items()}}


@router.get("/channels")
async def list_channels(_: dict[str, Any] = Admin,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(
        text(f"SELECT {CHANNEL_COLS} FROM channels ORDER BY id"))).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.post("/channels")
async def create_channel(body: ChannelIn, request: Request, user: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    defaults = (PRESETS[body.type][0].supported_params if PRESETS.get(body.type)
                else ["temperature", "top_p", "max_tokens", "stream"])
    sp = body.supported_params if body.supported_params is not None else defaults
    row = (await db.execute(
        text("INSERT INTO channels (name,type,base_url,api_key_enc,api_key_hint,preset,"
             "supported_params,weight,priority) "
             "VALUES (:n,:t,:b,:enc,:hint,:pr,CAST(:sp AS jsonb),:w,:pi) "
             f"RETURNING {CHANNEL_COLS}"),
        {"n": body.name, "t": body.type, "b": body.base_url.rstrip("/"),
         "enc": encrypt_api_key(body.api_key), "hint": key_hint(body.api_key),
         "pr": body.preset,
         "sp": json.dumps(sp),
         "w": body.weight, "pi": body.priority})).mappings().one()
    await audit_service.record(db, actor_id=user["id"], action="channel.create",
                               target_type="channel", target_id=str(row["id"]),
                               detail={"name": body.name, "type": body.type})
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": dict(row)}


async def _load_channel(db: AsyncSession, cid: int) -> dict[str, Any]:
    row = (await db.execute(text(f"SELECT {CHANNEL_COLS},api_key_enc,"
                                 "timeout_first_token_ms,timeout_total_ms "
                                 "FROM channels WHERE id=:i"), {"i": cid})).mappings().first()
    if row is None:
        raise AppError(404, "CHANNEL_NOT_FOUND", "渠道不存在")
    return dict(row)


@router.get("/channels/{cid}")
async def get_channel(cid: int, _: dict[str, Any] = Admin,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _load_channel(db, cid)
    row.pop("api_key_enc", None)
    return {"code": 0, "data": row}


@router.patch("/channels/{cid}")
async def patch_channel(cid: int, body: ChannelPatch, user: dict[str, Any] = Admin,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cur = await _load_channel(db, cid)
    if cur["version"] != body.version:
        raise AppError(409, "CONFLICT_STALE", "配置已被他人修改，请刷新后重试")
    sets: dict[str, Any] = {"version": cur["version"] + 1}
    for f in ("name", "base_url", "weight", "priority"):
        v = getattr(body, f)
        if v is not None:
            sets[f] = v
    if body.api_key:
        sets["api_key_enc"] = encrypt_api_key(body.api_key)
        sets["api_key_hint"] = key_hint(body.api_key)
    params: dict[str, Any] = {"i": cid, **sets}
    if body.supported_params is not None:
        params["sp"] = json.dumps(body.supported_params)
    clause = ", ".join(f"{k}=:{k}" for k in sets)
    if body.supported_params is not None:
        clause += ", supported_params=CAST(:sp AS jsonb)"
    row = (await db.execute(
        text(f"UPDATE channels SET {clause}, updated_at=now() WHERE id=:i "
             f"RETURNING {CHANNEL_COLS}"), params)).mappings().one()
    await audit_service.record(db, actor_id=user["id"], action="channel.update",
                               target_type="channel", target_id=str(cid))
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": dict(row)}


@router.delete("/channels/{cid}")
async def delete_channel(cid: int, user: dict[str, Any] = Admin, confirm: bool = False,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _load_channel(db, cid)
    refs = (await db.execute(
        text("SELECT m.public_name FROM model_channels mc "
             "JOIN models m ON m.id=mc.model_id WHERE mc.channel_id=:i"),
        {"i": cid})).scalars().all()
    if refs and not confirm:
        raise AppError(409, "CHANNEL_IN_USE", "该渠道仍被模型绑定，确认后删除",
                       affected_models=list(refs))
    await db.execute(text("DELETE FROM channels WHERE id=:i"), {"i": cid})
    await audit_service.record(db, actor_id=user["id"], action="channel.delete",
                               target_type="channel", target_id=str(cid),
                               detail={"affected_models": list(refs)})
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": {"deleted": True}}


@router.post("/channels/{cid}/test")
async def test_channel(cid: int, _: dict[str, Any] = Admin,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _load_channel(db, cid)
    result = build_adapter(row).test_connectivity()
    res = await result
    await db.execute(text("UPDATE channels SET last_check_at=now(), last_latency_ms=:l "
                          "WHERE id=:i"), {"l": res.latency_ms, "i": cid})
    await db.commit()
    return {"code": 0, "data": {"ok": res.ok, "latency_ms": res.latency_ms,
                                "error_kind": res.error_kind, "message": res.message}}


@router.post("/channels/{cid}/sync-models")
async def sync_models(cid: int, _: dict[str, Any] = Admin,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _load_channel(db, cid)
    try:
        models = await build_adapter(row).list_models()
    except UpstreamError as exc:
        raise AppError(502, "UPSTREAM_ERROR", f"拉取模型列表失败：{exc.kind}") from exc
    await db.execute(text("UPDATE channels SET discovered_models=CAST(:m AS jsonb) WHERE id=:i"),
                     {"m": json.dumps(models), "i": cid})
    await db.commit()
    return {"code": 0, "data": {"models": models}}


@router.post("/channels/{cid}/toggle")
async def toggle_channel(cid: int, body: ToggleIn, user: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cur = await _load_channel(db, cid)
    target = "enabled" if body.enabled else "disabled"
    affected: list[str] = []
    if cur["status"] == target:
        return {"code": 0, "data": {"status": target, "affected_models": affected}}
    if body.enabled and cur["status"] == "auto_disabled" and not body.confirm:
        raise AppError(409, "CONFIRM_REQUIRED", "该渠道曾被自动禁用，恢复需显式确认")
    await db.execute(text("UPDATE channels SET status=:s, fail_count=0, cooldown_until=NULL, "
                          "updated_at=now() WHERE id=:i"), {"s": target, "i": cid})
    if not body.enabled:
        rows = (await db.execute(
            text("SELECT m.id, m.public_name FROM models m "
                 "JOIN model_channels mc ON mc.model_id=m.id "
                 "WHERE m.enabled AND mc.enabled AND mc.channel_id=:i"),
            {"i": cid})).mappings().all()
        for m in rows:
            others = (await db.execute(
                text("SELECT count(*) FROM model_channels mc "
                     "JOIN channels c ON c.id=mc.channel_id "
                     "WHERE mc.model_id=:m AND mc.enabled AND c.status='enabled' AND c.id<>:i"),
                {"m": m["id"], "i": cid})).scalar_one()
            if others == 0:
                await db.execute(
                    text("UPDATE models SET enabled=false WHERE id=:m"), {"m": m["id"]})
                affected.append(m["public_name"])
    await audit_service.record(db, actor_id=user["id"], action="channel.toggle",
                               target_type="channel", target_id=str(cid),
                               detail={"status": target, "affected_models": affected})
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": {"status": target, "affected_models": affected}}


@router.get("/models")
async def list_models_admin(_: dict[str, Any] = Admin,
                            db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(
        text("SELECT * FROM models ORDER BY sort_order,id"))).mappings().all()
    binds = (await db.execute(text(
        "SELECT mc.model_id, mc.channel_id, mc.upstream_model, c.name AS channel_name "
        "FROM model_channels mc JOIN channels c ON c.id=mc.channel_id "
        "ORDER BY mc.channel_id"))).mappings().all()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for b in binds:
        grouped.setdefault(int(b["model_id"]), []).append(
            {"channel_id": b["channel_id"], "channel_name": b["channel_name"],
             "upstream_model": b["upstream_model"]})
    items = [dict(r) | {"channels": grouped.get(int(r["id"]), [])} for r in rows]
    return {"code": 0, "data": {"items": items}}


@router.post("/models")
async def create_model(body: ModelIn, user: dict[str, Any] = Admin,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    exists = (await db.execute(text("SELECT 1 FROM models WHERE public_name=:n"),
                               {"n": body.public_name})).first()
    if exists:
        raise AppError(409, "MODEL_EXISTS", "该对外模型名已存在")
    row = (await db.execute(
        text("INSERT INTO models (public_name,display_name,tier,context_limit,"
             "price_input,price_output) VALUES (:n,:d,:t,:c,:pi,:po) RETURNING *"),
        {"n": body.public_name, "d": body.display_name, "t": body.tier,
         "c": body.context_limit, "pi": body.price_input,
         "po": body.price_output})).mappings().one()
    await audit_service.record(db, actor_id=user["id"], action="model.create",
                               target_type="model", target_id=str(row["id"]))
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": dict(row)}


@router.patch("/models/{mid}")
async def patch_model(mid: int, body: ModelPatch, user: dict[str, Any] = Admin,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cur = (await db.execute(text("SELECT version FROM models WHERE id=:i"),
                            {"i": mid})).scalar_one_or_none()
    if cur is None:
        raise AppError(404, "MODEL_NOT_FOUND", "模型不存在")
    if cur != body.version:
        raise AppError(409, "CONFLICT_STALE", "配置已被他人修改，请刷新后重试")
    sets = {k: v for k, v in body.model_dump().items() if v is not None and k != "version"}
    if not sets:
        raise AppError(422, "VALIDATION_ERROR", "没有需要修改的字段")
    sets["version"] = cur + 1
    clause = ", ".join(f"{k}=:{k}" for k in sets)
    row = (await db.execute(
        text(f"UPDATE models SET {clause}, updated_at=now() WHERE id=:i RETURNING *"),
        {**sets, "i": mid})).mappings().one()
    await audit_service.record(db, actor_id=user["id"], action="model.update",
                               target_type="model", target_id=str(mid))
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": dict(row)}


@router.delete("/models/{mid}")
async def delete_model(mid: int, user: dict[str, Any] = Admin,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    exists = (await db.execute(text("SELECT 1 FROM models WHERE id=:i"), {"i": mid})).first()
    if exists is None:
        raise AppError(404, "MODEL_NOT_FOUND", "模型不存在")
    # messages/usage_logs 的 model_id 为 SET NULL；usage_logs 的快照列保留历史维度
    await db.execute(text("DELETE FROM models WHERE id=:i"), {"i": mid})
    await audit_service.record(db, actor_id=user["id"], action="model.delete",
                               target_type="model", target_id=str(mid))
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": {"deleted": True}}


@router.post("/models/by-name/{public_name}/default")
async def set_default_model(public_name: str, user: dict[str, Any] = Admin,
                            db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    mid = (await db.execute(text("SELECT id FROM models WHERE public_name=:n"),
                            {"n": public_name})).scalar_one_or_none()
    if mid is None:
        raise AppError(404, "MODEL_NOT_FOUND", "模型不存在")
    await db.execute(text("UPDATE models SET is_default=false WHERE is_default"))
    await db.execute(text("UPDATE models SET is_default=true WHERE id=:i"), {"i": mid})
    await audit_service.record(db, actor_id=user["id"], action="model.set_default",
                               target_type="model", target_id=str(mid))
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": {"default": public_name}}


@router.post("/models/{mid}/channels")
async def bind_channel(mid: int, body: BindIn, user: dict[str, Any] = Admin,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await db.execute(
        text("INSERT INTO model_channels (model_id,channel_id,upstream_model) "
             "VALUES (:m,:c,:u) ON CONFLICT (model_id,channel_id) DO UPDATE "
             "SET upstream_model=EXCLUDED.upstream_model"),
        {"m": mid, "c": body.channel_id, "u": body.upstream_model})
    await audit_service.record(db, actor_id=user["id"], action="model.bind_channel",
                               target_type="model", target_id=str(mid),
                               detail={"channel_id": body.channel_id})
    await db.commit()
    await invalidate_model_cache()
    return {"code": 0, "data": {"bound": True}}


@router.get("/invite-codes")
async def list_invites(_: dict[str, Any] = Admin,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(text(
        "SELECT id,code,max_uses,used_count,expires_at,note,created_at "
        "FROM invite_codes ORDER BY id DESC"))).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        code = d.pop("code")
        d["code_masked"] = code[:3] + "****" + code[-2:] if len(code) > 5 else "****"
        items.append(d)
    return {"code": 0, "data": {"items": items}}


@router.post("/invite-codes")
async def create_invites(body: InviteIn, user: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    codes: list[str] = []
    for _ in range(body.count):
        while True:
            c = f"RM-{secrets.token_hex(4).upper()}"
            dup = (await db.execute(text("SELECT 1 FROM invite_codes WHERE code=:c"),
                                    {"c": c})).first()
            if dup is None:
                break
        await db.execute(text(
            "INSERT INTO invite_codes (code,created_by,max_uses,note) VALUES (:c,:u,:m,:n)"),
            {"c": c, "u": user["id"], "m": body.max_uses, "n": body.note})
        codes.append(c)
    await audit_service.record(db, actor_id=user["id"], action="invite.generate",
                               target_type="invite_code", detail={"count": body.count})
    await db.commit()
    # 完整 code 仅在本次生成响应中返回一次
    return {"code": 0, "data": {"codes": codes}}


@router.delete("/invite-codes/{iid}")
async def revoke_invite(iid: int, user: dict[str, Any] = Admin,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(text("SELECT id FROM invite_codes WHERE id=:i"),
                            {"i": iid})).first()
    if row is None:
        raise AppError(404, "INVITE_NOT_FOUND", "邀请码不存在")
    await db.execute(text("UPDATE invite_codes SET expires_at=now() WHERE id=:i"), {"i": iid})
    await audit_service.record(db, actor_id=user["id"], action="invite.revoke",
                               target_type="invite_code", target_id=str(iid))
    await db.commit()
    return {"code": 0, "data": {"revoked": True}}


_SETTING_RULES: dict[str, Any] = {
    "registration": lambda v: v.get("mode") in {"open", "invite_code", "closed"},
    "quota": lambda v: all(
        isinstance(x, int | float) and x >= 0
        for k, x in v.items() if k.endswith("limit") or k.endswith("budget")),
    "moderation": lambda v: isinstance(v.get("enabled", True), bool),
    "feature_flags": lambda v: all(isinstance(x, bool) for x in v.values()),
    "retention": lambda v: isinstance(v.get("days", 90), int) and v.get("days", 90) > 0,
    "alert_webhook": lambda v: (
        str(v.get("url", "")).startswith(("http://", "https://"))
        and v.get("type", "generic") in {"dingtalk", "feishu", "generic"}
        and isinstance(v.get("enabled", True), bool)),
}


@router.put("/settings/{key}")
async def put_setting(key: str, body: SettingIn, user: dict[str, Any] = Admin,
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rule = _SETTING_RULES.get(key)
    if rule is None:
        raise AppError(422, "VALIDATION_ERROR", f"未知配置项 {key}")
    if not rule(body.value):
        raise AppError(422, "VALIDATION_ERROR", f"配置项 {key} 的值不合法")
    cur = (await db.execute(text("SELECT version FROM settings WHERE key=:k"),
                            {"k": key})).scalar_one_or_none()
    if cur is None:
        if body.version != 0:
            raise AppError(409, "CONFLICT_STALE", "配置已被他人修改，请刷新后重试")
        await db.execute(text(
            "INSERT INTO settings (key,value,version,updated_by) "
            "VALUES (:k,CAST(:v AS jsonb),1,:u)"),
            {"k": key, "v": json.dumps(body.value), "u": user["id"]})
    else:
        if cur != body.version:
            raise AppError(409, "CONFLICT_STALE", "配置已被他人修改，请刷新后重试")
        await db.execute(text(
            "UPDATE settings SET value=CAST(:v AS jsonb), version=version+1, "
            "updated_by=:u, updated_at=now() WHERE key=:k"),
            {"k": key, "v": json.dumps(body.value), "u": user["id"]})
    await audit_service.record(db, actor_id=user["id"], action="settings.update",
                               target_type="setting", target_id=key)
    await db.commit()
    await get_redis().delete(f"settings:{key}")
    return {"code": 0, "data": {"key": key, "updated": True}}


@router.get("/channels/{cid}/health")
async def channel_health(cid: int, hours: int = 24, _: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """EXT-012 渠道健康时序：近 N 小时采样 + 近 10 分钟失败率。"""
    rows = (await db.execute(text(
        "SELECT sampled_at,latency_ms,success,error_code FROM channel_health_samples "
        "WHERE channel_id=:c AND sampled_at >= now() - make_interval(hours => :h) "
        "ORDER BY sampled_at DESC LIMIT 500"), {"c": cid, "h": hours})).mappings().all()
    recent = (await db.execute(text(
        "SELECT count(*) AS n, count(*) FILTER (WHERE NOT success) AS fails "
        "FROM channel_health_samples "
        "WHERE channel_id=:c AND sampled_at >= now() - interval '10 minutes'"),
        {"c": cid})).mappings().one()
    n = int(recent["n"])
    return {"code": 0, "data": {
        "samples": [dict(r) for r in rows],
        "fail_rate": round(int(recent["fails"]) / n, 4) if n else None}}


@router.post("/alerts/test")
async def alert_test(_: dict[str, Any] = Admin,
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """EXT-013 告警测试发送：不受去重窗口限制。"""
    from app.services.health_service import _webhook_config, post_webhook
    cfg = await _webhook_config(db)
    if cfg is None:
        raise AppError(422, "ALERT_NOT_CONFIGURED", "请先配置并启用告警 webhook")
    ok = await post_webhook(cfg, "[AI聊天室] 告警通道测试：配置成功")
    if not ok:
        raise AppError(502, "ALERT_SEND_FAILED", "webhook 请求失败，请检查地址")
    return {"code": 0, "data": {"sent": True}}
