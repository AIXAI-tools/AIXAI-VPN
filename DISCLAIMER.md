# 免責聲明與使用條款（Disclaimer & Terms of Use）

版本：2026-10-09（v1）

使用 AIXAI-VPN（以下稱「本工具」）即表示你已閱讀、理解並同意以下全部內容。
若你不同意，或所在地法律不允許你依下列方式使用本工具，請立即停止使用並刪除本工具。

## 1. 用途

1. 本工具是學習用的開源 VPN 用戶端，用來保護連線隱私（加密從你電腦送出的流量），以及在**法律允許的範圍內**以其他國家的連線位置存取網路。
2. 你必須遵守所在地與連線目的地的法律。部分國家或地區限制或禁止使用 VPN 或 Tor；是否可以使用，由你自行確認並負責。
3. **嚴禁**將本工具用於：
   - 任何違法行為，包括詐騙、未經授權存取他人系統、散布惡意程式、侵害著作權或他人權利；
   - 攻擊、掃描、濫發訊息（spam）或其他會傷害網路、伺服器或他人的行為；
   - 讓免費服務承受不合理的負擔（例如長時間大量下載），或違反各服務的使用規範。

## 2. 第三方服務

本工具本身**沒有任何 VPN 伺服器**，只是協助你連到下列由第三方提供的免費服務。各服務有自己的使用條款與隱私政策，你須自行閱讀並遵守：

- **VPN Gate**：日本筑波大學的學術研究專案，伺服器由志願者提供。VPN Gate 會保存連線紀錄，並可能依法提供給有關機關；伺服器營運者也可能看到未加密的流量。
- **Tor**：由志願者運作的匿名網路。出口節點可以看到未加密的流量。
- **VPNBook**（選配）：限個人使用，設定檔由你本人在 VPNBook 網站同意條款並通過驗證後取得。

作者不控制、也不擔保上述服務的可用性、速度、安全性或紀錄政策。**請只瀏覽 HTTPS 網站**，不要透過免費 VPN 傳送敏感資料。

## 3. 網站條款與研究模式

1. 部分網站（例如串流平台）的條款禁止使用 VPN，或依連線位置限制內容。使用本工具存取這類網站，可能違反其條款，帳號可能被限制或停權，**風險由你自行承擔**。
2. 「研究模式」只是讓 VPN 斷線時維持網路暫停並自動重試；本工具**不會**、也不應被修改為規避網站的 VPN 偵測、付費機制或其他存取控制。

## 4. 本工具對你電腦做的變更

為了避免 VPN 斷線時外洩真實 IP，本工具會在執行期間：建立暫時的防火牆規則（Windows Filtering Platform 動態規則，程式結束即自動消失）、在 hosts 檔加入標記為 `# AIXAI-VPN` 的行、建立 VPN 連線設定，以及在 Tor 模式暫時修改系統代理。
程式正常結束時會還原；若網路異常，可執行 `AIXAI-VPN.exe --restore` 一鍵還原。

## 5. 無擔保與責任限制

本工具依「現狀」（AS IS）提供，不附任何明示或默示之擔保，包括但不限於適售性、特定目的適用性、正確性、連線可用性、匿名性及不侵權。
在法律允許之最大範圍內，作者及貢獻者對因使用或無法使用本工具所生之任何直接、間接、附帶、特殊或衍生性損害（包括資料外洩、帳號停權、連線中斷），均不負責任。
詳見 [LICENSE](LICENSE)（MIT 授權）。

## 6. 無關聯聲明

本工具與 VPN Gate／筑波大學、The Tor Project、VPNBook、WireGuard 或任何網站均無關聯，亦未獲其授權或背書；所有商標屬其各自所有人。

## 7. 聯絡

問題回報、權利人通知：請透過本專案的 GitHub Issues 或程式內「回報問題」提供的信箱與我們聯繫。

## 8. 條款變更

本條款可能隨版本更新而修改；修改後的條款於新版本中生效。若新版本的條款有變更，程式會再次請你確認。

---

*English summary:* AIXAI-VPN is an open-source, educational VPN client that connects you to third-party free services
(VPN Gate, Tor, optionally VPNBook); it operates no servers of its own. Obey the laws where you are and the terms of each
service; do not use it for illegal activity, attacks or abuse of volunteer servers. Some websites forbid VPNs — accessing
them is at your own risk, and this tool does not evade VPN detection. Free VPN operators may log or see unencrypted
traffic: use HTTPS. Provided "AS IS" without warranty; to the maximum extent permitted by law the authors are not liable
for any damages. Not affiliated with or endorsed by any of the services named above.
