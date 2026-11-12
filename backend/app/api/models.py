"""用户可见模型列表（PRD 8.2 / US-034）。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.db import get_session
from app.deps import get_current_user
from app.redis_client import get_redis

router = APIRouter(prefix="/api", tags=["models"])
CACHE_KEY = "models:enabled"


@router.get("/models")
async def visible_models(_: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    r = get_redis()
    cached = await r.get(CACHE_KEY)
    if cached is not None:
        return {"code": 0, "data": {"items": json.loads(cached)}}
    async with get_session() as s:
        rows = (await s.execute(text(
            "SELECT DISTINCT m.public_name,m.display_name,m.tier,m.context_limit,"
            "m.price_input,m.price_output,m.is_default,m.sort_order "
            "FROM models m JOIN model_channels mc ON mc.model_id=m.id "
            "JOIN channels c ON c.id=mc.channel_id "
            "WHERE m.enabled AND mc.enabled AND c.status='enabled' "
            "ORDER BY m.sort_order,m.public_name"))).mappings().all()
    items = [dict(x) for x in rows]
    await r.set(CACHE_KEY, json.dumps(items, default=str), ex=300)
    return {"code": 0, "data": {"items": items}}
