import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from src.core import updater
from src.server import feedback
from src.server.updates import UpdateService

NEW_EXE = b"MZ new version bytes"
EXE_NAME = "AIXAI-VPN_v1_1_0_Windows_x64.exe"
BASE = "https://github.com/AIXAI-tools/AIXAI-VPN/releases/download"


def release(tag, exe=True, sums=True, prerelease=False, draft=False):
    assets = []
    if exe:
        assets.append({"name": EXE_NAME, "browser_download_url": f"{BASE}/{tag}/{EXE_NAME}", "size": len(NEW_EXE)})
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"{BASE}/{tag}/SHA256SUMS.txt", "size": 100})
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "published_at": "2026-10-09T00:00:00Z",
            "body": "notes", "html_url": f"https://github.com/AIXAI-tools/AIXAI-VPN/releases/tag/{tag}",
            "assets": assets}


def fake_opener(files):
    """以網址對應內容，模擬 GitHub 下載。"""
    def open_(url, accept="*/*"):
        updater._check_url(url)
        return io.BytesIO(files[url])
    return open_


class UpdaterTest(unittest.TestCase):
    def test_version_tuple(self):
        self.assertEqual(updater.version_tuple("v1.2.3"), (1, 2, 3))
        self.assertIsNone(updater.version_tuple("v1.2"))
        self.assertIsNone(updater.version_tuple("latest"))

    def test_summarize_marks_newer_current_and_installable(self):
        rels = [release("v1.0.0"), release("v1.1.0"), release("v1.2.0", prerelease=True),
                release("v0.9.0", sums=False), release("v2.0.0", draft=True), release("nightly")]
        s = updater.summarize(rels, current="1.0.0")
        self.assertEqual([i["tag"] for i in s["items"]], ["v1.2.0", "v1.1.0", "v1.0.0", "v0.9.0"])  # 新到舊、略過草稿
        self.assertEqual(s["latest"], "1.1.0")  # 測試版不算最新穩定版
        self.assertTrue(s["update_available"])
        by = {i["tag"]: i for i in s["items"]}
        self.assertTrue(by["v1.0.0"]["current"])
        self.assertFalse(by["v0.9.0"]["installable"])  # 沒有校驗檔 → 不能安裝
        self.assertFalse(updater.summarize([release("v1.0.0")], current="1.0.0")["update_available"])

    def test_parse_sums(self):
        h = "a" * 64
        self.assertEqual(updater.parse_sums(f"{h}  other.exe\n{h.upper()} *{EXE_NAME}\n", EXE_NAME), h)
        with self.assertRaises(updater.UpdateError):
            updater.parse_sums("zzz  " + EXE_NAME, EXE_NAME)

    def test_rejects_untrusted_hosts(self):
        for url in ("http://github.com/x", "https://evil.example/x", "https://github.com.evil.example/x"):
            with self.assertRaises(updater.UpdateError):
                updater._check_url(url)

    def _setup(self, tmp, sums_hash=None):
        exe = Path(tmp) / "AIXAI-VPN.exe"
        exe.write_bytes(b"MZ old")
        good = hashlib.sha256(NEW_EXE).hexdigest()
        files = {f"{BASE}/v1.1.0/{EXE_NAME}": NEW_EXE,
                 f"{BASE}/v1.1.0/SHA256SUMS.txt": f"{sums_hash or good}  {EXE_NAME}\n".encode()}
        return exe, fake_opener(files)

    def test_install_replaces_exe_after_hash_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, opener = self._setup(tmp)
            seen = []
            updater.install("v1.1.0", exe, seen.append, releases=[release("v1.1.0")], opener=opener)
            self.assertEqual(exe.read_bytes(), NEW_EXE)
            self.assertEqual((Path(tmp) / "AIXAI-VPN.exe.old").read_bytes(), b"MZ old")
            self.assertEqual(seen[-1], 100)
            updater.cleanup_old(exe)
            self.assertFalse((Path(tmp) / "AIXAI-VPN.exe.old").exists())

    def test_cleanup_retries_until_old_process_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "AIXAI-VPN.exe"
            old = Path(tmp) / "AIXAI-VPN.exe.old"
            old.write_bytes(b"x")
            calls = []
            real_unlink = Path.unlink

            def busy_twice(self, missing_ok=False):  # 前兩次模擬「舊版還在執行，刪不掉」
                if self == old and len(calls) < 2:
                    calls.append(1)
                    raise PermissionError("in use")
                return real_unlink(self, missing_ok=missing_ok)

            Path.unlink = busy_twice
            try:
                self.assertFalse(updater.cleanup_old(exe, attempts=1, wait=0))
                self.assertTrue(updater.cleanup_old(exe, attempts=5, wait=0))
            finally:
                Path.unlink = real_unlink
            self.assertFalse(old.exists())

    def test_install_keeps_old_exe_on_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, opener = self._setup(tmp, sums_hash="b" * 64)
            with self.assertRaises(updater.UpdateError):
                updater.install("v1.1.0", exe, releases=[release("v1.1.0")], opener=opener)
            self.assertEqual(exe.read_bytes(), b"MZ old")
            self.assertFalse((Path(tmp) / "AIXAI-VPN.exe.new").exists())

    def test_install_requires_checksum_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, opener = self._setup(tmp)
            with self.assertRaises(updater.UpdateError):
                updater.install("v1.1.0", exe, releases=[release("v1.1.0", sums=False)], opener=opener)
            self.assertEqual(exe.read_bytes(), b"MZ old")

    def test_service_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, opener = self._setup(tmp)
            installed = []
            svc = UpdateService(exe, on_installed=installed.append, fetch=lambda: [release("v1.1.0")],
                                install=lambda tag, path, progress, releases:
                                updater.install(tag, path, progress, releases, opener))
            self.assertIn("先檢查", svc.start_install("v1.1.0"))  # 還沒查過版本
            svc.check(wait=True)
            self.assertTrue(svc.snapshot()["summary"]["update_available"])
            self.assertIsNone(svc.start_install("v1.1.0", wait=True))
            self.assertEqual(installed, ["v1.1.0"])
            self.assertEqual(svc.snapshot()["stage"], "restarting")


class FeedbackTest(unittest.TestCase):
    def test_scrub_masks_ip_paths_and_keys(self):
        home = str(Path.home())
        out = feedback.scrub(f"{home}\\x 8.8.8.8 PrivateKey = abc123")
        self.assertNotIn("8.8.8.8", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn(home, out)

    def test_report_without_diag_has_no_status(self):
        title, body = feedback.build_report("idea", "希望加入暗色以外的主題", None)
        self.assertEqual(title, "[功能建議] 希望加入暗色以外的主題")
        self.assertNotIn("診斷資訊", body)

    def test_report_never_contains_connection_ip(self):
        diag = {"status": {"mode": "vpngate", "status": "connected", "ip": "219.100.37.1", "loc": "JP"},
                "research_mode": False, "log": ["ok"]}
        _, body = feedback.build_report("bug", "x", diag)
        self.assertNotIn("219.100.37.1", body)
        self.assertIn("vpngate", body)

    def test_urls_are_bounded(self):
        title, body = feedback.build_report("bug", "長" * 4000, None)
        self.assertLessEqual(len(feedback.issue_url(title, body)), feedback.ISSUE_URL_LIMIT + 200)
        self.assertTrue(feedback.mail_url(title, body).startswith("mailto:aixai19861201@gmail.com?subject="))


if __name__ == "__main__":
    unittest.main()
