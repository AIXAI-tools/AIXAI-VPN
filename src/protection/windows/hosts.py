"""hosts 檔案：預先寫入候選伺服器 IP，讓斷線重連時不需要 DNS（設計決策點 1-i）。

只新增／移除結尾帶 `# AIXAI-VPN` 標記的行，其他內容一律不動。
第一次修改前，在 %LOCALAPPDATA%\\AIXAI-VPN\\ 留一份原始備份。
"""

import ipaddress
import os
from pathlib import Path

from src.connector.windows.sstp import validate_host

MARKER = "# AIXAI-VPN"
HOSTS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
BACKUP_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "hosts.backup"


def strip_marked(text: str) -> str:
    lines = text.splitlines()
    kept = [ln for ln in lines if not ln.rstrip().endswith(MARKER)]
    return "\r\n".join(kept) + ("\r\n" if kept else "")


def with_entries(text: str, entries: dict[str, str]) -> str:
    base = strip_marked(text)
    new = []
    for host, ip in entries.items():
        validate_host(host)
        ipaddress.IPv4Address(ip)  # 不合法會拋錯
        new.append(f"{ip} {host} {MARKER}")
    return base + "".join(line + "\r\n" for line in new)


class HostsFile:
    def __init__(self, path: Path = HOSTS_PATH, backup: Path = BACKUP_PATH) -> None:
        self.path = path
        self.backup = backup

    def _read(self) -> str:
        return self.path.read_bytes().decode("utf-8", errors="surrogateescape")

    def _write(self, text: str) -> None:
        self.path.write_bytes(text.encode("utf-8", errors="surrogateescape"))

    def write_entries(self, entries: dict[str, str]) -> None:
        original = self._read()
        if not self.backup.exists():
            self.backup.parent.mkdir(parents=True, exist_ok=True)
            self.backup.write_bytes(self.path.read_bytes())
        self._write(with_entries(original, entries))

    def remove_entries(self) -> None:
        text = self._read()
        if MARKER in text:
            self._write(strip_marked(text))
