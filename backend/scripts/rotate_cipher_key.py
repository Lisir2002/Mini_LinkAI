"""渠道密钥轮换（US-025 / PRD 10.1 第五层）。

用旧 CHANNEL_CIPHER_KEY 解密、NEW_CHANNEL_CIPHER_KEY 加密回写。
执行前必须确认已备份；--yes 用于自动化。全程不打印任何密钥明文。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

import asyncpg
from cryptography.fernet import Fernet


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="跳过备份确认（自动化用）")
    args = ap.parse_args()

    old = os.environ.get("CHANNEL_CIPHER_KEY", "")
    new = os.environ.get("NEW_CHANNEL_CIPHER_KEY", "")
    if not old or not new:
        print("需要 CHANNEL_CIPHER_KEY（旧）与 NEW_CHANNEL_CIPHER_KEY（新）", file=sys.stderr)
        return 2
    if not args.yes:
        if input("确认已完成数据库备份？输入 yes 继续：").strip().lower() != "yes":
            print("已取消")
            return 1

    u = urlparse(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(host=u.hostname, port=u.port or 5432, user=u.username,
                                 password=u.password, database=u.path.lstrip("/"))
    fo, fn = Fernet(old.encode()), Fernet(new.encode())
    try:
        rows = await conn.fetch("SELECT id, api_key_enc FROM channels ORDER BY id")
        async with conn.transaction():
            for r in rows:
                plain = fo.decrypt(r["api_key_enc"].encode())
                await conn.execute(
                    "UPDATE channels SET api_key_enc=$1, updated_at=now() WHERE id=$2",
                    fn.encrypt(plain).decode(), r["id"])
        print(f"已轮换 {len(rows)} 个渠道的密钥（明文未输出）")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
