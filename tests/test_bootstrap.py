import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nexus.bootstrap import Bootstrapper, Crawl
from nexus.knowledge import KnowledgeBase

BODY = "<p>" + "OSPF area 0 backbone routing tudás. " * 30 + "</p>"
PAGES = {
    "/docs/index.html": f"<title>Index</title>{BODY}<a href='a.html'>a</a><a href='/other/x.html'>kint</a>",
    "/docs/a.html": f"<title>A oldal</title>{BODY} VLAN trunk <a href='b.html#s'>b</a>",
    "/docs/b.html": f"<title>B oldal</title>{BODY} BGP szomszéd",
    "/other/x.html": f"<title>Kívül</title>{BODY}",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((body or "").encode())

    def log_message(self, *a):
        pass


class BootstrapTest(unittest.TestCase):
    def test_crawl_stays_in_prefix_and_dedups(self):
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with tempfile.TemporaryDirectory() as d:
            kb = KnowledgeBase(f"{d}/k.db")
            b = Bootstrapper(kb, log=lambda *_: None, delay=0)
            b.crawl(Crawl(f"{base}/docs/index.html", max_pages=10))
            uris = {r[0] for r in kb.db.execute("SELECT uri FROM sources")}
            self.assertEqual(uris, {f"{base}/docs/{p}" for p in ("index.html", "a.html", "b.html")})
            b.crawl(Crawl(f"{base}/docs/index.html", max_pages=10))  # újrafuttatás: nincs duplikátum
            self.assertEqual(kb.db.execute("SELECT count(*) FROM sources").fetchone()[0], 3)
            self.assertEqual(kb.search("BGP szomszéd")[0].source, f"{base}/docs/b.html")
            kb.close()
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
