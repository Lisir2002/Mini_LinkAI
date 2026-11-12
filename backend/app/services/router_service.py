"""渠道选路与容错（PRD 5.3）+ EXT-014 A/B 实验分桶。"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class NoChannelAvailable(Exception):
    pass


async def select_channel(session: AsyncSession, public_name: str) -> dict[str, Any]:
    rows = (await session.execute(text(
        "SELECT c.*, mc.upstream_model FROM model_channels mc "
        "JOIN channels c ON c.id=mc.channel_id JOIN models m ON m.id=mc.model_id "
        "WHERE m.public_name=:n AND m.enabled AND mc.enabled AND c.status='enabled' "
        "AND (c.cooldown_until IS NULL OR c.cooldown_until < now()) "
        "ORDER BY c.priority DESC, c.weight DESC"), {"n": public_name})).mappings().all()
    if not rows:
        raise NoChannelAvailable(public_name)
    top = rows[0]["priority"]
    pool = [dict(r) for r in rows if r["priority"] == top]
    total = sum(max(c["weight"], 0) for c in pool)
    if total <= 0:
        return pool[0]
    pick = random.uniform(0, total)          # noqa: S311 - 非密码学用途
    acc = 0.0
    for c in pool:
        acc += max(c["weight"], 0)
        if pick <= acc:
            return c
    return pool[-1]


def bucket_of(user_id: int, ratio_a: int) -> str:
    """稳定哈希分桶：同一用户在同一比例下恒同桶（跨进程一致，不用内置 hash）。"""
    h = int(hashlib.md5(str(user_id).encode()).hexdigest(), 16) % 100  # noqa: S324
    return "a" if h < ratio_a else "b"


async def pick_experiment(session: AsyncSession, model_id: int,
                          user_id: int | None) -> dict[str, Any] | None:
    """有运行中实验且分桶渠道可用时返回实验路由，否则 None 回退常规选路。"""
    if user_id is None:
        return None
    exp = (await session.execute(text(
        "SELECT * FROM route_experiments WHERE model_id=:m AND status='running'"),
        {"m": model_id})).mappings().first()
    if exp is None:
        return None
    bucket = bucket_of(user_id, int(exp["ratio_a"]))
    cid = exp["channel_a"] if bucket == "a" else exp["channel_b"]
    chan = (await session.execute(text(
        "SELECT c.*, mc.upstream_model FROM model_channels mc "
        "JOIN channels c ON c.id=mc.channel_id "
        "WHERE mc.model_id=:m AND mc.channel_id=:c AND mc.enabled AND c.status='enabled' "
        "AND (c.cooldown_until IS NULL OR c.cooldown_until < now())"),
        {"m": model_id, "c": cid})).mappings().first()
    if chan is None:
        return None
    return {"experiment_id": exp["id"], "bucket": bucket, "channel": dict(chan)}


async def route_channel(session: AsyncSession, public_name: str, model_id: int,
                        user_id: int | None) -> dict[str, Any]:
    """实验优先，其次常规优先级/权重选路。实验信息以 _ 前缀键附带。"""
    exp = await pick_experiment(session, model_id, user_id)
    if exp is not None:
        ch: dict[str, Any] = exp["channel"]
        ch["_experiment_id"] = exp["experiment_id"]
        ch["_bucket"] = exp["bucket"]
        return ch
    return await select_channel(session, public_name)


async def record_failure(session: AsyncSession, channel_id: int, *, kind: str) -> None:
    """鉴权类失败立即禁用；其余累计 3 次自动禁用，并写冷却窗口。"""
    prev = (await session.execute(text("SELECT status FROM channels WHERE id=:i"),
                                  {"i": channel_id})).scalar_one_or_none()
    if kind == "auth":
        await session.execute(
            text("UPDATE channels SET status='auto_disabled', fail_count=fail_count+1, "
                 "cooldown_until=now()+interval '60 s' WHERE id=:i"), {"i": channel_id})
    else:
        await session.execute(
            text("UPDATE channels SET fail_count=fail_count+1, "
                 "cooldown_until=now()+interval '60 s' WHERE id=:i"), {"i": channel_id})
        await session.execute(
            text("UPDATE channels SET status='auto_disabled' "
                 "WHERE id=:i AND fail_count>=3 AND status='enabled'"), {"i": channel_id})
    await session.commit()
    now_status = (await session.execute(text("SELECT status FROM channels WHERE id=:i"),
                                        {"i": channel_id})).scalar_one_or_none()
    if prev == "enabled" and now_status == "auto_disabled":
        from app.services.health_service import send_alert
        await send_alert(session, channel_id, "disabled",
                         "连续失败已自动熔断，冷却 60 秒后巡检恢复" if kind != "auth"
                         else "鉴权失败已立即禁用，请检查 API Key")


async def record_success(session: AsyncSession, channel_id: int) -> None:
    await session.execute(
        text("UPDATE channels SET fail_count=0, success_count=success_count+1 WHERE id=:i"),
        {"i": channel_id})
    await session.commit()
