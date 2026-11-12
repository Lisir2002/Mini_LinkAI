"""US-003：结构化日志、脱敏、异常不泄露堆栈。"""
from __future__ import annotations

import json

import httpx


def test_log_event_emits_json_with_required_fields(capsys):
    from app.core.logging import configure_logging, log_event

    configure_logging()
    log_event("user.login", user_id=42, status="success", trace_id="t-123")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(out)
    for k in ("timestamp", "level", "trace_id", "action", "status"):
        assert k in rec, f"缺少字段 {k}: {rec}"
    assert rec["action"] == "user.login"
    assert rec["user_id"] == 42


def test_sensitive_values_never_appear_in_logs(capsys):
    from app.core.logging import configure_logging, log_event

    configure_logging()
    log_event("channel.create", password="Sup3rSecret!", token="jwt-abc",
              api_key="sk-live-9999", content="用户消息正文全文")
    out = capsys.readouterr().out
    assert out.strip(), "日志为空会让本测试空转通过"
    for leaked in ("Sup3rSecret!", "jwt-abc", "sk-live-9999", "用户消息正文全文"):
        assert leaked not in out, f"敏感值泄露: {leaked}"


def test_email_and_phone_are_masked(capsys):
    from app.core.logging import configure_logging, log_event, mask_email, mask_phone

    assert mask_email("xiaowan@example.com") == "x***n@example.com"
    assert mask_phone("13812345678") == "138****5678"
    configure_logging()
    log_event("user.login", email="xiaowan@example.com", phone="13812345678")
    out = capsys.readouterr().out
    assert out.strip(), "日志为空会让本测试空转通过"
    assert "xiaowan@example.com" not in out
    assert "13812345678" not in out
    assert "x***n@example.com" in out


async def test_unhandled_exception_hides_stack_and_returns_trace_id():
    from app.main import app

    async def boom() -> dict:
        raise RuntimeError("内部细节不应出现在响应里")

    app.add_api_route("/_test/boom", boom, methods=["GET"])
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/_test/boom")
        assert r.status_code == 500
        body = r.json()
        assert body["code"] == "INTERNAL"
        assert body["trace_id"]
        assert "内部细节" not in r.text
        assert "Traceback" not in r.text
    finally:
        app.router.routes = [x for x in app.router.routes
                             if getattr(x, "path", None) != "/_test/boom"]
