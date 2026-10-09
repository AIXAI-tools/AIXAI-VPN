import ctypes
import ipaddress
import tempfile
import unittest
from pathlib import Path

from src.protection.ranges import ipv4_block_ranges, ipv6_block_ranges
from src.protection.windows.firewall import GROUP, build_enable_script
from src.protection.windows.hosts import MARKER, HostsFile, strip_marked, with_entries
from src.protection.windows.killswitch import KillSwitch


def in_ranges(ip, ranges):
    a = ipaddress.ip_address(ip)
    for r in ranges:
        lo, hi = (ipaddress.ip_address(x) for x in r.split("-"))
        if lo <= a <= hi:
            return True
    return False


class RangesTest(unittest.TestCase):
    def test_blocks_internet_but_not_server_or_lan(self):
        r = ipv4_block_ranges(["219.100.37.162"])
        for blocked in ["8.8.8.8", "1.1.1.1", "219.100.37.161", "219.100.37.163", "123.194.130.192"]:
            self.assertTrue(in_ranges(blocked, r), blocked)
        for allowed in ["219.100.37.162", "192.168.1.1", "10.0.0.5", "172.20.0.1", "127.0.0.1",
                        "169.254.1.1", "255.255.255.255", "224.0.0.251"]:
            self.assertFalse(in_ranges(allowed, r), allowed)

    def test_multiple_servers(self):
        r = ipv4_block_ranges(["1.1.1.1", "2.2.2.2"])
        self.assertFalse(in_ranges("1.1.1.1", r))
        self.assertFalse(in_ranges("2.2.2.2", r))
        self.assertTrue(in_ranges("1.1.1.2", r))

    def test_rejects_bad_ip(self):
        for bad in ["1.1.1", "x", "1.1.1.1; calc", "::1"]:
            with self.assertRaises(ValueError):
                ipv4_block_ranges([bad])

    def test_ipv6(self):
        r = ipv6_block_ranges()
        self.assertTrue(in_ranges("2001:4860:4860::8888", r))
        self.assertFalse(in_ranges("fe80::1", r))
        self.assertFalse(in_ranges("ff02::1", r))
        self.assertFalse(in_ranges("::1", r))


class FirewallScriptTest(unittest.TestCase):
    def test_script_shape(self):
        s = build_enable_script(["219.100.37.162"])
        self.assertIn(f"-Group '{GROUP}'", s)
        self.assertEqual(s.count("New-NetFirewallRule"), 4)
        self.assertIn("-InterfaceType Wired,Wireless", s)
        self.assertIn("-Action Block", s)
        self.assertNotIn("Allow", s)


class HostsTest(unittest.TestCase):
    ORIGINAL = "# Copyright (c) Microsoft\r\n127.0.0.1 localhost\r\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.path = d / "hosts"
        self.path.write_bytes(self.ORIGINAL.encode())
        self.hosts = HostsFile(self.path, d / "backup" / "hosts.backup")

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_and_remove_roundtrip(self):
        self.hosts.write_entries({"a.opengw.net": "1.1.1.1"})
        text = self.path.read_text()
        self.assertIn(f"1.1.1.1 a.opengw.net {MARKER}", text)
        self.assertIn("127.0.0.1 localhost", text)
        self.hosts.remove_entries()
        self.assertEqual(self.path.read_bytes().decode(), self.ORIGINAL)

    def test_rewrite_replaces_old_entries(self):
        self.hosts.write_entries({"a.opengw.net": "1.1.1.1"})
        self.hosts.write_entries({"b.opengw.net": "2.2.2.2"})
        text = self.path.read_text()
        self.assertNotIn("a.opengw.net", text)
        self.assertEqual(text.count(MARKER), 1)

    def test_backup_made_once(self):
        self.hosts.write_entries({"a.opengw.net": "1.1.1.1"})
        self.assertEqual(self.hosts.backup.read_bytes().decode(), self.ORIGINAL)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            with_entries("", {"evil.com": "1.1.1.1"})
        with self.assertRaises(ValueError):
            with_entries("", {"a.opengw.net": "1.1.1.1\r\n0.0.0.0 microsoft.com"})

    def test_strip_keeps_user_lines(self):
        t = "1.2.3.4 my.site\r\n5.6.7.8 x.opengw.net # AIXAI-VPN\r\n"
        self.assertEqual(strip_marked(t), "1.2.3.4 my.site\r\n")


class Recorder:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def enable(self, ips, luid):
        self.log.append(("wfp.enable", tuple(ips), luid))
        if self.fail:
            raise RuntimeError("boom")

    def disable(self):
        self.log.append(("disable",))

    def write_entries(self, e):
        self.log.append(("hosts.write", tuple(sorted(e))))

    def remove_entries(self):
        self.log.append(("hosts.remove",))


class KillSwitchTest(unittest.TestCase):
    def make(self, log, fail=False, luid=lambda: 42):
        return KillSwitch(wfp=Recorder(log, fail), hosts=Recorder(log), luid=luid, legacy_firewall=Recorder(log))

    def test_engage_passes_vpn_luid(self):
        log = []
        self.make(log).engage({"a.opengw.net": "1.1.1.1"})
        self.assertEqual(log, [("hosts.write", ("a.opengw.net",)), ("wfp.enable", ("1.1.1.1",), 42)])

    def test_engage_failure_rolls_back(self):
        log = []
        with self.assertRaises(RuntimeError):
            self.make(log, fail=True).engage({"a.opengw.net": "1.1.1.1"})
        self.assertEqual(log[-2:], [("disable",), ("hosts.remove",)])

    def test_missing_vpn_interface_fails_instead_of_blocking_vpn(self):
        def no_luid():
            raise OSError("找不到網路介面")
        log = []
        with self.assertRaises(OSError):
            self.make(log, luid=no_luid).engage({"a.opengw.net": "1.1.1.1"})
        self.assertNotIn("wfp.enable", [e[0] for e in log])

    def test_release_order(self):
        log = []
        self.make(log).release()
        self.assertEqual(log, [("disable",), ("hosts.remove",)])


class WfpLayoutTest(unittest.TestCase):
    """結構大小必須與 WireGuard for Windows（x64）的 *_Size 常數一致，否則呼叫 Windows API 會出錯。"""

    def test_struct_sizes(self):
        from src.protection.windows import wfp
        expected = {wfp.VALUE: 16, wfp.FILTER_CONDITION: 40, wfp.ACTION: 20, wfp.FILTER: 200,
                    wfp.SESSION: 72, wfp.SUBLAYER: 72, wfp.DISPLAY_DATA: 16, wfp.BYTE_BLOB: 16,
                    wfp.V4_ADDR_AND_MASK: 8, wfp.V6_ADDR_AND_MASK: 17}
        for cls, size in expected.items():
            self.assertEqual(ctypes.sizeof(cls), size, cls.__name__)

    def test_filter_offsets(self):
        from src.protection.windows.wfp import FILTER
        for name, off in {"displayData": 16, "flags": 32, "providerKey": 40, "providerData": 48, "layerKey": 64,
                          "subLayerKey": 80, "weight": 96, "numFilterConditions": 112, "filterCondition": 120,
                          "action": 128, "context": 152, "reserved": 168, "filterId": 176,
                          "effectiveWeight": 184}.items():
            self.assertEqual(getattr(FILTER, name).offset, off, name)

    def test_guid_bytes(self):
        import uuid
        from src.protection.windows.wfp import GUID
        g = GUID.of(uuid.UUID("c38d57d1-05a7-4c33-904f-7fbceee60e82"))
        self.assertEqual((g.Data1, g.Data2, g.Data3, bytes(g.Data4)),
                         (0xc38d57d1, 0x05a7, 0x4c33, bytes([0x90, 0x4f, 0x7f, 0xbc, 0xee, 0xe6, 0x0e, 0x82])))

    def test_v4_mask_host_order(self):
        from src.protection.windows.wfp import V4_ADDR_AND_MASK, v4_net_condition
        keep = []
        c = v4_net_condition("192.168.0.0/16", keep)
        obj = V4_ADDR_AND_MASK.from_address(c.conditionValue.value)
        self.assertEqual((obj.addr, obj.mask), (0xC0A80000, 0xFFFF0000))

    def test_rejects_bad_server_ip_before_touching_windows(self):
        from src.protection.windows.wfp import WfpKillSwitch
        with self.assertRaises(ValueError):
            WfpKillSwitch().enable(["1.2.3.4; evil"], None)


if __name__ == "__main__":
    unittest.main()
