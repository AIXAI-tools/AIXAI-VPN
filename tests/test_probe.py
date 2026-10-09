import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.core.cache import ServerCache
from src.core.probe import probe_all, sstp_probe
from src.server import api

SAMPLE = (Path(__file__).parent / "fixtures" / "vpngate_sample.csv").read_text(encoding="utf-8")


class ProbeAllTest(unittest.TestCase):
    def test_keeps_only_usable_and_dedupes(self):
        calls = []

        def fake(host):
            calls.append(host)
            return {"a": 120, "c": 40}.get(host)

        self.assertEqual(probe_all(["a", "b", "c", "a"], probe=fake), {"a": 120, "c": 40})
        self.assertEqual(sorted(calls), ["a", "b", "c"])  # 重複的主機只檢查一次

    def test_empty(self):
        self.assertEqual(probe_all([]), {})

    def test_unreachable_returns_none(self):
        # 保留測試位址（TEST-NET-1）不會有人回應
        self.assertIsNone(sstp_probe("192.0.2.1", timeout=0.5))


class SearchFiltersByProbeTest(unittest.TestCase):
    def test_only_probed_servers_shown_sorted_by_latency(self):
        latency = {"public-vpn-1.opengw.net": 300, "public-vpn-2.opengw.net": 80}  # vpn-au 不通
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(api, "fetch_list", return_value=SAMPLE), \
                mock.patch.object(api, "tor_countries", return_value=None):
            search = api.make_search(ServerCache(Path(tmp) / "c.json"), prober=lambda hosts: latency)
            result = search()
        jp = next(c for c in result["countries"] if c["code"] == "JP")
        au = next(c for c in result["countries"] if c["code"] == "AU")
        self.assertEqual(jp["count"], 2)
        self.assertEqual(jp["best"], {"host": "public-vpn-2.opengw.net", "latency_ms": 80, "operator": "Bob"})
        self.assertEqual(au["count"], 0)  # 清單上有，但實測連不上 → 不顯示
        self.assertEqual(result["_candidates"]["JP"], ["public-vpn-2.opengw.net", "public-vpn-1.opengw.net"])
        self.assertNotIn("AU", result["_candidates"])
        self.assertEqual((result["checked"], result["usable"]), (3, 2))

    def test_custom_tcp_port_endpoint_used_when_443_closed(self):  # ADR-017
        import base64
        from src.core.vpngate import Server
        cfg = base64.b64encode(b"client\r\nproto tcp\r\nremote 203.0.113.5 1382\r\n").decode()
        csv_text = SAMPLE.replace(",AAAA", "," + cfg, 1)  # 第一台（public-vpn-1）改成 TCP 1382
        latency = {"public-vpn-1.opengw.net:1382": 150, "public-vpn-2.opengw.net": 300}
        seen = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(api, "fetch_list", return_value=csv_text), \
                mock.patch.object(api, "tor_countries", return_value=None):
            search = api.make_search(ServerCache(Path(tmp) / "c.json"),
                                     prober=lambda hosts: seen.extend(hosts) or latency)
            result = search()
        self.assertIn("public-vpn-1.opengw.net", seen)        # 443 也會試
        self.assertIn("public-vpn-1.opengw.net:1382", seen)   # 再試自己的 TCP port
        jp = next(c for c in result["countries"] if c["code"] == "JP")
        self.assertEqual(jp["best"]["host"], "public-vpn-1.opengw.net:1382")
        self.assertEqual(result["_candidates"]["JP"], ["public-vpn-1.opengw.net:1382", "public-vpn-2.opengw.net"])


class EndpointTest(unittest.TestCase):
    def test_openvpn_tcp_port(self):
        import base64
        from src.core.vpngate import openvpn_tcp_port
        enc = lambda t: base64.b64encode(t.encode()).decode()
        self.assertEqual(openvpn_tcp_port(enc("proto tcp\nremote 1.2.3.4 1382\n")), 1382)
        self.assertEqual(openvpn_tcp_port(enc("proto udp\nremote 1.2.3.4 1336\n")), 443)  # UDP 不能走 SSTP
        self.assertEqual(openvpn_tcp_port(enc("proto tcp\nremote 1.2.3.4 99999\n")), 443)
        self.assertEqual(openvpn_tcp_port("not base64!!"), 443)

    def test_split_endpoint(self):
        from src.core.vpngate import split_endpoint
        self.assertEqual(split_endpoint("a.opengw.net"), ("a.opengw.net", 443))
        self.assertEqual(split_endpoint("a.opengw.net:1382"), ("a.opengw.net", 1382))


if __name__ == "__main__":
    unittest.main()
