"""US-014：种子脚本必须幂等、按协议建渠道、不泄露明文密钥。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
SEED_DB = "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike"


def _run_seed(**extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": SEED_DB,
        "REDIS_URL": "redis://:spikepass@127.0.0.1:6379/15",
        "JWT_SECRET": "spike-secret-not-for-production-0123456789",
        "CHANNEL_CIPHER_KEY": Fernet.generate_key().decode(),
        "SEED_ADMIN_EMAIL": "admin@example.com",
        "SEED_ADMIN_PASSWORD": "AdminPass2026",
        "PYTHONPATH": str(BACKEND),
    })
    env.update(extra)
    return subprocess.run([sys.executable, "-m", "scripts.seed"],
                          cwd=BACKEND, env=env, capture_output=True, text=True)


async def test_seed_creates_admin_and_defaults(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    r = _run_seed()
    assert r.returncode == 0, r.stderr[-1500:]
    row = (await spike_session.execute(
        text("SELECT role, must_change_password FROM users WHERE email='admin@example.com'"))).one()
    assert row.role == "admin" and row.must_change_password is True
    n = (await spike_session.execute(
        text("SELECT count(*) FROM models WHERE public_name IN ('smart','fast')"))).scalar_one()
    assert n == 2
    d = (await spike_session.execute(
        text("SELECT public_name FROM models WHERE is_default"))).scalar_one()
    assert d == "smart"


async def test_seed_is_idempotent(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    assert _run_seed().returncode == 0
    assert _run_seed().returncode == 0
    for t, expect in (("users", 1), ("models", 2), ("invite_codes", 5), ("rooms", 1)):
        n = (await spike_session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
        assert n == expect, f"{t} 重复执行后为 {n}，应为 {expect}"


async def test_seed_creates_channels_by_protocol_and_skips_empty(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    r = _run_seed(
        SEED_OPENAI_COMPAT_1_NAME="DeepSeek",
        SEED_OPENAI_COMPAT_1_BASE_URL="https://api.deepseek.com/v1",
        SEED_OPENAI_COMPAT_1_KEY="sk-test-deepseek-9999",
        SEED_ANTHROPIC_KEY="sk-ant-test-8888",
        SEED_GEMINI_KEY="",
    )
    assert r.returncode == 0, r.stderr[-1500:]
    rows = (await spike_session.execute(
        text("SELECT type, count(*) FROM channels GROUP BY type ORDER BY type"))).all()
    got = {r[0]: r[1] for r in rows}
    assert got.get("openai_compatible") == 1
    assert got.get("anthropic") == 1
    assert "gemini" not in got, "空 Key 的协议不应建渠道"
    assert "sk-test-deepseek-9999" not in r.stdout
    assert "AdminPass2026" not in r.stdout


async def test_seed_prints_five_invite_codes_once(spike_session):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    r1 = _run_seed()
    codes = (await spike_session.execute(text("SELECT code FROM invite_codes"))).scalars().all()
    assert len(codes) == 5
    for c in codes:
        assert c in r1.stdout, "邀请码应打印到控制台供一次性取用"
    r2 = _run_seed()
    assert sum(1 for c in codes if c in r2.stdout) == 0, "重复执行不应再次生成或打印邀请码"
