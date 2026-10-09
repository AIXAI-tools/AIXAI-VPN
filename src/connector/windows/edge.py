"""開啟 Edge App 模式小視窗，以及關閉指定設定檔的 Edge 視窗。"""

import os
import subprocess
from pathlib import Path

EDGE_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_edge() -> Path | None:
    return next((p for p in EDGE_CANDIDATES if p.exists()), None)


def open_app_window(url: str, profile_dir: Path, size: tuple[int, int]) -> bool:
    edge = find_edge()
    if edge is None:
        return False
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={profile_dir}",
                      f"--window-size={size[0]},{size[1]}", "--no-first-run", "--no-default-browser-check"])
    return True


def close_profile_windows(profile_dir: Path) -> None:
    """關閉使用指定設定檔資料夾的 Edge（只影響這個專用設定檔，不動使用者平常的 Edge）。"""
    marker = str(profile_dir).replace("'", "''")
    script = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   capture_output=True, timeout=30, creationflags=NO_WINDOW)
