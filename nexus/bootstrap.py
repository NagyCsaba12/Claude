"""ALAPTUDÁS: a legjobb elérhető, hiteles források letöltése a netről (egyszeri / frissíthető).

Forrástípusok (magas megbízhatósági pontszámmal, hogy a keresésnél előnyt élvezzenek):
  - hivatalos dokumentációk (Python, MDN, Microsoft Learn, Rust Book, Go, Git Book, Arch Wiki, ...)
  - RFC szabványok (TCP/IP, DNS, DHCP, OSPF, BGP, TLS, ...) – a hálózati tudás elsődleges forrása
  - Wikipedia szócikkek (fogalmi alapok, magyar és angol)
  - gyártói dokumentáció célzott kereséssel (Cisco, MikroTik, Juniper, HPE Aruba, Fortinet, Microsoft)

Használat:  nexus bootstrap                      (minden terület)
            nexus bootstrap -a halozat programozas
            nexus bootstrap --scale 0.3           (gyors, kisebb alap)
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass

from nexus.knowledge import KnowledgeBase
from nexus.tools import web
from nexus.tools.documents import html_to_text


@dataclass(frozen=True)
class Crawl:
    url: str              # kiinduló oldal
    prefix: str = ""      # csak az ezzel kezdődő linkeket követi (alap: a kiinduló URL könyvtára)
    max_pages: int = 25


# ---------------------------------------------------------------- hivatalos dokumentációk
CRAWLS: dict[str, list[Crawl]] = {
    "programozas": [
        Crawl("https://docs.python.org/3/tutorial/index.html", max_pages=20),
        Crawl("https://docs.python.org/3/howto/index.html", max_pages=25),
        Crawl("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
              "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", 25),
        Crawl("https://www.typescriptlang.org/docs/handbook/intro.html",
              "https://www.typescriptlang.org/docs/handbook/", 20),
        Crawl("https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/", max_pages=15),
        Crawl("https://doc.rust-lang.org/book/", max_pages=30),
        Crawl("https://go.dev/doc/effective_go", max_pages=1),
        Crawl("https://dev.java/learn/", max_pages=25),
        Crawl("https://en.cppreference.com/w/cpp/language", "https://en.cppreference.com/w/cpp/language", 25),
        Crawl("https://www.postgresql.org/docs/current/tutorial.html",
              "https://www.postgresql.org/docs/current/tutorial", 20),
        Crawl("https://git-scm.com/book/en/v2", "https://git-scm.com/book/en/v2", 30),
        Crawl("https://www.gnu.org/software/bash/manual/bash.html", max_pages=1),
        Crawl("https://learn.microsoft.com/en-us/powershell/scripting/overview",
              "https://learn.microsoft.com/en-us/powershell/scripting/", 25),
        Crawl("https://owasp.org/Top10/", max_pages=15),
    ],
    "rendszergazda": [
        Crawl("https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/"
              "get-started/virtual-dc/active-directory-domain-services-overview",
              "https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/", 25),
        Crawl("https://learn.microsoft.com/en-us/troubleshoot/windows-server/welcome-windows-server",
              "https://learn.microsoft.com/en-us/troubleshoot/windows-server/", 30),
        Crawl("https://learn.microsoft.com/en-us/windows-server/networking/technologies/dhcp/dhcp-top",
              "https://learn.microsoft.com/en-us/windows-server/networking/", 20),
        Crawl("https://wiki.archlinux.org/title/General_recommendations", "https://wiki.archlinux.org/title/", 40),
        Crawl("https://ubuntu.com/server/docs", "https://ubuntu.com/server/docs", 30),
        Crawl("https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html", max_pages=1),
    ],
    "halozat": [],
    "dokumentumok": [
        Crawl("https://developers.google.com/style", "https://developers.google.com/style", 25),
        Crawl("https://www.writethedocs.org/guide/", "https://www.writethedocs.org/guide/", 20),
    ],
}

# ---------------------------------------------------------------- RFC szabványok
RFCS = {
    791: "IPv4", 8200: "IPv6", 9293: "TCP", 768: "UDP", 792: "ICMP", 826: "ARP", 1918: "Privát címek",
    4632: "CIDR", 1034: "DNS fogalmak", 1035: "DNS implementáció", 2131: "DHCP", 2328: "OSPFv2",
    4271: "BGP-4", 5798: "VRRP", 3022: "NAT", 4301: "IPsec architektúra", 7296: "IKEv2", 8446: "TLS 1.3",
    9110: "HTTP szemantika", 5424: "Syslog", 3411: "SNMP architektúra", 5905: "NTPv4", 4253: "SSH protokoll",
    2865: "RADIUS", 7348: "VXLAN",
}

# ---------------------------------------------------------------- Wikipedia fogalmak
WIKI_EN = [
    "OSI model", "Internet protocol suite", "Virtual LAN", "IEEE 802.1Q", "Spanning Tree Protocol",
    "Link aggregation", "Open Shortest Path First", "Border Gateway Protocol", "Routing Information Protocol",
    "Network address translation", "Subnetwork", "Classless Inter-Domain Routing", "Access-control list",
    "Firewall (computing)", "Virtual private network", "WireGuard", "IPsec", "Quality of service",
    "Wi-Fi", "IEEE 802.1X", "Simple Network Management Protocol", "Domain Name System",
    "Dynamic Host Configuration Protocol", "Active Directory", "Group Policy", "Kerberos (protocol)",
    "Lightweight Directory Access Protocol", "Hyper-V", "VMware ESXi", "Kubernetes", "Docker (software)",
    "Systemd", "RAID", "Backup", "Public key infrastructure", "Transport Layer Security",
    "Secure Shell", "Zero trust security model", "Principle of least privilege",
    "Software design pattern", "SOLID", "Test-driven development", "Big O notation",
    "Data structure", "Algorithm", "Regular expression", "Object-oriented programming",
    "Functional programming", "Concurrency (computer science)", "Relational database", "SQL",
    "Database normalization", "REST", "Git", "Continuous integration", "Infrastructure as code",
    "Ansible (software)", "Terraform (software)", "Technical writing", "Information retrieval",
]
WIKI_HU = [
    "Számítógép-hálózat", "IP-cím", "Útválasztás", "Tűzfal (informatika)", "Rendszergazda",
    "Programozási nyelv", "Operációs rendszer", "Adatbázis", "Mesterséges intelligencia",
]

# ---------------------------------------------------------------- gyártói dokumentáció (célzott keresés)
VENDOR_SEARCHES = {
    "halozat": [
        "site:cisco.com IOS XE VLAN configuration guide", "site:cisco.com IOS OSPF configuration guide",
        "site:cisco.com IOS ACL configuration guide", "site:cisco.com IOS NAT configuration guide",
        "site:cisco.com troubleshooting spanning tree", "site:help.mikrotik.com RouterOS firewall",
        "site:help.mikrotik.com RouterOS bridge VLAN", "site:help.mikrotik.com RouterOS WireGuard",
        "site:juniper.net Junos VLAN configuration", "site:juniper.net Junos OSPF configuration",
        "site:arubanetworks.com AOS-CX VLAN configuration", "site:docs.fortinet.com FortiGate firewall policy",
        "site:docs.netmiko.org OR site:ktbyers.github.io netmiko examples",
    ],
    "rendszergazda": [
        "site:learn.microsoft.com Windows Server backup best practices",
        "site:learn.microsoft.com Active Directory security best practices",
        "site:learn.microsoft.com Hyper-V overview", "site:learn.microsoft.com Group Policy troubleshooting",
    ],
}

AREAS = ["programozas", "rendszergazda", "halozat", "dokumentumok"]
TRUST_OFFICIAL = 0.9
TRUST_RFC = 0.95
TRUST_WIKI = 0.8
TRUST_VENDOR = 0.85


def _links(html: str, base: str) -> list[str]:
    out = []
    for href in re.findall(r'href\s*=\s*["\']([^"\'#]+)', html, re.I):
        u = urllib.parse.urljoin(base, href).split("#")[0].split("?")[0]
        if u.startswith("http"):
            out.append(u)
    return out


class Bootstrapper:
    def __init__(self, kb: KnowledgeBase, log=print, delay: float = 1.0, scale: float = 1.0):
        self.kb, self.log, self.delay, self.scale = kb, log, delay, scale
        self.added = 0

    def _store(self, text: str, uri: str, title: str, trust: float) -> None:
        if len(text) >= 300 and self.kb.add_document(text[:2_000_000], uri, "web", title, trust):
            self.added += 1
            self.log(f"  ✓ {title[:80]}")

    def crawl(self, c: Crawl) -> None:
        prefix = c.prefix or c.url.rsplit("/", 1)[0] + "/"
        limit = max(1, int(c.max_pages * self.scale))
        queue, seen, fetched = deque([c.url]), {c.url}, 0
        self.log(f"🌐 {c.url} (max {limit} oldal)")
        while queue and fetched < limit:
            url = queue.popleft()
            try:
                if not web.allowed_by_robots(url):
                    continue
                raw = web._get(url)
            except Exception as e:
                self.log(f"  × {url} ({type(e).__name__})")
                continue
            fetched += 1
            m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
            self._store(html_to_text(raw), url, html_to_text(m.group(1)) if m else url, TRUST_OFFICIAL)
            for u in _links(raw, url):
                if u.startswith(prefix) and u not in seen and not re.search(r"\.(png|jpg|gif|svg|zip|pdf)$", u):
                    seen.add(u)
                    queue.append(u)
            time.sleep(self.delay)

    def rfcs(self) -> None:
        items = list(RFCS.items())[: max(1, int(len(RFCS) * self.scale))]
        for num, name in items:
            url = f"https://www.rfc-editor.org/rfc/rfc{num}.txt"
            try:
                self._store(web._get(url, timeout=60), url, f"RFC {num} – {name}", TRUST_RFC)
            except Exception as e:
                self.log(f"  × RFC {num} ({type(e).__name__})")
            time.sleep(self.delay)

    def wikipedia(self) -> None:
        for lang, titles in (("en", WIKI_EN), ("hu", WIKI_HU)):
            titles = titles[: max(1, int(len(titles) * self.scale))]
            for i in range(0, len(titles), 20):  # az API egyszerre max 20 kivonatot ad
                q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1,
                                            "format": "json", "redirects": 1, "titles": "|".join(titles[i:i + 20])})
                try:
                    data = json.loads(web._get(f"https://{lang}.wikipedia.org/w/api.php?{q}"))
                except Exception as e:
                    self.log(f"  × Wikipedia ({type(e).__name__})")
                    continue
                for page in data.get("query", {}).get("pages", {}).values():
                    title = page.get("title", "")
                    url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                    self._store(page.get("extract", ""), url, f"Wikipedia: {title}", TRUST_WIKI)
                time.sleep(self.delay)

    def vendor_docs(self, area: str, per_query: int = 3) -> None:
        for q in VENDOR_SEARCHES.get(area, [])[: max(1, int(len(VENDOR_SEARCHES.get(area, [])) * self.scale))]:
            self.log(f"🔎 {q}")
            try:
                results = web.search(q, per_query)
            except Exception as e:
                self.log(f"  × keresés ({type(e).__name__})")
                continue
            for r in results:
                try:
                    self._store(web.fetch_text(r["url"]), r["url"], r["title"], TRUST_VENDOR)
                except Exception as e:
                    self.log(f"  × {r['url']} ({type(e).__name__})")
                time.sleep(self.delay)

    def run(self, areas: list[str] | None = None) -> int:
        areas = areas or AREAS
        for area in areas:
            self.log(f"\n===== ALAPTUDÁS: {area} =====")
            for c in CRAWLS.get(area, []):
                self.crawl(c)
            if area == "halozat":
                self.rfcs()
            self.vendor_docs(area)
        if set(areas) & {"halozat", "rendszergazda", "programozas"}:
            self.log("\n===== ALAPTUDÁS: Wikipedia fogalmak =====")
            self.wikipedia()
        return self.added
