"""記住最近看過的伺服器（方案 2）。

VPN Gate 每次只公開部分伺服器；如果清單會隨時間輪換，把最近 N 小時看過的合併起來，
就能累積更多國家。舊伺服器可能已下線 → 連線時要「連不上就換下一台」。
"""

import json
from dataclasses import asdict
from pathlib import Path

from .vpngate import Server

DEFAULT_TTL_HOURS = 6.0


class ServerCache:
    def __init__(self, path: Path, ttl_hours: float = DEFAULT_TTL_HOURS) -> None:
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self._entries: dict[str, tuple[Server, float]] = self._load()  # hostname → (server, last_seen)

    def _load(self) -> dict[str, tuple[Server, float]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {d["server"]["hostname"]: (Server(**d["server"]), float(d["last_seen"])) for d in raw}
        except (OSError, ValueError, KeyError, TypeError):
            return {}  # 沒有檔案或檔案壞掉 → 從空的開始

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [{"server": asdict(s), "last_seen": t} for s, t in self._entries.values()]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # 先寫暫存檔再取代，避免寫到一半當掉造成檔案損毀

    def merge(self, fresh: list[Server], now: float) -> list[tuple[Server, bool]]:
        """合併本次清單，丟掉過期的，存檔。回傳 [(server, 是否本次清單內)]，本次的排前面。"""
        for s in fresh:
            self._entries[s.hostname] = (s, now)
        self._entries = {h: e for h, e in self._entries.items() if now - e[1] <= self.ttl_seconds}
        self._save()
        fresh_hosts = {s.hostname for s in fresh}
        result = [(s, s.hostname in fresh_hosts) for s, _ in self._entries.values()]
        result.sort(key=lambda x: (not x[1], -x[0].score))
        return result
