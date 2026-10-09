"""開發／打包用：下載官方 Tor Expert Bundle，驗證數位簽章後解壓到 vendor/tor/（ADR-011）。

執行：python tools/fetch_tor.py
- 版本：讀 Tor Project 官方的版本資訊
- 簽章：Tor Browser Developers 金鑰（指紋見下方，來源 support.torproject.org/tbb/how-to-verify-signature/）
- 簽章驗證失敗 → 不解壓、直接結束
vendor/ 已列入 .gitignore，不會進 repo。
"""

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "vendor" / "tor"
VERSION_URL = "https://aus1.torproject.org/torbrowser/update_3/release/downloads.json"
DIST = "https://dist.torproject.org/torbrowser/{v}/tor-expert-bundle-windows-x86_64-{v}.tar.gz"
SIGNING_KEY = "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290"


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "AIXAI-VPN/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r, path.open("wb") as f:
        shutil.copyfileobj(r, f)


def gpg_path(p: Path) -> str:
    """Git for Windows 內附的 gpg 是 MSYS 程式，要用 /c/路徑/... 這種格式。"""
    s = str(p.resolve()).replace("\\", "/")
    return f"/{s[0].lower()}{s[2:]}" if len(s) > 1 and s[1] == ":" else s


def verify(archive: Path, sig: Path, gnupg_home: Path) -> bool:
    gpg = shutil.which("gpg")
    if not gpg:
        print("找不到 gpg，無法驗證簽章（Git for Windows 內附 gpg）。")
        return False
    env_args = ["--homedir", gpg_path(gnupg_home)]
    subprocess.run([gpg, *env_args, "--auto-key-locate", "nodefault,wkd", "--locate-keys", "torbrowser@torproject.org"],
                   capture_output=True)
    r = subprocess.run([gpg, *env_args, "--status-fd", "1", "--verify", gpg_path(sig), gpg_path(archive)],
                       capture_output=True, text=True)
    # 必須是「有效簽章」且簽署金鑰正是 Tor Browser Developers 的主金鑰
    ok = any(line.startswith("[GNUPG:] VALIDSIG") and line.split()[-1] == SIGNING_KEY for line in r.stdout.splitlines())
    print(r.stderr.strip())
    return ok


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with urllib.request.urlopen(VERSION_URL, timeout=30) as r:
        version = json.load(r)["version"]
    url = DIST.format(v=version)
    print(f"Tor Expert Bundle {version}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive, sig = tmp / "tor.tar.gz", tmp / "tor.tar.gz.asc"
        download(url, archive)
        download(url + ".asc", sig)
        (tmp / "gnupg").mkdir()
        if not verify(archive, sig, tmp / "gnupg"):
            print("簽章驗證失敗，已中止（沒有解壓任何檔案）。")
            sys.exit(1)
        print("簽章驗證通過。")
        DEST.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(DEST, filter="data")  # filter="data"：擋掉路徑穿越等危險項目
    (DEST / "VERSION").write_text(version, encoding="utf-8")
    print(f"已解壓到 {DEST}")


if __name__ == "__main__":
    main()
