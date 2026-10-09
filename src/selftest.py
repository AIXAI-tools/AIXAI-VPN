"""自我檢查（AIXAI-VPN.exe --selftest <輸出檔>）：不需要系統管理員權限，確認打包內容完整。

只讀取與計算，不改任何系統設定。結果以 JSON 寫到指定檔案（exe 沒有主控台）。
"""

import ctypes
import json
import subprocess
from pathlib import Path


def run() -> dict:
    results: dict[str, object] = {}

    def check(name, fn):
        try:
            value = fn()
            results[name] = {"ok": bool(value), "detail": str(value)[:200]}
        except Exception as exc:  # 自我檢查要把所有錯誤都記下來，不中斷
            results[name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}

    from src.server import api
    from src.connector import tor
    from src.core.geoip import GeoIP
    from src.protection.windows import wfp

    check("ui_files", lambda: all((api.UI_DIR / n).exists() for n, _ in api.STATIC_FILES.values()))
    check("tor_exe", lambda: tor.TOR_EXE.exists() and tor.TOR_EXE)
    check("tor_runs", lambda: subprocess.run([str(tor.TOR_EXE), "--version"], capture_output=True, text=True,
                                             timeout=30, creationflags=tor.NO_WINDOW).stdout.splitlines()[0])
    check("geoip", lambda: GeoIP(tor.TOR_DIR / "data" / "geoip").country("219.100.37.243") == "JP")
    check("wfp_layout", lambda: ctypes.sizeof(wfp.FILTER) == 200 and ctypes.sizeof(wfp.SESSION) == 72)
    check("webview", lambda: __import__("webview") and "pywebview 可用")
    check("terms", lambda: all((api.DOCS_DIR / n).exists() for n in ("DISCLAIMER.md", "PRIVACY.md", "LICENSE")))
    check("version", lambda: __import__("src.version", fromlist=["APP_VERSION"]).APP_VERSION)
    return results


def main(out_path: str) -> int:
    results = run()
    Path(out_path).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r["ok"] for r in results.values()) else 1
