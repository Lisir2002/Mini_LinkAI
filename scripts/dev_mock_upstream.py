"""本地 mock 上游（OpenAI 兼容），用于无真实 Key 时端到端验证全链路。

启动：python scripts/dev_mock_upstream.py   监听 127.0.0.1:8097
在管理端把渠道 Base URL 填 http://127.0.0.1:8097/v1 即可跑通真实流式对话。
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "这是来自本地 mock 上游的流式回复：链路已打通，配额按实际用量结算。"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # 静默
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            self._json({"data": [{"id": "mock-chat"}, {"id": "mock-fast"}]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if not self.headers.get("Authorization"):
            self._json({"error": {"message": "missing key"}}, 401)
            return
        if not body.get("stream"):
            self._json({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for ch in REPLY:
            chunk = {"choices": [{"delta": {"content": ch}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.012)
        tail = {"choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 24, "completion_tokens": len(REPLY),
                          "total_tokens": 24 + len(REPLY)}}
        self.wfile.write(f"data: {json.dumps(tail)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8097), Handler).serve_forever()
