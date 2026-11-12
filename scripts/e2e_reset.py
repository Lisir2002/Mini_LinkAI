"""把本地演示库重置到可重复验证的初始状态（仅用于开发/验证，不用于生产）。"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg

from app.core.security import hash_password

TABLES = ("daily_usage", "usage_logs", "notifications", "audit_logs", "message_feedbacks",
          "model_tokenizer_drift", "messages",
          "room_join_requests", "room_members", "rooms", "model_channels", "models",
          "channels", "conversations", "invite_codes", "settings")


async def main() -> None:
    u = urlparse(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(host=u.hostname, port=u.port or 5432, user=u.username,
                                 password=u.password, database=u.path.lstrip("/"))
    try:
        async with conn.transaction():
            for t in TABLES:
                await conn.execute(f"DELETE FROM {t}")  # noqa: S608 - 固定白名单
            await conn.execute("DELETE FROM users")
            await conn.execute(
                "INSERT INTO users (email,password_hash,nickname,role,must_change_password,"
                "daily_msg_limit,daily_token_limit) VALUES ($1,$2,'管理员','admin',true,200,500000)",
                "admin@demo.com", hash_password("AdminPass2026"))
        print("演示库已重置：admin@demo.com / AdminPass2026（首次登录需改密）")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
