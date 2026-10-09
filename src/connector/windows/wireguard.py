"""WireGuard 連線器（VPNBook 選配，ADR-011、TASK-009）。

使用官方 WireGuard for Windows 的指令（docs/enterprise.md）：
  wireguard /installtunnelservice <路徑>\\AIXAI-VPNBook.conf   → 建立並啟動通道服務
  wireguard /uninstalltunnelservice AIXAI-VPNBook              → 停止並移除
通道名稱取自檔名；AllowedIPs 為 /0 時，WireGuard 會自動啟用內建 kill switch。
需要系統管理員權限。
"""

import os
import subprocess
import time
from pathlib import Path

WG_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WireGuard"
WG_EXE = WG_DIR / "wireguard.exe"
WG_CLI = WG_DIR / "wg.exe"
TUNNEL = "AIXAI-VPNBook"
RUN_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "vpnbook"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


class WireGuardConnector:
    def __init__(self, exe: Path = WG_EXE, cli: Path = WG_CLI, run_dir: Path = RUN_DIR) -> None:
        self.exe, self.cli, self.run_dir = exe, cli, run_dir

    def available(self) -> bool:
        return self.exe.exists()

    def latest_handshake(self) -> int:
        """最近一次握手的 Unix 時間（0 = 還沒握手或通道不存在）。"""
        try:
            r = _run([str(self.cli), "show", TUNNEL, "latest-handshakes"], timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return 0
        parts = r.stdout.decode("ascii", "replace").split()
        return int(parts[-1]) if r.returncode == 0 and parts and parts[-1].isdigit() else 0

    def connect(self, config_text: str, timeout: float = 30) -> tuple[bool, str]:
        """寫入通道設定 → 安裝並啟動服務 → 等到第一次握手成功。"""
        if not self.available():
            return False, "尚未安裝 WireGuard"
        self.disconnect()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        conf = self.run_dir / f"{TUNNEL}.conf"
        conf.write_text(config_text, encoding="utf-8")
        r = _run([str(self.exe), "/installtunnelservice", str(conf)], timeout=60)
        if r.returncode != 0:
            return False, "啟動 WireGuard 通道失敗：" + r.stderr.decode("utf-8", "replace")[:200]
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.latest_handshake():
                return True, "已連線"
            time.sleep(1)
        self.disconnect()
        return False, f"{int(timeout)} 秒內沒有和伺服器完成握手（設定檔可能已過期）"

    def is_connected(self) -> bool:
        """通道服務是否在執行。不用握手時間判斷：沒有流量時 WireGuard 不會重新握手。"""
        try:
            # Get-Service 的狀態是英文列舉值，不受系統語言影響
            r = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                      f"(Get-Service -Name 'WireGuardTunnel${TUNNEL}' -ErrorAction SilentlyContinue).Status"], timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.stdout.strip() == b"Running"

    def disconnect(self) -> None:
        try:
            _run([str(self.exe), "/uninstalltunnelservice", TUNNEL], timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
