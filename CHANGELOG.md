# 版本紀錄（Changelog）

## v1.0.0 — 2026-10-09
首次公開版本。
- 三種連線模式：VPN Gate（免註冊、免安裝，搜尋時逐台實測只列可連伺服器）、Tor（內建，指定出口國家）、VPNBook（選配，需 WireGuard，半自動取得設定檔）
- 斷線保護：Windows Filtering Platform 動態規則，VPN 斷線時網路暫停不外洩、自動重連；程式結束或當掉時自動解除
- 研究模式：網路暫停時持續自動重試
- 程式內版本更新／退版（GitHub Releases＋SHA256 核對）
- 問題回報（GitHub Issues 或 Email，由使用者確認後送出）
- 首次啟動同意使用條款
- 一鍵還原網路：`AIXAI-VPN.exe --restore`
