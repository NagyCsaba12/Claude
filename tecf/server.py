"""Helyi, OpenAI-kompatibilis API szerver, hogy más programok is használhassák a TecF Ai-t.

  POST http://127.0.0.1:8765/v1/chat/completions   {"messages": [...]}
  GET  http://127.0.0.1:8765/v1/models
  GET  http://127.0.0.1:8765/status

Alapból csak a saját gépről érhető el (127.0.0.1). A szerver módban a veszélyes
eszközök (parancsfuttatás, eszközkonfiguráció) le vannak tiltva.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tecf.brain import Brain
from tecf.config import Config
from tecf.knowledge import KnowledgeBase


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    lock = threading.Lock()
    # nincs interaktív jóváhagyás -> a veszélyes eszközök mindig tiltva
    cfg.confirm_system_commands = cfg.confirm_network_changes = True
    brain = Brain(cfg, KnowledgeBase(cfg.db_path, threaded=True), confirm=lambda _action: False)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/models":
                self._send(200, {"object": "list", "data": [{"id": "tecf", "object": "model"}]})
            elif self.path == "/status":
                with lock:
                    stats = brain.kb.stats()
                self._send(200, stats)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return self._send(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                msgs = [m for m in req.get("messages", []) if m.get("role") in ("user", "assistant")]
                question = msgs[-1]["content"]
            except (ValueError, KeyError, IndexError):
                return self._send(400, {"error": "hibás kérés"})
            with lock:  # SQLite kapcsolat szálbiztos használata
                answer, cid = brain.ask(question, msgs[:-1])
            self._send(200, {"id": f"tecf-{cid}", "object": "chat.completion", "created": int(time.time()),
                             "model": "tecf", "choices": [{"index": 0, "finish_reason": "stop",
                                                            "message": {"role": "assistant", "content": answer}}]})

    print(f"TecF Ai API: http://{host}:{port}/v1/chat/completions  (Ctrl+C a leállításhoz)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
