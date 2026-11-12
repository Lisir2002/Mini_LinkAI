"""US-007~013：Alembic 迁移必须能从零建出全量 schema，且可逐级升降。"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

BACKEND = Path(__file__).resolve().parents[2]
DSN = dict(host="127.0.0.1", port=5432, user="aicr",
           password="spikepass", database="ai_chatroom_test")


def _env() -> dict[str, str]:
    e = os.environ.copy()
    e["DATABASE_URL"] = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_test"
    e["PYTHONPATH"] = str(BACKEND)
    return e


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, env=_env(), capture_output=True, text=True)


def _query(coro):
    return asyncio.run(coro)


async def _tables() -> list[str]:
    conn = await asyncpg.connect(**DSN)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name <> 'alembic_version' ORDER BY 1")
        return [r[0] for r in rows]
    finally:
        await conn.close()


async def _named_indexes() -> int:
    conn = await asyncpg.connect(**DSN)
    try:
        return await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
            "AND (indexname LIKE 'idx_%' OR indexname LIKE 'uniq_%')")
    finally:
        await conn.close()


def test_upgrade_head_builds_full_schema():
    assert _alembic("downgrade", "base").returncode == 0
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-1200:]
    tables = _query(_tables())
    assert len(tables) == 25, f"表数 {len(tables)}: {tables}"
    n = _query(_named_indexes())
    assert n == 38, f"命名索引应 38 条，实际 {n}"


def test_revisions_apply_incrementally():
    assert _alembic("downgrade", "base").returncode == 0
    counts = []
    for _ in range(40):  # 动态升级到 head，不随迁移数量写死
        r = _alembic("upgrade", "+1")
        if r.returncode != 0:
            break
        counts.append(len(_query(_tables())))
    assert counts, "没有任何可升级的 revision"
    assert counts == sorted(counts), f"表数未单调递增: {counts}"
    assert counts[-1] == 25, f"逐级升级后表数 {counts[-1]}，应为 25"
    assert len(counts) >= 6, f"迁移粒度不足，只有 {len(counts)} 级"


def test_downgrade_base_removes_all_tables():
    assert _alembic("upgrade", "head").returncode == 0
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr[-1200:]
    assert _query(_tables()) == [], f"残留表: {_query(_tables())}"


def test_zz_restore_head_for_later_suites():
    """迁移用例会把库降到 base，收尾恢复到 head，供后续接口用例使用。"""
    assert _alembic("upgrade", "head").returncode == 0
