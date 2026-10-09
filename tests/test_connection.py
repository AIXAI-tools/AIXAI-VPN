import threading
import time
import unittest

from src.connector.windows.sstp import DialResult, validate_host
from src.server.connection import MAX_ATTEMPTS, ConnectionManager


class FakeConnector:
    def __init__(self, good_hosts=(), delay=0.0):
        self.good_hosts = set(good_hosts)
        self.delay = delay
        self.tried = []
        self.disconnects = 0
        self.up = False  # 模擬 VPN 是否還連著
        self.release = threading.Event()

    def connect(self, host):
        self.tried.append(host)
        if self.delay:
            self.release.wait(self.delay)
        if host in self.good_hosts:
            self.up = True
            return DialResult(True, "已連線")
        return DialResult(False, "伺服器離線", 800)

    def disconnect(self):
        self.disconnects += 1
        self.up = False
        self.release.set()

    def is_connected(self):
        return self.up


def wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def locate():
    return {"ip": "1.2.3.4", "loc": "JP"}


class ValidateHostTest(unittest.TestCase):
    def test_accepts_vpngate_host(self):
        self.assertEqual(validate_host("public-vpn-184.opengw.net"), "public-vpn-184.opengw.net")

    def test_rejects_injection_and_other_domains(self):
        for bad in ["x.opengw.net'; Remove-Item C:\\ -Recurse; '", "evil.com", "a.opengw.net.evil.com",
                    "", "a b.opengw.net", "$(calc).opengw.net"]:
            with self.assertRaises(ValueError, msg=bad):
                validate_host(bad)


class ValidateEndpointTest(unittest.TestCase):
    def test_accepts_host_with_port(self):
        from src.connector.windows.sstp import validate_endpoint
        for ok in ["vpn687646657.opengw.net", "vpn687646657.opengw.net:1382", "a.opengw.net:65535"]:
            self.assertEqual(validate_endpoint(ok), ok)

    def test_rejects_bad_ports_and_injection(self):
        from src.connector.windows.sstp import validate_endpoint
        for bad in ["a.opengw.net:0", "a.opengw.net:65536", "a.opengw.net:1382;calc", "a.opengw.net:",
                    "a.opengw.net:1382'", "evil.com:443", "a.opengw.net:01382"]:
            with self.assertRaises(ValueError, msg=bad):
                validate_endpoint(bad)


class ConnectionManagerTest(unittest.TestCase):
    def test_falls_back_to_next_server(self):
        fake = FakeConnector(good_hosts={"b.opengw.net"})
        m = ConnectionManager(fake, locate)
        self.assertTrue(m.start("JP", ["a.opengw.net", "b.opengw.net", "c.opengw.net"]))
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "connected"))
        s = m.snapshot()
        self.assertEqual(fake.tried, ["a.opengw.net", "b.opengw.net"])
        self.assertEqual((s["host"], s["ip"], s["loc"]), ("b.opengw.net", "1.2.3.4", "JP"))

    def test_all_fail_reports_error(self):
        m = ConnectionManager(FakeConnector(), locate)
        m.start("JP", ["a.opengw.net", "b.opengw.net"])
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertIn("全部 2 台都連不上", m.snapshot()["message"])

    def test_attempts_capped(self):
        fake = FakeConnector()
        m = ConnectionManager(fake, locate)
        m.start("JP", [f"h{i}.opengw.net" for i in range(20)])
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertEqual(len(fake.tried), MAX_ATTEMPTS)

    def test_rejects_second_start_while_busy(self):
        fake = FakeConnector(good_hosts={"a.opengw.net"})
        m = ConnectionManager(fake, locate)
        m.start("JP", ["a.opengw.net"])
        wait_until(lambda: m.snapshot()["status"] == "connected")
        self.assertFalse(m.start("AU", ["b.opengw.net"]))

    def test_no_hosts(self):
        m = ConnectionManager(FakeConnector(), locate)
        self.assertFalse(m.start("US", []))
        self.assertEqual(m.snapshot()["status"], "idle")

    def test_disconnect_when_connected(self):
        fake = FakeConnector(good_hosts={"a.opengw.net"})
        m = ConnectionManager(fake, locate)
        m.start("JP", ["a.opengw.net"])
        wait_until(lambda: m.snapshot()["status"] == "connected")
        m.stop()
        self.assertEqual(m.snapshot()["status"], "idle")
        self.assertGreaterEqual(fake.disconnects, 1)

    def test_cancel_while_connecting(self):
        fake = FakeConnector(delay=2.0)
        m = ConnectionManager(fake, locate)
        m.start("JP", ["a.opengw.net", "b.opengw.net"])
        wait_until(lambda: fake.tried)
        m.stop()
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertEqual(m.snapshot()["message"], "已中斷")
        self.assertEqual(fake.tried, ["a.opengw.net"])  # 取消後不再試下一台


class FakeKillSwitch:
    def __init__(self, fail=False):
        self.fail = fail
        self.active = False
        self.engaged = []  # 每次 engage 收到的 host→ip
        self.releases = 0

    def engage(self, host_ips):
        if self.fail:
            raise RuntimeError("防火牆錯誤")
        self.engaged.append(dict(host_ips))
        self.active = True

    def release(self):
        self.releases += 1
        self.active = False


FAKE_DNS = {"a.opengw.net": "1.1.1.1", "b.opengw.net": "2.2.2.2"}


def fake_resolve(host):
    if host not in FAKE_DNS:
        raise OSError("not found")
    return FAKE_DNS[host]


class KillSwitchFlowTest(unittest.TestCase):
    def make(self, good=("a.opengw.net", "b.opengw.net"), ks=None, loc="JP"):
        self.fake = FakeConnector(good_hosts=set(good))
        self.ks = ks or FakeKillSwitch()
        return ConnectionManager(self.fake, lambda: {"ip": "9.9.9.9", "loc": loc}, killswitch=self.ks,
                                 resolve=fake_resolve, monitor_interval=0.02)

    def connected(self, m, host=None):
        return wait_until(lambda: m.snapshot()["status"] == "connected"
                          and (host is None or m.snapshot()["host"] == host))

    def test_engages_after_connect_with_resolved_ips(self):
        m = self.make()
        m.start("JP", ["a.opengw.net", "b.opengw.net", "c.opengw.net"])
        self.assertTrue(self.connected(m))
        self.assertTrue(m.snapshot()["protected"])
        self.assertEqual(self.ks.engaged[0], FAKE_DNS)  # c 查不到就跳過
        m.stop()

    def test_endpoint_with_port_resolves_host_only(self):  # ADR-017
        m = self.make(good=("a.opengw.net:1382",))
        m.start("JP", ["a.opengw.net:1382", "b.opengw.net"])
        self.assertTrue(self.connected(m, "a.opengw.net:1382"))
        self.assertEqual(self.ks.engaged[0], FAKE_DNS)  # 鍵是主機名稱，不含 port
        m.stop()

    def test_engage_failure_disconnects(self):
        m = self.make(ks=FakeKillSwitch(fail=True))
        m.start("JP", ["a.opengw.net"])
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "idle"))
        self.assertIn("斷線保護開啟失敗", m.snapshot()["message"])
        self.assertFalse(self.fake.up)

    def test_drop_reconnects_without_releasing_protection(self):
        m = self.make()
        m.start("JP", ["a.opengw.net", "b.opengw.net"])
        self.connected(m)
        self.fake.good_hosts = {"b.opengw.net"}  # a 掛了
        self.fake.up = False                     # 模擬意外斷線
        self.assertTrue(self.connected(m, "b.opengw.net"))
        self.assertEqual(self.ks.releases, 0)    # 重連期間保護一直開著
        self.assertTrue(self.ks.active)
        m.stop()

    def test_all_reconnects_fail_then_blocked_and_retry(self):
        m = self.make()
        m.start("JP", ["a.opengw.net", "b.opengw.net"])
        self.connected(m)
        self.fake.good_hosts = set()
        self.fake.up = False
        self.assertTrue(wait_until(lambda: m.snapshot()["status"] == "blocked"))
        self.assertTrue(m.snapshot()["protected"])
        self.assertTrue(self.ks.active)
        self.assertFalse(m.start("JP", ["a.opengw.net"]))  # blocked 時不能直接換國家
        self.fake.good_hosts = {"a.opengw.net"}
        self.assertTrue(m.retry())
        self.assertTrue(self.connected(m))
        m.stop()

    def test_stop_releases_protection(self):
        m = self.make()
        m.start("JP", ["a.opengw.net"])
        self.connected(m)
        m.stop()
        s = m.snapshot()
        self.assertEqual(s["status"], "idle")
        self.assertFalse(s["protected"])
        self.assertFalse(self.ks.active)

    def test_stop_from_blocked_restores_network(self):  # 「改用一般網路」
        m = self.make()
        m.start("JP", ["a.opengw.net"])
        self.connected(m)
        self.fake.good_hosts = set()
        self.fake.up = False
        wait_until(lambda: m.snapshot()["status"] == "blocked")
        m.stop()
        self.assertFalse(self.ks.active)
        self.assertEqual(m.snapshot()["status"], "idle")

    def test_country_mismatch_warning(self):
        m = self.make(loc="US")
        m.start("JP", ["a.opengw.net"])
        self.connected(m)
        self.assertIn("實際出口國家是 US", m.snapshot()["warning"])
        m.stop()


if __name__ == "__main__":
    unittest.main()
