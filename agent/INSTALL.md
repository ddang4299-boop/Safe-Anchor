# Cài OGK Agent trên máy Windows của trẻ

> Trạng thái: chế độ **console** đã chạy thật (DNS 127.0.0.1:53, Named Pipe, heartbeat, WebSocket).
> Chế độ **Windows Service** + ép DNS/firewall **chưa kiểm chứng trên máy sạch** — hãy thử trên máy ảo trước.

## Yêu cầu
- Windows 10/11 x64, Python 3.11+ (đã thử 3.14), tài khoản của trẻ là **Standard** (không thuộc Administrators).
- Server OGK đã chạy và có mã ghép 8 ký tự (Dashboard → con → Thiết bị → *Tạo mã ghép*).

## A. Chạy thử nhanh (console, không cài dịch vụ)
```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m agent.run_agent enroll --code K7QM-2XPA --server http://IP-SERVER:8000
.\.venv\Scripts\python.exe -m agent.run_agent run            # DNS 127.0.0.1:53 (cổng 53 phải trống)
.\.venv\Scripts\python.exe -m agent.tray.app                 # cửa sổ khác: OGK Kids
nslookup tiktok.com 127.0.0.1                                # -> Non-existent domain
nslookup www.google.com 127.0.0.1                            # -> forcesafesearch.google.com
```
`--enforce` để thật sự kết thúc ứng dụng bị chặn và khóa máy (mặc định chỉ ghi log).
Nếu cổng 53 bận: `--dns-port 15353` rồi `nslookup -port=15353 ...` (cổng 5353 thường bị mDNS chiếm).

## B. Cài như dịch vụ (PowerShell "Run as Administrator")
```powershell
powershell -ExecutionPolicy Bypass -File agent\install.ps1 -Server https://IP:8443 -Code K7QM-2XPA `
  -CaFile certs\ca.crt -PinSha256 <giá trị in bởi tools\gen_lab_ca.py> -ManageNetwork
```
Script làm: ACL `%ProgramData%\OGK` (SID SYSTEM + Administrators) → lưu DNS gốc làm upstream → ghép đôi →
cài dịch vụ `OGKAgent` (LocalSystem, tự khởi động) → recovery `restart/5000 ×3, reset 86400` →
(tùy chọn) DNS card mạng = 127.0.0.1, firewall 53/853/DoH-IP, policy trình duyệt tắt DoH → Tray tự chạy khi đăng nhập (HKLM Run).

Xem trước các lệnh mạng sẽ áp dụng: `python -m agent.run_agent netguard-plan`.

## Kiểm tra
```powershell
Get-Service OGKAgent                     # Running
sc.exe qfailure OGKAgent                 # RESTART -- Delay = 5000 milliseconds
icacls $env:ProgramData\OGK              # chỉ NT AUTHORITY\SYSTEM và BUILTIN\Administrators
Get-DnsClientServerAddress -AddressFamily IPv4
netsh advfirewall firewall show rule name=OGK-DoT-853
```

## Gỡ cài đặt (người lớn có quyền Administrator)
```powershell
python agent\service.py stop; python agent\service.py remove
Get-NetAdapter | ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses }
netsh advfirewall firewall delete rule name=OGK-DoT-853   # tương tự OGK-DNS-53-UDP/TCP, OGK-DoH-IP-443
Remove-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Run -Name OGKKids
```
Chưa làm: trình gỡ yêu cầu mật khẩu phụ huynh (đề NÊN CÓ) và gói `OGK-Kids-Setup.exe` (PyInstaller + Inno Setup).
