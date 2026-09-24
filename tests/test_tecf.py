import json
import tempfile
import unittest
from pathlib import Path

from tecf.brain import Brain
from tecf.config import Config
from tecf.knowledge import KnowledgeBase, chunk_text
from tecf.providers import PROVIDERS, get_provider
from tecf.tools import load_all, parse_tool_calls, run_tool
from tecf.tools.documents import create_document, extract_text


class TecFTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config.load(self.tmp.name)
        self.cfg.offline_only = True
        self.cfg.local_provider = "llamacpp"  # nem fut -> offline tudásbázis mód
        self.kb = KnowledgeBase(self.cfg.db_path)

    def tearDown(self):
        self.kb.close()
        self.tmp.cleanup()

    def test_chunking(self):
        text = "\n\n".join(f"Bekezdés {i} " + "szó " * 60 for i in range(20))
        chunks = chunk_text(text, size=500)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 700 for c in chunks))

    def test_search_hungarian_diacritics_and_dedup(self):
        sid = self.kb.add_document("A VLAN trunk port konfigurálása Cisco kapcsolón: switchport mode trunk.",
                                   "doc1", trust=0.9)
        self.assertIsNotNone(sid)
        self.assertIsNone(self.kb.add_document("A VLAN trunk port konfigurálása Cisco kapcsolón: switchport "
                                               "mode trunk.", "doc1"))
        hits = self.kb.search("hogyan konfiguralok trunk portot")
        self.assertEqual(hits[0].source, "doc1")

    def test_memory_confidence_grows(self):
        self.kb.remember("A szerver neve DC01.")
        self.kb.remember("A szerver neve DC01.")
        row = self.kb.recall("szerver neve")[0]
        self.assertGreater(row["confidence"], 0.6)

    def test_rating_feeds_knowledge_and_topics(self):
        good = self.kb.log_conversation("Mi a DHCP?", "Dinamikus címkiosztó protokoll.", "t", 0)
        bad = self.kb.log_conversation("Mi az OSPF area 0?", "nem tudom", "t", 0)
        self.kb.rate(good, 1)
        self.kb.rate(bad, -1)
        self.assertTrue(self.kb.search("DHCP címkiosztó"))
        self.assertIn("OSPF", self.kb.next_topics(5)[0]["topic"])
        out = Path(self.tmp.name) / "train.jsonl"
        self.assertEqual(self.kb.export_training_data(out), 1)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["messages"][0]["content"], "Mi a DHCP?")

    def test_offline_answer_uses_kb(self):
        self.kb.add_document("A PowerShell Get-ADUser parancs lekérdezi az Active Directory felhasználókat.",
                             "ps-doc", trust=0.9)
        brain = Brain(self.cfg, self.kb, log=lambda *_: None)
        answer, cid = brain.ask("Get-ADUser mire jó?")
        self.assertIn("Get-ADUser", answer)
        self.assertGreater(cid, 0)

    def test_tool_protocol(self):
        load_all()
        calls = parse_tool_calls('Nézzük:\n```tool\n{"tool": "list_dir", "args": {"path": "."}}\n```')
        self.assertEqual(calls[0]["tool"], "list_dir")
        self.assertEqual(run_tool({"tool": "run_command", "args": {"command": "echo x"}}, lambda _: False),
                         "A felhasználó elutasította a műveletet.")

    def test_documents_roundtrip(self):
        p = Path(self.tmp.name) / "doc.html"
        create_document(str(p), "# Cím\n\n- elem\n\nSzöveg **fontos**", "Teszt")
        self.assertIn("fontos", extract_text(p))

    def test_providers_registry(self):
        self.assertGreaterEqual(len(PROVIDERS), 25)
        p = get_provider("openai:gpt-4o", {"openai": "sk-test"})
        self.assertEqual((p.model, p.api_key), ("gpt-4o", "sk-test"))


if __name__ == "__main__":
    unittest.main()
