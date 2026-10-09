"""VPNBook 選配：半自動取得設定檔 + WireGuard 連線管理（ADR-011、TASK-009）。

半自動流程：
  App：開啟 VPNBook 官方產生頁 → 偵測下載資料夾的 vpnbook-*.conf → 檢查 → 存到 App 資料夾 → 關閉產生頁
  使用者本人：選伺服器、勾選同意、通過真人驗證（Cloudflare Turnstile）、按產生、按下載
App 不代勾、不模擬點擊、不繞過真人驗證。
"""

import ctypes
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.countries import TARGET_COUNTRIES
from src.core.wgconf import ConfigError, parse, resolve_known_hosts

# 固定開簡體中文版（/zh/）：繁中瀏覽器也會被導到這裡，固定下來才能讓使用說明的文字一字不差地對得上
GENERATE_URL = "https://www.vpnbook.com/zh/freevpn/wireguard-vpn"
# 各國在 VPNBook 頁面「1 选择服务器」中要點的選項（頁面原文）
SERVER_LABELS = {"US": ("US Server 1", "us16.vpnbook.com"), "CA": ("Canada Server 1", "ca149.vpnbook.com"),
                 "GB": ("UK Server 1", "uk205.vpnbook.com"), "DE": ("Germany Server 1", "de20.vpnbook.com"),
                 "FR": ("France Server 1", "fr200.vpnbook.com")}
VALID_DAYS = 7  # VPNBook："Each configuration is valid for 7 days."
BASE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "vpnbook"
FOLDERID_DOWNLOADS = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")


def downloads_dir() -> Path:
    """使用者的「下載」資料夾（Windows Known Folder，使用者改過位置也找得到）。"""
    try:
        guid = (ctypes.c_byte * 16).from_buffer_copy(FOLDERID_DOWNLOADS.bytes_le)
        path = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) == 0:
            result = Path(path.value)
            ctypes.windll.ole32.CoTaskMemFree(path)
            return result
    except (AttributeError, OSError):
        pass
    return Path.home() / "Downloads"


LOG_PATH = BASE_DIR / "vpnbook.log"


def log(msg: str) -> None:
    """簡單的事件記錄（不寫任何金鑰），卡住時方便查原因。"""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            print(datetime.now().isoformat(timespec="seconds"), msg, file=f)
    except OSError:
        pass


class ConfigStore:
    """每個國家保留最新一份設定檔（<代碼>.conf + <代碼>.json 記錄到期日）。"""

    def __init__(self, base: Path = BASE_DIR / "configs", resolve_known=resolve_known_hosts) -> None:
        self.base = base
        self.resolve_known = resolve_known

    def import_text(self, text: str, generated_at: float) -> dict:
        cfg = parse(text, self.resolve_known)
        code = cfg.country
        if code not in TARGET_COUNTRIES:
            raise ConfigError(f"這台伺服器（{cfg.server}）不在目標國家內")
        self.base.mkdir(parents=True, exist_ok=True)
        expires = datetime.fromtimestamp(generated_at, timezone.utc) + timedelta(days=VALID_DAYS)
        (self.base / f"{code}.conf").write_text(cfg.render(), encoding="utf-8")
        meta = {"server": cfg.server, "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "expires_at": expires.isoformat(timespec="seconds")}
        (self.base / f"{code}.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"code": code, **meta}

    def list(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        items = []
        for code, name in TARGET_COUNTRIES.items():
            try:
                meta = json.loads((self.base / f"{code}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            left = datetime.fromisoformat(meta["expires_at"]) - now
            items.append({"code": code, "name": name, "server": meta["server"], "expires_at": meta["expires_at"],
                          "hours_left": max(0, int(left.total_seconds() // 3600)), "expired": left.total_seconds() <= 0})
        return items

    def load(self, code: str) -> str | None:
        """取出未過期的設定檔內容；沒有或已過期回傳 None。"""
        item = next((i for i in self.list() if i["code"] == code), None)
        if item is None or item["expired"]:
            return None
        return (self.base / f"{code}.conf").read_text(encoding="utf-8")


class Fetcher:
    """開 VPNBook 產生頁 → 等使用者下載 → 自動匯入。"""

    TIMEOUT = 600  # 給使用者 10 分鐘完成頁面上的步驟

    def __init__(self, store: ConfigStore, open_page, close_page, downloads=downloads_dir) -> None:
        self.store = store
        self.open_page, self.close_page = open_page, close_page
        self.downloads = downloads
        self._lock = threading.Lock()
        self.state = {"fetching": False, "message": "", "imported": None, "country": None}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    def start(self, country: str = "US") -> bool:
        if country not in SERVER_LABELS:
            raise ValueError("VPNBook 沒有這個國家的 WireGuard 伺服器")
        with self._lock:
            if self.state["fetching"]:
                return False
            self.state.update(fetching=True, imported=None, country=country,
                              message="等待你在 VPNBook 頁面完成步驟並下載設定檔…")
        threading.Thread(target=self._run, args=(time.time(),), daemon=True).start()
        return True

    def find_new(self, since: float) -> Path | None:
        folder = self.downloads()
        try:
            files = [p for p in folder.glob("vpnbook-*.conf") if p.stat().st_mtime >= since - 2]
        except OSError:
            return None
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def _try_import(self, path: Path) -> dict:
        """瀏覽器可能還沒寫完 → 失敗時再試幾次。最後一次的錯誤照樣拋出。"""
        for attempt in range(3):
            time.sleep(1)
            try:
                return self.store.import_text(path.read_text(encoding="utf-8-sig"), path.stat().st_mtime)
            except (OSError, ConfigError):
                if attempt == 2:
                    raise

    def _run(self, since: float) -> None:
        if not self.open_page():
            self._set(fetching=False, message="無法開啟 VPNBook 頁面（找不到 Edge）")
            return
        end = since + self.TIMEOUT
        tried: dict[Path, float] = {}  # 已試過的檔案與當時的修改時間（同一檔案沒變就不重試）
        while time.time() < end:
            path = self.find_new(since)
            if path is not None and tried.get(path) != path.stat().st_mtime:
                tried[path] = path.stat().st_mtime
                try:
                    info = self._try_import(path)
                except (OSError, ConfigError) as exc:
                    log(f"匯入失敗 {path.name}: {exc}")
                    # 不停止：使用者可以重新下載一次，會再偵測
                    self._set(message=f"匯入失敗：{exc}（可在 VPNBook 頁面重新下載一次）")
                    time.sleep(1)
                    continue
                log(f"已匯入 {path.name} → {info['code']} {info['server']}")
                self.close_page()
                self._set(fetching=False, imported=info,
                          message=f"已匯入 {TARGET_COUNTRIES[info['code']]}（{info['server']}）設定檔")
                return
            time.sleep(1)
        self._set(fetching=False, message="10 分鐘內沒有成功匯入設定檔，已停止等待")


class VpnbookManager:
    """VPNBook 連線（WireGuard）。狀態欄位與其他管理器相同。kill switch 由 WireGuard 內建提供（AllowedIPs /0）。"""

    def __init__(self, connector, store: ConfigStore, locate, monitor_interval: float = 5.0) -> None:
        self.connector, self.store, self.locate = connector, store, locate
        self.monitor_interval = monitor_interval
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._state = {"mode": "vpnbook", "status": "idle", "country": None, "host": None, "ip": None, "loc": None,
                       "message": "", "warning": "", "attempt": 0, "attempts_max": 1, "protected": False,
                       "progress": 0}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def available(self) -> bool:
        return self.connector.available()

    def start(self, country: str) -> bool:
        text = self.store.load(country)
        with self._lock:
            if self._state["status"] != "idle":
                return False
            if text is None:
                self._state.update(message="沒有這個國家的有效設定檔，請先取得")
                return False
            self._state.update(status="connecting", country=country, ip=None, loc=None, warning="",
                               message="連線到 VPNBook…", attempt=1)
        self._cancel.clear()
        threading.Thread(target=self._run, args=(country, text), daemon=True).start()
        return True

    def retry(self) -> bool:
        return False  # WireGuard 服務自己會持續重試握手，不需要 App 重試

    def stop(self) -> None:
        with self._lock:
            if self._state["status"] == "idle" and not self._state["protected"]:
                return
            self._state.update(status="disconnecting", message="中斷中")
        self._cancel.set()
        self.connector.disconnect()
        self._set(status="idle", country=None, host=None, ip=None, loc=None, warning="", message="已中斷",
                  protected=False)

    def cleanup(self) -> None:
        """App 啟動時：上次若當掉，通道服務還在跑 → 移除，回到一般網路。"""
        if self.connector.available():
            self.connector.disconnect()

    def _run(self, country: str, text: str) -> None:
        ok, msg = self.connector.connect(text)
        if self._cancel.is_set():
            return
        if not ok:
            self._set(status="idle", message=msg)
            return
        try:
            where = self.locate()
        except OSError:
            where = {"ip": "", "loc": ""}
        warning = ""
        if where["loc"] and where["loc"] != country:
            warning = f"注意：實際出口國家是 {where['loc']}，不是所選的 {country}"
        server = next((i["server"] for i in self.store.list() if i["code"] == country), "VPNBook")
        log(f"已連線 {country} {server} 出口 {where['loc']}")
        self._set(status="connected", host=server, ip=where["ip"], loc=where["loc"], warning=warning,
                  message="已連線", protected=True)
        while not self._cancel.wait(self.monitor_interval):
            if self.snapshot()["status"] == "connected" and not self.connector.is_connected():
                # 通道服務意外停止：WireGuard 內建保護也跟著消失 → 如實回報
                self._set(status="idle", host=None, ip=None, loc=None, protected=False,
                          message="VPNBook 通道意外停止，已回到一般網路")
                return
