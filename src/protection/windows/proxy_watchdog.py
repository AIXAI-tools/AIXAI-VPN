"""看門狗：等 App 程序結束後，若系統代理還沒還原，就自動還原（TASK-011 設計 ③）。

執行：python -m src.protection.windows.proxy_watchdog <App 的 PID>
      python -m src.protection.windows.proxy_watchdog --now   （立刻還原，給還原腳本用）
App 正常結束時會先自己還原（備份標成 inactive），看門狗就什麼都不做。
"""

import ctypes
import sys

SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF


def wait_for_exit(pid: int) -> None:
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p  # 64 位元 handle
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return  # 程序已經不在了
    try:
        k32.WaitForSingleObject(handle, INFINITE)
    finally:
        k32.CloseHandle(handle)


def main() -> None:
    from src.protection.windows.proxy import SystemProxy

    if sys.argv[1] != "--now":
        wait_for_exit(int(sys.argv[1]))
    SystemProxy().restore()


if __name__ == "__main__":
    main()
