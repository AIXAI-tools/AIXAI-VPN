"""計算防火牆「封鎖範圍」：全部位址扣掉例外（純計算，不碰系統，可單元測試）。

Windows 防火牆的封鎖規則優先於允許規則，而且封鎖規則沒有「例外」欄位，
所以要把「全部 − 例外」算成一段段位址範圍，交給 -RemoteAddress。
"""

import ipaddress

# 不封鎖：本機迴路、區域網路、連結本機、多播、廣播（維持印表機、路由器、DHCP 可用）
IPV4_ALWAYS_ALLOWED = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "224.0.0.0/4",
    "255.255.255.255/32",
]
# IPv6 只放行連結本機與多播（鄰居探索必要）；其餘全擋
IPV6_ALWAYS_ALLOWED = ["::1/128", "fe80::/10", "ff00::/8"]


def _complement(version: int, allowed: list[str]) -> list[str]:
    nets = sorted(ipaddress.collapse_addresses(ipaddress.ip_network(n) for n in allowed))
    cls = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
    cursor = 0
    top = (1 << (32 if version == 4 else 128)) - 1
    ranges = []
    for net in nets:
        start, end = int(net.network_address), int(net.broadcast_address)
        if start > cursor:
            ranges.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if cursor <= top:
        ranges.append((cursor, top))
    return [f"{cls(a)}-{cls(b)}" for a, b in ranges]


def ipv4_block_ranges(server_ips: list[str]) -> list[str]:
    """封鎖所有 IPv4，除了 VPN 伺服器 IP 與區域網路。"""
    servers = [f"{ipaddress.IPv4Address(ip)}/32" for ip in server_ips]  # 不合法的 IP 會在這裡拋錯
    return _complement(4, IPV4_ALWAYS_ALLOWED + servers)


def ipv6_block_ranges() -> list[str]:
    return _complement(6, IPV6_ALWAYS_ALLOWED)
