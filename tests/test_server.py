"""本機 API 伺服器安全測試（ADR-007）。"""

import http.client
import json
import threading
import unittest

from src.server.api import TOKEN_HEADER, AppServer
from src.server.connection import ConnectionManager
from tests.test_connection import FakeConnector, locate, wait_until
from tests.test_tor import FakeGeo, FakeKS, FakeProxy, FakeRunner
from src.server.tor_session import TorManager
from src.server.settings import Settings
from src.version import TERMS_VERSION
from src.server.vpnbook import ConfigStore, Fetcher, VpnbookManager
from tests.test_vpnbook import FakeWG, sample
import tempfile, time
from pathlib import Path

TOKEN = "test-token-123"
FAKE_RESULT = {"total": 0, "fetched_at": "2026-10-09T00:00:00+00:00", "countries": []}
FAKE_SEARCH = dict(FAKE_RESULT, _candidates={"JP": ["good.opengw.net"]})


class ServerSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = ConnectionManager(FakeConnector(good_hosts={"good.opengw.net"}), locate)
        cls.tor = TorManager(FakeRunner(), FakeKS(), FakeProxy(), FakeGeo(), monitor_interval=0.02)
        cls.tor._exit_location = lambda: {"ip": "204.8.96.120", "loc": "US"}
        cls.tmp = tempfile.TemporaryDirectory()
        store = ConfigStore(Path(cls.tmp.name))
        store.import_text(sample(), time.time())
        cls.vpnbook = VpnbookManager(FakeWG(), store, locate, monitor_interval=0.02)
        cls.opened = []
        cls.fetcher = Fetcher(store, open_page=lambda: cls.opened.append(1) or True, close_page=lambda: None,
                              downloads=lambda: Path(cls.tmp.name))
        settings = Settings(Path(cls.tmp.name) / "settings.json")
        settings.set("terms_accepted", TERMS_VERSION)  # 既有測試假設已同意條款；條款流程另外測
        cls.urls = []  # 攔截「開啟網頁」，不真的開瀏覽器
        cls.quits = []
        cls.server = AppServer(TOKEN, search=lambda: FAKE_SEARCH, manager=cls.manager, tor=cls.tor,
                               vpnbook=cls.vpnbook, fetcher=cls.fetcher, settings=settings,
                               on_quit=lambda: cls.quits.append(1),
                               open_url=lambda url: cls.urls.append(url) or True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.port
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fetcher.TIMEOUT = 0
        cls.tmp.cleanup()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res.status, body, res

    def test_binds_to_localhost_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_static_page_served_with_csp(self):
        status, body, res = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"AIXAI-VPN", body)
        self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))

    def test_wrong_host_rejected(self):  # 防 DNS rebinding
        status, _, _ = self.request("GET", "/", {"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_unknown_path_and_traversal(self):
        self.assertEqual(self.request("GET", "/../src/app.py")[0], 404)
        self.assertEqual(self.request("GET", "/api.py")[0], 404)

    def test_api_requires_token(self):
        self.assertEqual(self.request("GET", "/api/status")[0], 403)
        self.assertEqual(self.request("GET", "/api/status", {TOKEN_HEADER: "wrong"})[0], 403)

    def test_api_with_token(self):
        status, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["connected"], False)

    def test_post_requires_origin(self):
        self.assertEqual(self.request("POST", "/api/search", {TOKEN_HEADER: TOKEN})[0], 403)

    def test_post_rejects_foreign_origin(self):  # 防其他網站跨站呼叫
        status, _, _ = self.request("POST", "/api/search", {TOKEN_HEADER: TOKEN, "Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_post_rejects_missing_token_even_with_origin(self):
        self.assertEqual(self.request("POST", "/api/search", {"Origin": self.origin})[0], 403)

    def test_search_ok(self):
        status, body, _ = self.request("POST", "/api/search", {TOKEN_HEADER: TOKEN, "Origin": self.origin})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), FAKE_RESULT)

    def test_search_failure_reported(self):
        def boom():
            raise OSError("network down")
        self.server.search = boom
        try:
            status, body, _ = self.request("POST", "/api/search", {TOKEN_HEADER: TOKEN, "Origin": self.origin})
        finally:
            self.server.search = lambda: FAKE_SEARCH
        self.assertEqual(status, 502)
        self.assertIn("network down", json.loads(body)["error"])

    # ---- 連線 API ----
    def post(self, path, body=None):
        h = {TOKEN_HEADER: TOKEN, "Origin": self.origin, "Content-Type": "application/json"}
        return self.request("POST", path, h, None if body is None else json.dumps(body))

    def test_search_hides_internal_candidates(self):
        status, body, _ = self.post("/api/search")
        self.assertNotIn("_candidates", json.loads(body))

    def test_connect_rejects_unknown_country(self):
        self.assertEqual(self.post("/api/connect", {"country": "KR"})[0], 400)
        self.assertEqual(self.post("/api/connect", {"country": "'; drop"})[0], 400)

    def test_connect_rejects_oversized_body(self):
        self.assertEqual(self.post("/api/connect", {"country": "JP", "pad": "x" * 5000})[0], 400)

    def test_connect_requires_token(self):
        status, _, _ = self.request("POST", "/api/connect", {"Origin": self.origin}, json.dumps({"country": "JP"}))
        self.assertEqual(status, 403)

    def test_connect_and_disconnect_flow(self):
        self.post("/api/search")
        status, _, _ = self.post("/api/connect", {"country": "JP"})
        self.assertEqual(status, 202)
        self.assertTrue(wait_until(lambda: self.manager.snapshot()["status"] == "connected"))
        _, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
        st = json.loads(body)
        self.assertTrue(st["connected"])
        self.assertEqual(st["connection"]["host"], "good.opengw.net")
        self.assertEqual(self.post("/api/connect", {"country": "JP"})[0], 409)  # 已連線不能再連
        self.assertEqual(self.post("/api/disconnect", {})[0], 200)
        self.assertEqual(self.manager.snapshot()["status"], "idle")

    # ---- 視窗心跳 ----
    def test_heartbeat_requires_token(self):
        status, _, _ = self.request("POST", "/api/heartbeat", {"Origin": self.origin}, "{}")
        self.assertEqual(status, 403)

    def test_heartbeat_and_bye(self):
        self.assertEqual(self.post("/api/heartbeat", {})[0], 200)
        self.assertFalse(self.server.ui_gone())
        self.assertEqual(self.post("/api/bye", {})[0], 200)
        self.assertFalse(self.server.ui_gone())  # 還在寬限期內（重新整理會再送心跳）
        self.server.last_seen -= self.server.BYE_GRACE + 1
        self.assertTrue(self.server.ui_gone())
        self.post("/api/heartbeat", {})  # 復原，避免影響其他測試
        self.assertFalse(self.server.ui_gone())

    # ---- Tor 模式 ----
    def test_connect_rejects_unknown_mode(self):
        self.assertEqual(self.post("/api/connect", {"country": "US", "mode": "evil"})[0], 400)

    def test_tor_connect_and_only_one_mode_at_a_time(self):
        self.assertEqual(self.post("/api/connect", {"country": "US", "mode": "tor"})[0], 202)
        self.assertTrue(wait_until(lambda: self.tor.snapshot()["status"] == "connected"))
        _, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
        st = json.loads(body)
        self.assertEqual((st["connection"]["mode"], st["connection"]["loc"]), ("tor", "US"))
        self.post("/api/search")
        self.assertEqual(self.post("/api/connect", {"country": "JP"})[0], 409)  # Tor 連著時不能再開 VPN Gate
        self.assertEqual(self.post("/api/disconnect", {})[0], 200)
        self.assertEqual(self.tor.snapshot()["status"], "idle")

    # ---- VPNBook ----
    def test_status_lists_vpnbook_configs_without_keys(self):
        _, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
        vb = json.loads(body)["vpnbook"]
        self.assertEqual([c["code"] for c in vb["configs"]], ["US"])
        self.assertNotIn("PrivateKey", body.decode())

    def test_vpnbook_connect_and_disconnect(self):
        self.assertEqual(self.post("/api/connect", {"country": "US", "mode": "vpnbook"})[0], 202)
        self.assertTrue(wait_until(lambda: self.vpnbook.snapshot()["status"] == "connected"))
        self.assertEqual(self.post("/api/connect", {"country": "US", "mode": "tor"})[0], 409)  # 同時只能一種
        self.post("/api/disconnect", {})
        self.assertEqual(self.vpnbook.snapshot()["status"], "idle")

    def test_vpnbook_fetch_requires_token_and_starts_once(self):
        status, _, _ = self.request("POST", "/api/vpnbook/fetch", {"Origin": self.origin}, "{}")
        self.assertEqual(status, 403)
        self.assertEqual(self.post("/api/vpnbook/fetch", {"country": "JP"})[0], 400)  # VPNBook 沒有日本
        self.assertEqual(self.post("/api/vpnbook/fetch", {"country": "CA"})[0], 202)
        self.assertEqual(self.post("/api/vpnbook/fetch", {})[0], 409)
        self.assertTrue(wait_until(lambda: self.opened))

    # ---- 研究模式 ----
    def test_research_mode_setting_validated_and_persisted(self):
        self.assertEqual(self.post("/api/settings", {"research_mode": "yes"})[0], 400)
        self.assertEqual(self.post("/api/settings", {"research_mode": True})[0], 200)
        _, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
        self.assertTrue(json.loads(body)["research_mode"])
        self.assertTrue(Settings(self.server.settings.path).get("research_mode"))  # 重開也記得
        self.post("/api/settings", {"research_mode": False})

    def test_research_tick_retries_only_when_blocked_and_enabled(self):
        calls = []
        blocked = {"status": "blocked", "protected": True}
        fake = type("M", (), {"snapshot": lambda self: blocked, "retry": lambda self: calls.append(1) or True})()
        original = self.server.active
        self.server.active = lambda: fake
        try:
            self.server.settings.set("research_mode", False)
            self.assertFalse(self.server.research_tick())   # 沒開研究模式 → 不自動重試
            self.server.settings.set("research_mode", True)
            self.assertTrue(self.server.research_tick())
            blocked["status"] = "connected"
            self.assertFalse(self.server.research_tick())   # 不是暫停狀態 → 不動作
        finally:
            self.server.active = original
            self.server.settings.set("research_mode", False)
        self.assertEqual(calls, [1])

    # ---- 使用條款、回報、更新（ADR-016）----
    def test_terms_gate_connect_until_accepted(self):
        settings = self.server.settings
        settings.set("terms_accepted", "")
        try:
            _, body, _ = self.request("GET", "/api/status", {TOKEN_HEADER: TOKEN})
            self.assertFalse(json.loads(body)["terms"]["accepted"])
            status, body, _ = self.post("/api/connect", {"country": "JP", "mode": "vpngate"})
            self.assertEqual(status, 409)
            self.assertIn("條款", json.loads(body)["error"])
            self.assertEqual(self.post("/api/terms/accept", {"version": "1999-01-01"})[0], 400)  # 舊版本不算
            self.assertEqual(self.post("/api/terms/accept", {"version": TERMS_VERSION})[0], 200)
            self.assertEqual(Settings(settings.path).get("terms_accepted"), TERMS_VERSION)
        finally:
            settings.set("terms_accepted", TERMS_VERSION)

    def test_terms_text_requires_token(self):
        self.assertEqual(self.request("GET", "/api/terms")[0], 403)
        status, body, _ = self.request("GET", "/api/terms", {TOKEN_HEADER: TOKEN})
        self.assertEqual(status, 200)
        self.assertIn("使用條款", json.loads(body)["text"])

    def test_feedback_opens_issue_without_ip(self):
        self.urls.clear()
        self.assertEqual(self.post("/api/feedback", {"text": "", "channel": "github"})[0], 400)
        self.assertEqual(self.post("/api/feedback", {"text": "x", "channel": "evil"})[0], 400)
        status, body, _ = self.post("/api/feedback", {"kind": "bug", "text": "連不上 203.0.113.9\n詳細", "channel": "github",
                                                   "include_diag": True})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["title"].startswith("[問題回報]"))
        self.assertIn("連不上 203.0.113.9", data["body"])  # 使用者自己寫的內容原樣保留（送出前會在 GitHub 頁面再看一次）
        self.assertNotIn("'ip'", data["body"])            # 診斷資訊不含連線 IP 欄位
        self.assertIn("診斷資訊", data["body"])
        self.assertTrue(self.urls[-1].startswith("https://github.com/AIXAI-tools/AIXAI-VPN/issues/new?"))
        self.post("/api/feedback", {"text": "hi", "channel": "email"})
        self.assertTrue(self.urls[-1].startswith("mailto:"))

    def test_open_only_fixed_targets_and_quit(self):
        self.urls.clear()
        self.assertEqual(self.post("/api/open", {"target": "https://evil.example"})[0], 400)
        self.assertEqual(self.post("/api/open", {"target": "releases"})[0], 200)
        self.assertEqual(self.urls, ["https://github.com/AIXAI-tools/AIXAI-VPN/releases"])
        self.post("/api/quit", {})
        self.assertEqual(self.quits, [1])

    def test_update_install_refused_in_dev_build(self):
        status, body, _ = self.post("/api/updates/install", {"tag": "v9.9.9"})
        self.assertEqual(status, 409)
        self.assertIn("開發版", json.loads(body)["error"])
        self.assertEqual(self.post("/api/updates/install", {})[0], 400)

    def test_auto_update_setting(self):
        self.assertEqual(self.post("/api/settings", {"auto_update_check": False})[0], 200)
        self.assertFalse(Settings(self.server.settings.path).get("auto_update_check"))
        self.assertEqual(self.post("/api/settings", {"terms_accepted": "x"})[0], 400)  # 不能從這裡改條款
        self.post("/api/settings", {"auto_update_check": True})


if __name__ == "__main__":
    unittest.main()
