"""当前用户配额与重置倒计时（PRD 8.5）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.timeutil import quota_date, seconds_until_reset
from app.db import get_session
from app.deps import get_current_user

router = APIRouter(prefix="/api/quota", tags=["quota"])


@router.get("/me")
async def my_quota(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    qd = quota_date()
    async with get_session() as s:
        row = (await s.execute(text(
            "SELECT coalesce(sum(total_tokens),0) AS tokens, "
            "coalesce(sum(ai_call_count),0) AS calls, "
            "coalesce(sum(cost),0) AS cost FROM daily_usage "
            "WHERE owner_id=:u AND room_id IS NULL AND quota_date=:d"),
            {"u": user["id"], "d": qd})).mappings().first()
        month = (await s.execute(text(
            "SELECT coalesce(sum(cost),0) FROM daily_usage "
            "WHERE owner_id=:u AND room_id IS NULL AND date_trunc('month', quota_date) "
            "= date_trunc('month', CAST(:d AS date))"), {"u": user["id"], "d": qd})).scalar_one()
    tokens = int(row["tokens"]) if row else 0
    calls = int(row["calls"]) if row else 0
    cost_today = float(row["cost"]) if row else 0.0
    return {"code": 0, "data": {
        "quota_date": qd.isoformat(),
        "msg_limit": user["daily_msg_limit"], "token_limit": user["daily_token_limit"],
        "tokens_used": tokens, "ai_calls": calls,
        "cost_today": cost_today, "cost_month": float(month),
        "reset_in_seconds": seconds_until_reset(),
    }}
