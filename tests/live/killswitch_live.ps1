# 實機測試外殼（以系統管理員身分執行）；-Module 指定要跑的 Python 測試（預設 TASK-005）
# 1. 先排「12 分鐘後自動還原」的安全網  2. 單獨測還原腳本  3. 跑 Python 實機測試  4. 取消安全網並再還原一次
param([Parameter(Mandatory)] [string]$Log, [string]$Module = "tests.live.killswitch_live")

$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$restore = Join-Path $root 'tools\restore-network.ps1'
Set-Location $root
function W($m) { Add-Content -Path $Log -Value "$(Get-Date -Format HH:mm:ss) $m" -Encoding UTF8 }

W "=== live test (admin) ==="
# 安全網：一次性排程，以 SYSTEM 身分 12 分鐘後執行還原（測試正常結束會取消）
$task = 'AIXAI-VPN-SafetyRestore'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$restore`" -NoPause"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(12)
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
W "safety restore scheduled at +12 min"

# 還原腳本單獨測試：放假規則（封鎖保留測試位址 203.0.113.1）＋假 hosts 行 → 還原 → 確認清乾淨
New-NetFirewallRule -DisplayName 'AIXAI-VPN TEST' -Group 'AIXAI-VPN' -Direction Outbound -Action Block -RemoteAddress 203.0.113.1 | Out-Null
$hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
Add-Content -Path $hosts -Value '203.0.113.1 test.opengw.net # AIXAI-VPN' -Encoding ASCII
& $restore -NoPause | Out-Null
$rules = @(Get-NetFirewallRule -Group 'AIXAI-VPN' -ErrorAction SilentlyContinue).Count
$marked = @(Get-Content $hosts | Where-Object { $_.TrimEnd().EndsWith('# AIXAI-VPN') }).Count
if ($rules -eq 0 -and $marked -eq 0) { W "PASS 還原腳本清除假規則與假 hosts 行" } else { W "FAIL 還原腳本 rules=$rules marked=$marked" }

# Python 實機測試（有自己的時間上限；安全網保底）
python -m $Module $Log

Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
& $restore -NoPause | Out-Null
W "safety task removed; final restore done"
