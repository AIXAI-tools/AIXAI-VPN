import unittest
from pathlib import Path

from src.core.countries import TARGET_COUNTRIES
from src.core.vpngate import availability, fetch_list, filter_targets, group_by_country, parse_list

SAMPLE = (Path(__file__).parent / "fixtures" / "vpngate_sample.csv").read_text(encoding="utf-8")


class ParseListTest(unittest.TestCase):
    def test_skips_header_footer_and_broken_rows(self):
        servers = parse_list(SAMPLE)
        self.assertEqual([s.hostname for s in servers], ["public-vpn-1", "public-vpn-2", "vpn-kr", "vpn-au"])

    def test_fields(self):
        s = parse_list(SAMPLE)[0]
        self.assertEqual(s.ip, "10.0.0.1")
        self.assertEqual(s.score, 500000)
        self.assertEqual(s.ping_ms, 12)
        self.assertEqual(s.country_code, "JP")
        self.assertEqual(s.sstp_host, "public-vpn-1.opengw.net")

    def test_missing_ping_is_none(self):
        au = [s for s in parse_list(SAMPLE) if s.country_code == "AU"][0]
        self.assertIsNone(au.ping_ms)


class FilterTest(unittest.TestCase):
    def test_only_target_countries(self):
        codes = {s.country_code for s in filter_targets(parse_list(SAMPLE))}
        self.assertEqual(codes, {"JP", "AU"})  # KR 不在 15 國

    def test_group_sorted_by_score(self):
        groups = group_by_country(filter_targets(parse_list(SAMPLE)))
        self.assertEqual([s.hostname for s in groups["JP"]], ["public-vpn-2", "public-vpn-1"])

    def test_availability_lists_all_15(self):
        result = availability(parse_list(SAMPLE))
        self.assertEqual(len(result), 15)
        self.assertEqual([c for c, _, _ in result], list(TARGET_COUNTRIES))
        counts = {c: n for c, _, n in result}
        self.assertEqual(counts["JP"], 2)
        self.assertEqual(counts["AU"], 1)
        self.assertEqual(counts["US"], 0)


class FetchTest(unittest.TestCase):
    def test_rejects_plain_http(self):
        with self.assertRaises(ValueError):
            fetch_list("http://www.vpngate.net/api/iphone/")


if __name__ == "__main__":
    unittest.main()
