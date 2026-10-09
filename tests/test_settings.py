import tempfile
import unittest
from pathlib import Path

from src.server.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            self.assertFalse(Settings(path).get("research_mode"))
            Settings(path).set("research_mode", True)
            self.assertTrue(Settings(path).get("research_mode"))

    def test_rejects_unknown_or_wrong_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp) / "s.json")
            for key, value in [("evil", True), ("research_mode", "true"), ("research_mode", 1)]:
                with self.assertRaises(ValueError):
                    s.set(key, value)

    def test_corrupt_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertFalse(Settings(path).get("research_mode"))
            path.write_text('{"research_mode": "yes"}', encoding="utf-8")
            self.assertFalse(Settings(path).get("research_mode"))  # 型別不對就忽略


if __name__ == "__main__":
    unittest.main()
