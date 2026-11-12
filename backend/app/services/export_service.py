"""EXT-010 导出渲染：Markdown / JSON 两种格式。"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from fastapi import Response

from app.core.errors import AppError


def render_export(title: str, messages: list[dict[str, Any]], fmt: str) -> Response:
    if fmt not in ("md", "json"):
        raise AppError(422, "EXPORT_FORMAT_INVALID", "format 仅支持 md/json")
    safe = quote(title) or "export"
    if fmt == "json":
        body = json.dumps({"title": title, "messages": messages},
                          ensure_ascii=False, indent=2, default=str)
        return Response(content=body, media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename*=UTF-8''{safe}.json"})
    lines = [f"# {title}", ""]
    for m in messages:
        who = m.get("nickname") or ("AI" if m["role"] == "assistant"
                                    else "我" if m["role"] == "user" else "系统")
        lines.append(f"**{who}**：{m['content']}")
        lines.append("")
    return Response(content="\n".join(lines), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{safe}.md"})