"""問題回報（ADR-016）。

管道：GitHub Issues（公開、可追蹤）或 Email（給沒有 GitHub 帳號的人）。
App 只負責「整理內容、開啟頁面或郵件程式」，**不會自動送出**，也不持有任何 token；
使用者在瀏覽器／郵件程式確認後自己送出。

隱私：診斷資訊不含對外 IP、私鑰、使用者名稱路徑；只放版本、系統、連線狀態與最近的記錄。
"""

import os
import platform
import re
import urllib.parse

from src.version import APP_NAME, APP_VERSION, FEEDBACK_EMAIL, REPO_URL

KINDS = {"bug": "問題回報", "idea": "功能建議", "other": "其他意見"}
CHANNELS = ("github", "email")
MAX_TEXT = 4000
ISSUE_URL_LIMIT = 7000  # GitHub 預填網址太長會失敗；超過就截斷（完整內容另外提供複製）
MAIL_BODY_LIMIT = 1500  # mailto 網址太長時部分郵件程式會打不開

# 連線狀態中可以放進回報的欄位（刻意不含 ip）
SAFE_STATUS_KEYS = ("mode", "status", "country", "host", "loc", "message", "warning", "attempt", "protected")

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_KEY = re.compile(r"(?i)(privatekey|presharedkey|token|password)\s*[=:]\s*\S+")


def scrub(text: str) -> str:
    """遮蔽可能的個資：使用者資料夾路徑、IPv4 位址、金鑰類欄位。"""
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "%USERPROFILE%").replace(home.replace("\\", "/"), "%USERPROFILE%")
    text = _KEY.sub(lambda m: m.group(1) + " = ***", text)
    return _IPV4.sub("x.x.x.x", text)


def build_report(kind: str, text: str, diag: dict | None) -> tuple[str, str]:
    """回傳 (標題, 內文 Markdown)。diag 為 None 表示使用者不附診斷資訊。"""
    label = KINDS.get(kind, "意見回報")
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    first = (first[:50] + "…") if len(first) > 50 else (first or "（未填寫摘要）")
    title = f"[{label}] {first}"

    parts = ["### 說明", "", text.strip(), ""]
    if diag is not None:
        status = diag.get("status") or {}
        parts += ["### 診斷資訊", "",
                  f"- 版本：{APP_NAME} v{APP_VERSION}",
                  f"- 系統：{platform.platform()}",
                  f"- 研究模式：{diag.get('research_mode')}"]
        parts += [f"- 連線 {k}：{scrub(str(status.get(k)))}" for k in SAFE_STATUS_KEYS if k in status]
        lines = [scrub(line) for line in diag.get("log", [])][-40:]
        if lines:
            parts += ["", "<details><summary>最近的記錄（已遮蔽 IP 與路徑）</summary>", "", "```",
                      *lines, "```", "</details>"]
    return title, "\n".join(parts) + "\n"


def _shorten(body: str, fits) -> str:
    if fits(body):
        return body
    while body and not fits(body + "\n…（內容較長已截斷）"):
        body = body[: len(body) * 3 // 4]
    return body + "\n…（內容較長已截斷）"


def issue_url(title: str, body: str) -> str:
    q = lambda b: f"{REPO_URL}/issues/new?" + urllib.parse.urlencode({"title": title, "body": b})
    return q(_shorten(body, lambda b: len(q(b)) <= ISSUE_URL_LIMIT))


def mail_url(title: str, body: str) -> str:
    short = _shorten(body, lambda b: len(b) <= MAIL_BODY_LIMIT)
    return f"mailto:{FEEDBACK_EMAIL}?" + urllib.parse.urlencode(
        {"subject": title, "body": short}, quote_via=urllib.parse.quote)


def read_tail(path, n: int = 20) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []
