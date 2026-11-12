"""业务异常与错误码（PRD 10.2）。"""
from __future__ import annotations


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, **detail: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
