"""渠道健康巡检（PRD 5.3）：成功即清零失败计数并恢复自动禁用的渠道。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.llm.services.channel_service import build_adapter


async def check_channels(session: AsyncSession) -> int:
    rows = (await session.execute(text(
        "SELECT id,name,type,base_url,api_key_enc,supported_params,"
        "timeout_first_token_ms,timeout_total_ms,status FROM channels "
        "WHERE status IN ('enabled','auto_disabled') ORDER BY id"))).mappings().all()
    recovered = 0
    for r in rows:
        res = await build_adapter(dict(r)).test_connectivity()
        if res.ok:
            await session.execute(text(
                "UPDATE channels SET fail_count=0, cooldown_until=NULL, last_check_at=now(), "
                "last_latency_ms=:l, status='enabled' WHERE id=:i"),
                {"l": res.latency_ms, "i": r["id"]})
            if r["status"] == "auto_disabled":
                recovered += 1
                log_event("channel.recovered", status="success", channel_id=r["id"])
        else:
            await session.execute(text(
                "UPDATE channels SET last_check_at=now() WHERE id=:i"), {"i": r["id"]})
        await session.commit()
    return recovered
