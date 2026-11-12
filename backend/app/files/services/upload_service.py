"""EXT-020 文件上传：魔数校验、UUID 重命名、本地隔离存储、附件权限。"""
from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError

MAX_BYTES = 10 * 1024 * 1024

# 魔数 → (content_type, kind)；以内容为准，扩展名仅作展示
MAGIC: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "image"),
    (b"\xff\xd8\xff", "image/jpeg", "image"),
    (b"GIF87a", "image/gif", "image"),
    (b"GIF89a", "image/gif", "image"),
    (b"%PDF", "application/pdf", "file"),
]


def detect_type(head: bytes) -> tuple[str, str] | None:
    for magic, ctype, kind in MAGIC:
        if head.startswith(magic):
            return ctype, kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "image"
    return None


async def save_upload(session: AsyncSession, *, owner_id: int, filename: str,
                      data: bytes) -> dict[str, Any]:
    if not settings.FEATURE_FILE_UPLOAD:
        raise AppError(403, "FEATURE_DISABLED", "文件上传功能未启用")
    if len(data) > MAX_BYTES:
        raise AppError(413, "UPLOAD_TOO_LARGE", "文件不能超过 10MB")
    detected = detect_type(data[:16])
    if detected is None:
        raise AppError(422, "UPLOAD_TYPE_INVALID", "仅支持 PNG/JPEG/GIF/WebP/PDF，且以文件头校验")
    ctype, kind = detected
    stored = f"{uuid.uuid4().hex}.{ctype.split('/')[-1]}"
    directory = Path(settings.UPLOAD_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / stored).write_bytes(data)
    row = (await session.execute(text(
        "INSERT INTO uploads (owner_id,filename,stored_name,content_type,size_bytes,kind) "
        "VALUES (:o,:f,:s,:c,:b,:k) RETURNING id"),
        {"o": owner_id, "f": filename[:255], "s": stored, "c": ctype,
         "b": len(data), "k": kind})).mappings().one()
    await session.commit()
    return {"id": row["id"], "url": f"/api/uploads/{row['id']}/content",
            "filename": filename[:255], "content_type": ctype,
            "size_bytes": len(data), "kind": kind}


async def load_upload(session: AsyncSession, upload_id: int) -> dict[str, Any] | None:
    row = (await session.execute(text("SELECT * FROM uploads WHERE id=:i"),
                                 {"i": upload_id})).mappings().first()
    return dict(row) if row else None


async def can_access(session: AsyncSession, user: dict[str, Any], upload_id: int) -> bool:
    """属主/管理员，或能看到引用该附件的消息（会话属主/房间成员）。"""
    if user["role"] == "admin":
        return True
    row = (await session.execute(text("SELECT owner_id FROM uploads WHERE id=:i"),
                                 {"i": upload_id})).mappings().first()
    if row is None:
        return False
    if row["owner_id"] == user["id"]:
        return True
    vis = (await session.execute(text(
        "SELECT 1 FROM messages m "
        "LEFT JOIN conversations c ON c.id=m.conversation_id "
        "WHERE m.attachment_id=:a AND ("
        "  c.user_id=:u OR EXISTS (SELECT 1 FROM room_members rm "
        "    WHERE rm.room_id=m.room_id AND rm.user_id=:u)) LIMIT 1"),
        {"a": upload_id, "u": user["id"]})).first()
    if vis is not None:
        return True
    # 私聊附件：收发双方可见，且须仍为好友（解除好友即收回）
    dm_vis = (await session.execute(text(
        "SELECT 1 FROM direct_messages dm WHERE dm.attachment_id=:a "
        "AND (dm.sender_id=:u OR dm.recipient_id=:u) "
        "AND EXISTS (SELECT 1 FROM friendships f WHERE f.status='accepted' AND "
        "  ((f.requester_id=dm.sender_id AND f.addressee_id=dm.recipient_id) "
        "   OR (f.requester_id=dm.recipient_id AND f.addressee_id=dm.sender_id))) LIMIT 1"),
        {"a": upload_id, "u": user["id"]})).first()
    return dm_vis is not None


def read_bytes(stored_name: str) -> bytes:
    return (Path(settings.UPLOAD_DIR) / stored_name).read_bytes()


def data_uri(row: dict[str, Any]) -> str:
    raw = read_bytes(row["stored_name"])
    return f"data:{row['content_type']};base64,{base64.b64encode(raw).decode()}"


async def validate_attachment(session: AsyncSession, user: dict[str, Any],
                              attachment_id: int | None) -> None:
    if attachment_id is None:
        return
    row = (await session.execute(text("SELECT owner_id FROM uploads WHERE id=:i"),
                                 {"i": attachment_id})).mappings().first()
    if row is None or row["owner_id"] != user["id"]:
        raise AppError(422, "ATTACHMENT_INVALID", "附件不存在或不属于你")

async def assemble_content(session: AsyncSession, attachment_id: int | None,
                           text_content: str, supports_vision: bool) -> Any:
    """视觉模型组装多模态 content；否则文本占位。"""
    if attachment_id is None:
        return text_content
    row = await load_upload(session, attachment_id)
    if row is None:
        return text_content
    if supports_vision and row["kind"] == "image":
        return [{"type": "text", "text": text_content},
                {"type": "image_url", "image_url": {"url": data_uri(row)}}]
    return text_content + "\n[图片]"
