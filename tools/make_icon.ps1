# 由 assets/APP_ICON.png 產生多尺寸圖示（ADR-018）：
#   assets/AIXAI-VPN.ico   exe 與視窗圖示（48px 以上用完整插畫；32px 以下用「盾牌地球」裁切，縮小後才認得出來）
#   src/ui/logo.png        App 介面左上角的小圖（盾牌地球裁切，64px）
# 只用 Windows 內建的 System.Drawing，不需額外套件。執行：powershell -File tools/make_icon.ps1
param(
    [string]$Source = (Join-Path $PSScriptRoot '..\assets\APP_ICON.png'),
    # 盾牌地球在 1254x1254 原圖中的位置（x, y, 邊長）
    [int[]]$Crop = @(285, 520, 690)
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$root = Split-Path $PSScriptRoot -Parent
$src = [System.Drawing.Image]::FromFile((Resolve-Path $Source))

function Render([int]$size, [bool]$cropped) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $dest = New-Object System.Drawing.Rectangle(0, 0, $size, $size)
    if ($cropped) {
        $rect = New-Object System.Drawing.Rectangle($Crop[0], $Crop[1], $Crop[2], $Crop[2])
    } else {
        $rect = New-Object System.Drawing.Rectangle(0, 0, $src.Width, $src.Height)
    }
    $g.DrawImage($src, $dest, $rect, [System.Drawing.GraphicsUnit]::Pixel)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    return ,$ms.ToArray()
}

# ICO：每個尺寸存 PNG 資料（Windows Vista 起支援）
$sizes = @(16, 24, 32, 48, 64, 128, 256)
$images = foreach ($s in $sizes) { ,(Render $s ($s -le 32)) }
$ico = Join-Path $root 'assets\AIXAI-VPN.ico'
$fs = [System.IO.File]::Create($ico)
$w = New-Object System.IO.BinaryWriter($fs)
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $data = $images[$i]
    $dim = if ($s -ge 256) { 0 } else { $s }
    $w.Write([byte]$dim); $w.Write([byte]$dim); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([uint16]1); $w.Write([uint16]32); $w.Write([uint32]$data.Length); $w.Write([uint32]$offset)
    $offset += $data.Length
}
foreach ($data in $images) { $w.Write($data) }
$w.Close()

[System.IO.File]::WriteAllBytes((Join-Path $root 'src\ui\logo.png'), (Render 64 $true))
$src.Dispose()
Write-Output "已產生 assets\AIXAI-VPN.ico（$($sizes -join '、') px）與 src\ui\logo.png"
