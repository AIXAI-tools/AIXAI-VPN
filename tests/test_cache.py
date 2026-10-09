import tempfile
import unittest
from pathlib import Path

from src.core.cache import ServerCache
from src.core.vpngate import Server


def srv(host, country="JP", score=100):
    return Server(host, "10.0.0.1", score, 10, 1000, "X", country, 1, 1, "2weeks", "op")


class ServerCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_accumulates_across_fetches(self):
        c = ServerCache(self.path, ttl_hours=6)
        c.merge([srv("a", "JP")], now=1000)
        result = c.merge([srv("b", "US")], now=2000)
        self.assertEqual({s.hostname for s, _ in result}, {"a", "b"})

    def test_fresh_first_then_score(self):
        c = ServerCache(self.path)
        c.merge([srv("old-high", score=999)], now=1000)
        result = c.merge([srv("new-low", score=1), srv("new-mid", score=50)], now=2000)
        self.assertEqual([s.hostname for s, _ in result], ["new-mid", "new-low", "old-high"])
        self.assertEqual([f for _, f in result], [True, True, False])

    def test_expired_entries_dropped(self):
        c = ServerCache(self.path, ttl_hours=1)
        c.merge([srv("old")], now=0)
        result = c.merge([srv("new")], now=3601)
        self.assertEqual([s.hostname for s, _ in result], ["new"])

    def test_persists_to_disk(self):
        ServerCache(self.path).merge([srv("a")], now=1000)
        result = ServerCache(self.path).merge([], now=1001)
        self.assertEqual([s.hostname for s, _ in result], ["a"])
        self.assertEqual(result[0][1], False)

    def test_corrupt_file_starts_empty(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(ServerCache(self.path).merge([], now=0), [])


if __name__ == "__main__":
    unittest.main()
