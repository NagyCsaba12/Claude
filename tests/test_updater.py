import tempfile
import unittest
import zipfile
from pathlib import Path

from tecf import updater

REPO_ROOT = Path(__file__).resolve().parent.parent


def github_like_zip(dest: Path, extra_req: str = "") -> Path:
    """A GitHub által adott forráskód-zip szerkezete: egyetlen gyökérmappa (Claude-<sha>/...)."""
    zp = dest / "src.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for p in (REPO_ROOT / "tecf").rglob("*.py"):
            z.write(p, f"Claude-abc123/{p.relative_to(REPO_ROOT)}")
        z.writestr("Claude-abc123/requirements-optional.txt", "pypdf\n" + extra_req)
        z.writestr("Claude-abc123/scripts/tecf.bat", "@echo uj\r\n")
        z.writestr("Claude-abc123/README.md", "uj")
    return zp


class UpdaterTest(unittest.TestCase):
    def test_apply_keeps_user_data(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "TecFAi"
            app = home / "app"
            (app / "tecf").mkdir(parents=True)
            (app / "tecf" / "__init__.py").write_text("# regi")
            (app / "tecf" / "torolt_modul.py").write_text("# regi")
            (app / "requirements-optional.txt").write_text("pypdf\n")
            (home / "data").mkdir()
            (home / "data" / "knowledge.db").write_bytes(b"tudas")
            (home / "config").mkdir()
            (home / "config" / "api_keys.json").write_text('{"openai": "sk"}')
            (home / "tecf.bat").write_bytes(b"@echo regi\r\n")

            changed = updater.apply_zip(github_like_zip(Path(d), "netmiko\n"), app, "abc123", log=lambda *_: None)

            self.assertIn("__version__", (app / "tecf" / "__init__.py").read_text())
            self.assertFalse((app / "tecf" / "torolt_modul.py").exists())
            self.assertTrue((app / "tecf" / "llm" / "base.py").exists())
            self.assertEqual(changed, ["requirements-optional.txt"])
            self.assertEqual((app / ".version").read_text(), "abc123")
            # a felhasználó adatai érintetlenek
            self.assertEqual((home / "data" / "knowledge.db").read_bytes(), b"tudas")
            self.assertEqual((home / "config" / "api_keys.json").read_text(), '{"openai": "sk"}')
            # a futó indítót nem írja felül, csak mellé teszi az újat
            self.assertEqual((home / "tecf.bat").read_bytes(), b"@echo regi\r\n")
            self.assertTrue((home / "tecf.bat.uj").exists())
            self.assertFalse(any(p.name.startswith(".tecf") for p in app.iterdir()))

    def test_rejects_foreign_zip(self):
        with tempfile.TemporaryDirectory() as d:
            zp = Path(d) / "x.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("valami/readme.txt", "x")
            with self.assertRaises(RuntimeError):
                updater.apply_zip(zp, Path(d), "x")

    def test_dev_checkout_is_not_overwritten(self):
        self.assertFalse(updater.is_installed_copy())
        self.assertFalse(updater.update(log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
