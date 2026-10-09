"""連線管理 + 斷線保護（ADR-012 模式 B）。

狀態：
  idle → connecting → connected ⇄ reconnecting → (blocked)
  任何狀態按「中斷」／「改用一般網路」→ disconnecting → idle
  - connected：已連線，斷線保護開啟
  - reconnecting：VPN 意外斷線，保護仍開著（網路暫停），正在換伺服器重連
  - blocked：重連全部失敗，保護仍開著；等使用者按「重試」或「改用一般網路」
"""

import socket
import threading

MAX_ATTEMPTS = 5  # 每次最多試幾台，避免無止盡重試


class NoProtection:
    """沒有系統管理員權限或測試時使用：不做任何事。"""

    def engage(self, host_ips):
        pass

    def release(self):
        pass


class ConnectionManager:
    def __init__(self, connector, locate, killswitch=None, resolve=socket.gethostbyname,
                 monitor_interval: float = 2.0) -> None:
        self.connector = connector
        self.locate = locate  # 查對外 IP／國家的函式
        self.killswitch = killswitch or NoProtection()
        self.resolve = resolve
        self.monitor_interval = monitor_interval
        self._lock = threading.Lock()
        self._state = {"mode": "vpngate", "progress": 0, "status": "idle", "country": None, "host": None, "ip": None, "loc": None,
                       "message": "", "warning": "", "attempt": 0, "attempts_max": 0, "protected": False}
        self._cancel = threading.Event()
        self._hosts: list[str] = []

    # ---- 狀態 ----
    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    # ---- 對外操作 ----
    def start(self, country: str, hosts: list[str]) -> bool:
        """開始連線（只能從 idle 開始）。回傳是否有開始。"""
        with self._lock:
            if self._state["status"] != "idle":
                return False
            if not hosts:
                self._state.update(message="這個國家目前沒有伺服器")
                return False
            self._state.update(status="connecting", country=country, host=None, ip=None, loc=None,
                               message="", warning="", attempt=0,
                               attempts_max=min(len(hosts), MAX_ATTEMPTS))
        self._hosts = hosts[:MAX_ATTEMPTS]
        self._cancel.clear()
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def retry(self) -> bool:
        """blocked 狀態下，在保護中重試同一批伺服器（它們的 IP 已在例外清單裡）。"""
        with self._lock:
            if self._state["status"] != "blocked":
                return False
            self._state.update(status="reconnecting", message="重新連線中（網路暫停中）")
        threading.Thread(target=self._reconnect_and_monitor, daemon=True).start()
        return True

    def stop(self) -> None:
        """中斷 VPN 並解除保護（也是「改用一般網路」）。"""
        with self._lock:
            if self._state["status"] == "idle" and not self._state["protected"]:
                return
            self._state.update(status="disconnecting", message="中斷中")
        self._cancel.set()
        self.connector.disconnect()
        self._release()
        self._set(status="idle", host=None, ip=None, loc=None, country=None, warning="", message="已中斷")

    def cleanup(self) -> None:
        """App 啟動時清理上次殘留（當掉時留下的規則與 hosts 行）。"""
        try:
            getattr(self.killswitch, "cleanup", self.killswitch.release)()
        except Exception:
            pass

    # ---- 內部 ----
    def _release(self) -> None:
        try:
            self.killswitch.release()
        finally:
            self._set(protected=False)

    def _dial_any(self, hosts: list[str]) -> tuple[str | None, str]:
        last_error = ""
        for i, host in enumerate(hosts, 1):
            if self._cancel.is_set():
                return None, "已取消"
            self._set(attempt=i, attempts_max=len(hosts), host=host)
            result = self.connector.connect(host)
            if result.ok:
                return host, ""
            last_error = result.message
        return None, f"全部 {len(hosts)} 台都連不上（最後錯誤：{last_error}）"

    def _after_connected(self, host: str) -> bool:
        """連上後：查出口位置 → 透過隧道查好候選 IP → 開保護。失敗就斷線，回傳 False。"""
        try:
            where = self.locate()
        except OSError:
            where = {"ip": "", "loc": ""}
        country = self.snapshot()["country"]
        warning = ""
        if where["loc"] and where["loc"] != country:
            warning = f"注意：實際出口國家是 {where['loc']}，不是所選的 {country}"

        if self._cancel.is_set():
            self.connector.disconnect()
            return False
        host_ips = {}
        for h in [host] + [x for x in self._hosts if x != host]:
            try:
                host_ips[h] = self.resolve(h)
            except OSError:
                continue  # 查不到的候選就跳過
        try:
            self.killswitch.engage(host_ips)
        except Exception as exc:
            self.connector.disconnect()
            self._set(status="idle", host=None, protected=False,
                      message=f"斷線保護開啟失敗，已中斷 VPN：{exc}")
            return False
        self._set(protected=True)
        if self._cancel.is_set():  # 開保護途中使用者按了中斷 → stop() 可能已先解除，這裡再補一次
            self._release()
            return False
        self._set(status="connected", host=host, ip=where["ip"], loc=where["loc"],
                  warning=warning, message="已連線")
        return True

    def _run(self) -> None:
        host, err = self._dial_any(self._hosts)
        if self._cancel.is_set():
            if host:
                self.connector.disconnect()
            return  # stop() 會負責收尾
        if host is None:
            self._set(status="idle", host=None, message=err)
            return
        if not self._after_connected(host):
            return
        self._monitor()

    def _monitor(self) -> None:
        """每隔幾秒檢查 VPN；意外斷線就在保護下重連（模式 B）。"""
        while not self._cancel.wait(self.monitor_interval):
            if self.snapshot()["status"] != "connected" or self.connector.is_connected():
                continue
            self._set(status="reconnecting", message="VPN 中斷，正在重新連線（網路暫停中）")
            if not self._reconnect():
                return

    def _reconnect(self) -> bool:
        current = self.snapshot()["host"]
        order = [h for h in [current] if h] + [h for h in self._hosts if h != current]
        host, err = self._dial_any(order)
        if self._cancel.is_set():
            if host:
                self.connector.disconnect()
            return False
        if host is None:
            self._set(status="blocked", message=f"重新連線失敗，網路仍受保護（暫停中）。{err}")
            return False
        return self._after_connected(host)

    def _reconnect_and_monitor(self) -> None:
        if self._reconnect():
            self._monitor()
