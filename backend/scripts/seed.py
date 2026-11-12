"""种子数据脚本（US-014 / PRD 28.1）。

按 FK 正序创建：admin → settings → 渠道 → models → model_channels → 示例房间 → 邀请码。
幂等：重复执行不产生重复数据。邀请码仅首次生成并打印到控制台一次。
明文密码与 API Key 绝不打印、绝不写日志。
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys

import asyncpg

from app.core.crypto import encrypt_api_key, key_hint
from app.core.security import hash_password

DEFAULT_SETTINGS: dict[str, str] = {
    "quota": '{"daily_msg_limit":50,"daily_token_limit":100000,'
             '"room_daily_token_budget":500000,"warn_ratio":0.8,"reset_tz":"Asia/Shanghai"}',
    "registration": '{"mode":"invite_code","require_invite":true}',
    "moderation": '{"enabled":true,"block_input":true,"block_output":true,"wordlist_version":1}',
    "feature_flags": '{"room_ai":true,"web_search":false,"voice_input":false,"file_upload":false}',
    "retention": '{"days":90}',
}


def _dsn() -> dict[str, object]:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlparse
    u = urlparse(url)
    return dict(host=u.hostname, port=u.port or 5432, user=u.username,
                password=u.password, database=u.path.lstrip("/"))


def _channel_specs() -> list[tuple[str, str, str, str]]:
    """返回 (name, protocol, base_url, plain_key)，空 Key 的协议自动跳过。"""
    specs: list[tuple[str, str, str, str]] = []
    for i in (1, 2):
        key = os.environ.get(f"SEED_OPENAI_COMPAT_{i}_KEY", "")
        if key:
            specs.append((
                os.environ.get(f"SEED_OPENAI_COMPAT_{i}_NAME") or f"openai-compat-{i}",
                "openai_compatible",
                os.environ.get(f"SEED_OPENAI_COMPAT_{i}_BASE_URL", ""),
                key,
            ))
    if os.environ.get("SEED_ANTHROPIC_KEY"):
        specs.append(("Anthropic", "anthropic", "https://api.anthropic.com",
                      os.environ["SEED_ANTHROPIC_KEY"]))
    if os.environ.get("SEED_GEMINI_KEY"):
        specs.append(("Google AI Studio", "gemini",
                      "https://generativelanguage.googleapis.com",
                      os.environ["SEED_GEMINI_KEY"]))
    return specs


async def main() -> int:
    admin_email = os.environ.get("SEED_ADMIN_EMAIL", "")
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD", "")
    if not admin_email or not admin_password:
        print("缺少 SEED_ADMIN_EMAIL 或 SEED_ADMIN_PASSWORD，拒绝执行", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(**_dsn())  # type: ignore[arg-type]
    try:
        admin_id = await conn.fetchval("SELECT id FROM users WHERE email=$1", admin_email)
        if admin_id is None:
            admin_id = await conn.fetchval(
                "INSERT INTO users (email,password_hash,nickname,role,must_change_password) "
                "VALUES ($1,$2,'管理员','admin',true) RETURNING id",
                admin_email, hash_password(admin_password))
            print(f"已创建管理员 {admin_email}（首次登录必须改密）")
        else:
            print(f"管理员 {admin_email} 已存在，跳过")

        for k, v in DEFAULT_SETTINGS.items():
            await conn.execute(
                "INSERT INTO settings (key,value) VALUES ($1,$2::jsonb) "
                "ON CONFLICT (key) DO NOTHING", k, v)

        created_channels: list[tuple[int, str]] = []
        for name, proto, base_url, plain in _channel_specs():
            if not base_url:
                print(f"渠道 {name} 缺少 base_url，跳过", file=sys.stderr)
                continue
            cid = await conn.fetchval("SELECT id FROM channels WHERE name=$1", name)
            if cid is None:
                cid = await conn.fetchval(
                    "INSERT INTO channels (name,type,base_url,api_key_enc,api_key_hint) "
                    "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                    name, proto, base_url, encrypt_api_key(plain), key_hint(plain))
                print(f"已创建渠道 {name}（协议 {proto}）")
            created_channels.append((int(cid), proto))

        for public, display, tier, ctx, pin, pout in (
            ("smart", "主力模型", "premium", 32768, 2.4, 9.6),
            ("fast", "低价模型", "fast", 65536, 1.0, 2.0),
        ):
            await conn.execute(
                "INSERT INTO models (public_name,display_name,tier,context_limit,"
                "price_input,price_output) VALUES ($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (public_name) DO NOTHING",
                public, display, tier, ctx, pin, pout)

        has_default = await conn.fetchval("SELECT 1 FROM models WHERE is_default")
        if not has_default:
            await conn.execute("UPDATE models SET is_default=true WHERE public_name='smart'")

        for public, env_key in (("smart", "SEED_SMART_UPSTREAM_MODEL"),
                                ("fast", "SEED_FAST_UPSTREAM_MODEL")):
            upstream = os.environ.get(env_key, "")
            if upstream and created_channels:
                mid = await conn.fetchval("SELECT id FROM models WHERE public_name=$1", public)
                await conn.execute(
                    "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
                    "VALUES ($1,$2,$3) ON CONFLICT (model_id,channel_id) DO NOTHING",
                    mid, created_channels[0][0], upstream)

        room_id = await conn.fetchval(
            "SELECT id FROM rooms WHERE name='闲聊室' AND owner_id=$1", admin_id)
        if room_id is None:
            room_id = await conn.fetchval(
                "INSERT INTO rooms (name,description,owner_id,access_type) "
                "VALUES ('闲聊室','随便聊，@AI 才触发模型',$1,'public') RETURNING id", admin_id)
            await conn.execute(
                "INSERT INTO room_members (room_id,user_id,role) VALUES ($1,$2,'owner') "
                "ON CONFLICT DO NOTHING", room_id, admin_id)
            await conn.execute("UPDATE rooms SET member_count=1 WHERE id=$1", room_id)
            print("已创建示例房间「闲聊室」")

        existing = await conn.fetchval("SELECT count(*) FROM invite_codes")
        if existing == 0:
            codes = [f"RM-{secrets.token_hex(3).upper()}" for _ in range(5)]
            for c in codes:
                await conn.execute(
                    "INSERT INTO invite_codes (code,created_by,max_uses) VALUES ($1,$2,1)",
                    c, admin_id)
            await conn.execute(
                "INSERT INTO audit_logs (actor_id,action,target_type,detail) "
                "VALUES ($1,'invite.generate','invite_code',CAST($2 AS jsonb))",
                admin_id, '{"count":5}')
            print("邀请码（仅此一次显示，请妥善保存）：")
            for c in codes:
                print(f"  {c}")
        else:
            print(f"已有 {existing} 个邀请码，跳过生成")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
