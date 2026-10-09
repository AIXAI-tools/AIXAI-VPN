"""Windows 內建 VPN（SSTP）連線器（ADR-006）。

- VPN 設定只建立在目前使用者底下（不加 -AllUserConnection），不需要系統管理員權限
- 主機名稱來自外部清單 → 一律先用白名單規則檢查，避免指令注入
"""

import re
import subprocess
from dataclasses import dataclass

PROFILE_NAME = "AIXAI-VPN-SSTP"
# VPN Gate 的 SSTP 主機名稱格式：英數字與連字號 + .opengw.net
HOST_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,63}\.opengw\.net$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# rasdial 常見錯誤碼 → 中文說明
RAS_ERRORS = {
    623: "找不到 VPN 設定",
    651: "網路裝置回報錯誤",
    691: "帳號或密碼被拒絕",
    800: "無法建立 VPN 連線（伺服器可能已離線）",
    809: "連線被防火牆或網路擋住",
    868: "找不到伺服器（DNS 解析失敗）",
    13801: "伺服器憑證驗證失敗",
    0x8007274C: "伺服器沒有回應（連線逾時）",
    0x8007274D: "伺服器拒絕連線",
}


@dataclass
class DialResult:
    ok: bool
    message: str
    code: int | None = None


def validate_host(host: str) -> str:
    if not HOST_PATTERN.fullmatch(host):
        raise ValueError(f"不合法的伺服器名稱：{host!r}")
    return host


def _powershell(script: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
    )


def _rasdial(*args: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(["rasdial.exe", *args], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


class SstpConnector:
    def ensure_profile(self, host: str) -> None:
        """建立或更新 VPN 設定，指向指定伺服器。所有流量走 VPN（不分流）。"""
        host = validate_host(host)
        script = (
            f"$n='{PROFILE_NAME}'; $h='{host}';"
            "if (Get-VpnConnection -Name $n -ErrorAction SilentlyContinue) {"
            "  Set-VpnConnection -Name $n -ServerAddress $h -SplitTunneling $false -Force -ErrorAction Stop"
            "} else {"
            "  Add-VpnConnection -Name $n -ServerAddress $h -TunnelType Sstp -AuthenticationMethod MSChapv2"
            "  -EncryptionLevel Required -Force -ErrorAction Stop"
            "}"
        )
        r = _powershell(script)
        if r.returncode != 0:
            raise RuntimeError("建立 VPN 設定失敗：" + r.stderr.decode("utf-8", "replace")[:300])

    def connect(self, host: str, timeout: float = 45) -> DialResult:
        try:
            self.ensure_profile(host)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return DialResult(False, str(exc))
        try:
            # VPN Gate 官方公開的共用帳密：vpn / vpn（不是秘密）
            r = _rasdial(PROFILE_NAME, "vpn", "vpn", timeout=timeout)
        except subprocess.TimeoutExpired:
            self.disconnect()
            return DialResult(False, f"{int(timeout)} 秒內沒有連上")
        if r.returncode == 0:
            return DialResult(True, "已連線")
        return DialResult(False, RAS_ERRORS.get(r.returncode, f"連線失敗（錯誤碼 {r.returncode}）"), r.returncode)

    def disconnect(self) -> None:
        try:
            _rasdial(PROFILE_NAME, "/disconnect", timeout=20)
        except subprocess.TimeoutExpired:
            pass

    def is_connected(self) -> bool:
        try:
            r = _rasdial(timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return PROFILE_NAME.encode() in r.stdout

    def remove_profile(self) -> None:
        """還原用：移除本 App 建立的 VPN 設定。"""
        self.disconnect()
        _powershell(f"Remove-VpnConnection -Name '{PROFILE_NAME}' -Force -ErrorAction SilentlyContinue")
