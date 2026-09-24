import tempfile
import unittest
from pathlib import Path

try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@unittest.skipUnless(HAS_TORCH, "PyTorch nincs telepítve")
class OwnModelTest(unittest.TestCase):
    def test_build_train_resume_and_chat(self):
        from tecf.config import Config
        from tecf.knowledge import KnowledgeBase
        from tecf.llm import model_dir, pipeline
        from tecf.llm.train import train
        from tecf.providers import get_provider

        with tempfile.TemporaryDirectory() as d:
            cfg = Config.load(d)
            kb = KnowledgeBase(cfg.db_path)
            for i in range(40):
                kb.add_document(f"{i}. dokumentum: a VLAN a hálózat logikai felosztása. " * 20, f"doc{i}")
            cid = kb.log_conversation("Mi a VLAN?", "A VLAN virtuális helyi hálózat.", "t", 1)
            kb.rate(cid, 1)
            kb.close()
            root = model_dir(cfg.root)
            logs = []
            pipeline.collect(cfg, sources={}, log=logs.append)
            meta = pipeline.prepare(cfg, log=logs.append)
            self.assertGreater(meta["pretrain"]["train"], 1000)
            self.assertGreater(meta["sft"]["train"], 0)

            r1 = train(root, "pretrain", minutes=0.1, preset="teszt", log=logs.append)
            self.assertTrue((root / "model.pt").exists())
            r2 = train(root, "pretrain", minutes=0.1, log=logs.append)  # folytatás a checkpointból
            self.assertGreater(r2["steps"], r1["steps"])
            self.assertEqual(r2["preset"], "teszt")

            pipeline.use(cfg, True)
            self.assertEqual(Config.load(d).local_provider, "tecf-sajat")
            p = get_provider("tecf-sajat", {}, None)
            p.base_url = str(root)
            self.assertTrue(p.available())
            self.assertIsInstance(p.chat([{"role": "user", "content": "Mi a VLAN?"}]), str)


if __name__ == "__main__":
    unittest.main()
