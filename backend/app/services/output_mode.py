"""EXT-018 结构化输出：约束注入与校验（JSON 走 jsonschema）。"""
from __future__ import annotations

import json

import jsonschema

MODES = ("free", "json", "table", "code")


def constraint_prompt(mode: str, schema: str | None) -> str:
    if mode == "json":
        base = ("\n\n【输出约束】你必须只输出一个合法的 JSON 对象，"
                "不要用 markdown 代码围栏包裹，不要输出任何额外文本。")
        if schema:
            base += f"输出必须符合以下 JSON Schema：{schema}"
        return base
    if mode == "table":
        return "\n\n【输出约束】只输出一个 Markdown 表格，不要输出表格以外的额外文本。"
    if mode == "code":
        return ("\n\n【输出约束】只输出一个代码块（用 ``` 包裹并标注语言），"
                "不要输出额外的解释文本。")
    return ""


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def validate_output(mode: str, content: str, schema: str | None) -> bool:
    if mode != "json":
        return True
    try:
        data = json.loads(strip_fences(content))
    except (ValueError, TypeError):
        return False
    if schema:
        try:
            jsonschema.validate(data, json.loads(schema))
        except (jsonschema.ValidationError, jsonschema.SchemaError, ValueError):
            return False
    return True