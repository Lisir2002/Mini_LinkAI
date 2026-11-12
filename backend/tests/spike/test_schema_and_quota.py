"""基座验证 spike：把 PRD 的 DDL 建到真实 PostgreSQL 16 上，并验证配额不超卖。

这是本项目第一优先级的正确性风险：并发 @AI 时额度不能被扣穿。
使用独立数据库 ai_chatroom_spike，与 smoke 用的 ai_chatroom_test 隔离。
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCHEMA_SQL = BACKEND.parent / "scripts" / "prd_schema.sql"
DSN = dict(host="127.0.0.1", port=5432, user="aicr",
           password="spikepass", database="ai_chatroom_spike")


@pytest.fixture(scope="module")
def schema():
    async def _apply():
        conn = await asyncpg.connect(**DSN)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        finally:
            await conn.close()
    asyncio.run(_apply())
    return True


def test_full_ddl_executes_on_pg16(schema):
    async def _count():
        conn = await asyncpg.connect(**DSN)
        try:
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1")
            idx = await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE schemaname='public'")
            return [r["table_name"] for r in tables], idx
        finally:
            await conn.close()
    tables, idx = asyncio.run(_count())
    assert len(tables) == 25, f"表数量不符: {len(tables)} → {tables}"
    assert idx >= 27, f"索引数量不足: {idx}"


def test_quota_no_oversell_under_20_concurrent(schema):
    """20 个并发各预扣 100，上限 1000：必须恰好 10 个成功，总量恰好 1000。"""
    from app.services.quota_service import freeze

    async def _run():
        conn = await asyncpg.connect(**DSN)
        try:
            await conn.execute("DELETE FROM daily_usage")
            await conn.execute("DELETE FROM users")
            uid = await conn.fetchval(
                "INSERT INTO users (email,password_hash,nickname,role) "
                "VALUES ('spike@x.com','x','spike','admin') RETURNING id")
        finally:
            await conn.close()

        # 每个协程用独立连接，才是真实的数据库级并发
        results = await asyncio.gather(*[
            freeze(quota_date=date(2026, 11, 11), owner_id=uid, room_id=None,
                   tokens=100, limit=1000, dsn=DSN)
            for _ in range(20)
        ])
        conn = await asyncpg.connect(**DSN)
        try:
            total = await conn.fetchval(
                "SELECT total_tokens FROM daily_usage "
                "WHERE quota_date=$1 AND owner_id=$2 AND room_id IS NULL",
                date(2026, 11, 11), uid)
        finally:
            await conn.close()
        return sum(1 for r in results if r), total

    ok, total = asyncio.run(_run())
    assert ok == 10, f"成功数应为 10，实际 {ok}（超卖或误拒）"
    assert total == 1000, f"总量应恰为 1000，实际 {total}"
