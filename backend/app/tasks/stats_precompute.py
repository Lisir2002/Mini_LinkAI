"""EXT-026 统计预聚合：usage_logs 按日汇总到 stats_daily（幂等 upsert）。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WINDOW_DAYS = 35


async def precompute_stats(session: AsyncSession, days: int = WINDOW_DAYS) -> int:
    row = (await session.execute(text(
        "INSERT INTO stats_daily (stat_date, ai_calls, total_tokens, cost, active_users) "
        "SELECT quota_date, count(*), coalesce(sum(total_tokens),0), "
        "coalesce(sum(cost),0), count(DISTINCT user_id) "
        "FROM usage_logs WHERE status='settled' "
        "AND quota_date >= CURRENT_DATE - make_interval(days => :d) "
        "GROUP BY quota_date "
        "ON CONFLICT (stat_date) DO UPDATE SET "
        "ai_calls=EXCLUDED.ai_calls, total_tokens=EXCLUDED.total_tokens, "
        "cost=EXCLUDED.cost, active_users=EXCLUDED.active_users, updated_at=now() "
        "RETURNING 1"), {"d": days})).all()
    await session.commit()
    return len(row)
