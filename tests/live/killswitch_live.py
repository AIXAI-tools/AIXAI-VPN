"""TASK-005 實機測試（需系統管理員權限；由 killswitch_live.ps1 以提權方式呼叫）。

會真的改防火牆與 hosts。每一步都寫入紀錄檔，最後一定還原。
用法：python -m tests.live.killswitch_live <紀錄檔路徑>
"""

import socket
import subprocess
import sys
import time
import urllib.request

from src.connector.windows.sstp import SstpConnector, _rasdial, PROFILE_NAME
from src.core.geo import public_location
from src.core.vpngate import fetch_list, filter_targets, group_by_country, parse_list
from src.protection.windows.firewall import FirewallKillSwitch
from src.protection.windows.wfp import WfpKillSwitch
from src.protection.windows.hosts import MARKER, HostsFile
from src.protection.windows.killswitch import KillSwitch
from src.server.connection import ConnectionManager

LOG = open(sys.argv[1], "a", encoding="utf-8")
results = []


def log(msg):
    LOG.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    LOG.flush()


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    log(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def can_reach(url="https://www.cloudflare.com/cdn-cgi/trace", timeout=6):
    try:
        urllib.request.urlopen(url, timeout=timeout).read()
        return True
    except OSError:
        return False


def wait_status(m, want, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if m.snapshot()["status"] in want:
            return True
        time.sleep(0.5)
    return False


def main():
    ks = KillSwitch()
    hosts = HostsFile()
    try:
        log("=== start ===")
        check("baseline 可上網", can_reach())

        server_ip = socket.gethostbyname("public-vpn-184.opengw.net")

        # 1. 只開 WFP 保護、不連 VPN → 應該完全上不了網
        w = WfpKillSwitch()
        w.enable([server_ip], None)
        check("WFP 保護開啟", w.is_active())
        check("沒有 VPN 時上不了網（不外洩）", not can_reach())
        w.disable()
        check("關閉 WFP 後恢復上網", can_reach())

        # 2. 模擬 App 當掉：另一個程序開保護後被強制結束 → Windows 應自動刪除規則
        code = ("from src.protection.windows.wfp import WfpKillSwitch;import time;"
                f"w=WfpKillSwitch();w.enable(['{server_ip}'],None);print('ON',flush=True);time.sleep(120)")
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        on = child.stdout.readline().strip() == "ON"
        check("子程序開啟保護", on)
        check("子程序執行中上不了網", not can_reach())
        subprocess.run(["taskkill", "/F", "/PID", str(child.pid)], capture_output=True)  # 強制結束 = 模擬當掉
        child.wait(timeout=10)
        back = False
        for _ in range(10):
            if can_reach(timeout=3):
                back = True
                break
            time.sleep(1)
        check("程序被強制結束後，網路自動恢復（不需還原）", back)

        # 2. 完整流程：連線 → 保護 → 模擬斷線 → 自動重連 → 中斷
        jp = group_by_country(filter_targets(parse_list(fetch_list()))).get("JP", [])
        cands = [s.sstp_host for s in jp[:5]]
        log(f"候選：{cands}")
        check("沒有舊版防火牆規則", not FirewallKillSwitch().is_active())
        m = ConnectionManager(SstpConnector(), public_location, killswitch=ks)
        m.start("JP", cands)
        check("連線並開啟保護", wait_status(m, {"connected"}, 240), str(m.snapshot()))
        check("WFP 保護開著、hosts 有標記行", ks.wfp.is_active() and MARKER in hosts.path.read_text(encoding="utf-8", errors="replace"))
        s = m.snapshot()
        check("出口在日本", s["loc"] == "JP", f"{s['ip']} {s['loc']}")
        check("保護中仍可經 VPN 上網", can_reach())

        log("模擬意外斷線（直接 rasdial /disconnect）")
        t0 = time.time()
        _rasdial(PROFILE_NAME, "/disconnect", timeout=20)
        # 監控每 2 秒檢查一次 → 等它真的離開 connected
        detected = wait_status(m, {"reconnecting", "blocked"}, 15)
        check("偵測到斷線並進入重連", detected, f"{m.snapshot()['status']}，{time.time() - t0:.1f}s")
        if detected and m.snapshot()["status"] == "reconnecting":
            check("重連期間上不了網（不外洩）", not can_reach(timeout=3))
        check("自動重連成功", wait_status(m, {"connected"}, 240), f"{m.snapshot()}，{time.time() - t0:.1f}s")
        check("重連後保護仍開著", ks.wfp.is_active() and m.snapshot()["protected"])
        loc = ""
        for _ in range(5):  # 隧道剛建好，給幾次機會
            try:
                loc = public_location()["loc"]
                break
            except OSError:
                time.sleep(2)
        check("重連後出口仍在日本", loc == "JP", loc)

        m.stop()
        check("中斷後 WFP 規則清除", not ks.wfp.is_active())
        check("中斷後 hosts 清乾淨", MARKER not in hosts.path.read_text(encoding="utf-8", errors="replace"))
        check("中斷後恢復上網且回到台灣", public_location()["loc"] == "TW")
    except Exception as exc:
        check("未預期錯誤", False, repr(exc))
    finally:
        try:
            ks.release()
        except Exception as exc:
            log(f"最後還原錯誤：{exc!r}")
        subprocess.run(["rasdial.exe", PROFILE_NAME, "/disconnect"], capture_output=True)
        passed = sum(ok for _, ok in results)
        log(f"=== done: {passed}/{len(results)} passed ===")


if __name__ == "__main__":
    main()
