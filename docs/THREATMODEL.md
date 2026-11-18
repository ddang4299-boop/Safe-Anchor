# THREATMODEL — STRIDE

| # | STRIDE | Mối đe dọa | Biện pháp trong mã | Rủi ro còn lại |
|---|---|---|---|---|
| T1 | Tampering | **Chính trẻ là kẻ tấn công**: sửa chính sách/cache để tăng quota | Chữ ký Ed25519 + device_id + version tăng; kiểm lại chữ ký khi nạp cache; ACL ProgramData | Trẻ có quyền admin |
| T2 | Tampering | Trẻ lùi/tua đồng hồ | Monotonic + Cristian; ngày chỉ tăng; `integrity_alerts` | Tua tới + reboot + offline |
| T3 | Elevation / DoS | Trẻ kill agent/Tray qua Task Manager | LocalSystem phiên 0; SCM recovery 5 s; TrayWatchdog mở lại Tray | Trẻ là admin |
| T4 | Spoofing / bypass | Đổi DNS 8.8.8.8, DoH, DoT, VPN | Ép DNS card mạng, firewall 53/853/DoH-IP, NXDOMAIN DoH + canary, policy trình duyệt | DoH lạ, VPN |
| T5 | Spoofing | Đổi tên game.exe thành tên hệ thống | SHA-256; bảo vệ tiến trình hệ thống theo tên **và** đường dẫn | Game cập nhật đổi băm |
| T6 | Elevation | Trẻ gửi lệnh nguy hiểm vào IPC | Danh sách trắng thao tác vô hại; DACL pipe; token cho TCP | — |
| T7 | Spoofing | **Trẻ giả yêu cầu đổi quà / tự cộng giờ / tự cộng điểm** | Tray chỉ tạo *yêu cầu*; giờ chỉ cộng qua lệnh có xác thực từ server; server là nơi duy nhất quyết | — |
| T8 | Info disclosure | **Bị lạm dụng làm stalkerware theo dõi người lớn** | Không chế độ ẩn; Tray luôn hiện, không hiện được thì tự dừng; tối thiểu hóa dữ liệu; người bị quản lý xem được mọi thứ; audit đồng ý | Kẻ có quyền admin trên máy nạn nhân (nhưng nạn nhân thấy biểu tượng) |
| T9 | Info disclosure / EoP | IDOR giữa các phụ huynh | Sở hữu trong WHERE, 404 | — |
| T10 | Spoofing | Dò mật khẩu phụ huynh | scrypt, khóa 15' sau 5 lần, rate limit IP, so sánh thời gian hằng | Không có TOTP |
| T11 | Tampering | CSRF trên dashboard | SameSite=Lax + token HMAC theo phiên | — |
| T12 | Spoofing | MITM giữa agent và server | TLS 1.2+, ghim CA + chứng chỉ lá | Cấu hình sai (chạy HTTP) |
| T13 | Spoofing | Đánh cắp refresh token | DPAPI + ACL; xoay vòng + phát hiện dùng lại → thu hồi cả họ | Đến lần xoay kế tiếp |
| T14 | Repudiation | Phụ huynh chối đã đổi cài đặt | `audit_log` ai/lúc nào/IP/cũ/mới | — |
| T15 | DoS | Lạm dụng DNS proxy làm bộ khuếch đại / gói độc | Chỉ nghe 127.0.0.1; semaphore 256; parser chống con trỏ vòng | — |

## Checklist ASVS (rút gọn, L1)
- [x] V2 Mật khẩu ≥ 10 ký tự, băm scrypt có muối, khóa sau nhiều lần sai, không tiết lộ email tồn tại
- [x] V3 Phiên phía server, cookie HttpOnly/Secure/SameSite, hủy phiên khi đăng xuất, hạn 12 giờ
- [x] V4 Kiểm soát truy cập ở tầng dữ liệu (IDOR), từ chối mặc định
- [x] V5 Kiểm tra đầu vào (Pydantic, regex tên miền/exe/sha256, chuỗi lịch 336 ký tự), escape đầu ra (Jinja autoescape)
- [x] V6 AES-256-GCM có AAD, khóa từ biến môi trường, không hardcode
- [x] V9 TLS 1.2+, ghim chứng chỉ phía agent
- [x] V13 Rate limit enroll/login/refresh
- [x] V14 Header bảo mật: CSP, X-Frame-Options, nosniff, Referrer-Policy
- [ ] V2.8 TOTP (điểm cộng — chưa làm)
