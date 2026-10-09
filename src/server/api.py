"""本機 API 伺服器（ADR-007）。

安全規則（全部必須做到）：
1. 只監聽 127.0.0.1，隨機 port
2. API 請求必須帶正確 token（header: X-AIXAI-Token）
3. 檢查 Host 與 Origin，只接受本機來源（防 DNS rebinding 與跨站請求）
4. 會改變狀態的操作只接受 POST，且 POST 一定要有正確的 Origin
"""

import hmac
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.connector.tor import TOR_DIR, TorRunner
from src.connector.windows import edge, shell
from src.connector.windows.sstp import SstpConnector
from src.connector.windows.wireguard import WireGuardConnector
from src.core.cache import ServerCache
from src.core.countries import TARGET_COUNTRIES
from src.core.geo import public_location
from src.core.geoip import GeoIP
from src.core.probe import probe_all
from src.core.tor_exits import fetch_exit_counts
from src.core.vpngate import fetch_list, parse_list
from src.protection.windows.killswitch import KillSwitch
from src.protection.windows.proxy import SystemProxy
from src.server import feedback
from src.server.connection import ConnectionManager
from src.server.settings import Settings
from src.server.tor_session import TorManager
from src.server.updates import UpdateService
from src.server.vpnbook import BASE_DIR as VPNBOOK_DIR, GENERATE_URL, LOG_PATH as VPNBOOK_LOG
from src.server.vpnbook import ConfigStore, Fetcher, VpnbookManager
from src.version import APP_VERSION, REPO_URL, TERMS_VERSION

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DOCS_DIR = Path(__file__).resolve().parent.parent.parent  # DISCLAIMER.md 所在（專案根目錄或 exe 解壓處）
TOKEN_HEADER = "X-AIXAI-Token"

# 白名單：只提供這幾個檔案，不做目錄瀏覽，避免路徑穿越
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/logo.png": ("logo.png", "image/png"),
}

SECURITY_HEADERS = {
    # 只允許載入自己的檔案；不外連任何資源
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


CACHE_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "server-cache.json"


def tor_countries() -> list[dict] | None:
    """目標國家各有幾個 Tor 出口節點；抓不到（例如網路被擋）就回傳 None，不影響 VPN Gate 清單。"""
    try:
        counts = fetch_exit_counts()
    except (OSError, ValueError):
        return None
    return [{"code": c, "name": n, "exits": counts.get(c, 0)} for c, n in TARGET_COUNTRIES.items()]


def make_search(cache: ServerCache, prober=probe_all):
    """回傳搜尋函式：抓最新清單 → 和快取合併 → **實際檢查 SSTP 能不能連** → 只留可用的，依延遲排序。"""

    def search_servers() -> dict:
        fresh = parse_list(fetch_list())
        merged = cache.merge(fresh, time.time())
        targets = [(s, f) for s, f in merged if s.country_code in TARGET_COUNTRIES]
        # 每台伺服器探測 443 與它自己的 TCP port（ADR-017）；{可用端點: 毫秒}
        latency = prober([ep for s, _ in targets for ep in s.sstp_endpoints])

        by_country: dict[str, list[tuple]] = {}
        endpoint: dict[str, str] = {}  # 伺服器主機名稱 → 最快的可用端點
        for server, is_fresh in targets:
            usable = [ep for ep in server.sstp_endpoints if ep in latency]
            if usable:
                endpoint[server.sstp_host] = min(usable, key=latency.get)
                by_country.setdefault(server.country_code, []).append((server, is_fresh))
        for entries in by_country.values():
            entries.sort(key=lambda e: latency[endpoint[e[0].sstp_host]])  # 從使用者這端量到的延遲，越快越前面

        countries = []
        for code, name in TARGET_COUNTRIES.items():
            entries = by_country.get(code, [])
            best = entries[0][0] if entries else None
            countries.append(
                {
                    "code": code,
                    "name": name,
                    "count": len(entries),
                    "fresh_count": sum(1 for _, f in entries if f),
                    "best": None if best is None else {
                        "host": endpoint[best.sstp_host],
                        "latency_ms": latency[endpoint[best.sstp_host]],
                        "operator": best.operator,
                    },
                }
            )
        return {
            "total": len(fresh),
            "cached_total": len(merged),
            "checked": len(targets),
            "usable": sum(len(e) for e in by_country.values()),
            "cache_hours": cache.ttl_seconds / 3600,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "countries": countries,
            "tor": tor_countries(),
            # 內部用：每國的候選主機（已排序），不回傳給介面
            "_candidates": {code: [endpoint[s.sstp_host] for s, _ in entries] for code, entries in by_country.items()},
        }

    return search_servers


MAX_BODY = 1024  # 請求內容上限（bytes）
MAX_FEEDBACK_BODY = 16 * 1024  # 回報內容較長，單獨放寬
# 「開啟網頁」只允許這幾個固定目標
OPEN_TARGETS = {"releases": f"{REPO_URL}/releases", "repo": f"{REPO_URL}/",
                "terms": f"{REPO_URL}/blob/main/DISCLAIMER.md", "privacy": f"{REPO_URL}/blob/main/PRIVACY.md"}


class Handler(BaseHTTPRequestHandler):
    server: "AppServer"

    # ---- 安全檢查 ----
    def _host_ok(self) -> bool:
        return self.headers.get("Host") == self.server.expected_host

    def _origin_ok(self, required: bool) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return not required
        return origin == self.server.expected_origin

    def _token_ok(self) -> bool:
        given = self.headers.get(TOKEN_HEADER, "")
        return hmac.compare_digest(given.encode(), self.server.token.encode())

    # ---- 回應 ----
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _forbidden(self) -> None:
        self._json(403, {"error": "forbidden"})

    def _read_json(self, limit: int = MAX_BODY) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length > limit:
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _status(self) -> dict:
        active = self.server.active()
        conn = (active or self.server.manager).snapshot()
        settings = self.server.settings
        return {
            "version": APP_VERSION,
            "terms": {"version": TERMS_VERSION, "accepted": settings.get("terms_accepted") == TERMS_VERSION},
            "auto_update_check": settings.get("auto_update_check"),
            "update": self.server.updates.snapshot(),
            "connected": conn["status"] == "connected",
            "connection": conn,
            "kill_switch": conn["protected"],
            "research_mode": self.server.settings.get("research_mode"),
            "tor_available": self.server.tor.available(),
            "vpnbook": {
                "available": self.server.vpnbook.available(),
                "configs": self.server.vpnbook.store.list(),
                "fetch": self.server.fetcher.snapshot(),
            },
        }

    # ---- 路由 ----
    def do_GET(self) -> None:
        if not self._host_ok() or not self._origin_ok(required=False):
            return self._forbidden()
        path = self.path.split("?", 1)[0]
        if path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            return self._send(200, (UI_DIR / name).read_bytes(), ctype)
        if path == "/api/status":
            if not self._token_ok():
                return self._forbidden()
            return self._json(200, self._status())
        if path == "/api/terms":
            if not self._token_ok():
                return self._forbidden()
            try:
                text = (DOCS_DIR / "DISCLAIMER.md").read_text(encoding="utf-8")
            except OSError:
                text = f"找不到條款檔案，請到 {OPEN_TARGETS['terms']} 閱讀。"
            return self._json(200, {"version": TERMS_VERSION, "text": text})
        self._json(404, {"error": "not found"})

    def _terms_ok(self) -> bool:
        return self.server.settings.get("terms_accepted") == TERMS_VERSION

    def do_POST(self) -> None:
        if not self._host_ok() or not self._origin_ok(required=True) or not self._token_ok():
            return self._forbidden()
        path = self.path.split("?", 1)[0]
        if path == "/api/search":
            try:
                result = dict(self.server.search())
            except Exception as exc:  # 網路錯誤等，回報給介面顯示
                return self._json(502, {"error": f"抓取伺服器清單失敗：{exc}"})
            self.server.candidates = result.pop("_candidates", {})
            return self._json(200, result)
        if path == "/api/connect":
            body = self._read_json()
            country = body.get("country") if body else None
            mode = body.get("mode", "vpngate") if body else None
            if country not in TARGET_COUNTRIES or mode not in ("vpngate", "tor", "vpnbook"):
                return self._json(400, {"error": "不支援的國家或模式"})
            if not self._terms_ok():
                return self._json(409, {"error": "請先同意使用條款"})
            if self.server.active() is not None:  # 同一時間只能有一種連線
                return self._json(409, {"error": "請先中斷目前的連線", "status": self._status()})
            if mode == "tor":
                started = self.server.tor.start(country)
            elif mode == "vpnbook":
                started = self.server.vpnbook.start(country)
            else:
                started = self.server.manager.start(country, self.server.candidates.get(country, []))
            if not started:
                return self._json(409, {"error": "目前無法開始連線", "status": self._status()})
            return self._json(202, self._status())
        if path == "/api/retry":
            active = self.server.active()
            if active is None or not active.retry():
                return self._json(409, {"error": "目前不需要重試", "status": self._status()})
            return self._json(202, self._status())
        if path == "/api/vpnbook/fetch":  # 開 VPNBook 產生頁並等待下載（半自動）
            if not self.server.vpnbook.available():
                return self._json(409, {"error": "尚未安裝 WireGuard"})
            body = self._read_json()
            country = body.get("country", "US") if body is not None else None  # 空的 {} 也算合法，預設美國
            if country not in ("US", "CA", "GB", "DE", "FR"):
                return self._json(400, {"error": "VPNBook 沒有這個國家的 WireGuard 伺服器"})
            if not self._terms_ok():
                return self._json(409, {"error": "請先同意使用條款"})
            if not self.server.fetcher.start(country):
                return self._json(409, {"error": "已經在等待下載中"})
            return self._json(202, self._status())
        if path == "/api/settings":
            body = self._read_json()
            changes = {k: body[k] for k in ("research_mode", "auto_update_check") if k in body} if body else {}
            if not changes or not all(isinstance(v, bool) for v in changes.values()):
                return self._json(400, {"error": "設定值必須是 true 或 false"})
            for key, value in changes.items():
                self.server.settings.set(key, value)
            return self._json(200, self._status())
        if path == "/api/terms/accept":
            body = self._read_json()
            if not body or body.get("version") != TERMS_VERSION:
                return self._json(400, {"error": "條款版本不符，請重新開啟 App"})
            self.server.settings.set("terms_accepted", TERMS_VERSION)
            return self._json(200, self._status())
        if path == "/api/updates/check":
            self.server.updates.check()
            return self._json(202, self._status())
        if path == "/api/updates/install":
            body = self._read_json()
            tag = body.get("tag") if body else None
            if not isinstance(tag, str):
                return self._json(400, {"error": "缺少版本"})
            if self.server.active() is not None:
                return self._json(409, {"error": "請先中斷 VPN 再切換版本"})
            reason = self.server.updates.start_install(tag)
            if reason:
                return self._json(409, {"error": reason})
            return self._json(202, self._status())
        if path == "/api/feedback":
            body = self._read_json(MAX_FEEDBACK_BODY)
            if not body:
                return self._json(400, {"error": "內容格式不正確"})
            text, channel = body.get("text"), body.get("channel")
            if not isinstance(text, str) or not text.strip():
                return self._json(400, {"error": "請先寫下想回報的內容"})
            if len(text) > feedback.MAX_TEXT or channel not in feedback.CHANNELS:
                return self._json(400, {"error": "內容太長或回報方式不正確"})
            diag = self.server.diagnostics() if body.get("include_diag") is True else None
            title, report = feedback.build_report(body.get("kind"), text, diag)
            url = feedback.issue_url(title, report) if channel == "github" else feedback.mail_url(title, report)
            opened = self.server.open_url(url)
            return self._json(200, {"opened": opened, "title": title, "body": report})
        if path == "/api/open":
            body = self._read_json()
            url = OPEN_TARGETS.get(body.get("target")) if body else None
            if url is None:
                return self._json(400, {"error": "不支援的頁面"})
            return self._json(200, {"opened": self.server.open_url(url)})
        if path == "/api/quit":  # 不同意條款 → 結束 App
            self.server.on_quit()
            return self._json(200, {"ok": True})
        if path == "/api/heartbeat":
            self.server.touch()
            return self._json(200, {"ok": True})
        if path == "/api/bye":  # 視窗關閉或重新整理：給幾秒寬限，重新整理會立刻再送心跳
            self.server.touch(grace_only=True)
            return self._json(200, {"ok": True})
        if path == "/api/disconnect":
            active = self.server.active()
            if active is not None:
                active.stop()
            return self._json(200, self._status())
        self._json(404, {"error": "not found"})

    def log_message(self, format, *args) -> None:  # 不在主控台印出每個請求
        pass


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, token: str, search=None, manager=None, tor=None, vpnbook=None, fetcher=None,
                 settings=None, updates=None, on_quit=lambda: None, open_url=shell.open_url) -> None:
        super().__init__(("127.0.0.1", 0), Handler)  # port 0 = 系統挑一個空的 port
        self.token = token
        self.search = search or make_search(ServerCache(CACHE_PATH))
        self.manager = manager or ConnectionManager(SstpConnector(), public_location, killswitch=KillSwitch())
        self.tor = tor or TorManager(TorRunner(), KillSwitch(), SystemProxy(), GeoIP(TOR_DIR / "data" / "geoip"))
        self.manager.cleanup()  # 清掉上次當掉時殘留的規則與 hosts 行
        self.tor.cleanup()      # 上次當掉若代理沒還原，這裡補還原
        self.vpnbook = vpnbook or VpnbookManager(WireGuardConnector(), ConfigStore(), public_location)
        self.vpnbook.cleanup()  # 上次當掉若 WireGuard 通道還在，移除
        profile = VPNBOOK_DIR / "edge-profile"
        self.fetcher = fetcher or Fetcher(
            self.vpnbook.store,
            open_page=lambda: edge.open_app_window(GENERATE_URL, profile, (900, 1000)),
            close_page=lambda: edge.close_profile_windows(profile))
        self.candidates: dict[str, list[str]] = {}  # 最近一次搜尋的候選主機
        self.last_seen: float | None = None  # 介面最後一次心跳的時間（None = 還沒連上過）
        self.settings = settings or Settings()
        self.updates = updates or UpdateService(None)
        self.on_quit = on_quit
        self.open_url = open_url
        self.port = self.server_address[1]
        self.expected_host = f"127.0.0.1:{self.port}"
        self.expected_origin = f"http://127.0.0.1:{self.port}"

    # ---- 視窗存活判斷（ADR-007 補充）----
    # Edge 被管理員權限啟動時會自動降權重開，原本的程序立刻結束，
    # 所以不能用「Edge 程序結束」判斷視窗關閉，改用介面送來的心跳。
    HEARTBEAT_TIMEOUT = 150.0  # 視窗最小化時瀏覽器會把計時器降到約每分鐘一次，所以要寬鬆
    BYE_GRACE = 5.0

    def touch(self, grace_only: bool = False) -> None:
        now = time.monotonic()
        self.last_seen = now - (self.HEARTBEAT_TIMEOUT - self.BYE_GRACE) if grace_only else now

    def ui_gone(self) -> bool:
        return self.last_seen is not None and time.monotonic() - self.last_seen > self.HEARTBEAT_TIMEOUT

    def active(self):
        """目前正在使用（非閒置或保護中）的連線管理器；都沒有就回傳 None。"""
        for m in (self.manager, self.tor, self.vpnbook):
            snap = m.snapshot()
            if snap["status"] != "idle" or snap["protected"]:
                return m
        return None

    def diagnostics(self) -> dict:
        """回報用的診斷資料（feedback.build_report 會再遮蔽 IP 與路徑）。"""
        active = self.active() or self.manager
        log = feedback.read_tail(VPNBOOK_LOG)
        log += [f"tor: {line}" for line in list(getattr(self.tor.runner, "log", []))[-15:]]
        return {"status": active.snapshot(), "research_mode": self.settings.get("research_mode"), "log": log}

    # ---- 研究模式（ADR-004、TASK-006b）----
    RESEARCH_RETRY_SECONDS = 30.0

    def research_tick(self) -> bool:
        """研究模式下，若連線處於「網路暫停」（blocked），就自動重試。回傳是否有觸發重試。
        由啟動器定期呼叫；不開研究模式時什麼都不做（交給使用者決定要重試或改用一般網路）。"""
        if not self.settings.get("research_mode"):
            return False
        active = self.active()
        if active is None or active.snapshot()["status"] != "blocked":
            return False
        return bool(active.retry())

