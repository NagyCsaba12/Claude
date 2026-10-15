"""Wake-on-LAN: csomagépítés, MAC-formázás, megjegyzett gépek."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tecf.tools import network


class TestWakeOnLan(unittest.TestCase):
    def test_normalize_mac(self):
        for text in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF", "aa bb cc dd ee ff"):
            self.assertEqual(network._normalize_mac(text), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_hibas(self):
        for text in ("", "aa:bb:cc", "nem mac", "aa:bb:cc:dd:ee:ff:00"):
            with self.assertRaises(ValueError):
                network._normalize_mac(text)

    def test_magic_packet(self):
        pkt = network._magic_packet("aa:bb:cc:dd:ee:ff")
        self.assertEqual(len(pkt), 102)
        self.assertEqual(pkt[:6], b"\xff" * 6)
        self.assertEqual(pkt[6:12], b"\xaa\xbb\xcc\xdd\xee\xff")
        self.assertEqual(pkt[6:12] * 16, pkt[6:])

    def test_broadcast_of(self):
        self.assertEqual(network._broadcast_of("192.168.1.187"), "192.168.1.255")
        self.assertIsNone(network._broadcast_of("nem ip"))

    def test_megjegyzett_gep(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("TECF_HOME")
            os.environ["TECF_HOME"] = d
            try:
                network._remember_host("192.168.1.187", "aa:bb:cc:dd:ee:ff")
                self.assertEqual(network._known_hosts()["192.168.1.187"], "aa:bb:cc:dd:ee:ff")
                # BOM-os (PowerShell által írt) fájlt is el kell olvasni
                p = Path(d) / "data" / "gepek.json"
                p.write_text("﻿" + json.dumps({"gep": "00:11:22:33:44:55"}), encoding="utf-8")
                self.assertEqual(network._known_hosts()["gep"], "00:11:22:33:44:55")
            finally:
                os.environ.pop("TECF_HOME")
                if old is not None:
                    os.environ["TECF_HOME"] = old

    def test_mac_nelkul_nem_kuld(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("TECF_HOME")
            os.environ["TECF_HOME"] = d
            try:
                out = network.wake_host("10.99.99.99", wait_s=0)
            finally:
                os.environ.pop("TECF_HOME")
                if old is not None:
                    os.environ["TECF_HOME"] = old
        self.assertIn("MAC", out)

    def test_eszkozok_regisztralva(self):
        from tecf.tools import load_all
        for name in ("wake_host", "mac_lookup", "arp_table"):
            self.assertIn(name, load_all())


if __name__ == "__main__":
    unittest.main()
