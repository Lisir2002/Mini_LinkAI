"""薄入口：保留 uvicorn app.interfaces.app:app 部署命令兼容。应用装配在 interfaces/app.py。"""
from app.interfaces.app import app

__all__ = ["app"]
