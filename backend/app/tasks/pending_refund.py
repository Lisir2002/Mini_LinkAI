"""悬挂预扣兜底（PRD 5.6.4 / US-040）：进程崩溃也不让额度被永久冻结。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.services.quota_service import refund_call


async def refund_stale_pending(session: AsyncSession, *, older_than_minutes: int = 10) -> int:
    rows = (await session.execute(text(
        "SELECT call_id, owner_id, room_id, frozen_tokens, quota_date FROM usage_logs "
        "WHERE status='pending' AND created_at < now() - make_interval(mins => :m)"),
        {"m": older_than_minutes})).mappings().all()
    for r in rows:
        await refund_call(session, call_id=str(r["call_id"]), quota_date=r["quota_date"],
                          owner_id=r["owner_id"], room_id=r["room_id"],
                          frozen=int(r["frozen_tokens"]), reason="stale_pending_timeout")
    if rows:
        log_event("quota.stale_pending_refunded", status="success", count=len(rows))
    return len(rows)
