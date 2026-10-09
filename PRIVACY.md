# 隱私權政策（Privacy Policy）

AIXAI-VPN **不收集、不上傳任何使用者資料**，沒有分析、追蹤或廣告功能。本專案沒有自己的伺服器。

## 程式會連線的地方

| 時機 | 連線對象 | 傳送的內容 |
|---|---|---|
| 每次啟動（可在「關於」關閉）、按「檢查更新」 | GitHub（`api.github.com`） | 一般 HTTPS 請求（含程式版本的 User-Agent），查詢是否有新版本 |
| 你選擇安裝某個版本 | GitHub Releases | 下載該版本的執行檔與校驗檔 |
| 按「搜尋伺服器」 | VPN Gate 公開清單（`www.vpngate.net`）、清單上的伺服器、Tor 公開資料（`onionoo.torproject.org`） | 下載伺服器清單；對各伺服器做一次加密連線測試以量延遲；查詢各國 Tor 出口節點數 |
| 連線前後 | Cloudflare（`www.cloudflare.com/cdn-cgi/trace`） | 查詢目前對外 IP 與國家，確認 VPN 是否生效 |
| 使用 VPN | 你選擇的 VPN Gate 伺服器、Tor 網路或 VPNBook 伺服器 | 你的網路流量（經加密送到該服務；離開該服務後的去向由你瀏覽的網站決定） |
| 你按「取得 VPNBook 設定檔」 | VPNBook 網站（以 Edge 開啟） | 與你自己用瀏覽器開啟相同 |
| 你按「回報問題」並選擇送出方式 | GitHub Issues 或你的郵件程式 | 只有你確認後的內容；程式只負責開啟頁面或郵件程式，不會自動送出。診斷資訊會遮蔽 IP 位址與使用者資料夾路徑。**GitHub Issues 是公開的**，任何人都看得到；用 Email 回報時，我們會看到你的 Email 地址（只用於回覆該問題） |

## 存在你電腦上的資料

全部位於 `%LOCALAPPDATA%\AIXAI-VPN\`，程式不會上傳：

- 設定（研究模式、已同意的條款版本、是否自動檢查更新）
- VPN Gate 伺服器快取（6 小時）
- VPNBook 設定檔（**含 WireGuard 私鑰，以明文儲存**；7 天到期）與事件紀錄
- 程式視窗與 VPNBook 頁面專用的瀏覽器資料
- Tor 模式時備份的原本系統代理設定（結束時還原）

## 第三方服務

VPN Gate、Tor、VPNBook、GitHub、Cloudflare 各自有其隱私權政策，本程式無法控制。
特別是 **VPN Gate 會保存連線紀錄至少 3 個月**（含來源 IP、目的主機與 port），並可依法提供給有關機關；免費 VPN 營運者與 Tor 出口節點可能看到未加密的流量，請只瀏覽 HTTPS 網站。

---

**English summary:** AIXAI-VPN collects no user data and has no telemetry or servers of its own. It connects to GitHub
(update check at startup — can be turned off), VPN Gate / onionoo (server lists and latency probes), Cloudflare (to
check your public IP), the VPN service you choose, and — only when you send feedback — GitHub Issues or your own mail
client, with IPs and user paths masked. Local data (settings, cache, VPNBook configs including the WireGuard private
key in plain text) stays in `%LOCALAPPDATA%\AIXAI-VPN\`. Third-party services have their own policies; VPN Gate keeps
connection logs.
