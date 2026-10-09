"""IP → 國家：使用 Tor 內附的 GeoIP 檔（本機查詢，不連外部服務）。

Cloudflare 對 Tor 出口回傳 loc=T1（代表 Tor），無法得知國家，所以改用這個。
檔案格式：每行「起始整數,結束整數,國家代碼」，已排序。
"""

import bisect
import ipaddress
from pathlib import Path


class GeoIP:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._starts: list[int] = []
        self._rows: list[tuple[int, int, str]] = []

    def _load(self) -> None:
        if self._rows:
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            a, b, cc = line.split(",")
            self._rows.append((int(a), int(b), cc))
        self._rows.sort()
        self._starts = [r[0] for r in self._rows]

    def country(self, ip: str) -> str:
        """回傳兩碼國家代碼；查不到回傳空字串。只支援 IPv4。"""
        self._load()
        n = int(ipaddress.IPv4Address(ip))
        i = bisect.bisect_right(self._starts, n) - 1
        if i >= 0 and self._rows[i][0] <= n <= self._rows[i][1]:
            return self._rows[i][2]
        return ""
