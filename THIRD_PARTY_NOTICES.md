# 第三方元件授權聲明（Third-Party Notices）

`AIXAI-VPN.exe` 內含下列第三方元件。授權資訊取自各元件隨附的授權檔或套件中繼資料（2026-10-09 查證）。

| 元件 | 版本 | 授權 | 用途 |
|---|---|---|---|
| Tor（Tor Expert Bundle） | 15.0.24 bundle／tor 0.4.9.13 | BSD 3-Clause（完整條文含相依元件：`vendor/tor/docs/tor.txt`） | Tor 模式 |
| ├ OpenSSL | 隨 Tor | Apache License 2.0（`vendor/tor/docs/openssl.txt`） | Tor 加密 |
| ├ Libevent | 隨 Tor | BSD 3-Clause（`vendor/tor/docs/libevent.txt`） | Tor |
| └ zlib | 隨 Tor | zlib License（`vendor/tor/docs/zlib.txt`） | Tor |
| pywebview | 6.2.1 | BSD 3-Clause | App 視窗 |
| ├ Microsoft WebView2 SDK 執行元件 | 隨 pywebview | Microsoft 授權（可隨應用程式散布） | 顯示介面 |
| pythonnet | 3.2.1 | MIT | pywebview 在 Windows 的相依套件 |
| clr_loader | 0.3.1 | MIT | pythonnet 相依套件 |
| bottle | 0.13.4 | MIT | pywebview 相依套件 |
| proxy_tools | 0.1.0 | MIT | pywebview 相依套件 |
| typing_extensions | 4.16.0 | PSF-2.0 | pywebview 相依套件 |
| cffi | 2.1.1 | MIT-0 | clr_loader 相依套件 |
| pycparser | 3.1 | BSD-3-Clause | cffi 相依套件 |
| CPython 執行環境 | 3.14 | PSF License | 執行程式 |
| PyInstaller 啟動程式 | 6.22.3 | GPLv2+，附「可用於打包任何程式（含非 GPL）」的例外條款 | 打包 |

## 未打包、需使用者自行安裝的軟體
- **WireGuard for Windows**（VPNBook 選配）：由使用者從 https://www.wireguard.com/install/ 安裝，本程式只呼叫其官方指令列。

## 使用的外部服務（各自的使用條款由使用者遵守）
- VPN Gate（筑波大學學術專案）：https://www.vpngate.net/
- Tor 網路與 onionoo 公開資料：https://www.torproject.org/
- VPNBook（限個人使用）：https://www.vpnbook.com/
- Cloudflare trace（查詢對外 IP）：https://www.cloudflare.com/cdn-cgi/trace
