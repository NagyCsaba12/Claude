import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tecf.brain import Brain
from tecf.config import Config

REQUESTS = []


class FakeLLM(BaseHTTPRequestHandler):
    """OpenAI-kompatibilis ál-modell: először eszközt hív, aztán végleges választ ad."""

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json({"data": [{"id": "fake"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(req)
        last = req["messages"][-1]["content"]
        if last.startswith("ESZKÖZ EREDMÉNYEK"):
            content = "Kész. " + last.splitlines()[-1]
        else:
            content = 'Megjegyzem.\n```tool\n{"tool": "remember", "args": {"fact": "A router IP-je 10.0.0.1"}}\n```'
        self._json({"choices": [{"message": {"role": "assistant", "content": content}}]})

    def log_message(self, *a):
        pass


class AgentTest(unittest.TestCase):
    def test_tool_loop_with_local_model(self):
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            cfg = Config.load(d)
            cfg.local_provider, cfg.offline_only = "llamacpp", True
            cfg.set_key("llamacpp_url", f"http://127.0.0.1:{srv.server_address[1]}/v1")
            brain = Brain(cfg, log=lambda *_: None)
            answer, _ = brain.ask("Jegyezd meg: a router IP-je 10.0.0.1")
            self.assertEqual(answer, "Kész. Megjegyeztem.")
            self.assertIn("ESZKÖZ", REQUESTS[0]["messages"][0]["content"])  # system prompt eszközlistával
            self.assertEqual(brain.kb.recall("router IP")[0]["text"], "A router IP-je 10.0.0.1")
            brain.kb.close()
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
