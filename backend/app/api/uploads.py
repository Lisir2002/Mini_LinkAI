"""EXT-020 上传接口：multipart 上传 + 鉴权内容读取。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.deps import get_current_user, get_db
from app.services import upload_service

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
User = Depends(get_current_user)


@router.post("")
async def upload(file: UploadFile, user: dict[str, Any] = User,
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    data = await file.read()
    result = await upload_service.save_upload(
        db, owner_id=user["id"], filename=file.filename or "file", data=data)
    return {"code": 0, "data": result}


@router.get("/{uid}/content")
async def content(uid: int, user: dict[str, Any] = User,
                  db: AsyncSession = Depends(get_db)) -> Response:
    row = await upload_service.load_upload(db, uid)
    if row is None:
        raise AppError(404, "UPLOAD_NOT_FOUND", "文件不存在")
    if not await upload_service.can_access(db, user, uid):
        raise AppError(403, "FORBIDDEN", "无权访问该文件")
    try:
        data = upload_service.read_bytes(row["stored_name"])
    except FileNotFoundError:
        raise AppError(404, "UPLOAD_NOT_FOUND", "文件已丢失") from None
    return Response(content=data, media_type=row["content_type"],
                    headers={"Cache-Control": "private, max-age=86400"})