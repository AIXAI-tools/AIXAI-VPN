"""用使用者平常的瀏覽器／郵件程式開啟網址。

App 以系統管理員身分執行；直接啟動瀏覽器會讓瀏覽器也變成管理員權限。
交給 explorer.exe 開啟，會由使用者原本（一般權限）的桌面程序接手。
只允許本專案的 GitHub 頁面與 mailto，避免被拿來開任意程式或網址。
"""

import subprocess

from src.version import FEEDBACK_EMAIL, REPO_URL

ALLOWED_PREFIXES = (REPO_URL + "/", f"mailto:{FEEDBACK_EMAIL}?")


def allowed(url: str) -> bool:
    return url.startswith(ALLOWED_PREFIXES) and not any(c in url for c in '"\r\n')


def open_url(url: str) -> bool:
    if not allowed(url):
        return False
    try:
        subprocess.Popen(["explorer.exe", url])
        return True
    except OSError:
        return False
