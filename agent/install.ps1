# agent/install.ps1 — Cài OGK Agent thủ công (tương đương trình cài OGK-Kids-Setup.exe).
# Chạy trong PowerShell "Run as Administrator":
#   powershell -ExecutionPolicy Bypass -File agent\install.ps1 -Server https://192.168.1.10:8443 -Code K7QM-2XPA [-CaFile certs\ca.crt] [-ManageNetwork]
param(
  [Parameter(Mandatory=$true)][string]$Server,
  [Parameter(Mandatory=$true)][string]$Code,
  [string]$CaFile = "",
  [string]$PinSha256 = "",
  [switch]$ManageNetwork
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$Data = Join-Path $env:ProgramData "OGK"

Write-Host "1) Tạo $Data và đặt ACL chỉ SYSTEM (S-1-5-18) + Administrators (S-1-5-32-544)"
New-Item -ItemType Directory -Force $Data | Out-Null
icacls $Data /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null

Write-Host "2) Lưu DNS gốc của card mạng làm upstream"
$orig = (Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses } |
         ForEach-Object { $_.ServerAddresses } | Where-Object { $_ -ne "127.0.0.1" } | Select-Object -Unique)
if (-not $orig) { $orig = @("1.1.1.3", "1.0.0.3") }   # resolver lọc cho gia đình
$cfg = @{ server_url = $Server; upstreams = @($orig); enforce = $true; manage_network = [bool]$ManageNetwork;
          ca_file = $(if ($CaFile) { (Resolve-Path $CaFile).Path } else { $null });
          pin_sha256 = $(if ($PinSha256) { $PinSha256 } else { $null }) }
$cfg | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Data "config.json")

Write-Host "3) Ghép đôi với server bằng mã $Code"
& $Py -m agent.run_agent --data-dir $Data enroll --code $Code --server $Server
if ($LASTEXITCODE -ne 0) { throw "Ghép đôi thất bại" }

Write-Host "4) Cài Windows Service OGKAgent (LocalSystem, tự khởi động) + recovery: restart sau 5 giây x3, reset sau 1 ngày"
& $Py (Join-Path $Root "agent\service.py") --startup auto install
sc.exe failure OGKAgent reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null

if ($ManageNetwork) {
  Write-Host "5) Đặt DNS mọi card mạng = 127.0.0.1, luật firewall chặn DoT/53/DoH-IP, policy trình duyệt tắt DoH"
  Get-NetAdapter | Where-Object Status -eq "Up" | ForEach-Object {
    Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses 127.0.0.1 }
  & $Py -c "from agent import netguard, config; import json; c=json.load(open(r'$Data\config.json',encoding='utf-8-sig')); netguard.apply_all(c['upstreams'], dry_run=False)"
  ipconfig /flushdns | Out-Null
}

Write-Host "6) Tray OGK Kids tự chạy khi trẻ đăng nhập (HKLM Run — mọi người dùng, trẻ không xóa được)"
$pyw = $Py -replace "python.exe$", "pythonw.exe"
New-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "OGKKids" -Force `
  -Value "`"$pyw`" -m agent.tray.app --data-dir `"$Data`"" | Out-Null

& $Py (Join-Path $Root "agent\service.py") start
Write-Host "Xong. Kiểm tra: Get-Service OGKAgent; nslookup example.com 127.0.0.1"
