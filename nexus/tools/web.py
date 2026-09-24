"""Internetes kutatás: keresés (DuckDuckGo HTML, kulcs nélkül) és oldal letöltés."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import urllib.robotparser
from functools import lru_cache

from nexus.tools import tool
from nexus.tools.documents import html_to_text

UA = "NexusAI/0.1 (+personal research assistant)"


def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "hu,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read(3_000_000).decode(charset, "replace")


@lru_cache(maxsize=256)
def _robots(base: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
    try:
        rp.read()
    except Exception:
        rp.allow_all = True
    return rp


def allowed_by_robots(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return _robots(f"{u.scheme}://{u.netloc}").can_fetch(UA, url)


def search(query: str, max_results: int = 8) -> list[dict]:
    raw = _get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}))
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw, re.S):
        href = m.group(1)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        url = q.get("uddg", [href])[0]
        if url.startswith("//"):
            url = "https:" + url
        title = html_to_text(m.group(2))
        if url.startswith("http") and "duckduckgo.com" not in url:
            results.append({"title": title, "url": url})
        if len(results) >= max_results:
            break
    return results


def fetch_text(url: str) -> str:
    if not allowed_by_robots(url):
        raise PermissionError(f"A robots.txt tiltja: {url}")
    return html_to_text(_get(url))


@tool("Internetes keresés. Címeket és URL-eket ad vissza.")
def web_search(query: str, max_results: int = 8) -> str:
    res = search(query, max_results)
    return "\n".join(f"{i + 1}. {r['title']}\n   {r['url']}" for i, r in enumerate(res)) or "Nincs találat."


@tool("Weboldal letöltése és szöveges tartalmának kinyerése.")
def web_fetch(url: str, max_chars: int = 15000) -> str:
    return fetch_text(url)[:max_chars]
