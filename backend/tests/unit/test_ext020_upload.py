"""EXT-020 文件上传：魔数校验、UUID 重命名、大小限制、权限、多模态组装。"""
from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest
from sqlalchemy import text

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
SSE = ('data: {"choices":[{"delta":{"content":"看到了"}}]}\n\n'
       'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
       '"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
       'data: [DONE]\n\n')


@pytest.fixture(autouse=True)
async def _clean(spike_session, tmp_path, monkeypatch):
    from tests.factories import cleanup_all

    await cleanup_all(spike_session)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FEATURE_FILE_UPLOAD", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "FEATURE_FILE_UPLOAD", True)
    yield


@pytest.fixture
async def actors(spike_session):
    from app.core.security import create_access_token
    from tests.factories import make_user

    owner = await make_user(spike_session, nickname="上传者", daily_token_limit=1000000)
    other = await make_user(spike_session, nickname="路人")
    to, _ = create_access_token(owner, "member")
    tx, _ = create_access_token(other, "member")
    return {"owner": owner, "other": other,
            "h_owner": {"Authorization": f"Bearer {to}"},
            "h_other": {"Authorization": f"Bearer {tx}"}}


@pytest.fixture
async def client():
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", timeout=60) as c:
        yield c


async def _upload(client, headers, data=PNG, name="pic.png", ctype="image/png"):
    return await client.post("/api/uploads", headers=headers,
                             files={"file": (name, data, ctype)})


async def test_upload_png_uuid_rename(client, actors, tmp_path):
    r = await _upload(client, actors["h_owner"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["kind"] == "image" and d["content_type"] == "image/png"
    assert d["size_bytes"] == len(PNG) and d["filename"] == "pic.png"
    stored = list((tmp_path / "uploads").iterdir())
    assert len(stored) == 1
    assert stored[0].name != "pic.png" and stored[0].read_bytes() == PNG
    assert d["url"] == f"/api/uploads/{d['id']}/content"


async def test_disguised_extension_rejected(client, actors):
    r = await _upload(client, actors["h_owner"],
                      data="# 我是文本不是图片".encode(), name="evil.png")
    assert r.status_code == 422 and r.json()["code"] == "UPLOAD_TYPE_INVALID"
    r2 = await _upload(client, actors["h_owner"], data=b"MZ\x90\x00exe", name="virus.jpg")
    assert r2.status_code == 422


async def test_magic_over_extension(client, actors):
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    r = await _upload(client, actors["h_owner"], data=jpeg, name="actually.png")
    assert r.status_code == 200
    assert r.json()["data"]["content_type"] == "image/jpeg", "以魔数为准而非扩展名"


async def test_too_large_413(client, actors):
    big = PNG + b"\x00" * (10 * 1024 * 1024 + 1)
    r = await _upload(client, actors["h_owner"], data=big)
    assert r.status_code == 413 and r.json()["code"] == "UPLOAD_TOO_LARGE"


async def test_content_permission(client, actors):
    uid = (await _upload(client, actors["h_owner"])).json()["data"]["id"]
    ok = await client.get(f"/api/uploads/{uid}/content", headers=actors["h_owner"])
    assert ok.status_code == 200 and ok.content == PNG
    assert ok.headers["content-type"].startswith("image/png")
    no = await client.get(f"/api/uploads/{uid}/content", headers=actors["h_other"])
    assert no.status_code == 403
    assert (await client.get(f"/api/uploads/{uid}/content")).status_code == 401


async def test_feature_flag_off(client, actors, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "FEATURE_FILE_UPLOAD", False)
    r = await _upload(client, actors["h_owner"])
    assert r.status_code == 403 and r.json()["code"] == "FEATURE_DISABLED"


async def test_message_attachment_ownership(client, spike_session, actors):
    from tests.factories import make_conversation

    uid = (await _upload(client, actors["h_owner"])).json()["data"]["id"]
    cid = await make_conversation(spike_session, user_id=actors["owner"])
    ok = await client.post(f"/api/conversations/{cid}/messages",
                           json={"content": "看图", "attachment_id": uid},
                           headers=actors["h_owner"])
    assert ok.status_code == 200, ok.text
    msgs = (await client.get(f"/api/conversations/{cid}/messages",
                             headers=actors["h_owner"])).json()["data"]["items"]
    assert msgs[-1]["attachment_id"] == uid
    steal = await client.post(f"/api/conversations/{cid}/messages",
                              json={"content": "x", "attachment_id": uid},
                              headers=actors["h_other"])
    assert steal.status_code in (403, 404, 422)


async def test_vision_assembly(client, spike_session, actors, block_external_http):
    from tests.factories import make_channel, make_conversation, make_model

    uid = (await _upload(client, actors["h_owner"])).json()["data"]["id"]
    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"vl-{uuid.uuid4().hex[:8]}",
                           supports_vision=True)
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.commit()
    cid = await make_conversation(spike_session, user_id=actors["owner"], model_id=mid)
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    block_external_http.post("https://api.test/v1/chat/completions").mock(side_effect=handler)
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "这是什么图", "attachment_id": uid},
                             headers=actors["h_owner"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    last = captured["body"]["messages"][-1]
    assert isinstance(last["content"], list), "视觉模型必须组装多模态 content"
    img = next(p for p in last["content"] if p["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    assert any(p["type"] == "text" and "这是什么图" in p["text"] for p in last["content"])


async def test_non_vision_placeholder(client, spike_session, actors, block_external_http):
    from tests.factories import make_channel, make_conversation, make_model

    uid = (await _upload(client, actors["h_owner"])).json()["data"]["id"]
    ch = await make_channel(spike_session, base_url="https://api.test/v1")
    mid = await make_model(spike_session, public_name=f"txt-{uuid.uuid4().hex[:8]}")
    await spike_session.execute(text(
        "INSERT INTO model_channels (model_id,channel_id,upstream_model) "
        "VALUES (:m,:c,'up')"), {"m": mid, "c": ch})
    await spike_session.commit()
    cid = await make_conversation(spike_session, user_id=actors["owner"], model_id=mid)
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    block_external_http.post("https://api.test/v1/chat/completions").mock(side_effect=handler)
    async with client.stream("POST", f"/api/conversations/{cid}/ai/completions",
                             json={"content": "看图", "attachment_id": uid},
                             headers=actors["h_owner"]) as r:
        assert r.status_code == 200
        async for _ in r.aiter_lines():
            pass
    last = captured["body"]["messages"][-1]
    assert isinstance(last["content"], str) and "[图片]" in last["content"]


async def test_room_member_can_view_attachment(client, spike_session, actors):
    from tests.factories import add_member, make_room

    uid = (await _upload(client, actors["h_owner"])).json()["data"]["id"]
    rid = await make_room(spike_session, owner_id=actors["owner"])
    await add_member(spike_session, room_id=rid, user_id=actors["other"])
    await client.post(f"/api/rooms/{rid}/messages",
                      json={"content": "房间图片", "attachment_id": uid},
                      headers=actors["h_owner"])
    ok = await client.get(f"/api/uploads/{uid}/content", headers=actors["h_other"])
    assert ok.status_code == 200, "房间成员应能看房间消息里的附件"