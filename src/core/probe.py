"""SSTP 可用性檢查：只做 SSTP 連線的第一步，不登入（TASK-003c）。

VPN Gate 的清單只代表「伺服器曾回報上線」；實測 105 台中只有約 1/3 真的能用 SSTP 連。
所以搜尋時對每台伺服器：
  1. TCP 連 443（或伺服器自己的 TCP port，ADR-017）
  2. TLS 握手並驗證憑證（和 Windows 連線時一樣嚴格）
  3. 送出 SSTP 規格的開頭請求（SSTP_DUPLEX_POST），伺服器回 HTTP 200 才算可用
同時量測延遲（從使用者這端），用來排序。
"""

import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor

from src.core.vpngate import split_endpoint

# MS-SSTP 規格固定的請求路徑
SSTP_PATH = "/sra_{BA195980-CD49-458b-9E23-C84EE0ADCD75}/"


def sstp_probe(host: str, port: int = 443, timeout: float = 3.0) -> int | None:
    """可用回傳延遲（毫秒），不可用回傳 None。"""
    if ":" in host:  # 「主機:port」格式
        host, port = split_endpoint(host)
    start = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                tls.settimeout(timeout)
                tls.sendall((f"SSTP_DUPLEX_POST {SSTP_PATH} HTTP/1.1\r\n"
                             f"Host: {host}\r\n"
                             "SSTPCORRELATIONID: {00000000-0000-0000-0000-000000000000}\r\n"
                             "Content-Length: 18446744073709551615\r\n\r\n").encode("ascii"))
                status = tls.recv(64).decode("latin-1").split("\r\n", 1)[0]
    except (OSError, ssl.SSLError, UnicodeError):
        return None
    if not status.startswith("HTTP/1.1 200"):
        return None
    return int((time.monotonic() - start) * 1000)


def probe_all(hosts: list[str], probe=sstp_probe, workers: int = 48) -> dict[str, int]:
    """同時檢查多台；回傳 {可用的主機: 延遲毫秒}。"""
    unique = list(dict.fromkeys(hosts))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as ex:
        results = dict(zip(unique, ex.map(probe, unique)))
    return {h: ms for h, ms in results.items() if ms is not None}
