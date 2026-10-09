import base64
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.wgconf import ConfigError, parse
from src.server.vpnbook import ConfigStore, Fetcher, VpnbookManager
from tests.test_connection import wait_until

PRIV = base64.b64encode(b"\x01" * 32).decode()
PUB = base64.b64encode(b"\x02" * 32).decode()


def sample(endpoint="us16.vpnbook.com:443", allowed="0.0.0.0/0", extra=""):
    return f"""[Interface]
PrivateKey = {PRIV}
Address = 10.8.0.2/32
DNS = 1.1.1.1
{extra}
[Peer]
PublicKey = {PUB}
AllowedIPs = {allowed}
Endpoint = {endpoint}
"""


class WgConfTest(unittest.TestCase):
    def test_parse_and_country(self):
        cfg = parse(sample())
        self.assertEqual(cfg.summary(), {"server": "us16.vpnbook.com", "country": "US"})
        self.assertEqual(parse(sample("uk205.vpnbook.com:443")).country, "GB")

    def test_forces_full_tunnel(self):
        cfg = parse(sample(allowed="0.0.0.0/0"))
        self.assertIn("::/0", cfg.peer["allowedips"])
        self.assertIn("AllowedIPs = 0.0.0.0/0, ::/0", cfg.render())

    def test_rejects_non_vpnbook_endpoint(self):
        for ep in ["evil.com:443", "vpnbook.com.evil.com:443", "1.2.3.4:51820"]:
            with self.assertRaises(ConfigError, msg=ep):
                parse(sample(ep))

    def test_ip_endpoint_must_be_known_vpnbook_server(self):
        known = lambda: {"147.135.15.16": "us16.vpnbook.com"}
        cfg = parse(sample("147.135.15.16:443"), known)
        self.assertEqual(cfg.summary(), {"server": "us16.vpnbook.com", "country": "US"})
        with self.assertRaises(ConfigError):
            parse(sample("1.2.3.4:443"), known)
        with self.assertRaises(ConfigError):
            parse(sample("147.135.15.16:443"))  # 沒有比對清單就不接受 IP

    def test_rejects_script_hooks(self):
        with self.assertRaises(ConfigError):
            parse(sample(extra="PostUp = calc.exe"))

    def test_errors_never_contain_private_key(self):
        bad = sample().replace(PUB, "not-a-key")
        try:
            parse(bad)
        except ConfigError as exc:
            self.assertNotIn(PRIV, str(exc))
        else:
            self.fail("應該要拒絕")

    def test_rejects_bad_structure(self):
        for text in ["", "PrivateKey = x", sample() + "\n[Peer]\nPublicKey = " + PUB, "x" * 5000]:
            with self.assertRaises(ConfigError):
                parse(text)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_list_load(self):
        info = self.store.import_text(sample(), time.time())
        self.assertEqual(info["code"], "US")
        items = self.store.list()
        self.assertEqual([(i["code"], i["expired"]) for i in items], [("US", False)])
        self.assertGreaterEqual(items[0]["hours_left"], 167)
        self.assertIn("::/0", self.store.load("US"))
        self.assertIsNone(self.store.load("CA"))

    def test_expired_not_loadable(self):
        self.store.import_text(sample(), time.time() - 8 * 86400)
        self.assertTrue(self.store.list()[0]["expired"])
        self.assertIsNone(self.store.load("US"))

    def test_rejects_non_target_country(self):
        with self.assertRaises(ConfigError):
            self.store.import_text(sample("pl134.vpnbook.com:443"), time.time())


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.downloads = base / "Downloads"
        self.downloads.mkdir()
        self.store = ConfigStore(base / "store")
        self.events = []
        self.f = Fetcher(self.store, open_page=lambda: self.events.append("open") or True,
                         close_page=lambda: self.events.append("close"), downloads=lambda: self.downloads)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ignores_old_files_and_imports_new_download(self):
        old = self.downloads / "vpnbook-old.conf"
        old.write_text(sample(), encoding="utf-8")
        past = time.time() - 3600
        os.utime(old, (past, past))
        self.assertTrue(self.f.start())
        self.assertFalse(self.f.start())  # 等待中不能重複開始
        time.sleep(0.3)
        self.assertFalse(self.store.list())  # 舊檔不算
        (self.downloads / "vpnbook-client123.conf").write_text(sample("ca149.vpnbook.com:443"), encoding="utf-8")
        self.assertTrue(wait_until(lambda: not self.f.snapshot()["fetching"], timeout=8))
        self.assertEqual(self.f.snapshot()["imported"]["code"], "CA")
        self.assertEqual(self.events, ["open", "close"])

    def test_bad_download_reports_error_and_keeps_waiting(self):
        self.f.start()
        time.sleep(0.2)
        (self.downloads / "vpnbook-x.conf").write_text("garbage", encoding="utf-8")
        self.assertTrue(wait_until(lambda: "匯入失敗" in self.f.snapshot()["message"], timeout=8))
        self.assertTrue(self.f.snapshot()["fetching"])  # 不停止，等使用者重新下載
        (self.downloads / "vpnbook-y.conf").write_text(sample(), encoding="utf-8")
        self.assertTrue(wait_until(lambda: not self.f.snapshot()["fetching"], timeout=10))
        self.assertEqual(self.f.snapshot()["imported"]["code"], "US")


class FakeWG:
    def __init__(self, ok=True):
        self.ok, self.up, self.texts, self.disconnects = ok, False, [], 0

    def available(self):
        return True

    def connect(self, text):
        self.texts.append(text)
        self.up = self.ok
        return (self.ok, "已連線" if self.ok else "握手失敗")

    def is_connected(self):
        return self.up

    def disconnect(self):
        self.disconnects += 1
        self.up = False


class VpnbookManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.store.import_text(sample(), time.time())

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, ok=True, loc="US"):
        self.wg = FakeWG(ok)
        return VpnbookManager(self.wg, self.store, lambda: {"ip": "9.9.9.9", "loc": loc}, monitor_interval=0.02)

    def test_connect_and_stop(self):
        m = self.make()
        self.assertTrue(m.start("US"))
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "connected"))
        s = m.snapshot()
        self.assertEqual((s["mode"], s["host"], s["protected"]), ("vpnbook", "us16.vpnbook.com", True))
        m.stop()
        self.assertEqual(m.snapshot()["status"], "idle")
        self.assertFalse(self.wg.up)

    def test_no_config_refuses(self):
        m = self.make()
        self.assertFalse(m.start("CA"))
        self.assertIn("請先取得", m.snapshot()["message"])

    def test_handshake_failure(self):
        m = self.make(ok=False)
        m.start("US")
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertIn("握手失敗", m.snapshot()["message"])

    def test_tunnel_stops_unexpectedly_reported(self):
        m = self.make()
        m.start("US")
        wait_until(lambda: m.snapshot()["status"] == "connected")
        self.wg.up = False
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertIn("意外停止", m.snapshot()["message"])
        self.assertFalse(m.snapshot()["protected"])


if __name__ == "__main__":
    unittest.main()
