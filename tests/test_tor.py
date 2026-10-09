import json
import tempfile
import threading
import unittest
from pathlib import Path

from src.connector.tor import build_torrc
from src.core.geoip import GeoIP
from src.core.tor_exits import count_exits
from src.protection.windows.proxy import BYPASS, PROXY_TYPE_PROXY, SystemProxy, tor_settings
from src.server.tor_session import TorManager
from tests.test_connection import wait_until


class GeoIPTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name) / "geoip"
        # 1.0.0.0-1.0.0.255 → AU；8.8.8.0-8.8.8.255 → US
        p.write_text("# comment\n16777216,16777471,AU\n134744064,134744319,US\n", encoding="utf-8")
        self.geo = GeoIP(p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lookup(self):
        self.assertEqual(self.geo.country("8.8.8.8"), "US")
        self.assertEqual(self.geo.country("1.0.0.1"), "AU")
        self.assertEqual(self.geo.country("9.9.9.9"), "")

    def test_real_tor_geoip_if_present(self):
        real = Path(__file__).resolve().parent.parent / "vendor" / "tor" / "data" / "geoip"
        if not real.exists():
            self.skipTest("vendor/tor 不存在")
        self.assertEqual(GeoIP(real).country("219.100.37.243"), "JP")


class TorExitsTest(unittest.TestCase):
    def test_count_only_targets_uppercased(self):
        data = {"relays": [{"country": "us"}, {"country": "us"}, {"country": "ca"}, {"country": "ru"}, {}]}
        counts = count_exits(data)
        self.assertEqual((counts["US"], counts["CA"], counts["JP"]), (2, 1, 0))
        self.assertNotIn("RU", counts)
        self.assertEqual(len(counts), 15)


class TorrcTest(unittest.TestCase):
    def test_contents(self):
        rc = build_torrc("US", 19080, 1234, Path("C:/x/data"), Path("C:/tor"))
        self.assertIn("ExitNodes {us}", rc)
        self.assertIn("StrictNodes 1", rc)
        self.assertIn("HTTPTunnelPort 127.0.0.1:19080", rc)  # 只聽本機
        self.assertIn("SocksPort 0", rc)
        self.assertIn("__OwningControllerProcess 1234", rc)  # App 消失 → Tor 自動結束

    def test_rejects_unknown_country(self):
        for bad in ["KR", "us}\nSocksPort 0.0.0.0:9050", ""]:
            with self.assertRaises(ValueError):
                build_torrc(bad, 1, 1, Path("x"))


class SystemProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.current = {"flags": 9, "server": None, "bypass": None, "autoconfig": None}
        self.applied = []

        def apply(s):
            self.applied.append(dict(s))
            self.current = dict(s)

        self.proxy = SystemProxy(Path(self.tmp.name) / "proxy-backup.json", lambda: dict(self.current), apply)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_and_restore(self):
        original = dict(self.current)
        self.proxy.set_tor(19080)
        self.assertEqual(self.current["server"], "127.0.0.1:19080")
        self.assertTrue(self.current["flags"] & PROXY_TYPE_PROXY)
        self.assertEqual(self.current["bypass"], BYPASS)
        self.assertTrue(self.proxy.restore())
        self.assertEqual(self.current, original)
        self.assertFalse(json.loads(self.proxy.backup_path.read_text())["active"])

    def test_second_set_keeps_original_backup(self):  # Tor 換 port 重設時，不能把 Tor 設定當成原始值
        original = dict(self.current)
        self.proxy.set_tor(1)
        self.proxy.set_tor(2)
        self.proxy.restore()
        self.assertEqual(self.current, original)

    def test_restore_without_backup_does_nothing(self):
        self.assertFalse(self.proxy.restore())
        self.assertEqual(self.applied, [])

    def test_tor_settings_disable_pac(self):
        self.assertEqual(tor_settings(5)["autoconfig"], "")


# ---- TorManager 流程 ----
class FakeRunner:
    exe = "C:/fake/tor.exe"

    def __init__(self, ok=True):
        self.ok = ok
        self.running = False
        self.port = 19080
        self.starts = 0

    def available(self):
        return True

    def start(self, country, timeout=180, on_progress=None):
        self.starts += 1
        if on_progress:
            on_progress(50)
            on_progress(100)
        self.running = self.ok
        return (self.ok, "ok" if self.ok else "Tor 啟動失敗")

    def is_running(self):
        return self.running

    def stop(self):
        self.running = False


class FakeKS:
    def __init__(self):
        self.apps = None
        self.active = False

    def engage_apps(self, paths):
        self.apps, self.active = list(paths), True

    def release(self):
        self.active = False


class FakeProxy:
    def __init__(self):
        self.port = None
        self.log = []

    def set_tor(self, port):
        self.port = port
        self.log.append("set")

    def restore(self):
        self.log.append("restore")
        self.port = None
        return True


class FakeGeo:
    def country(self, ip):
        return "US"


class TorManagerTest(unittest.TestCase):
    def make(self, ok=True):
        self.runner, self.ks, self.proxy = FakeRunner(ok), FakeKS(), FakeProxy()
        m = TorManager(self.runner, self.ks, self.proxy, FakeGeo(), monitor_interval=0.02)
        m._exit_location = lambda: {"ip": "204.8.96.120", "loc": "US"}
        return m

    def test_connect_engages_protection_then_proxy(self):
        m = self.make()
        self.assertTrue(m.start("US"))
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "connected"))
        s = m.snapshot()
        self.assertEqual((s["mode"], s["loc"], s["progress"], s["protected"]), ("tor", "US", 100, True))
        self.assertEqual(self.ks.apps, ["C:/fake/tor.exe"])  # 只放行 tor.exe
        self.assertEqual(self.proxy.port, 19080)
        m.stop()

    def test_stop_restores_everything(self):
        m = self.make()
        m.start("US")
        wait_until(lambda: m.snapshot()["status"] == "connected")
        m.stop()
        self.assertEqual(m.snapshot()["status"], "idle")
        self.assertIsNone(self.proxy.port)
        self.assertFalse(self.ks.active)
        self.assertFalse(self.runner.running)

    def test_boot_failure_leaves_system_untouched(self):
        m = self.make(ok=False)
        m.start("US")
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertIn("Tor 啟動失敗", m.snapshot()["message"])
        self.assertEqual(self.proxy.log, [])
        self.assertFalse(self.ks.active)

    def test_tor_crash_restarts_under_protection(self):
        m = self.make()
        m.start("US")
        wait_until(lambda: m.snapshot()["status"] == "connected")
        self.runner.running = False  # Tor 意外結束
        self.assertTrue(wait_until(lambda: self.runner.starts == 2 and m.snapshot()["status"] == "connected"))
        self.assertTrue(self.ks.active)  # 保護全程沒解除
        self.assertNotIn("restore", self.proxy.log)
        m.stop()

    def test_restart_failure_blocks_then_stop_restores(self):
        m = self.make()
        m.start("US")
        wait_until(lambda: m.snapshot()["status"] == "connected")
        self.runner.ok = False
        self.runner.running = False
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "blocked"))
        self.assertTrue(self.ks.active)
        m.stop()  # 改用一般網路
        self.assertFalse(self.ks.active)
        self.assertIsNone(self.proxy.port)

    def test_country_mismatch_warning(self):
        m = self.make()
        m._exit_location = lambda: {"ip": "1.1.1.1", "loc": "DE"}
        m.start("US")
        wait_until(lambda: m.snapshot()["status"] == "connected")
        self.assertIn("實際出口國家是 DE", m.snapshot()["warning"])
        m.stop()


if __name__ == "__main__":
    unittest.main()
