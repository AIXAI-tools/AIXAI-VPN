<p align="center"><img src="assets/APP_ICON.png" alt="AIXAI-VPN" width="180"></p>

# AIXAI-VPN

讓 Windows 電腦依需求切換成不同國家連線的 VPN 用戶端。免費、以學習為目的開發，嚴格遵守各服務商規範。

> 非駭客用途。不提供、也不會加入任何躲避網站 VPN 偵測的功能。

## 功能
| 模式 | 註冊 | 安裝 | 說明 |
|---|---|---|---|
| **VPN Gate** | 免 | 免（Windows 內建 SSTP） | 筑波大學學術專案的志願者伺服器；搜尋時逐台實測，只列出確定能連的伺服器 |
| **Tor** | 免 | 免（已內含 Tor） | 指定出口國家；只對套用 Windows Proxy 設定的程式（主要是瀏覽器）有效，速度較慢 |
| **VPNBook**（選配） | 免 | 需安裝 [WireGuard](https://www.wireguard.com/install/) | 半自動取得設定檔：使用者本人勾選同意並通過真人驗證，其餘自動；設定檔 7 天到期；限個人使用 |

- **斷線保護**：連線後自動開啟（Windows Filtering Platform 動態規則）。VPN 意外斷線時網路暫停、不外洩，並自動重連；App 結束或當掉時自動解除
- **研究模式**：網路暫停時持續自動重試（開啟前會顯示風險說明）
- **版本更新／退版**：「關於」視窗列出所有版本，一鍵更新或退回舊版；只安裝本專案 GitHub Releases 中、SHA256 核對通過的執行檔
- **回報問題**：自動整理內容（可附診斷資訊，IP 與使用者路徑會遮蔽），開啟 GitHub Issues 或郵件程式，由你確認後送出
- 本機介面只聽 127.0.0.1，並以隨機 token、Host／Origin 檢查保護

## 系統需求
- Windows 10／11（64 位元）
- 系統管理員權限（斷線保護需要；啟動時會跳出 UAC）
- 執行 exe 不需要安裝 Python

## 下載與使用
- 從 [Releases](https://github.com/AIXAI-tools/AIXAI-VPN/releases) 下載 `AIXAI-VPN_vX_Y_Z_Windows_x64.exe` 後直接執行
  - 執行檔由 GitHub Actions 從本 repo 原始碼編譯（見 `.github/workflows/build.yml`），可用同一個 Release 的 `SHA256SUMS.txt` 核對
  - 本程式沒有數位簽章，首次執行可能出現 SmartScreen「Windows 已保護您的電腦」，請自行判斷是否「仍要執行」
- 第一次啟動須同意[使用條款](DISCLAIMER.md)
- 詳細步驟：[docs/USER-GUIDE.md](docs/USER-GUIDE.md)
- 網路異常時一鍵還原：`AIXAI-VPN.exe --restore`
- 問題回報：程式右上角 ⓘ →「回報問題」，或直接開 [Issues](https://github.com/AIXAI-tools/AIXAI-VPN/issues)

## 從原始碼執行／打包
```
python -m src.app                      # 開發執行（Python 3.14，只用標準函式庫）
python -m unittest                     # 單元測試
python tools/fetch_tor.py              # 下載並以 gpg 驗證官方 Tor
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python tools/build_exe.py   # 產生 dist/AIXAI-VPN.exe
```

## 隱私與條款
- 不收集任何使用者資料；個人資料只存在本機 `%LOCALAPPDATA%\AIXAI-VPN\`。詳見 [PRIVACY.md](PRIVACY.md)
- 各服務的紀錄政策不同（例如 VPN Gate 會保存連線紀錄），請只瀏覽 HTTPS 網站
- 使用條款與免責聲明：[DISCLAIMER.md](DISCLAIMER.md)
- 安全性漏洞請私下回報：[SECURITY.md](SECURITY.md)
- 版本紀錄：[CHANGELOG.md](CHANGELOG.md)

## 授權
- 本專案：[MIT License](LICENSE)，Copyright (c) 2026 AIXAI
- 第三方元件：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 本專案與 VPN Gate、The Tor Project、VPNBook、WireGuard 均無關聯。「Tor」為 The Tor Project, Inc. 的商標；「WireGuard」為 Jason A. Donenfeld 的註冊商標
