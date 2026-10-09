"""打包成 dist/AIXAI-VPN.exe（ADR-008、TASK-008）。

前置（只需一次）：
  python -m venv .venv
  .venv\\Scripts\\python -m pip install -r requirements-build.txt
  python tools/fetch_tor.py          （下載並驗證 Tor）
執行：
  .venv\\Scripts\\python tools/build_exe.py

打包內容：程式碼、介面（src/ui）、Tor 本體與 GeoIP、本專案 LICENSE／DISCLAIMER／PRIVACY、Tor 及其元件的授權文件。
exe 的「內容」頁會顯示 src/version.py 的版本號。
不打包 Tor 的 pluggable_transports（用不到）。
暫存檔在 %LOCALAPPDATA%\AIXAI-VPN\build-cache（OneDrive 外）；dist/ 已列入 .gitignore。
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 暫存資料夾放在 OneDrive 外：OneDrive 同步時會鎖住檔案，導致 PyInstaller 無法覆寫
CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "build-cache"
TOR = ROOT / "vendor" / "tor"
sys.path.insert(0, str(ROOT))
from src.version import APP_NAME, APP_VERSION  # noqa: E402

# Windows 檔案內容中的版本資訊（PyInstaller --version-file 格式）
VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040404B0', [
      StringStruct('CompanyName', 'AIXAI'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 AIXAI. MIT License.'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x0404, 1200])])])
"""


def main() -> int:
    if not (TOR / "tor" / "tor.exe").exists():
        print("找不到 vendor/tor，請先執行 python tools/fetch_tor.py")
        return 1
    sep = ";"  # Windows 的 --add-data 分隔符號
    datas = [
        (ROOT / "src" / "ui", "src/ui"),
        (TOR / "tor" / "tor.exe", "vendor/tor/tor"),
        (TOR / "data", "vendor/tor/data"),
        (TOR / "docs", "vendor/tor/docs"),
        (TOR / "VERSION", "vendor/tor"),
        (ROOT / "assets" / "AIXAI-VPN.ico", "assets"),
        (ROOT / "LICENSE", "."),
        (ROOT / "DISCLAIMER.md", "."),
        (ROOT / "PRIVACY.md", "."),
        (ROOT / "THIRD_PARTY_NOTICES.md", "."),
    ]
    CACHE.mkdir(parents=True, exist_ok=True)
    version_file = CACHE / "version_info.txt"
    version_file.write_text(VERSION_INFO.format(v=APP_VERSION.replace(".", ", "), ver=APP_VERSION, name=APP_NAME),
                            encoding="utf-8")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",  # 沒有主控台視窗
        "--name", "AIXAI-VPN",
        "--paths", str(ROOT),
        "--collect-submodules", "src",
        "--hidden-import", "webview",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(CACHE / "work"),
        "--specpath", str(CACHE),
        "--version-file", str(version_file),
        "--icon", str(ROOT / "assets" / "AIXAI-VPN.ico"),
    ]
    for src, dest in datas:
        args += ["--add-data", f"{src}{sep}{dest}"]
    args.append(str(ROOT / "src" / "app.py"))
    return subprocess.run(args, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
