"""VPN Gate 伺服器清單：抓取、解析、篩選。

只用 Python 標準函式庫，不碰作業系統設定（ARCHITECTURE：core 必須可攜）。
"""

import csv
import io
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

    @property
    def sstp_host(self) -> str:
        return self.hostname + SSTP_DOMAIN


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
            )
        )
    return servers


def filter_targets(servers: list[Server]) -> list[Server]:
    """只留目標 15 國。"""
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
    """回傳 15 國各自有幾台伺服器：[(代碼, 中文名, 台數)]，順序同 TARGET_COUNTRIES。"""
    groups = group_by_country(filter_targets(servers))
    return [(code, name, len(groups.get(code, []))) for code, name in TARGET_COUNTRIES.items()]
