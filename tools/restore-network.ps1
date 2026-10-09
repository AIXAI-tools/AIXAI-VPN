<#
  AIXAI-VPN 一鍵還原網路（最後手段；ADR-012、ADR-013、ADR-014）
  只移除 AIXAI-VPN 自己建立的東西：
    1. 中斷 VPN Gate 連線（AIXAI-VPN-SSTP）
    2. 移除舊版防火牆群組 AIXAI-VPN 的規則（WFP 動態規則會隨程式結束自動消失，不需處理）
    3. 移除 hosts 檔案中結尾為 "# AIXAI-VPN" 的行
    4. 還原 Tor 模式改過的系統代理（有啟用中的備份才還原）
    5. 移除 VPNBook 的 WireGuard 通道（AIXAI-VPNBook）
  加上 -RemoveProfile 會一併移除 VPN Gate 的 VPN 設定。
  需要系統管理員權限；不是的話會自動要求提權。
#>
param([switch]$RemoveProfile, [switch]$NoPause)

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($RemoveProfile) { $argList += '-RemoveProfile' }
    if ($NoPause) { $argList += '-NoPause' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit
}

$ok = $true
Write-Host "AIXAI-VPN 還原網路..." -ForegroundColor Cyan

# 1. 中斷 VPN Gate
rasdial AIXAI-VPN-SSTP /disconnect | Out-Null
Write-Host "  [1/5] 已中斷 VPN Gate 連線（若原本有連線）"

# 2. 舊版防火牆規則
Remove-NetFirewallRule -Group 'AIXAI-VPN' -ErrorAction SilentlyContinue
$left = @(Get-NetFirewallRule -Group 'AIXAI-VPN' -ErrorAction SilentlyContinue).Count
if ($left -eq 0) { Write-Host "  [2/5] 防火牆規則已清除" } else { Write-Host "  [2/5] 仍有 $left 條規則未清除！" -ForegroundColor Red; $ok = $false }

# 3. hosts 標記行（只移除結尾為 "# AIXAI-VPN" 的行）
$hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$lines = [System.IO.File]::ReadAllLines($hosts)
$kept = @($lines | Where-Object { -not $_.TrimEnd().EndsWith('# AIXAI-VPN') })
if ($kept.Count -ne $lines.Count) {
    [System.IO.File]::WriteAllLines($hosts, [string[]]$kept)
    Write-Host "  [3/5] hosts 已移除 $($lines.Count - $kept.Count) 行"
} else {
    Write-Host "  [3/5] hosts 沒有需要移除的行"
}

# 4. 系統代理（Tor 模式）
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
python -m src.protection.windows.proxy_watchdog --now 2>$null
Pop-Location
Write-Host "  [4/5] 系統代理已檢查（若 Tor 模式留下設定則已還原）"

# 5. VPNBook 的 WireGuard 通道
$wg = Join-Path $env:ProgramFiles 'WireGuard\wireguard.exe'
if ((Test-Path $wg) -and (Get-Service 'WireGuardTunnel$AIXAI-VPNBook' -ErrorAction SilentlyContinue)) {
    & $wg /uninstalltunnelservice AIXAI-VPNBook
    Write-Host "  [5/5] 已移除 VPNBook 的 WireGuard 通道"
} else {
    Write-Host "  [5/5] 沒有 VPNBook 通道需要移除"
}

if ($RemoveProfile) {
    Remove-VpnConnection -Name 'AIXAI-VPN-SSTP' -Force -ErrorAction SilentlyContinue
    Write-Host "  [+]   已移除 VPN 設定 AIXAI-VPN-SSTP"
}

if ($ok) { Write-Host "完成：網路已還原。" -ForegroundColor Green } else { Write-Host "部分項目未完成，請截圖回報。" -ForegroundColor Yellow }
if (-not $NoPause) { Read-Host "按 Enter 關閉" | Out-Null }
