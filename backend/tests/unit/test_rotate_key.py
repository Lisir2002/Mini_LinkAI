"""US-025：渠道密钥轮换脚本。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]


async def test_rotation_reencrypts_all_channel_keys(spike_session):
    from app.core import crypto
    from tests.factories import cleanup_all, make_channel

    await cleanup_all(spike_session)
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    os.environ["CHANNEL_CIPHER_KEY"] = old_key
    crypto.reset_cipher()
    cid = await make_channel(spike_session, api_key_enc=crypto.encrypt_api_key("sk-rotate-me"))

    env = os.environ.copy()
    env.update({"DATABASE_URL": "postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_spike",
                "REDIS_URL": "redis://:spikepass@127.0.0.1:6379/15",
                "JWT_SECRET": "spike-secret-not-for-production-0123456789",
                "CHANNEL_CIPHER_KEY": old_key, "NEW_CHANNEL_CIPHER_KEY": new_key,
                "PYTHONPATH": str(BACKEND)})
    r = subprocess.run([sys.executable, "-m", "scripts.rotate_cipher_key", "--yes"],
                       cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]

    enc = (await spike_session.execute(
        text("SELECT api_key_enc FROM channels WHERE id=:i"), {"i": cid})).scalar_one()
    assert Fernet(new_key.encode()).decrypt(enc.encode()).decode() == "sk-rotate-me"
    try:
        Fernet(old_key.encode()).decrypt(enc.encode())
        raise AssertionError("旧密钥仍能解密，说明未真正轮换")
    except InvalidToken:
        pass
