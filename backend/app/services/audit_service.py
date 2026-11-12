"""审计日志（PRD 10.3）。detail 中的敏感字段一律剔除后再落库。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import SENSITIVE_KEYS


async def record(
    session: AsyncSession,
    *,
    actor_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    trace_id: str | None = None,
) -> None:
    safe = {k: v for k, v in (detail or {}).items() if k.lower() not in SENSITIVE_KEYS}
    await session.execute(
        text("INSERT INTO audit_logs (actor_id,action,target_type,target_id,detail,ip,trace_id) "
             "VALUES (:a,:ac,:tt,:ti,CAST(:d AS jsonb),CAST(:ip AS inet),CAST(:tr AS uuid))"),
        {"a": actor_id, "ac": action, "tt": target_type, "ti": target_id,
         "d": json.dumps(safe, ensure_ascii=False), "ip": ip, "tr": trace_id},
    )
