"""【舊版，已由 wfp.py 取代（ADR-013）】Windows 防火牆封鎖規則。

保留原因：App 啟動清理與 tools/restore-network.ps1 仍會移除舊版可能留下的 AIXAI-VPN 規則群組。

- 全部規則放在群組 AIXAI-VPN，還原時整組移除
- 只作用在實體網卡（Wired、Wireless）；VPN 介面（RemoteAccess）不受影響
- 需要系統管理員權限
"""

import subprocess

from src.protection.ranges import ipv4_block_ranges, ipv6_block_ranges

GROUP = "AIXAI-VPN"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ps(script: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
    )


def _ps_list(items: list[str]) -> str:
    # 範圍字串只會含 0-9a-f . : -（由 ipaddress 產生），仍一律加引號
    return ",".join(f"'{x}'" for x in items)


def build_enable_script(server_ips: list[str]) -> str:
    v4 = _ps_list(ipv4_block_ranges(server_ips))
    v6 = _ps_list(ipv6_block_ranges())
    common = f"-Group '{GROUP}' -Direction Outbound -Action Block -InterfaceType Wired,Wireless -ErrorAction Stop"
    return "; ".join([
        "$ErrorActionPreference='Stop'",
        f"Remove-NetFirewallRule -Group '{GROUP}' -ErrorAction SilentlyContinue",
        f"New-NetFirewallRule -DisplayName 'AIXAI-VPN KS-IPv4' {common} -RemoteAddress {v4} | Out-Null",
        f"New-NetFirewallRule -DisplayName 'AIXAI-VPN KS-IPv6' {common} -RemoteAddress {v6} | Out-Null",
        f"New-NetFirewallRule -DisplayName 'AIXAI-VPN KS-DNS-UDP' {common} -Protocol UDP -RemotePort 53,853 | Out-Null",
        f"New-NetFirewallRule -DisplayName 'AIXAI-VPN KS-DNS-TCP' {common} -Protocol TCP -RemotePort 53,853 | Out-Null",
    ])


class FirewallKillSwitch:
    def enable(self, server_ips: list[str]) -> None:
        """開啟（或更新例外 IP）。失敗時把已建立的規則清掉再拋錯，避免半套狀態。"""
        r = _ps(build_enable_script(server_ips))
        if r.returncode != 0:
            self.disable()
            raise RuntimeError("開啟斷線保護失敗：" + r.stderr.decode("utf-8", "replace")[:300])

    def disable(self) -> None:
        _ps(f"Remove-NetFirewallRule -Group '{GROUP}' -ErrorAction SilentlyContinue")

    def is_active(self) -> bool:
        r = _ps(f"@(Get-NetFirewallRule -Group '{GROUP}' -ErrorAction SilentlyContinue).Count")
        return r.stdout.strip() not in (b"", b"0")
