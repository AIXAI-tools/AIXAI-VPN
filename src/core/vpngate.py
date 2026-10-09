"""VPN Gate 伺服器清單：抓取、解析、篩選。

只用 Python 標準函式庫，不碰作業系統設定（ARCHITECTURE：core 必須可攜）。
"""

import base64
import binascii
import csv
import io
import re
import urllib.request
from dataclasses import dataclass

from .countries import TARGET_COUNTRIES

LIST_URL = "https://www.vpngate.net/api/iphone/"
SSTP_DOMAIN = ".opengw.net"  # SSTP 必須用 DDNS 主機名稱，不能直接用 IP


@dataclass(frozen=True)
class Server:
    hostname: str
    ip: str
    score: int
    ping_ms: int | None  # VPN Gate 自己量的，不是從我們這邊量的
    speed_bps: int
    country_code: str
    country_name: str
    sessions: int
    uptime_ms: int
    log_type: str
    operator: str
    tcp_port: int = 443  # 伺服器 TCP 監聽 port（取自 OpenVPN 設定）；SSTP 也能走這個 port

    @property
    def sstp_host(self) -> str:
        return self.hostname + SSTP_DOMAIN

    @property
    def sstp_endpoints(self) -> list[str]:
        """可嘗試的 SSTP 端點：先 443，再試伺服器自己的 TCP port（家用網路的志願者伺服器常只開這個）。"""
        eps = [self.sstp_host]
        if self.tcp_port != 443:
            eps.append(f"{self.sstp_host}:{self.tcp_port}")
        return eps


def split_endpoint(endpoint: str) -> tuple[str, int]:
    """「主機」或「主機:port」→ (主機, port)。"""
    host, sep, port = endpoint.rpartition(":")
    if not sep:
        return endpoint, 443
    return host, int(port)


def openvpn_tcp_port(config_b64: str) -> int:
    """從 OpenVPN 設定（base64）找出 TCP 監聽 port；不是 TCP 或解析失敗就回傳 443。"""
    try:
        cfg = base64.b64decode(config_b64, validate=False).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return 443
    proto = re.search(r"^proto\s+(\w+)", cfg, re.M)
    remote = re.search(r"^remote\s+\S+\s+(\d{1,5})\s*$", cfg, re.M)
    if not proto or proto.group(1).lower() != "tcp" or not remote:
        return 443
    port = int(remote.group(1))
    return port if 1 <= port <= 65535 else 443


def fetch_list(url: str = LIST_URL, timeout: float = 20.0) -> str:
    """用 HTTPS 下載清單原文。urllib 預設會驗證伺服器憑證。"""
    if not url.startswith("https://"):
        raise ValueError("只允許 HTTPS（安全要求：出去的資訊都要加密）")
    req = urllib.request.Request(url, headers={"User-Agent": "AIXAI-VPN/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_list(text: str) -> list[Server]:
    """解析 CSV。第一行 `*vpn_servers`、第二行 `#HostName,...` 表頭、最後一行 `*`。"""
    servers = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].startswith(("*", "#")) or len(row) < 13:
            continue
        ping = _to_int(row[3], default=-1)
        servers.append(
            Server(
                hostname=row[0],
                ip=row[1],
                score=_to_int(row[2]),
                ping_ms=ping if ping >= 0 else None,
                speed_bps=_to_int(row[4]),
                country_name=row[5],
                country_code=row[6].upper(),
                sessions=_to_int(row[7]),
                uptime_ms=_to_int(row[8]),
                log_type=row[11],
                operator=row[12],
                tcp_port=openvpn_tcp_port(row[14]) if len(row) > 14 else 443,
            )
        )
    return servers


def filter_targets(servers: list[Server]) -> list[Server]:
    """只留目標國家。"""
    return [s for s in servers if s.country_code in TARGET_COUNTRIES]


def group_by_country(servers: list[Server]) -> dict[str, list[Server]]:
    """依國家分組，組內依 VPN Gate 分數由高到低排序（分數高 = 品質較好）。"""
    groups: dict[str, list[Server]] = {}
    for s in servers:
        groups.setdefault(s.country_code, []).append(s)
    for group in groups.values():
        group.sort(key=lambda s: s.score, reverse=True)
    return groups


def availability(servers: list[Server]) -> list[tuple[str, str, int]]:
    """回傳目標國家各自有幾台伺服器：[(代碼, 中文名, 台數)]，順序同 TARGET_COUNTRIES。"""
    groups = group_by_country(filter_targets(servers))
    return [(code, name, len(groups.get(code, []))) for code, name in TARGET_COUNTRIES.items()]
