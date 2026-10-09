"""一鍵還原（Python 版，給 exe 使用者：AIXAI-VPN.exe --restore）。內容同 tools/restore-network.ps1。

只移除 AIXAI-VPN 自己建立的東西；每一步失敗不影響下一步。需要系統管理員權限。
"""

from src.connector.windows.sstp import SstpConnector
from src.connector.windows.wireguard import WireGuardConnector
from src.protection.windows.firewall import FirewallKillSwitch
from src.protection.windows.hosts import HostsFile
from src.protection.windows.proxy import SystemProxy


def restore_all(log=print) -> bool:
    steps = [
        ("中斷 VPN Gate 連線", SstpConnector().disconnect),
        ("移除舊版防火牆規則", FirewallKillSwitch().disable),
        ("移除 hosts 標記行", HostsFile().remove_entries),
        ("還原系統代理（Tor 模式）", SystemProxy().restore),
        ("移除 VPNBook 的 WireGuard 通道", lambda: WireGuardConnector().available() and WireGuardConnector().disconnect()),
    ]
    ok = True
    for i, (name, step) in enumerate(steps, 1):
        try:
            step()
            log(f"[{i}/{len(steps)}] {name}：完成")
        except Exception as exc:
            ok = False
            log(f"[{i}/{len(steps)}] {name}：失敗（{exc}）")
    return ok
