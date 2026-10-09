"""Tor 啟動器（ADR-011）：用 vendor/tor 內的官方 tor.exe，指定出口國家，提供本機 HTTP 代理。

- 只監聽 127.0.0.1（HTTPTunnelPort，HTTP CONNECT 代理）；SOCKS 關閉
- `__OwningControllerProcess`：本 App 的程序消失時，Tor 會自動結束（當掉也不會殘留）
- 資料夾放在 %LOCALAPPDATA%\\AIXAI-VPN\\tor\\，保留快取，第二次啟動比較快
"""

import collections
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from src.core.countries import TARGET_COUNTRIES

ROOT = Path(__file__).resolve().parent.parent.parent
TOR_DIR = ROOT / "vendor" / "tor"
TOR_EXE = TOR_DIR / "tor" / "tor.exe"
WORK_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "tor"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BOOTSTRAP_RE = re.compile(r"Bootstrapped (\d+)%")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_torrc(country: str, port: int, owner_pid: int, data_dir: Path, tor_dir: Path = TOR_DIR) -> str:
    if country not in TARGET_COUNTRIES:  # 只接受白名單國家代碼，避免寫入任意設定
        raise ValueError(f"不支援的國家：{country!r}")
    geo = (tor_dir / "data").as_posix()
    return "\n".join([
        f'DataDirectory "{data_dir.as_posix()}"',
        f'GeoIPFile "{geo}/geoip"',
        f'GeoIPv6File "{geo}/geoip6"',
        "SocksPort 0",
        f"HTTPTunnelPort 127.0.0.1:{port}",
        f"ExitNodes {{{country.lower()}}}",
        "StrictNodes 1",
        f"__OwningControllerProcess {owner_pid}",
        "Log notice stdout",
        "",
    ])


class TorRunner:
    def __init__(self, exe: Path = TOR_EXE, work_dir: Path = WORK_DIR) -> None:
        self.exe = exe
        self.work_dir = work_dir
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.progress = 0
        self._ready = threading.Event()
        self.log = collections.deque(maxlen=30)  # 最近的 Tor 記錄，失敗時方便查原因

    def available(self) -> bool:
        return self.exe.exists()

    def start(self, country: str, timeout: float = 300, on_progress=None) -> tuple[bool, str]:
        """啟動並等到 100%。回傳 (成功與否, 訊息)。"""
        self.stop()
        if not self.available():
            return False, "找不到 Tor 程式（請先執行 python tools/fetch_tor.py）"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        torrc = self.work_dir / "torrc"
        torrc.write_text(build_torrc(country, self.port, os.getpid(), self.work_dir / "data"), encoding="utf-8")
        self.progress = 0
        self._ready.clear()
        self.proc = subprocess.Popen([str(self.exe), "-f", str(torrc)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        threading.Thread(target=self._read_log, args=(self.proc, on_progress), daemon=True).start()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._ready.wait(0.5):
                return True, "Tor 已就緒"
            if self.proc.poll() is not None:
                return False, f"Tor 意外結束（代碼 {self.proc.returncode}）"
        self.stop()
        return False, f"{int(timeout)} 秒內 Tor 沒有啟動完成（目前 {self.progress}%）"

    def _read_log(self, proc, on_progress) -> None:
        for line in proc.stdout:
            self.log.append(line.rstrip())
            m = BOOTSTRAP_RE.search(line)
            if m:
                self.progress = int(m.group(1))
                if on_progress:
                    on_progress(self.progress)
                if self.progress >= 100:
                    self._ready.set()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
