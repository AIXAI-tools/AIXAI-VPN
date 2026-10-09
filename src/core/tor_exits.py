"""Tor 出口節點：依國家統計目前運作中的出口數量（Tor 官方公開資料 onionoo，HTTPS、免註冊）。"""

import json
import urllib.request
from collections import Counter

from .countries import TARGET_COUNTRIES

ONIONOO_URL = "https://onionoo.torproject.org/details?running=true&flag=Exit&fields=country"


def fetch_exit_counts(timeout: float = 30) -> dict[str, int]:
    req = urllib.request.Request(ONIONOO_URL, headers={"User-Agent": "AIXAI-VPN/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return count_exits(json.load(resp))


def count_exits(data: dict) -> dict[str, int]:
    """onionoo 的國家代碼是小寫 → 轉大寫，只留目標 15 國。"""
    counts = Counter(r.get("country", "").upper() for r in data.get("relays", []))
    return {code: counts.get(code, 0) for code in TARGET_COUNTRIES}
