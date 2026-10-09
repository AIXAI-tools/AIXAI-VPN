"""Tor 模式連線管理（ADR-011、TASK-011）。狀態欄位與 ConnectionManager 相同，另外多 progress。

開啟順序（每一步都在「還沒導流量過去」時完成，避免外洩或斷網）：
  1. 啟動 Tor，等到 100%
  2. 經 Tor 查出口 IP，用 Tor 內附 GeoIP 判斷國家
  3. WFP：只放行 tor.exe
  4. 系統代理指向 Tor
關閉順序相反：還原代理 → 解除 WFP → 停 Tor。
Tor 意外結束 → 保護與代理維持（網路暫停，不外洩），自動重啟 Tor。
"""

import threading
import urllib.request


class TorManager:
    def __init__(self, runner, killswitch, proxy, geoip, monitor_interval: float = 2.0) -> None:
        self.runner = runner
        self.killswitch = killswitch
        self.proxy = proxy
        self.geoip = geoip
        self.monitor_interval = monitor_interval
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._state = {"mode": "tor", "status": "idle", "country": None, "host": None, "ip": None, "loc": None,
                       "message": "", "warning": "", "attempt": 0, "attempts_max": 0, "protected": False,
                       "progress": 0}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def available(self) -> bool:
        return self.runner.available()

    # ---- 對外操作 ----
    def start(self, country: str) -> bool:
        with self._lock:
            if self._state["status"] != "idle":
                return False
            self._state.update(status="connecting", country=country, ip=None, loc=None, message="啟動 Tor…",
                               warning="", progress=0, attempt=1, attempts_max=1)
        self._cancel.clear()
        threading.Thread(target=self._run, args=(country,), daemon=True).start()
        return True

    def retry(self) -> bool:
        with self._lock:
            if self._state["status"] != "blocked":
                return False
            self._state.update(status="reconnecting", message="重新啟動 Tor（網路暫停中）", progress=0)
        threading.Thread(target=self._restart_and_monitor, daemon=True).start()
        return True

    def stop(self) -> None:
        with self._lock:
            if self._state["status"] == "idle" and not self._state["protected"]:
                return
            self._state.update(status="disconnecting", message="中斷中")
        self._cancel.set()
        self._teardown()
        self._set(status="idle", country=None, host=None, ip=None, loc=None, warning="", message="已中斷",
                  progress=0)

    def cleanup(self) -> None:
        """App 啟動時：上次若當掉且看門狗沒還原代理，這裡補還原。"""
        try:
            self.proxy.restore()
        except Exception:
            pass

    # ---- 內部 ----
    def _teardown(self) -> None:
        for step in (self.proxy.restore, self.killswitch.release, self.runner.stop):
            try:
                step()
            except Exception:
                pass
        self._set(protected=False)

    def _boot(self, country: str) -> tuple[bool, str]:
        return self.runner.start(country, on_progress=lambda p: self._set(progress=p))

    def _exit_location(self) -> dict:
        """經 Tor 代理查出口 IP，再用 GeoIP 判斷國家（Cloudflare 對 Tor 只會回 T1）。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"https": f"http://127.0.0.1:{self.runner.port}"}))
        text = opener.open("https://www.cloudflare.com/cdn-cgi/trace", timeout=30).read().decode()
        ip = dict(l.split("=", 1) for l in text.splitlines() if "=" in l).get("ip", "")
        return {"ip": ip, "loc": self.geoip.country(ip) if ip and ":" not in ip else ""}

    def _run(self, country: str) -> None:
        ok, msg = self._boot(country)
        if self._cancel.is_set():
            return
        if not ok:
            self.runner.stop()
            self._set(status="idle", message=msg)
            return
        if not self._protect_and_route(country):
            return
        self._monitor()

    def _protect_and_route(self, country: str) -> bool:
        try:
            where = self._exit_location()
        except OSError:
            where = {"ip": "", "loc": ""}
        warning = ""
        if where["loc"] and where["loc"] != country:
            warning = f"注意：實際出口國家是 {where['loc']}，不是所選的 {country}"
        if self._cancel.is_set():
            return False
        try:
            self.killswitch.engage_apps([str(self.runner.exe)])
            self._set(protected=True)
            self.proxy.set_tor(self.runner.port)
        except Exception as exc:
            self._teardown()
            self._set(status="idle", message=f"開啟 Tor 模式失敗：{exc}")
            return False
        if self._cancel.is_set():
            self._teardown()
            return False
        self._set(status="connected", host="Tor 網路", ip=where["ip"], loc=where["loc"], warning=warning,
                  message="已連線", progress=100)
        return True

    def _monitor(self) -> None:
        while not self._cancel.wait(self.monitor_interval):
            if self.snapshot()["status"] != "connected" or self.runner.is_running():
                continue
            self._set(status="reconnecting", message="Tor 中斷，正在重新啟動（網路暫停中）", progress=0)
            if not self._restart():
                return

    def _restart(self) -> bool:
        """保護與代理維持不動，只重啟 Tor（WFP 已放行 tor.exe，可以直接連）。"""
        country = self.snapshot()["country"]
        ok, msg = self._boot(country)
        if self._cancel.is_set():
            return False
        if not ok:
            self._set(status="blocked", message=f"Tor 重新啟動失敗，網路仍受保護（暫停中）。{msg}")
            return False
        try:
            self.proxy.set_tor(self.runner.port)  # 新的 Tor 可能換了 port
            where = self._exit_location()
        except OSError:
            where = {"ip": "", "loc": ""}
        self._set(status="connected", ip=where["ip"], loc=where["loc"], message="已連線", progress=100)
        return True

    def _restart_and_monitor(self) -> None:
        if self._restart():
            self._monitor()
