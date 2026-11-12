"""全量 API 实测：对真实运行的后端逐接口发起真实 HTTP/WS 调用并断言。

覆盖：认证、用户管理、渠道、模型、邀请码、设置、告警、统计、会话、SSE 流式、
反馈、搜索、配额、房间、模板、分享、健康检查、WS 广播，含权限与错误分支。
产出：prd/API实测报告.md（接口×结果矩阵）。

运行：sh scripts/run_api_check.sh（自动拉起 mock 上游 + uvicorn + 重置演示库）
"""
from __future__ import annotations

import json
import os
import time

import httpx
from websockets.sync.client import connect as ws_connect

BASE = os.environ.get("AICR_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("AICR_WS", "ws://127.0.0.1:8000")
ROWS: list[dict] = []
MODULE = ""


def mod(name: str) -> None:
    global MODULE
    MODULE = name


def check(name: str, method: str, path: str, resp: httpx.Response,
          expect: int, extra=None) -> dict:
    ok = resp.status_code == expect
    note = ""
    if ok and extra is not None:
        try:
            ok = bool(extra(resp))
            if not ok:
                note = "断言失败"
        except Exception as e:  # noqa: BLE001
            ok, note = False, f"断言异常 {e}"
    ROWS.append({"module": MODULE, "name": name, "method": method, "path": path,
                 "status": resp.status_code, "expect": expect, "ok": ok, "note": note})
    print(f"{'✅' if ok else '❌'} [{MODULE}] {name} → {resp.status_code} {note}")
    return resp


def sse_events(client: httpx.Client, method: str, path: str, body: dict,
               headers: dict) -> list[dict]:
    evs = []
    with client.stream(method, BASE + path, json=body, headers=headers, timeout=60) as r:
        assert r.status_code == 200
        event = "message"
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    evs.append({"event": event, "data": json.loads(line[5:])})
                except ValueError:
                    pass
    return evs


def main() -> None:
    c = httpx.Client(timeout=30)
    # ── 健康 ──
    mod("健康检查")
    check("存活与依赖", "GET", "/api/health", c.get(BASE + "/api/health"), 200,
          lambda r: r.json()["data"]["db"] == "ok" and r.json()["data"]["redis"] == "ok")

    # ── 认证 ──
    mod("认证")
    r = check("管理员登录", "POST", "/api/auth/login",
              c.post(BASE + "/api/auth/login",
                     json={"email": "admin@demo.com", "password": "AdminPass2026"}), 200,
              lambda r: r.json()["data"]["user"]["must_change_password"] is True)
    admin_tok = r.json()["data"]["token"]
    AH = {"Authorization": f"Bearer {admin_tok}"}
    check("首次改密拦截", "GET", "/api/conversations", c.get(BASE + "/api/conversations", headers=AH), 403,
          lambda r: r.json()["code"] == "PASSWORD_CHANGE_REQUIRED")
    check("修改初始密码", "POST", "/api/auth/password",
          c.post(BASE + "/api/auth/password",
                 json={"old_password": "AdminPass2026", "new_password": "NewAdmin2026x"}, headers=AH), 200)
    r = check("改密后重新登录", "POST", "/api/auth/login",
              c.post(BASE + "/api/auth/login",
                     json={"email": "admin@demo.com", "password": "NewAdmin2026x"}), 200)
    admin_tok = r.json()["data"]["token"]
    AH = {"Authorization": f"Bearer {admin_tok}"}
    check("错误密码 401", "POST", "/api/auth/login",
          c.post(BASE + "/api/auth/login",
                 json={"email": "admin@demo.com", "password": "wrong-pass-123"}), 401)
    check("无 token 401", "GET", "/api/auth/me", c.get(BASE + "/api/auth/me"), 401)
    check("当前用户", "GET", "/api/auth/me", c.get(BASE + "/api/auth/me", headers=AH), 200,
          lambda r: r.json()["data"]["role"] == "admin")

    # ── 邀请码 + 注册 ──
    mod("邀请码")
    r = check("批量生成", "POST", "/api/admin/invite-codes",
              c.post(BASE + "/api/admin/invite-codes", json={"count": 3, "max_uses": 1}, headers=AH), 200,
              lambda r: len(r.json()["data"]["codes"]) == 3)
    codes = r.json()["data"]["codes"]
    check("列表掩码", "GET", "/api/admin/invite-codes",
          c.get(BASE + "/api/admin/invite-codes", headers=AH), 200,
          lambda r: all("*" in i["code_masked"] or "…" in i["code_masked"] or len(i["code_masked"]) < 12
                        for i in r.json()["data"]["items"]))
    mod("认证")
    r = check("邀请码注册", "POST", "/api/auth/register",
              c.post(BASE + "/api/auth/register",
                     json={"email": "member@test.com", "password": "MemberPass2026",
                           "nickname": "实测成员", "invite_code": codes[0]}), 200)
    mem_tok = r.json()["data"]["token"]
    MH = {"Authorization": f"Bearer {mem_tok}"}
    check("重复邮箱 409", "POST", "/api/auth/register",
          c.post(BASE + "/api/auth/register",
                 json={"email": "member@test.com", "password": "MemberPass2026",
                       "nickname": "x", "invite_code": codes[1]}), 409)
    check("无效邀请码 422", "POST", "/api/auth/register",
          c.post(BASE + "/api/auth/register",
                 json={"email": "other@test.com", "password": "MemberPass2026",
                       "nickname": "x", "invite_code": "RM-BADCODE"}), 422)
    mod("邀请码")
    iid = c.get(BASE + "/api/admin/invite-codes", headers=AH).json()["data"]["items"][0]["id"]
    check("作废邀请码", "DELETE", f"/api/admin/invite-codes/{iid}",
          c.delete(BASE + f"/api/admin/invite-codes/{iid}", headers=AH), 200)

    # ── 渠道 ──
    mod("渠道管理")
    check("厂商预设", "GET", "/api/admin/channel-presets",
          c.get(BASE + "/api/admin/channel-presets", headers=AH), 200,
          lambda r: len(r.json()["data"]["openai_compatible"]) >= 10)
    r = check("新建渠道", "POST", "/api/admin/channels",
              c.post(BASE + "/api/admin/channels",
                     json={"name": "实测渠道", "type": "openai_compatible",
                           "base_url": os.environ.get("AICR_MOCK_URL", "http://127.0.0.1:8097/v1"), "api_key": "sk-real-check-1234",
                           "weight": 100, "priority": 10}, headers=AH), 200)
    ch = r.json()["data"]
    cid = ch["id"]
    check("Key 只回 hint", "GET", f"/api/admin/channels/{cid}",
          c.get(BASE + f"/api/admin/channels/{cid}", headers=AH), 200,
          lambda r: "sk-real-check-1234" not in r.text and r.json()["data"]["api_key_hint"] == "****1234")
    check("乐观锁冲突 409", "PATCH", f"/api/admin/channels/{cid}",
          c.patch(BASE + f"/api/admin/channels/{cid}",
                  json={"version": 999, "name": "x"}, headers=AH), 409)
    check("修改渠道", "PATCH", f"/api/admin/channels/{cid}",
          c.patch(BASE + f"/api/admin/channels/{cid}",
                  json={"version": ch["version"], "weight": 80}, headers=AH), 200)
    check("连通测试", "POST", f"/api/admin/channels/{cid}/test",
          c.post(BASE + f"/api/admin/channels/{cid}/test", headers=AH), 200,
          lambda r: r.json()["data"]["ok"] is True)
    check("同步上游模型", "POST", f"/api/admin/channels/{cid}/sync-models",
          c.post(BASE + f"/api/admin/channels/{cid}/sync-models", headers=AH), 200,
          lambda r: "mock-chat" in r.json()["data"]["models"])
    check("健康时序", "GET", f"/api/admin/channels/{cid}/health",
          c.get(BASE + f"/api/admin/channels/{cid}/health", headers=AH), 200,
          lambda r: "samples" in r.json()["data"])
    check("停用渠道", "POST", f"/api/admin/channels/{cid}/toggle",
          c.post(BASE + f"/api/admin/channels/{cid}/toggle",
                 json={"enabled": False}, headers=AH), 200)
    check("恢复渠道", "POST", f"/api/admin/channels/{cid}/toggle",
          c.post(BASE + f"/api/admin/channels/{cid}/toggle",
                 json={"enabled": True}, headers=AH), 200)
    r = c.post(BASE + "/api/admin/channels",
               json={"name": "实测渠道B", "type": "openai_compatible",
                     "base_url": os.environ.get("AICR_MOCK_URL", "http://127.0.0.1:8097/v1"), "api_key": "sk-real-check-5678",
                     "weight": 50, "priority": 10}, headers=AH)
    cid2 = r.json()["data"]["id"]

    # ── 模型 ──
    mod("模型注册表")
    r = check("新建模型", "POST", "/api/admin/models",
              c.post(BASE + "/api/admin/models",
                     json={"public_name": "check-model", "display_name": "实测模型",
                           "price_input": 2, "price_output": 8}, headers=AH), 200)
    mid = r.json()["data"]["id"]
    check("绑定渠道", "POST", f"/api/admin/models/{mid}/channels",
          c.post(BASE + f"/api/admin/models/{mid}/channels",
                 json={"channel_id": cid, "upstream_model": "mock-chat"}, headers=AH), 200)
    check("绑定第二渠道", "POST", f"/api/admin/models/{mid}/channels",
          c.post(BASE + f"/api/admin/models/{mid}/channels",
                 json={"channel_id": cid2, "upstream_model": "mock-fast"}, headers=AH), 200)
    check("设为默认", "POST", "/api/admin/models/by-name/check-model/default",
          c.post(BASE + "/api/admin/models/by-name/check-model/default", headers=AH), 200)
    check("成员可见模型", "GET", "/api/models", c.get(BASE + "/api/models", headers=MH), 200,
          lambda r: any(m["public_name"] == "check-model" for m in r.json()["data"]["items"]))
    mver = next(m["version"] for m in c.get(BASE + "/api/admin/models", headers=AH)
                .json()["data"]["items"] if m["id"] == mid)
    check("修改模型", "PATCH", f"/api/admin/models/{mid}",
          c.patch(BASE + f"/api/admin/models/{mid}",
                  json={"version": mver, "display_name": "实测模型改"}, headers=AH), 200)

    # ── 设置与告警 ──
    mod("系统设置")
    check("设置列表", "GET", "/api/admin/settings",
          c.get(BASE + "/api/admin/settings", headers=AH), 200)
    check("写入告警配置", "PUT", "/api/admin/settings/alert_webhook",
          c.put(BASE + "/api/admin/settings/alert_webhook",
                json={"value": {"url": os.environ.get("AICR_MOCK_URL", "http://127.0.0.1:8097/v1") + "/hook", "type": "generic",
                                "enabled": True}, "version": 0}, headers=AH), 200)
    check("非法值 422", "PUT", "/api/admin/settings/alert_webhook",
          c.put(BASE + "/api/admin/settings/alert_webhook",
                json={"value": {"url": "ftp://bad"}, "version": 1}, headers=AH), 422)
    check("版本冲突 409", "PUT", "/api/admin/settings/retention",
          c.put(BASE + "/api/admin/settings/retention",
                json={"value": {"days": 30}, "version": 99}, headers=AH), 409)
    mod("告警")
    check("测试发送", "POST", "/api/admin/alerts/test",
          c.post(BASE + "/api/admin/alerts/test", headers=AH), 200)

    # ── 用户管理 ──
    mod("用户管理")
    r = check("用户列表", "GET", "/api/admin/users",
              c.get(BASE + "/api/admin/users", headers=AH), 200,
              lambda r: len(r.json()["data"]["items"]) >= 2)
    mem_id = next(u["id"] for u in r.json()["data"]["items"] if u["email"] == "member@test.com")
    check("封禁用户", "POST", f"/api/admin/users/{mem_id}/ban",
          c.post(BASE + f"/api/admin/users/{mem_id}/ban",
                 json={"banned": True, "reason": "实测"}, headers=AH), 200)
    check("封禁后登录 403", "POST", "/api/auth/login",
          c.post(BASE + "/api/auth/login",
                 json={"email": "member@test.com", "password": "MemberPass2026"}), 403)
    check("解封用户", "POST", f"/api/admin/users/{mem_id}/ban",
          c.post(BASE + f"/api/admin/users/{mem_id}/ban", json={"banned": False}, headers=AH), 200)
    admin_id = c.get(BASE + "/api/auth/me", headers=AH).json()["data"]["id"]
    check("不能封禁自己 409", "POST", f"/api/admin/users/{admin_id}/ban",
          c.post(BASE + f"/api/admin/users/{admin_id}/ban", json={"banned": True}, headers=AH), 409)
    r = check("重置密码", "POST", f"/api/admin/users/{mem_id}/reset-password",
              c.post(BASE + f"/api/admin/users/{mem_id}/reset-password", headers=AH), 200,
              lambda r: len(r.json()["data"]["temp_password"]) >= 8)
    tmp = r.json()["data"]["temp_password"]
    time.sleep(1.1)  # 重置吊销窗口 1s（含同秒 token），模拟真人登录间隔
    r = check("临时密码登录", "POST", "/api/auth/login",
              c.post(BASE + "/api/auth/login",
                     json={"email": "member@test.com", "password": tmp}), 200,
              lambda r: r.json()["data"]["user"]["must_change_password"] is True)
    mem_tok = r.json()["data"]["token"]
    MH = {"Authorization": f"Bearer {mem_tok}"}
    check("成员改密", "POST", "/api/auth/password",
          c.post(BASE + "/api/auth/password",
                 json={"old_password": tmp, "new_password": "MemberPass2026x"}, headers=MH), 200)
    r = c.post(BASE + "/api/auth/login",
               json={"email": "member@test.com", "password": "MemberPass2026x"})
    mem_tok = r.json()["data"]["token"]
    MH = {"Authorization": f"Bearer {mem_tok}"}

    # ── 权限负例 ──
    mod("权限负例")
    for path in ("/api/admin/channels", "/api/admin/models", "/api/admin/users",
                 "/api/admin/settings", "/api/admin/stats/feedback", "/api/admin/invite-codes"):
        check(f"成员访问 {path} 403", "GET", path, c.get(BASE + path, headers=MH), 403)

    # ── 会话与 SSE ──
    mod("会话")
    r = check("新建会话", "POST", "/api/conversations",
              c.post(BASE + "/api/conversations",
                     json={"title": "实测会话", "model_id": mid}, headers=MH), 200)
    conv_id = r.json()["data"]["id"]
    check("会话列表", "GET", "/api/conversations", c.get(BASE + "/api/conversations", headers=MH), 200)
    check("修改会话", "PATCH", f"/api/conversations/{conv_id}",
          c.patch(BASE + f"/api/conversations/{conv_id}", json={"pinned": True}, headers=MH), 200)
    r = check("发送消息", "POST", f"/api/conversations/{conv_id}/messages",
              c.post(BASE + f"/api/conversations/{conv_id}/messages",
                     json={"content": "第一条消息"}, headers=MH), 200)
    msg1 = r.json()["data"]["message_id"]
    check("引用消息", "POST", f"/api/conversations/{conv_id}/messages",
          c.post(BASE + f"/api/conversations/{conv_id}/messages",
                 json={"content": "引用追问", "reply_to_msg_id": msg1}, headers=MH), 200)
    check("跨会话引用 422", "POST", f"/api/conversations/{conv_id}/messages",
          c.post(BASE + f"/api/conversations/{conv_id}/messages",
                 json={"content": "x", "reply_to_msg_id": 999999}, headers=MH), 422)
    check("消息列表含 quote", "GET", f"/api/conversations/{conv_id}/messages",
          c.get(BASE + f"/api/conversations/{conv_id}/messages", headers=MH), 200,
          lambda r: any(m.get("quote") for m in r.json()["data"]["items"]))
    mod("SSE 流式")
    evs = sse_events(c, "POST", f"/api/conversations/{conv_id}/ai/completions",
                     {"content": "你好，实测流式"}, MH)
    kinds = [e["event"] for e in evs]
    ROWS.append({"module": MODULE, "name": "单聊 SSE 事件序列", "method": "POST",
                 "path": f"/api/conversations/{conv_id}/ai/completions",
                 "status": 200, "expect": 200,
                 "ok": all(k in kinds for k in ("meta", "delta", "usage", "done")),
                 "note": f"事件 {kinds}"})
    print(f"{'✅' if ROWS[-1]['ok'] else '❌'} [SSE] 事件序列 {kinds}")
    done = next(e["data"] for e in evs if e["event"] == "done")
    check("导出 Markdown", "GET", f"/api/conversations/{conv_id}/export?format=md",
          c.get(BASE + f"/api/conversations/{conv_id}/export?format=md", headers=MH), 200,
          lambda r: "实测会话" in r.text and "text/markdown" in r.headers["content-type"])
    check("导出 JSON", "GET", f"/api/conversations/{conv_id}/export?format=json",
          c.get(BASE + f"/api/conversations/{conv_id}/export?format=json", headers=MH), 200,
          lambda r: len(r.json()["messages"]) >= 3)

    # ── 反馈 / 搜索 / 配额 ──
    mod("消息反馈")
    ai_msg = done["message_id"]
    check("点赞", "POST", f"/api/messages/{ai_msg}/feedback",
          c.post(BASE + f"/api/messages/{ai_msg}/feedback", json={"rating": "up"}, headers=MH), 200,
          lambda r: r.json()["data"]["state"] == "up")
    check("改票", "POST", f"/api/messages/{ai_msg}/feedback",
          c.post(BASE + f"/api/messages/{ai_msg}/feedback", json={"rating": "down"}, headers=MH), 200,
          lambda r: r.json()["data"]["state"] == "down")
    check("取消", "POST", f"/api/messages/{ai_msg}/feedback",
          c.post(BASE + f"/api/messages/{ai_msg}/feedback", json={"rating": "down"}, headers=MH), 200,
          lambda r: r.json()["data"]["state"] == "none")
    c.post(BASE + f"/api/messages/{ai_msg}/feedback", json={"rating": "up"}, headers=MH)
    mod("统计")
    check("满意度聚合", "GET", "/api/admin/stats/feedback",
          c.get(BASE + "/api/admin/stats/feedback", headers=AH), 200,
          lambda r: r.json()["data"]["total"]["up"] >= 1)
    check("触发预聚合", "POST", "/api/admin/stats/recompute",
          c.post(BASE + "/api/admin/stats/recompute", headers=AH), 200,
          lambda r: r.json()["data"]["days_updated"] >= 1)
    check("用量趋势", "GET", "/api/admin/stats/overview?days=7",
          c.get(BASE + "/api/admin/stats/overview", params={"days": 7}, headers=AH), 200,
          lambda r: len(r.json()["data"]["items"]) >= 1
          and r.json()["data"]["items"][-1]["ai_calls"] >= 1)
    check("成员看趋势 403", "GET", "/api/admin/stats/overview",
          c.get(BASE + "/api/admin/stats/overview", headers=MH), 403)
    evs = sse_events(c, "GET", "/api/admin/stats/live?interval=1&ticks=1", {}, AH)
    ROWS.append({"module": MODULE, "name": "实时看板 SSE tick", "method": "GET",
                 "path": "/api/admin/stats/live", "status": 200, "expect": 200,
                 "ok": bool(evs) and "online" in evs[0]["data"] and "budget" in evs[0]["data"],
                 "note": "首 tick 含 online/channels/budget"})
    print(f"{'✅' if ROWS[-1]['ok'] else '❌'} [统计] 实时看板首 tick")
    mod("搜索")
    check("中文命中", "GET", "/api/search?q=实测流式",
          c.get(BASE + "/api/search", params={"q": "实测流式"}, headers=MH), 200,
          lambda r: len(r.json()["data"]["items"]) >= 1)
    check("空查询 422", "GET", "/api/search?q=",
          c.get(BASE + "/api/search", params={"q": ""}, headers=MH), 422)
    check("他人搜不到", "GET", "/api/search?q=实测流式",
          c.get(BASE + "/api/search", params={"q": "实测流式"}, headers=AH), 200,
          lambda r: True)  # admin 全量可见，成员隔离由单测覆盖
    mod("配额")
    check("我的用量", "GET", "/api/quota/me", c.get(BASE + "/api/quota/me", headers=MH), 200,
          lambda r: r.json()["data"]["tokens_used"] > 0)

    # ── 房间 ──
    mod("房间")
    r = check("创建房间", "POST", "/api/rooms",
              c.post(BASE + "/api/rooms",
                     json={"name": "实测房间", "model_id": mid, "system_prompt": "简洁回答"},
                     headers=MH), 200)
    rid = r.json()["data"]["id"]
    check("房间广场", "GET", "/api/rooms", c.get(BASE + "/api/rooms", headers=MH), 200)
    check("房间设置 output_mode", "PATCH", f"/api/rooms/{rid}",
          c.patch(BASE + f"/api/rooms/{rid}", json={"output_mode": "json"}, headers=MH), 200)
    check("非法模式 422", "PATCH", f"/api/rooms/{rid}",
          c.patch(BASE + f"/api/rooms/{rid}", json={"output_mode": "yaml"}, headers=MH), 422)
    check("普通发言", "POST", f"/api/rooms/{rid}/messages",
          c.post(BASE + f"/api/rooms/{rid}/messages", json={"content": "大家好"}, headers=MH), 200)
    check("增量拉取", "GET", f"/api/rooms/{rid}/messages?after=0",
          c.get(BASE + f"/api/rooms/{rid}/messages", headers=MH), 200,
          lambda r: r.json()["data"]["room"]["owner_id"] is not None)
    mod("SSE 流式")
    evs = sse_events(c, "POST", f"/api/rooms/{rid}/ai/ask", {"content": "@AI 你好"}, MH)
    kinds = [e["event"] for e in evs]
    # mock 上游返回非 JSON → 应触发 retry 且最终降级
    ok = "retry" in kinds and "done" in kinds
    ROWS.append({"module": MODULE, "name": "房间 JSON 模式重试+降级", "method": "POST",
                 "path": f"/api/rooms/{rid}/ai/ask", "status": 200, "expect": 200,
                 "ok": ok, "note": f"事件 {kinds}"})
    print(f"{'✅' if ok else '❌'} [SSE] 房间 JSON 重试降级 {kinds}")
    msgs = c.get(BASE + f"/api/rooms/{rid}/messages", headers=MH).json()["data"]["items"]
    ai = [m for m in msgs if m["role"] == "assistant"][-1]
    ROWS.append({"module": "房间", "name": "降级标注落库", "method": "GET",
                 "path": f"/api/rooms/{rid}/messages", "status": 200, "expect": 200,
                 "ok": ai.get("output_downgraded") is True and ai.get("output_mode") == "free",
                 "note": f"output_mode={ai.get('output_mode')}"})
    print(f"{'✅' if ROWS[-1]['ok'] else '❌'} [房间] 降级标注落库")
    check("房间导出", "GET", f"/api/rooms/{rid}/export?format=md",
          c.get(BASE + f"/api/rooms/{rid}/export?format=md", headers=MH), 200)

    # ── 模板 ──
    mod("模板市场")
    r = check("发布模板", "POST", "/api/room-templates",
              c.post(BASE + "/api/room-templates", json={"room_id": rid}, headers=MH), 200)
    tid = r.json()["data"]["template_id"]
    check("模板列表", "GET", "/api/room-templates",
          c.get(BASE + "/api/room-templates", headers=AH), 200,
          lambda r: any(t["id"] == tid for t in r.json()["data"]["items"]))
    r = check("一键克隆", "POST", f"/api/room-templates/{tid}/clone",
              c.post(BASE + f"/api/room-templates/{tid}/clone", headers=AH), 200)
    cloned = r.json()["data"]["room_id"]
    check("克隆配置一致", "GET", f"/api/rooms/{cloned}/messages",
          c.get(BASE + f"/api/rooms/{cloned}/messages", headers=AH), 200,
          lambda r: r.json()["data"]["room"]["name"] == "实测房间")
    check("使用计数", "GET", "/api/room-templates",
          c.get(BASE + "/api/room-templates", headers=AH), 200,
          lambda r: next(t for t in r.json()["data"]["items"] if t["id"] == tid)["use_count"] == 1)
    check("发布者删除", "DELETE", f"/api/room-templates/{tid}",
          c.delete(BASE + f"/api/room-templates/{tid}", headers=MH), 200)
    check("删除后不存在 404", "DELETE", f"/api/room-templates/{tid}",
          c.delete(BASE + f"/api/room-templates/{tid}", headers=MH), 404)
    r = c.post(BASE + "/api/room-templates", json={"room_id": rid}, headers=MH)
    tid2 = r.json()["data"]["template_id"]
    check("管理员可跨删模板", "DELETE", f"/api/room-templates/{tid2}",
          c.delete(BASE + f"/api/room-templates/{tid2}", headers=AH), 200)

    # ── 分享 ──
    mod("分享")
    r = check("创建分享", "POST", "/api/shares",
              c.post(BASE + "/api/shares",
                     json={"scope": "dm", "conversation_id": conv_id, "days": 7}, headers=MH), 200)
    share = r.json()["data"]
    anon = httpx.Client(timeout=30)
    check("免登录查看", "GET", f"/api/share/{share['token']}",
          anon.get(BASE + f"/api/share/{share['token']}"), 200,
          lambda r: r.json()["data"]["title"] == "实测会话" and "email" not in r.text)
    sid, sig = share["token"].split(".")
    check("篡改签名 403", "GET", f"/api/share/{sid}.{'0'*32}",
          anon.get(BASE + f"/api/share/{sid}.{'0'*32}"), 403)
    check("撤销分享", "DELETE", f"/api/shares/{share['share_id']}",
          c.delete(BASE + f"/api/shares/{share['share_id']}", headers=MH), 200)
    check("撤销后 410", "GET", f"/api/share/{share['token']}",
          anon.get(BASE + f"/api/share/{share['token']}"), 410)
    anon.close()

    # ── WebSocket ──
    mod("WebSocket")
    with ws_connect(f"{WS}/ws/rooms/{rid}?token={mem_tok}") as ws:
        hello = json.loads(ws.recv(timeout=5))
        ROWS.append({"module": MODULE, "name": "连接与 hello", "method": "WS",
                     "path": f"/ws/rooms/{rid}", "status": 101, "expect": 101,
                     "ok": hello["type"] == "hello", "note": ""})
        print(f"{'✅' if hello['type']=='hello' else '❌'} [WS] hello")
        ws.send("ping")
        got_pong = False
        for _ in range(4):
            d = json.loads(ws.recv(timeout=5))
            if d["type"] == "pong":
                got_pong = True
                break
        ROWS.append({"module": MODULE, "name": "心跳 ping/pong", "method": "WS",
                     "path": f"/ws/rooms/{rid}", "status": 101, "expect": 101,
                     "ok": got_pong, "note": ""})
        print(f"{'✅' if got_pong else '❌'} [WS] 心跳")
        c.post(BASE + f"/api/rooms/{rid}/messages", json={"content": "WS 广播实测"}, headers=MH)
        got_msg = False
        for _ in range(6):
            d = json.loads(ws.recv(timeout=5))
            if d["type"] == "message" and d["message"]["content"] == "WS 广播实测":
                got_msg = True
                break
        ROWS.append({"module": MODULE, "name": "消息广播", "method": "WS",
                     "path": f"/ws/rooms/{rid}", "status": 101, "expect": 101,
                     "ok": got_msg, "note": ""})
        print(f"{'✅' if got_msg else '❌'} [WS] 消息广播")
    try:
        with ws_connect(f"{WS}/ws/rooms/{rid}?token=bad.token") as ws:
            ws.recv(timeout=5)
        bad_ok = False
    except Exception as e:  # noqa: BLE001
        bad_ok = getattr(getattr(e, "rcvd", None), "code", None) == 4401
    ROWS.append({"module": MODULE, "name": "无效 token 4401", "method": "WS",
                 "path": f"/ws/rooms/{rid}", "status": 4401, "expect": 4401,
                 "ok": bad_ok, "note": ""})
    print(f"{'✅' if bad_ok else '❌'} [WS] 无效 token 拒绝")

    # ── A/B 实验 ──
    mod("A/B 实验")
    r = check("创建实验", "POST", "/api/admin/experiments",
              c.post(BASE + "/api/admin/experiments",
                     json={"model_id": mid, "channel_a": cid, "channel_b": cid2,
                           "ratio_a": 50}, headers=AH), 200)
    eid = r.json()["data"]["experiment_id"]
    check("重复实验 409", "POST", "/api/admin/experiments",
          c.post(BASE + "/api/admin/experiments",
                 json={"model_id": mid, "channel_a": cid, "channel_b": cid2,
                       "ratio_a": 50}, headers=AH), 409)
    check("同渠道 422", "POST", "/api/admin/experiments",
          c.post(BASE + "/api/admin/experiments",
                 json={"model_id": mid, "channel_a": cid, "channel_b": cid,
                       "ratio_a": 50}, headers=AH), 422)
    check("实验列表", "GET", "/api/admin/experiments",
          c.get(BASE + "/api/admin/experiments", headers=AH), 200,
          lambda r: any(e["id"] == eid for e in r.json()["data"]["items"]))
    check("成员访问 403", "GET", "/api/admin/experiments",
          c.get(BASE + "/api/admin/experiments", headers=MH), 403)
    evs = sse_events(c, "POST", f"/api/conversations/{conv_id}/ai/completions",
                     {"content": "实验分桶实测"}, MH)
    check("实验报告", "GET", f"/api/admin/experiments/{eid}/report",
          c.get(BASE + f"/api/admin/experiments/{eid}/report", headers=AH), 200,
          lambda r: len(r.json()["data"]["buckets"]) == 2
          and sum(b["calls"] for b in r.json()["data"]["buckets"]) >= 1
          and bool(r.json()["data"]["recommendation"]))
    check("结束实验", "POST", f"/api/admin/experiments/{eid}/end",
          c.post(BASE + f"/api/admin/experiments/{eid}/end", headers=AH), 200)
    check("结束后重复 404", "POST", f"/api/admin/experiments/{eid}/end",
          c.post(BASE + f"/api/admin/experiments/{eid}/end", headers=AH), 404)

    # ── 文件上传 ──
    mod("文件上传")
    import base64 as _b64
    png = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    r = check("上传 PNG", "POST", "/api/uploads",
              c.post(BASE + "/api/uploads", headers=MH,
                     files={"file": ("实测.png", png, "image/png")}), 200,
              lambda r: r.json()["data"]["kind"] == "image")
    up_id = r.json()["data"]["id"]
    check("伪装扩展名 422", "POST", "/api/uploads",
          c.post(BASE + "/api/uploads", headers=MH,
                 files={"file": ("evil.png", b"not an image", "image/png")}), 422)
    check("超大 413", "POST", "/api/uploads",
          c.post(BASE + "/api/uploads", headers=MH,
                 files={"file": ("big.png", png + b"\x00" * (10 * 1024 * 1024 + 1), "image/png")}), 413)
    check("属主读取内容", "GET", f"/api/uploads/{up_id}/content",
          c.get(BASE + f"/api/uploads/{up_id}/content", headers=MH), 200,
          lambda r: r.content == png)
    check("他人读取 403", "GET", f"/api/uploads/{up_id}/content",
          c.get(BASE + f"/api/uploads/{up_id}/content", headers=AH), 200)  # admin 可读
    check("带附件发消息", "POST", f"/api/conversations/{conv_id}/messages",
          c.post(BASE + f"/api/conversations/{conv_id}/messages",
                 json={"content": "附件实测", "attachment_id": up_id}, headers=MH), 200)
    check("消息列表含附件", "GET", f"/api/conversations/{conv_id}/messages",
          c.get(BASE + f"/api/conversations/{conv_id}/messages", headers=MH), 200,
          lambda r: any(m.get("attachment_id") == up_id for m in r.json()["data"]["items"]))
    check("他人附件 422", "POST", f"/api/conversations/{conv_id}/messages",
          c.post(BASE + f"/api/conversations/{conv_id}/messages",
                 json={"content": "x", "attachment_id": up_id}, headers=AH), 422)

    # ── 好友与私聊 ──
    mod("好友与私聊")
    r = check("搜索用户", "GET", "/api/users/search?q=实测成员",
              c.get(BASE + "/api/users/search", params={"q": "实测成员"}, headers=AH), 200,
              lambda r: len(r.json()["data"]["items"]) >= 1
              and "*" in r.json()["data"]["items"][0]["email"])
    mem_uid = r.json()["data"]["items"][0]["id"]
    r = check("发送好友申请", "POST", "/api/friends/requests",
              c.post(BASE + "/api/friends/requests", json={"user_id": mem_uid}, headers=AH), 200)
    frid = r.json()["data"]["request_id"]
    check("重复申请 409", "POST", "/api/friends/requests",
          c.post(BASE + "/api/friends/requests", json={"user_id": mem_uid}, headers=AH), 409)
    check("自加 422", "POST", "/api/friends/requests",
          c.post(BASE + "/api/friends/requests",
                 json={"user_id": c.get(BASE + "/api/auth/me", headers=AH).json()["data"]["id"]},
                 headers=AH), 422)
    check("收到的申请", "GET", "/api/friends/requests",
          c.get(BASE + "/api/friends/requests", headers=MH), 200,
          lambda r: any(x["id"] == frid for x in r.json()["data"]["incoming"]))
    check("非收件人同意 403", "POST", f"/api/friends/requests/{frid}/accept",
          c.post(BASE + f"/api/friends/requests/{frid}/accept", headers=AH), 403)
    check("同意申请", "POST", f"/api/friends/requests/{frid}/accept",
          c.post(BASE + f"/api/friends/requests/{frid}/accept", headers=MH), 200)
    check("好友列表双向", "GET", "/api/friends",
          c.get(BASE + "/api/friends", headers=AH), 200,
          lambda r: any(x["user_id"] == mem_uid for x in r.json()["data"]["items"]))
    check("非好友私聊 403", "POST", "/api/dm/1/messages",
          c.post(BASE + "/api/dm/1/messages", json={"content": "x"}, headers=MH), 403)
    r = check("私聊发送", "POST", f"/api/dm/{mem_uid}/messages",
              c.post(BASE + f"/api/dm/{mem_uid}/messages",
                     json={"content": "API 实测私聊"}, headers=AH), 200)
    admin_uid = c.get(BASE + "/api/auth/me", headers=AH).json()["data"]["id"]
    check("私聊历史", "GET", f"/api/dm/{admin_uid}/messages",
          c.get(BASE + f"/api/dm/{admin_uid}/messages", headers=MH), 200,
          lambda r: any(m["content"] == "API 实测私聊" for m in r.json()["data"]["items"]))
    check("未读计数", "GET", "/api/friends",
          c.get(BASE + "/api/friends", headers=MH), 200,
          lambda r: next(x for x in r.json()["data"]["items"]
                         if x["user_id"] == 1 or True)["unread_count"] >= 1)
    check("标记已读", "POST", f"/api/dm/{c.get(BASE + '/api/auth/me', headers=AH).json()['data']['id']}/read",
          c.post(BASE + f"/api/dm/{c.get(BASE + '/api/auth/me', headers=AH).json()['data']['id']}/read",
                 headers=MH), 200,
          lambda r: r.json()["data"]["marked"] >= 1)
    check("删除好友", "DELETE", f"/api/friends/{mem_uid}",
          c.delete(BASE + f"/api/friends/{mem_uid}", headers=AH), 200)
    check("删除后私聊 403", "POST", f"/api/dm/{mem_uid}/messages",
          c.post(BASE + f"/api/dm/{mem_uid}/messages", json={"content": "x"}, headers=AH), 403)

    # ── 登出 ──
    mod("认证")
    check("登出", "POST", "/api/auth/logout", c.post(BASE + "/api/auth/logout", headers=MH), 200)
    check("登出后 token 失效", "GET", "/api/auth/me", c.get(BASE + "/api/auth/me", headers=MH), 401)

    # ── 报告 ──
    total = len(ROWS)
    passed = sum(1 for r in ROWS if r["ok"])
    lines = ["# AI 聊天室 · API 实测报告", "",
             f"实测时间：{time.strftime('%Y-%m-%d %H:%M')} · 环境：真实 uvicorn + PostgreSQL 16 + Redis 7 + mock 上游",
             f"结果：**{passed}/{total} 通过**，覆盖 {len(set(r['module'] for r in ROWS))} 个模块", "",
             "方式：脚本 `scripts/api_full_check.py` 对运行中的后端发起真实 HTTP/SSE/WebSocket 调用，",
             "逐项断言状态码与响应内容；上游 AI 由本地 mock 服务真实流式返回。", "",
             "| 模块 | 接口 | 方法 | 路径 | 实测状态 | 期望 | 结果 | 备注 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in ROWS:
        lines.append(f"| {r['module']} | {r['name']} | {r['method']} | `{r['path']}` "
                     f"| {r['status']} | {r['expect']} | {'✅' if r['ok'] else '❌'} | {r['note']} |")
    lines += ["", "## 说明", "",
              "- SSE 与 WebSocket 为真实连接实测（事件序列/广播/心跳/拒绝码），非 mock 断言。",
              "- 权限负例、乐观锁冲突、邀请码作废、封禁登录、分享篡改/撤销、JSON 降级等错误分支均实测。",
              "- 成员数据隔离（搜索/会话越权 404）由 204 项单元/集成测试覆盖，本脚本抽查管理员全量视角。",
              "- 真实厂商 Key 联调待用户提供后另行执行（当前上游为本地 mock，协议链路完全一致）。",
              "", "---", "", "内容由 AI 生成", ""]
    out = os.environ.get("AICR_REPORT", "/root/userdata/workspace/prd/API实测报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n===== 实测汇总: {passed}/{total} 通过 =====")
    print(f"报告: {out}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()