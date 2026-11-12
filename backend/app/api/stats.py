"""管理端统计：EXT-003 反馈聚合 + EXT-007 实时看板 SSE。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, run_read
from app.deps import require_admin
from app.services.live_metrics import snapshot

router = APIRouter(prefix="/api/admin/stats", tags=["admin-stats"])
Admin = Depends(require_admin)


@router.get("/feedback")
async def feedback_stats(user: dict[str, Any] = Admin) -> dict[str, Any]:
    return await run_read(_feedback_stats)


async def _feedback_stats(db: AsyncSession) -> dict[str, Any]:
    total = (await db.execute(text(
        "SELECT count(*) FILTER (WHERE rating='up') AS up, "
        "count(*) FILTER (WHERE rating='down') AS down FROM message_feedbacks")
        )).mappings().one()
    up, down = int(total["up"]), int(total["down"])
    by_model = (await db.execute(text(
        "SELECT mo.id, mo.display_name, "
        "count(*) FILTER (WHERE f.rating='up') AS up, "
        "count(*) FILTER (WHERE f.rating='down') AS down "
        "FROM message_feedbacks f "
        "JOIN messages m ON m.id=f.message_id "
        "JOIN models mo ON mo.id=m.model_id "
        "GROUP BY mo.id, mo.display_name ORDER BY down DESC, mo.id"))).mappings().all()
    top_rooms = (await db.execute(text(
        "SELECT r.id, r.name, "
        "count(*) FILTER (WHERE f.rating='up') AS up, "
        "count(*) FILTER (WHERE f.rating='down') AS down "
        "FROM message_feedbacks f "
        "JOIN messages m ON m.id=f.message_id "
        "JOIN rooms r ON r.id=m.room_id "
        "GROUP BY r.id, r.name ORDER BY down DESC, r.id LIMIT 5"))).mappings().all()
    return {"code": 0, "data": {
        "total": {"up": up, "down": down,
                  "rate": round(up / (up + down), 4) if up + down else None},
        "by_model": [dict(r) for r in by_model],
        "top_rooms": [dict(r) for r in top_rooms],
    }}

@router.get("/live")
async def live(interval: int = Query(default=5, ge=1, le=60),
               ticks: int = Query(default=0, ge=0, le=1000),
               user: dict[str, Any] = Admin) -> StreamingResponse:
    """每 interval 秒推送一次实时指标；客户端断开即结束生成器。

    ticks>0 时限量推送后自动结束（管理员调试/测试用），0 为不限。
    """
    async def gen() -> AsyncIterator[str]:
        sent = 0
        while ticks == 0 or sent < ticks:
            tick = await run_read(snapshot)
            yield f"event: tick\ndata: {json.dumps(tick, ensure_ascii=False)}\n\n"
            sent += 1
            if ticks and sent >= ticks:
                break
            await asyncio.sleep(interval)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/overview")
async def overview(days: int = 30, user: dict[str, Any] = Admin) -> dict[str, Any]:
    """EXT-026 用量趋势：读预聚合表（副本优先，故障回退主库）。"""
    async def q(db: AsyncSession) -> list[dict[str, Any]]:
        rows = (await db.execute(text(
            "SELECT stat_date,ai_calls,total_tokens,cost,active_users,updated_at "
            "FROM stats_daily ORDER BY stat_date DESC LIMIT :d"),
            {"d": days})).mappings().all()
        return [dict(r) for r in reversed(rows)]

    items = await run_read(q)
    return {"code": 0, "data": {"items": items}}


@router.post("/recompute")
async def recompute(user: dict[str, Any] = Admin) -> dict[str, Any]:
    """手动触发预聚合（写操作恒走主库）；调度器每 10 分钟自动执行。"""
    from app.tasks.stats_precompute import precompute_stats

    async with get_session() as s:
        n = await precompute_stats(s)
    return {"code": 0, "data": {"days_updated": n}}
