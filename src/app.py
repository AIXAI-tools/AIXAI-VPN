"""AIXAI-VPN 啟動器：提權 → 啟動本機伺服器 → 開視窗 → 視窗關閉就中斷連線並結束。

執行（開發）：python -m src.app
執行（打包）：AIXAI-VPN.exe

視窗（ADR-008）：
- 有 pywebview（打包版）→ App 自己的視窗（Windows 內建 WebView2）
- 沒有 pywebview（開發用的系統 Python）→ Edge App 模式；設 AIXAI_UI=edge 也會強制用 Edge

特殊參數：
  --watchdog <PID>     看門狗：等該程序結束後還原系統代理（ADR-014）
  --restore            一鍵還原（給沒有 Python 的使用者；同 tools/restore-network.ps1）
  --selftest <輸出檔>  自我檢查打包內容（不需管理員權限）
  --updated-from=<版號> 程式內更新後由舊版啟動（只用來顯示，不影響行為）
"""

import ctypes
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # PyInstaller 打包後為 True
# 打包版：exe 所在資料夾；開發版：專案根目錄
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Edge 專用設定檔資料夾：和你平常用的 Edge 分開，視窗關閉時程序才會結束
PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "edge-profile"
WEBVIEW_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "webview"


def window_size() -> tuple[int, int]:
    """預設視窗：螢幕寬的 1/4、高的 1/3（使用者需求），太小時保留最低可用尺寸。"""
    try:
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)  # 主螢幕寬、高
    except (AttributeError, OSError):
        sw, sh = 1920, 1080
    return max(sw // 4, 360), max(sh // 3, 420)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def self_command(*args: str) -> list[str]:
    """重新執行自己的指令（打包版直接執行 exe；開發版用 python -m src.app）。"""
    return [sys.executable, *args] if FROZEN else [sys.executable, "-m", "src.app", *args]


def message(text: str, title: str = "AIXAI-VPN") -> None:
    """打包版沒有主控台 → 用 Windows 訊息框；開發版直接印出。"""
    if FROZEN:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(text)


def relaunch_as_admin(*args: str) -> None:
    """斷線保護需要系統管理員權限（決策點 2-a）。跳一次 UAC。"""
    cmd = self_command(*args)
    params = subprocess.list2cmdline(cmd[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, str(ROOT), 1)
    if rc <= 32:  # ShellExecute 回傳值 ≤ 32 代表失敗（包含使用者按「否」）
        message("需要系統管理員權限才能開啟斷線保護；已取消啟動。")


def start_proxy_watchdog() -> None:
    """另開一個小程序盯著本 App：App 若當掉，它負責把系統代理還原（ADR-014）。"""
    subprocess.Popen(self_command("--watchdog", str(os.getpid())), cwd=str(ROOT), creationflags=NO_WINDOW)


def use_webview() -> bool:
    if os.environ.get("AIXAI_UI") == "edge":
        return False
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def open_edge(url: str) -> None:
    from src.connector.windows.edge import find_edge

    edge = find_edge()
    if edge is None:
        print("找不到 Edge，改用預設瀏覽器開啟。")
        webbrowser.open(url)
        return
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # 不等 Edge 程序：它會自動降權重開（瀏覽器不該用管理員權限跑），原程序會立刻結束
    subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={PROFILE_DIR}",
                      "--window-size={},{}".format(*window_size()), "--no-first-run", "--no-default-browser-check"])


def launch_updated_exe(tag: str) -> None:
    """程式內更新完成：啟動新版 exe（已是管理員權限，不會再跳 UAC）。
    PYINSTALLER_RESET_ENVIRONMENT=1：讓新程序自己解壓，不沿用舊版的暫存資料夾（否則跑到的仍是舊版程式碼）。"""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([sys.executable, f"--updated-from={tag}"], cwd=str(ROOT), env=env)


def research_loop(server, stop: threading.Event) -> None:
    while not stop.wait(server.RESEARCH_RETRY_SECONDS):
        server.research_tick()  # 研究模式：網路暫停時自動重試


def run_app() -> None:
    from src.core.updater import cleanup_old
    from src.server.api import AppServer
    from src.server.updates import UpdateService

    # AIXAI_SKIP_ADMIN=1：只給自動化測試看介面用（不提權 → 斷線保護會開啟失敗，不會降低安全性）
    if not is_admin() and os.environ.get("AIXAI_SKIP_ADMIN") != "1":
        relaunch_as_admin()
        return
    start_proxy_watchdog()
    exe = Path(sys.executable) if FROZEN else None
    if exe is not None:
        cleanup_old(exe)  # 上次程式內更新留下的舊版檔案
    quit_requested = threading.Event()
    windows: list = []  # pywebview 視窗（Edge 模式為空）

    def request_quit() -> None:
        quit_requested.set()
        for w in windows:
            w.destroy()

    def on_installed(tag: str) -> None:
        launch_updated_exe(tag)
        time.sleep(1.5)  # 讓介面顯示「正在重新啟動」
        request_quit()

    token = secrets.token_urlsafe(32)
    server = AppServer(token, updates=UpdateService(exe, on_installed=on_installed), on_quit=request_quit)
    if server.settings.get("auto_update_check"):
        server.updates.check()  # 背景查詢；有新版時介面的「關於」按鈕會出現提示
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=research_loop, args=(server, stop), daemon=True).start()

    # token 放在 # 後面：不會送到伺服器記錄，也不會出現在 Referer
    url = f"http://127.0.0.1:{server.port}/#token={token}"
    print(f"AIXAI-VPN 已啟動（127.0.0.1:{server.port}）。關閉視窗即結束。")

    try:
        if use_webview():
            import webview

            WEBVIEW_DIR.mkdir(parents=True, exist_ok=True)
            w, h = window_size()
            windows.append(webview.create_window("AIXAI-VPN", url, width=w, height=h, min_size=(340, 400)))
            webview.start(private_mode=False, storage_path=str(WEBVIEW_DIR))  # 視窗關閉才會返回
        else:
            open_edge(url)
            wait_for_edge_window(server, quit_requested)
    except KeyboardInterrupt:
        pass
    finally:
        # 視窗關閉 → 若還連著 VPN 就中斷，讓網路回到原狀
        stop.set()
        server.manager.stop()
        server.tor.stop()
        server.vpnbook.stop()
        server.shutdown()


def wait_for_edge_window(server, quit_requested: threading.Event) -> None:
    """Edge 模式：用心跳判斷視窗是否還開著；60 秒內都沒連上就放棄。"""
    started = time.monotonic()
    while True:
        time.sleep(1)
        if server.ui_gone() or quit_requested.is_set():
            return
        if server.last_seen is None and time.monotonic() - started > 60:
            print("60 秒內視窗都沒有連上，結束。")
            return


def main(argv: list[str]) -> int:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--watchdog"] and len(argv) == 2:
        from src.protection.windows.proxy import SystemProxy
        from src.protection.windows.proxy_watchdog import wait_for_exit

        wait_for_exit(int(argv[1]))
        SystemProxy().restore()
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        from src import selftest

        return selftest.main(argv[1])
    if argv[:1] == ["--restore"]:
        if not is_admin():
            relaunch_as_admin("--restore")
            return 0
        from src.restore import restore_all

        lines: list[str] = []
        ok = restore_all(lines.append)
        message("\n".join(lines) + ("\n\n網路已還原。" if ok else "\n\n部分項目未完成。"))
        return 0 if ok else 1
    run_app()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
