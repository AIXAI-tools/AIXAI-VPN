"""TASK-011 Tor 模式實機測試（需系統管理員權限；由 tor_live.ps1 呼叫）。

會真的改 WFP 規則與系統代理。最後一定還原。
用法：python -m tests.live.tor_live <紀錄檔路徑>
"""

import subprocess
import sys
import time
import urllib.request

from src.connector.tor import TOR_DIR, TOR_EXE, TorRunner
from src.core.geoip import GeoIP
from src.protection.windows import proxy as winproxy
from src.protection.windows.killswitch import KillSwitch
from src.protection.windows.proxy import SystemProxy
from src.server.tor_session import TorManager

LOG = open(sys.argv[1], "a", encoding="utf-8")
results = []
TRACE = "https://www.cloudflare.com/cdn-cgi/trace"


def log(msg):
    LOG.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    LOG.flush()


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    log(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def fetch(proxies, timeout=20):
    """proxies={} = 直連；proxies=None = 用系統代理設定。回傳 trace 內容或 None。"""
    handler = urllib.request.ProxyHandler() if proxies is None else urllib.request.ProxyHandler(proxies)
    try:
        return urllib.request.build_opener(handler).open(TRACE, timeout=timeout).read().decode()
    except OSError:
        return None


def field(text, key):
    return dict(l.split("=", 1) for l in (text or "").splitlines() if "=" in l).get(key, "")


def tor_processes() -> int:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"@(Get-Process tor -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{TOR_EXE}' }}).Count"],
                       capture_output=True, text=True)
    return int((r.stdout or "0").strip() or 0)


def wait_status(m, want, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if m.snapshot()["status"] in want:
            return True
        time.sleep(1)
    return False


def main():
    original = winproxy.query()
    m = None
    try:
        log(f"=== tor live start === 原本代理：{original}")
        check("baseline 直連可上網", fetch({}) is not None)

        # 1. 正常流程
        m = TorManager(TorRunner(), KillSwitch(), SystemProxy(), GeoIP(TOR_DIR / "data" / "geoip"))
        t0 = time.time()
        m.start("US")
        check("Tor 模式連線完成", wait_status(m, {"connected"}, 330), f"{time.time() - t0:.0f}s {m.snapshot()}")
        s = m.snapshot()
        check("出口在美國（GeoIP）", s["loc"] == "US", f"{s['ip']} {s['loc']}")
        cur = winproxy.query()
        check("系統代理指向 Tor", cur["server"] == f"127.0.0.1:{m.runner.port}" and cur["flags"] & 2, str(cur))
        via_sys = fetch(None, timeout=40)
        check("依系統代理上網 → 經 Tor（Cloudflare 標記 T1）", field(via_sys, "loc") == "T1", field(via_sys, "ip"))
        check("不走代理的直連被擋（不外洩）", fetch({}, timeout=8) is None)

        m.stop()
        check("中斷後代理還原為原本設定", winproxy.query() == original, str(winproxy.query()))
        check("中斷後直連恢復", fetch({}) is not None)
        time.sleep(2)
        check("中斷後 Tor 已結束", tor_processes() == 0)

        # 2. 模擬 App 當掉：子程序開 Tor 模式後被強制結束 → 看門狗還原代理、WFP 自動消失、Tor 自動結束
        code = ("import time;from src.connector.tor import TorRunner,TOR_DIR;from src.core.geoip import GeoIP;"
                "from src.protection.windows.killswitch import KillSwitch;from src.protection.windows.proxy import SystemProxy;"
                "from src.server.tor_session import TorManager;"
                "m=TorManager(TorRunner(),KillSwitch(),SystemProxy(),GeoIP(TOR_DIR/'data'/'geoip'));m.start('US');"
                "[time.sleep(1) for _ in range(330) if m.snapshot()['status']!='connected'];"
                "print(m.snapshot()['status'],flush=True);time.sleep(600)")
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        dog = subprocess.Popen([sys.executable, "-m", "src.protection.windows.proxy_watchdog", str(child.pid)])
        status = child.stdout.readline().strip()
        check("子程序進入 Tor 模式", status == "connected", status)
        check("子程序執行中：代理已改", winproxy.query() != original)
        subprocess.run(["taskkill", "/F", "/PID", str(child.pid)], capture_output=True)  # 強制結束 = 當掉
        child.wait(10)
        dog.wait(20)
        check("當掉後看門狗把代理還原", winproxy.query() == original, str(winproxy.query()))
        check("當掉後直連自動恢復（WFP 已消失）", fetch({}) is not None)
        gone = False
        for _ in range(30):  # Tor 定期檢查擁有者程序，最多等 30 秒
            if tor_processes() == 0:
                gone = True
                break
            time.sleep(1)
        check("當掉後 Tor 自動結束（__OwningControllerProcess）", gone)
    except Exception as exc:
        check("未預期錯誤", False, repr(exc))
    finally:
        if m is not None:
            m.stop()
        SystemProxy().restore()
        if winproxy.query() != original:
            winproxy.apply(original)
            log("最後補還原代理")
        passed = sum(ok for _, ok in results)
        log(f"=== done: {passed}/{len(results)} passed ===")


if __name__ == "__main__":
    main()
