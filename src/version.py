"""版本與發佈資訊（ADR-016）。

APP_VERSION：發新版時改這裡；GitHub Actions 會檢查標籤 vX.Y.Z 必須等於它。
TERMS_VERSION：使用條款（DISCLAIMER.md）有實質修改時改這裡，使用者會被要求重新同意。
"""

APP_NAME = "AIXAI-VPN"
APP_VERSION = "1.0.1"
TERMS_VERSION = "2026-10-09.2"

# 公開發佈的 repo：程式內更新、回報都指向這裡
REPO_OWNER = "AIXAI-tools"
REPO_NAME = "AIXAI-VPN"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

# 給沒有 GitHub 帳號的使用者回報用（AIXAI 對外信箱）
FEEDBACK_EMAIL = "aixai19861201@gmail.com"
