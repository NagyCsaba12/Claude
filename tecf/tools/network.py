"""Hálózati eszközök: diagnosztika és hálózati eszközök (Cisco, MikroTik, Juniper,
HP/Aruba, Huawei, Linux) programozása SSH-n keresztül.

SSH-hoz: pip install netmiko   (paramiko-t is telepít)
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from tecf.tools import tool

IS_WIN = sys.platform.startswith("win")

# netmiko device_type nevek
DEVICE_TYPES = {
    "cisco": "cisco_ios", "cisco_nxos": "cisco_nxos", "cisco_asa": "cisco_asa",
    "mikrotik": "mikrotik_routeros", "juniper": "juniper_junos", "aruba": "aruba_os",
    "hp": "hp_procurve", "huawei": "huawei", "fortinet": "fortinet", "paloalto": "paloalto_panos",
    "ubiquiti": "ubiquiti_edgeswitch", "linux": "linux",
}


@tool("Ping egy hosztra.")
def ping(host: str, count: int = 4) -> str:
    argv = ["ping", "-n" if IS_WIN else "-c", str(count), host]
    return subprocess.run(argv, capture_output=True, text=True, errors="replace").stdout


@tool("TCP portok ellenőrzése egy SAJÁT/engedélyezett hoszton (pl. '22,80,443' vagy '1-1024').")
def port_check(host: str, ports: str = "22,23,80,443,3389,8080", timeout: float = 0.8) -> str:
    plist: list[int] = []
    for part in ports.split(","):
        if "-" in part:
            a, b = part.split("-")
            plist.extend(range(int(a), int(b) + 1))
        elif part.strip():
            plist.append(int(part))

    def check(p: int) -> tuple[int, bool]:
        with socket.socket() as s:
            s.settimeout(timeout)
            return p, s.connect_ex((host, p)) == 0

    with ThreadPoolExecutor(64) as ex:
        open_ports = [p for p, ok in ex.map(check, plist[:5000]) if ok]
    return f"Nyitott portok {host}: {open_ports or 'nincs'}"


@tool("Élő hosztok keresése a saját alhálózaton, pl. '192.168.1.0/24'.")
def lan_scan(cidr: str, port: int = 0) -> str:
    net = ipaddress.ip_network(cidr, strict=False)
    if not net.is_private:
        return "Biztonsági okból csak privát (helyi) hálózat szkennelhető."
    hosts = list(net.hosts())[:1024]

    def alive(ip) -> str | None:
        argv = ["ping", "-n", "1", "-w", "500", str(ip)] if IS_WIN else ["ping", "-c", "1", "-W", "1", str(ip)]
        ok = subprocess.run(argv, capture_output=True).returncode == 0
        return str(ip) if ok else None

    with ThreadPoolExecutor(64) as ex:
        live = [h for h in ex.map(alive, hosts) if h]
    return "Élő hosztok:\n" + "\n".join(live) if live else "Nem található élő hoszt."


@tool("DNS feloldás.")
def dns_lookup(name: str) -> str:
    return "\n".join(sorted({i[4][0] for i in socket.getaddrinfo(name, None)}))


def _connect(host: str, vendor: str, username: str, password: str, port: int = 22):
    try:
        from netmiko import ConnectHandler
    except ImportError as e:
        raise RuntimeError("Hálózati eszköz programozásához: pip install netmiko") from e
    return ConnectHandler(device_type=DEVICE_TYPES.get(vendor, vendor), host=host, username=username,
                          password=password, port=port)


@tool("Csak olvasó (show) parancs futtatása hálózati eszközön SSH-n. vendor: " + ", ".join(DEVICE_TYPES))
def device_show(host: str, vendor: str, username: str, password: str, command: str) -> str:
    with _connect(host, vendor, username, password) as c:
        return c.send_command(command)


@tool("Konfigurációs parancsok küldése hálózati eszközre (sorokra bontva). MÓDOSÍTJA az eszközt!",
      dangerous=True)
def device_configure(host: str, vendor: str, username: str, password: str, commands: str,
                     save: bool = False) -> str:
    lines = [ln for ln in commands.splitlines() if ln.strip()]
    with _connect(host, vendor, username, password) as c:
        out = c.send_config_set(lines)
        if save:
            out += "\n" + c.save_config()
    return out


@tool("Hálózati eszköz teljes konfigurációjának mentése fájlba (backup).")
def device_backup(host: str, vendor: str, username: str, password: str, path: str) -> str:
    cmd = {"mikrotik": "/export", "juniper": "show configuration | display set"}.get(vendor, "show running-config")
    with _connect(host, vendor, username, password) as c:
        cfg = c.send_command(cmd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cfg)
    return f"Konfiguráció mentve: {path} ({len(cfg)} karakter)"


# ---------------------------------------------------------------- Wake-on-LAN
MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _known_hosts_path():
    from tecf.config import default_home
    return default_home() / "data" / "gepek.json"


def _known_hosts() -> dict[str, str]:
    """Megjegyzett gépek: IP vagy név -> MAC-cím. Kikapcsolt gép MAC-címe már
    nincs az ARP táblában, ezért érdemes eltenni, amíg a gép még elérhető."""
    p = _known_hosts_path()
    try:
        # A PowerShell BOM-mal írhatja az UTF-8 fájlokat, ezért utf-8-sig.
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        return {str(k).lower(): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember_host(host: str, mac: str) -> None:
    data = _known_hosts()
    data[host.lower()] = mac
    p = _known_hosts_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _normalize_mac(mac: str) -> str:
    """Bármilyen írásmódból egységes 'aa:bb:cc:dd:ee:ff' alak."""
    hexa = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(hexa) != 12:
        raise ValueError(f"Érvénytelen MAC-cím: {mac!r} (12 hexa jegy kell)")
    return ":".join(hexa[i:i + 2].lower() for i in range(0, 12, 2))


def _magic_packet(mac: str) -> bytes:
    """A Wake-on-LAN „magic packet”: 6 bájt 0xFF, utána 16-szor a MAC-cím."""
    raw = bytes.fromhex(_normalize_mac(mac).replace(":", ""))
    return b"\xff" * 6 + raw * 16


def _broadcast_of(ip: str) -> str | None:
    """A gép alhálózatának szórási címe (/24-et feltételezve), pl. 192.168.1.255."""
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address)
    except ValueError:
        return None


def _arp_entries() -> dict[str, str]:
    """Az ARP gyorsítótár: IP -> MAC. Csak nemrég elérhető gépeket tartalmaz."""
    argv = ["arp", "-a"] if IS_WIN else ["ip", "neigh"]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, errors="replace").stdout
    except OSError:
        out = ""
    if not out and not IS_WIN:  # régebbi rendszeren nincs iproute2
        try:
            out = subprocess.run(["arp", "-a"], capture_output=True, text=True, errors="replace").stdout
        except OSError:
            return {}
    table: dict[str, str] = {}
    for line in out.splitlines():
        ip_m, mac_m = IP_RE.search(line), MAC_RE.search(line)
        if ip_m and mac_m:
            table[ip_m.group(0)] = _normalize_mac(mac_m.group(0))
    return table


@tool("A gépek MAC-címe a helyi hálózaton (ARP tábla) és a megjegyzett gépek listája.")
def arp_table() -> str:
    rows = [f"{ip}  {mac}" for ip, mac in sorted(_arp_entries().items())]
    known = [f"{h}  {mac}" for h, mac in sorted(_known_hosts().items())]
    parts = ["ARP tábla (most elérhető gépek):\n" + ("\n".join(rows) or "üres")]
    if known:
        parts.append("Megjegyzett gépek (kikapcsolva is bekapcsolhatók):\n" + "\n".join(known))
    return "\n\n".join(parts)


@tool("Egy helyi gép MAC-címének kikeresése IP alapján (a gépnek elérhetőnek kell lennie).")
def mac_lookup(ip: str) -> str:
    known = _known_hosts().get(ip.lower())
    mac = _arp_entries().get(ip)
    if not mac:  # az ARP bejegyzést egy ping kelti életre
        subprocess.run(["ping", "-n", "1", "-w", "800", ip] if IS_WIN else ["ping", "-c", "1", "-W", "1", ip],
                       capture_output=True)
        mac = _arp_entries().get(ip)
    if mac:
        _remember_host(ip, mac)
        return f"{ip} MAC-címe: {mac} (megjegyeztem)"
    if known:
        return f"{ip} most nem válaszol, de korábban megjegyeztem a MAC-címét: {known}"
    return (f"{ip} MAC-címe nem állapítható meg: a gép nem válaszol, és nincs megjegyezve. "
            "A MAC-címet a router (DHCP lista) vagy a gép matricája adja meg.")


@tool("Kikapcsolt gép bekapcsolása a helyi hálózaton (Wake-on-LAN). host: IP, mac: ha nincs megjegyezve.")
def wake_host(host: str, mac: str = "", wait_s: float = 60) -> str:
    mac = mac or _known_hosts().get(host.lower(), "") or _arp_entries().get(host, "")
    if not mac:
        return (f"Nem tudom, mi a(z) {host} MAC-címe, Wake-on-LAN csomagot pedig csak arra lehet küldeni. "
                "Nézd meg a router DHCP listájában (vagy a gépen: `ip link`), majd add meg: "
                f"wake_host('{host}', mac='aa:bb:cc:dd:ee:ff'). Ha a gép épp bekapcsolva van, a "
                f"mac_lookup('{host}') kikeresi és megjegyzi.")
    try:
        packet = _magic_packet(mac)
    except ValueError as e:
        return str(e)
    mac = _normalize_mac(mac)
    _remember_host(host, mac)

    targets = ["255.255.255.255"]
    bcast = _broadcast_of(host)
    if bcast and bcast not in targets:
        targets.insert(0, bcast)
    sent = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in targets:
            for port in (9, 7):
                for _ in range(3):  # UDP: egy csomag elveszhet
                    try:
                        s.sendto(packet, (addr, port))
                        sent.append(f"{addr}:{port}")
                    except OSError as e:
                        sent.append(f"{addr}:{port} HIBA ({e})")
    lines = [f"Bekapcsoló (Wake-on-LAN) csomag elküldve ide: {mac}", "Címek: " + ", ".join(sorted(set(sent)))]

    if wait_s > 0 and IP_RE.fullmatch(host):
        deadline = time.monotonic() + wait_s
        argv = ["ping", "-n", "1", "-w", "1000", host] if IS_WIN else ["ping", "-c", "1", "-W", "1", host]
        while time.monotonic() < deadline:
            if subprocess.run(argv, capture_output=True).returncode == 0:
                lines.append(f"A gép elindult, {host} válaszol.")
                return "\n".join(lines)
        lines.append(f"{host} {wait_s:.0f} másodperc után sem válaszol. Indulhat még "
                     "(a BIOS/boot eltarthat), próbáld újra a pinget. Ha nem jön fel: a gép BIOS-ában "
                     "legyen bekapcsolva a Wake-on-LAN / PCI-E Power On, Linuxon pedig "
                     "`sudo ethtool -s eth0 wol g` (és az ethtool beállítás legyen állandó). "
                     "Wi-Fi-n a Wake-on-LAN általában nem működik, vezetékes kapcsolat kell.")
    return "\n".join(lines)
