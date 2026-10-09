"""程式內更新／退版（ADR-016）：來源只有本專案的 GitHub Releases。

安全規則：
- 只看本 repo 的 Release；下載網址必須是 HTTPS 且主機在白名單內（GitHub 與其檔案伺服器）
- 執行檔必須列在同一個 Release 的 SHA256SUMS.txt 且雜湊相符，否則什麼都不換
- 執行中的 exe 先改名成 .old（Windows 允許改名執行中的檔案），驗證過的新檔接手原本檔名，
  捷徑照樣能用；任何一步失敗就把原檔改回來
"""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from src.version import APP_NAME, APP_VERSION, REPO_NAME, REPO_OWNER

API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases?per_page=30"
CHECKSUM_ASSET = "SHA256SUMS.txt"
EXE_SUFFIX = "_Windows_x64.exe"
ALLOWED_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
MAX_EXE_BYTES = 200 * 1024 * 1024
TIMEOUT = 30


class UpdateError(Exception):
    """要顯示給使用者的更新錯誤（訊息為中文）。"""


def _check_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"不允許的下載來源：{u.hostname}")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 的下載會轉址到檔案伺服器；每次轉址都要再檢查一次主機。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect())


def _open(url: str, accept: str = "*/*"):
    req = urllib.request.Request(_check_url(url), headers={
        "User-Agent": f"{APP_NAME}/{APP_VERSION}", "Accept": accept})
    return _opener.open(req, timeout=TIMEOUT)


def fetch_releases(opener=None) -> list[dict]:
    try:
        with (opener or _open)(API_URL, "application/vnd.github+json") as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError("GitHub 暫時限制查詢次數，請約一小時後再試") from exc
        raise UpdateError(f"查詢版本失敗（HTTP {exc.code}）") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError(f"查詢版本失敗：{exc}") from exc
    if not isinstance(data, list):
        raise UpdateError("版本資料格式不正確")
    return data


def version_tuple(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def _find_asset(release: dict, match) -> dict | None:
    return next((a for a in release.get("assets", []) if match(a.get("name", ""))), None)


def summarize(releases: list[dict], current: str = APP_VERSION) -> dict:
    """整理給介面顯示：新到舊排序；標出目前版本、較新版本、可否安裝。"""
    cur = version_tuple(current)
    items = []
    for r in releases:
        ver = version_tuple(r.get("tag_name", ""))
        if r.get("draft") or ver is None:
            continue
        installable = bool(_find_asset(r, lambda n: n.endswith(EXE_SUFFIX))
                           and _find_asset(r, lambda n: n == CHECKSUM_ASSET))
        items.append({
            "tag": r["tag_name"],
            "version": ".".join(map(str, ver)),
            "beta": bool(r.get("prerelease")),
            "published": (r.get("published_at") or "")[:10],
            "notes": (r.get("body") or "")[:1500],
            "current": ver == cur,
            "newer": cur is not None and ver > cur,
            "installable": installable,
            "url": r.get("html_url", ""),
        })
    items.sort(key=lambda i: version_tuple(i["version"]), reverse=True)
    stable = [i for i in items if not i["beta"]]
    latest = stable[0]["version"] if stable else None
    return {"current": current, "latest": latest,
            "update_available": bool(stable and stable[0]["newer"]), "items": items}


def parse_sums(text: str, name: str) -> str:
    """SHA256SUMS.txt 每行「<sha256>  <檔名>」（檔名前可有 * 代表二進位模式）。"""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError(f"校驗檔中沒有 {name}，基於安全不安裝")


def download(url: str, dest: Path, size: int, progress, opener=None) -> str:
    """下載到 dest，回傳 SHA256。超過上限或大小不符就中止。"""
    h = hashlib.sha256()
    done = 0
    with (opener or _open)(url) as r, dest.open("wb") as f:
        while chunk := r.read(256 * 1024):
            done += len(chunk)
            if done > MAX_EXE_BYTES:
                raise UpdateError("檔案大小異常，已取消")
            h.update(chunk)
            f.write(chunk)
            if size:
                progress(min(99, done * 100 // size))
    if size and done != size:
        raise UpdateError("下載不完整，已取消")
    return h.hexdigest()


def install(tag: str, exe_path: Path, progress=lambda pct: None, releases=None, opener=None) -> None:
    """下載指定版本並替換 exe_path。成功後由呼叫端重新啟動程式。"""
    rels = releases if releases is not None else fetch_releases(opener)
    rel = next((r for r in rels if r.get("tag_name") == tag and not r.get("draft")), None)
    if rel is None:
        raise UpdateError(f"找不到版本 {tag}")
    exe = _find_asset(rel, lambda n: n.endswith(EXE_SUFFIX))
    sums = _find_asset(rel, lambda n: n == CHECKSUM_ASSET)
    if exe is None:
        raise UpdateError(f"版本 {tag} 沒有 Windows 執行檔")
    if sums is None:
        raise UpdateError(f"版本 {tag} 沒有 SHA256SUMS.txt，基於安全不安裝")
    try:
        with (opener or _open)(sums["browser_download_url"]) as r:
            want = parse_sums(r.read(64 * 1024).decode("utf-8", "replace"), exe["name"])
    except OSError as exc:
        raise UpdateError(f"無法下載校驗檔：{exc}") from exc

    new_path = exe_path.with_name(exe_path.name + ".new")
    old_path = exe_path.with_name(exe_path.name + ".old")
    try:
        got = download(exe["browser_download_url"], new_path, int(exe.get("size") or 0), progress, opener)
    except OSError as exc:
        new_path.unlink(missing_ok=True)
        raise UpdateError(f"下載失敗（若防毒軟體攔截，可改到發佈頁手動下載）：{exc}") from exc
    except UpdateError:
        new_path.unlink(missing_ok=True)
        raise
    if got != want:
        new_path.unlink(missing_ok=True)
        raise UpdateError("SHA256 不符，檔案可能損毀或遭竄改，已取消更新")

    old_path.unlink(missing_ok=True)
    try:
        exe_path.rename(old_path)
    except OSError as exc:
        new_path.unlink(missing_ok=True)
        raise UpdateError(f"無法替換執行檔：{exc}。可改到發佈頁手動下載") from exc
    try:
        new_path.rename(exe_path)
    except OSError as exc:
        old_path.rename(exe_path)
        raise UpdateError(f"替換失敗，已還原原本版本：{exc}") from exc
    progress(100)


def cleanup_old(exe_path: Path) -> None:
    """新版啟動後刪掉上一版留下的 .old／.new（只刪本程式自己產生的這兩個檔）。"""
    for suffix in (".old", ".new"):
        try:
            exe_path.with_name(exe_path.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass  # 舊程序可能還沒完全結束；下次啟動再刪
