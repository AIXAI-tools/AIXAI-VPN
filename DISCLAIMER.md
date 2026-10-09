# 免責聲明與使用條款（Disclaimer & Terms of Use）

版本：2026-10-09.2（v2）

使用 AIXAI-VPN（以下稱「本工具」）即表示你已閱讀、理解並同意以下全部內容。
若你不同意，或所在地法律不允許你依下列方式使用本工具，請立即停止使用並刪除本工具。

## 1. 本工具是什麼

1. 本工具是**學習用途的開源 VPN 用戶端**，協助你連到第三方提供的免費服務，以加密從你電腦送出的流量，並在**法律允許的範圍內**以其他國家的連線位置存取網路。
2. 本工具**本身沒有任何 VPN 伺服器**，不提供、不經營、不轉售任何網路連線服務。
3. 本專案**不以營利為目的**：不收費、不含廣告、不販售任何功能，也不收集使用者資料（見 [PRIVACY.md](PRIVACY.md)）。

## 2. 使用資格與法律遵循

1. 你必須遵守**所在地與連線目的地**的法律。部分國家或地區限制或禁止使用 VPN、Tor 或加密通訊；是否可以合法使用，由你自行確認並負責。
2. 未成年人應在法定代理人同意與指導下使用。
3. 若你所在地的法律、你的雇主或學校規定禁止使用 VPN，請勿使用本工具。

## 3. 禁止的使用方式

**嚴禁**將本工具用於：
1. 任何違法行為，包括但不限於詐騙、洗錢、恐嚇、散布兒童性剝削內容、販售違禁品、侵害著作權或他人權利；
2. 未經授權存取他人電腦、帳號或網路，攻擊、掃描、阻斷服務、散布惡意程式、濫發訊息（spam）；
3. 規避、破解或移除任何網站的付費機制、數位權利管理（DRM）、存取控制或 VPN 偵測；
4. 讓免費服務承受不合理的負擔（例如長時間大量下載、P2P 分享），或違反各服務的使用規範；
5. 以本工具或其中的第三方服務從事商業用途（VPNBook 限個人使用）。

志願者營運的免費服務是許多人共用的資源。濫用可能導致服務關閉，並可能使你承擔法律責任。

## 4. 第三方服務

本工具連到下列由第三方提供的服務。各服務有自己的條款與隱私政策，你須自行閱讀並遵守；作者**不控制、也不擔保**其可用性、速度、安全性或紀錄政策：

- **VPN Gate**（日本筑波大學的學術研究專案，伺服器由志願者提供）：依其公開說明，會保存連線紀錄**至少 3 個月**（含來源 IP、目的主機名稱／IP 與 port、時間等），並可依法提供給警察、檢察官、律師或法院；各志願者伺服器另會保存封包標頭；未加密的 HTTP 請求會被加入 VPN 工作階段識別碼。詳見 https://www.vpngate.net/en/about_abuse.aspx
- **Tor**（志願者運作的匿名網路）：出口節點可以看到未加密的流量；Tor 不會讓你在已登入的網站上匿名。
- **VPNBook**（選配）：限個人使用；設定檔由你本人在 VPNBook 網站同意其條款並通過真人驗證後取得，本工具不代為同意、不模擬點擊、不繞過驗證。
- **WireGuard**（選配，由你自行安裝）、**GitHub**（版本更新與回報）、**Cloudflare**（查詢對外 IP）。

## 5. 安全與匿名性的限制

1. **免費 VPN 不等於匿名**。服務營運者、志願者伺服器與 Tor 出口節點可能看到或記錄你的流量；你登入的網站仍可辨識你的帳號、Cookie 與瀏覽器特徵。
2. **請只瀏覽 HTTPS 網站**，不要透過免費 VPN 傳送密碼、金融、醫療或其他敏感資料。
3. 「斷線保護」可降低 VPN 斷線時外洩真實 IP 的風險，但無法保證在所有情況下（例如作業系統更新、其他安全軟體、硬體或驅動程式問題）都能完全防止。
4. Tor 模式只對會套用 Windows Proxy 設定的程式有效。
5. 本工具不是專業的資安、法律或隱私保護服務；有高度隱私或安全需求者，請尋求專業協助。

## 6. 網站條款與研究模式

1. 部分網站（例如串流平台）的條款禁止使用 VPN，或依連線位置限制內容。使用本工具存取這類網站，可能違反其條款，帳號可能被限制或停權，**風險由你自行承擔**。
2. 「研究模式」只是讓 VPN 斷線時維持網路暫停並自動重試；本工具**不會**、也不應被修改為規避網站的 VPN 偵測、付費機制或其他存取控制。

## 7. 本工具對你電腦做的變更

為了避免 VPN 斷線時外洩真實 IP，本工具需要系統管理員權限，並在執行期間：
- 建立暫時的防火牆規則（Windows Filtering Platform 動態規則，程式結束即自動消失）；
- 在 hosts 檔加入標記為 `# AIXAI-VPN` 的行；
- 建立名為 `AIXAI-VPN-SSTP` 的 Windows VPN 連線設定；
- Tor 模式時暫時修改系統代理；VPNBook 模式時暫時建立 WireGuard 通道。

程式正常結束時會還原；若網路異常，可執行 `AIXAI-VPN.exe --restore` 一鍵還原。使用前建議確認你有權限變更這台電腦的網路設定（例如公司或學校的電腦）。

## 8. 程式更新

程式內更新只會下載本專案 GitHub Releases 中、SHA256 核對相符的執行檔。執行檔未經數位簽章，防毒軟體或 SmartScreen 可能顯示警告；請只從本專案的 Releases 頁取得本工具。

## 9. 無擔保

本工具依「現狀」（AS IS）及「現有」（AS AVAILABLE）提供，不附任何明示或默示之擔保，包括但不限於適售性、特定目的適用性、正確性、連線可用性、速度、匿名性、安全性及不侵權。

## 10. 責任限制

在法律允許之最大範圍內，作者及貢獻者對因使用或無法使用本工具所生之任何直接、間接、附帶、特殊、懲罰性或衍生性損害，均不負責任，包括但不限於：資料外洩或遺失、真實 IP 暴露、帳號被限制或停權、連線中斷、裝置或網路設定異常、第三方服務的行為，以及因違反法律或第三方條款所生之責任。詳見 [LICENSE](LICENSE)（MIT 授權）。

## 11. 使用者責任與賠償

1. 你因使用本工具所為之一切行為及其法律責任，概由你自行承擔。
2. 若因你違反本條款、法律或第三方服務條款，而使作者或貢獻者遭受第三人請求，你同意負責處理並賠償其因此所受之損失（於法律允許之範圍內）。

## 12. 無關聯與商標

本工具與 VPN Gate／筑波大學、SoftEther、The Tor Project、VPNBook、WireGuard、Cloudflare、GitHub 或任何網站均無關聯，亦未獲其授權或背書。
「Tor」為 The Tor Project, Inc. 的商標；「WireGuard」為 Jason A. Donenfeld 的註冊商標；其他名稱與商標屬其各自所有人，本文件僅為說明相容性而提及。

## 13. 聯絡與權利人通知

一般問題請透過本專案的 GitHub Issues 或程式內「回報問題」。安全性漏洞請勿公開，改依 [SECURITY.md](SECURITY.md) 以 Email 回報。
權利人若認為本專案的原始碼或文件侵害其權利，請提供足以辨識的資訊與我們聯繫，我們會儘速審查並採取適當處理（包括移除相關內容）。

## 14. 其他

1. 本條款任何部分若經認定無效或無法執行，不影響其他部分之效力。
2. 本條款可能隨版本更新而修改，修改後的條款於新版本中生效；若條款有變更，程式會再次請你確認。繼續使用新版本即表示你同意修改後的條款。

---

*English summary:* AIXAI-VPN is a non-commercial, open-source, educational VPN client. It operates no servers; it only
connects you to third-party free services (VPN Gate, Tor, optionally VPNBook), each with its own terms and logging
policies — VPN Gate keeps connection logs (source IP, destinations) for at least three months and may disclose them to
authorities. Obey the laws where you are and the terms of each service. Do not use it for illegal activity, attacks,
circumventing paywalls/DRM/access controls or VPN detection, abuse of volunteer servers, or commercial purposes.
Free VPNs are not anonymity tools: use HTTPS only. The kill switch reduces but cannot fully eliminate leak risks.
Provided "AS IS" and "AS AVAILABLE" without warranty; to the maximum extent permitted by law the authors are not
liable for any damages, and you agree to indemnify them for claims arising from your misuse. Not affiliated with or
endorsed by any service named above. Tor is a trademark of The Tor Project, Inc.; WireGuard is a registered trademark
of Jason A. Donenfeld.
