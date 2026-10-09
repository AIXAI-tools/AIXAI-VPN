"""TASK-007 QA：三種模式的 IP／DNS／IPv6／直連外洩檢測（需系統管理員權限；由 killswitch_live.ps1 -Module 呼叫）。

每種模式都用 App 真正的連線管理器（含斷線保護）連線，再檢查：
  - 對外 IP 國家是否為所選國家
  - DNS 外洩：whoami.akamai.net 回傳「替你查詢的 DNS 伺服器」IP，不能是開始測試時所在國家（本地 ISP）的 DNS
  - IPv6 外洩：直接連 IPv6 位址必須失敗
  - （Tor）不走代理的直連必須失敗
最後一定中斷並確認回到台灣。
用法：python -m tests.live.qa_leaks <紀錄檔路徑>
"""

import socket
import sys
import time
import urllib.request

from src.connector.tor import TOR_DIR, TorRunner
from src.connector.windows.sstp import SstpConnector
from src.connector.windows.wireguard import WireGuardConnector
from src.core.cache import ServerCache
from src.core.geo import public_location
from src.core.geoip import GeoIP
from src.protection.windows.killswitch import KillSwitch
from src.protection.windows.proxy import SystemProxy
from src.server.api import CACHE_PATH, make_search
from src.server.connection import ConnectionManager
from src.server.tor_session import TorManager
from src.server.vpnbook import ConfigStore, VpnbookManager

LOG = open(sys.argv[1], "a", encoding="utf-8")
GEO = GeoIP(TOR_DIR / "data" / "geoip")
HOME = public_location()["loc"]  # 測試開始時（未連 VPN）的所在國家
results = []


def log(msg):
    LOG.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    LOG.flush()


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    log(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    return bool(ok)  # 呼叫端用 `if not check(...)` 判斷是否繼續


def dns_egress():
    """回傳 [(DNS 伺服器對外 IP, 國家)]；查詢失敗回傳 None（被擋也算沒外洩）。"""
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo("whoami.akamai.net", None, socket.AF_INET)})
    except OSError:
        return None
    return [(ip, GEO.country(ip)) for ip in ips]


def ipv6_reachable(timeout=4):
    try:
        with socket.create_connection(("2606:4700:4700::1111", 443), timeout=timeout):
            return True
    except OSError:
        return False


def direct_reachable(timeout=6):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open("https://www.cloudflare.com/cdn-cgi/trace", timeout=timeout).read()
        return True
    except OSError:
        return False


def wait_status(m, want, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if m.snapshot()["status"] in want:
            return True
        time.sleep(1)
    return False


def common_checks(label, country, m):
    s = m.snapshot()
    check(f"[{label}] 出口國家 = {country}", s["loc"] == country, f"{s['ip']} {s['loc']}")
    eg = dns_egress()
    check(f"[{label}] DNS 不外洩（不是 {HOME} 的 DNS）", eg is None or all(c != HOME for _, c in eg), str(eg))
    check(f"[{label}] IPv6 不外洩", not ipv6_reachable())


def run_mode(label, m, start, country):
    log(f"--- {label} ---")
    try:
        start()
        if not check(f"[{label}] 連線成功", wait_status(m, {"connected"}, 330), str(m.snapshot())):
            return
        check(f"[{label}] 斷線保護開啟", m.snapshot()["protected"])
        common_checks(label, country, m)
        if label == "Tor":
            check("[Tor] 不走代理的直連被擋", not direct_reachable())
    finally:
        m.stop()
        time.sleep(2)
        loc = public_location()["loc"]
        check(f"[{label}] 中斷後回到 {HOME}", loc == HOME, loc)


def main():
    try:
        log("=== QA leaks start ===")
        eg = dns_egress()
        check(f"基準：一般網路 DNS 在 {HOME}（確認檢測方法有效）", eg and all(c == HOME for _, c in eg), str(eg))

        # 1. VPN Gate（日本）
        cands = make_search(ServerCache(CACHE_PATH))()["_candidates"].get("JP", [])
        vg = ConnectionManager(SstpConnector(), public_location, killswitch=KillSwitch())
        run_mode("VPN Gate", vg, lambda: vg.start("JP", cands), "JP")

        # 2. Tor（美國）
        tor = TorManager(TorRunner(), KillSwitch(), SystemProxy(), GEO)
        run_mode("Tor", tor, lambda: tor.start("US"), "US")

        # 3. VPNBook（美國；需要已取得的有效設定檔）
        store = ConfigStore()
        if store.load("US") is None:
            log("SKIP VPNBook：沒有有效的美國設定檔")
        else:
            vb = VpnbookManager(WireGuardConnector(), store, public_location)
            run_mode("VPNBook", vb, lambda: vb.start("US"), "US")
    except Exception as exc:
        check("未預期錯誤", False, repr(exc))
    finally:
        SystemProxy().restore()
        passed = sum(ok for _, ok in results)
        log(f"=== done: {passed}/{len(results)} passed ===")


if __name__ == "__main__":
    main()
