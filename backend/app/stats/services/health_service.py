"""EXT-012 渠道健康：采样、清理、失败率与熔断告警（10 分钟去重）。"""
from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.core.redis_client import get_redis
from app.llm.services.channel_service import build_adapter

RETENTION_DAYS = 7
RATE_WINDOW_MIN = 10
RATE_MIN_SAMPLES = 4
RATE_THRESHOLD = 0.5
ALERT_DEDUP_SEC = 600


async def sample_all(session: AsyncSession) -> int:
    rows = (await session.execute(text(
        "SELECT id,name,type,base_url,api_key_enc,supported_params,"
        "timeout_first_token_ms,timeout_total_ms,status FROM channels "
        "WHERE status IN ('enabled','auto_disabled') ORDER BY id"))).mappings().all()
    for r in rows:
        res = await build_adapter(dict(r)).test_connectivity()
        await session.execute(text(
            "INSERT INTO channel_health_samples (channel_id,latency_ms,success,error_code) "
            "VALUES (:c,:l,:s,:e)"),
            {"c": r["id"], "l": res.latency_ms, "s": res.ok,
             "e": None if res.ok else (res.error_kind or "error")[:32]})
        await session.commit()
    return len(rows)


async def cleanup_samples(session: AsyncSession) -> int:
    row = (await session.execute(text(
        "WITH gone AS (DELETE FROM channel_health_samples "
        "WHERE sampled_at < now() - make_interval(days => :d) RETURNING 1) "
        "SELECT count(*) FROM gone"), {"d": RETENTION_DAYS})).scalar_one()
    await session.commit()
    return int(row)


async def _webhook_config(session: AsyncSession) -> dict[str, Any] | None:
    raw = (await session.execute(text(
        "SELECT value FROM settings WHERE key='alert_webhook'"))).scalar_one_or_none()
    if raw is None:
        return None
    cfg = raw if isinstance(raw, dict) else json.loads(raw)
    if not cfg.get("enabled", True) or not str(cfg.get("url", "")).startswith(("http://", "https://")):
        return None
    return cfg


async def send_alert(session: AsyncSession, channel_id: int, event: str, message: str) -> bool:
    """触发告警；同一渠道同一事件 10 分钟内只发一次。返回是否实际发送。"""
    cfg = await _webhook_config(session)
    if cfg is None:
        return False
    r = get_redis()
    if not await r.set(f"alert:{channel_id}:{event}", "1", nx=True, ex=ALERT_DEDUP_SEC):
        return False
    name = (await session.execute(text("SELECT name FROM channels WHERE id=:i"),
                                  {"i": channel_id})).scalar_one_or_none() or str(channel_id)
    text_body = f"[AI聊天室] 渠道「{name}」{message}"
    ok = await post_webhook(cfg, text_body, channel_id=channel_id, event=event)
    if ok:
        log_event("channel.alert_sent", status="success", channel_id=channel_id,
                  alert_event=event)
    return ok


async def post_webhook(cfg: dict[str, Any], text_body: str, *,
                       channel_id: int = 0, event: str = "test") -> bool:
    kind = cfg.get("type", "generic")
    if kind in ("dingtalk", "feishu"):
        payload: dict[str, Any] = {"msgtype": "text", "text": {"content": text_body}}
    else:
        payload = {"channel_id": channel_id, "event": event, "message": text_body}
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(str(cfg["url"]), json=payload)
        return True
    except Exception as exc:       # noqa: BLE001 - 告警失败不得影响主链路
        log_event("channel.alert_failed", status="failure", channel_id=channel_id,
                  error=str(exc)[:120])
        return False


async def check_failure_rates(session: AsyncSession) -> int:
    rows = (await session.execute(text(
        "SELECT channel_id, count(*) AS n, "
        "count(*) FILTER (WHERE NOT success) AS fails "
        "FROM channel_health_samples "
        "WHERE sampled_at >= now() - make_interval(mins => :w) "
        "GROUP BY channel_id HAVING count(*) >= :m"),
        {"w": RATE_WINDOW_MIN, "m": RATE_MIN_SAMPLES})).mappings().all()
    fired = 0
    for r in rows:
        rate = int(r["fails"]) / int(r["n"])
        if rate > RATE_THRESHOLD:
            if await send_alert(session, int(r["channel_id"]), "fail_rate",
                                f"近 {RATE_WINDOW_MIN} 分钟失败率 {rate:.0%}"):
                fired += 1
    return fired