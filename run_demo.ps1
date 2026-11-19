# run_demo.ps1 — Chạy toàn bộ OGK trên MỘT máy Windows để kiểm tra nhanh.
#   powershell -ExecutionPolicy Bypass -File .\run_demo.ps1            # reset dữ liệu mẫu + chạy tất cả
#   powershell -ExecutionPolicy Bypass -File .\run_demo.ps1 -NoReset   # giữ dữ liệu cũ
#   ... -DnsPort 15353   # nếu cổng 53 đang bận
# Mở 3 cửa sổ: (1) server, (2) agent, (3) SafeAnchor Kids (Tray). Trình duyệt mở dashboard.
param([switch]$NoReset, [int]$DnsPort = 53)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Chưa có .venv — xem README mục Cài đặt" }
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:OGK_COOKIE_SECURE = "0"   # chạy HTTP trong LAN để thử; triển khai thật dùng HTTPS (python -m server.main --tls)

if (-not $NoReset) {
  Write-Host "== Tạo dữ liệu mẫu (xóa DB cũ) =="
  & $Py -m server.seed
  Remove-Item -Recurse -Force (Join-Path $PSScriptRoot ".ogk_agent") -ErrorAction SilentlyContinue
}

Write-Host "== (1) Khởi động server :8000 =="
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='SafeAnchor Server'; `$env:PYTHONIOENCODING='utf-8'; `$env:OGK_COOKIE_SECURE='0'; & '$Py' -m server.main --host 0.0.0.0 --port 8000"
$up = $false
for ($i = 0; $i -lt 40; $i++) {
  try { Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $up) { throw "Server không lên — xem cửa sổ SafeAnchor Server" }

if (-not (Test-Path (Join-Path $PSScriptRoot ".ogk_agent\agent.db"))) {
  Write-Host "== Ghép đôi agent với bé Bin =="
  $line = (& $Py -m server.seed --code | Select-String "PAIRING_CODE=").ToString()
  $code = $line.Split("=")[-1].Trim()
  & $Py -m agent.run_agent enroll --code $code --server http://127.0.0.1:8000
}

Write-Host "== (2) Khởi động agent (DNS 127.0.0.1:$DnsPort, enforce=False) =="
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='SafeAnchor Agent'; `$env:PYTHONIOENCODING='utf-8'; & '$Py' -m agent.run_agent run --dns-port $DnsPort"
Start-Sleep -Seconds 3

Write-Host "== (3) Mở SafeAnchor (Tray của trẻ) =="
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-Command",
  "`$host.UI.RawUI.WindowTitle='SafeAnchor Kids'; & '$Py' -m agent.tray.app"

Start-Process "http://127.0.0.1:8000"
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq "Dhcp" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "Dashboard: http://127.0.0.1:8000  (điện thoại cùng Wi-Fi: http://$ip`:8000)"
Write-Host "Đăng nhập: demo@ogk.local / OgkDemo@2026"
Write-Host "Trang của trẻ: http://127.0.0.1:8000/kid/xem-cua-bin-demo-token-2026"
Write-Host "Thử DNS:  nslookup tiktok.com 127.0.0.1   |   nslookup www.google.com 127.0.0.1"
