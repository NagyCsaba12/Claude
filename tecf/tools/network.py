"""Hálózati eszközök: diagnosztika és hálózati eszközök (Cisco, MikroTik, Juniper,
HP/Aruba, Huawei, Linux) programozása SSH-n keresztül.

SSH-hoz: pip install netmiko   (paramiko-t is telepít)
"""
from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
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
