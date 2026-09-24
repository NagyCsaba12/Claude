import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tecf.brain import STOPPED, Brain
from tecf.config import Config

STATE = {"sent": 0, "closed": False}


class SlowStreamingLLM(BaseHTTPRequestHandler):
    """OpenAI-kompatibilis ál-modell, amely lassan, darabonként küldi a választ (mint az Ollama)."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        words = ["Ez ", "egy ", "nagyon ", "hosszú ", "válasz "] * 40 if req.get("stream") else []
        try:
            for w in words:
                chunk = {"choices": [{"delta": {"content": w}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                STATE["sent"] += 1
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            STATE["closed"] = True  # a kliens bontotta a kapcsolatot -> a "modell" abbahagyja

    def log_message(self, *a):
        pass


class StopTest(unittest.TestCase):
    def setUp(self):
        STATE.update(sent=0, closed=False)
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), SlowStreamingLLM)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Config.load(self.tmp.name)
        cfg.local_provider, cfg.offline_only = "llamacpp", True
        cfg.set_key("llamacpp_url", f"http://127.0.0.1:{self.srv.server_address[1]}/v1")
        self.brain = Brain(cfg, log=lambda *_: None)

    def tearDown(self):
        self.brain.kb.close()
        self.srv.shutdown()
        self.tmp.cleanup()

    def test_stop_mid_answer(self):
        cancel, tokens = threading.Event(), []

        def on_token(t):
            tokens.append(t)
            if len(tokens) == 5:
                cancel.set()  # mintha a felhasználó megnyomta volna a Leállítás gombot

        start = time.time()
        answer, cid = self.brain.ask("Mesélj hosszan", cancel=cancel, on_token=on_token)
        self.assertLess(time.time() - start, 3)  # a teljes válasz 10 mp lenne
        self.assertTrue(answer.startswith("Ez egy nagyon hosszú válasz"))
        self.assertTrue(answer.endswith(STOPPED))
        self.assertLess(len(tokens), 10)
        time.sleep(0.5)
        self.assertLess(STATE["sent"], 30)  # a szerver is abbahagyta a küldést (200 helyett)
        self.assertTrue(STATE["closed"])  # mert a kapcsolat bezárult
        self.assertGreater(cid, 0)

    def test_full_streamed_answer(self):
        tokens = []
        answer, _ = self.brain.ask("Szia", cancel=threading.Event(), on_token=tokens.append)
        self.assertEqual(answer, "".join(tokens))
        self.assertEqual(len(tokens), 200)


if __name__ == "__main__":
    unittest.main()
