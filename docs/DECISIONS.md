# Quyết định thiết kế & cách hiểu đề

Mỗi mục: **Bối cảnh – Lựa chọn – Lý do – Phương án bị loại.**

### D1. Chính sách hết hạn khi mất kết nối (đề §4.3)
- **Bối cảnh:** đề bắt nhóm tự chọn fail-open/fail-closed sau N ngày.
- **Lựa chọn:** lai, N = 7 ngày. Lọc nội dung **fail-closed** (giữ danh sách chặn cuối); giới hạn thời gian **fail-open có giới hạn** (120 phút/ngày, 06:00–21:00). N đo bằng giờ tin cậy, lưu đĩa.
- **Lý do:** không trừng phạt trẻ vì lỗi mạng (khóa máy = mất giờ học), nhưng rút dây mạng cũng không thành "hết giới hạn".
- **Loại:** fail-closed toàn phần; fail-open toàn phần. (`agent/core.py: time_policy`)

### D2. Ký hiệu toàn vẹn chính sách: Ed25519 mặc định, hỗ trợ HMAC-SHA256
- **Bối cảnh:** đề cho "HMAC hoặc chữ ký".
- **Lựa chọn:** cả hai, cấu hình `OGK_POLICY_ALG`; mặc định Ed25519; agent khóa thuật toán từ lúc ghép (chống hạ cấp).
- **Lý do:** HMAC đối xứng — khóa kiểm cũng là khóa ký, phải nằm trên máy trẻ (môi trường không tin cậy, P6). Ed25519 chỉ để khóa công khai trên máy trẻ.
- **Loại:** chỉ HMAC dùng chung một khóa cho mọi thiết bị (lộ một máy là lộ tất cả).

### D3. Sự kiện chỉnh đồng hồ ghi vào bảng riêng `integrity_alerts`
- **Bối cảnh:** lược đồ sự kiện bắt buộc đúng 7 trường, 9 type, không thêm type.
- **Lựa chọn:** bảng riêng `integrity_alerts(device_id, child_id, ts, kind, detail_json)` cho clock_jump, dns_changed, policy_rejected, policy_cache_tampered, tray_unavailable; gửi kèm heartbeat.
- **Loại:** nhét vào `locked`/`quota_warning` (sai ngữ nghĩa, làm bẩn báo cáo).

### D4. "Ngoài khung giờ → máy bị khóa trong 5 giây"
- **Cách hiểu:** trong ≤ 5 giây (thực tế ≤ 1 giây, tick 1 s) **bắt đầu quy trình khóa**: thông báo + đếm ngược ân hạn 60 giây, sau đó khóa. Lệnh "Khóa ngay" của phụ huynh thì khóa tức thì, không ân hạn.
- **Lý do:** đề cũng bắt buộc "ân hạn 60 giây để trẻ lưu bài" — hai yêu cầu chỉ nhất quán theo cách hiểu này.

### D5. Khóa phiên bằng `WTSDisconnectSession`, khóa lại sau 30 giây nếu trẻ mở
- **Bối cảnh:** dịch vụ ở phiên 0 không gọi được `LockWorkStation` cho phiên trẻ.
- **Lựa chọn:** ngắt phiên console; khi trẻ đăng nhập lại trong lúc LOCKED, Tray hiện màn hình giải thích + "Xin thêm giờ" trong 30 giây rồi khóa lại.
- **Loại:** đăng xuất cưỡng bức (mất bài chưa lưu — trái nguyên tắc).

### D6. Chặn web bằng NXDOMAIN + toast trên Tray (không dựng trang chặn)
- **Lý do:** trang HTTPS không thể chèn trang chặn nếu không giả chứng chỉ (MITM). NXDOMAIN báo lỗi ngay, không lộ thêm dữ liệu; Tray giải thích lý do (P4 không chặn im lặng).

### D7. Firewall cổng 53: chặn tới "phần bù IP của upstream"
- **Bối cảnh:** Windows Firewall — luật chặn luôn thắng luật cho phép; không thể "chặn 53 trừ dịch vụ OGK".
- **Lựa chọn:** chặn 53 tới mọi IPv4 trừ upstream + loopback; khuyến nghị upstream là resolver lọc gia đình. Kiểm tra định kỳ DNS card mạng.
- **Loại:** WFP theo App-ID (đúng nhất nhưng cần lập trình nhân/C — ghi là hướng phát triển).

### D8. Tray đặt trong `/agent/tray` (không tách `/tray`)
- **Lý do:** đề §4.2 coi Tray UI là một phần của OGK-Agent; cấu trúc nộp bài chỉ có `/agent`.

### D9. Dữ liệu cấp hai: server ép `subject` về tên miền cấp hai
- **Lý do:** tối thiểu hóa (P2) không được phụ thuộc vào việc agent (máy không tin cậy) tự giác.

### D10. Quota theo từng thiết bị
- **Bối cảnh:** 1 trẻ : m thiết bị.
- **Lựa chọn hiện tại:** mỗi máy tự đếm quota của mình; báo cáo cộng dồn mọi máy.
- **Hướng phát triển:** server phát "ngân sách còn lại" chung qua heartbeat.

### D11. Hub WebSocket & rate limiter trong RAM
- Đủ cho một tiến trình Uvicorn trong lab; triển khai nhiều worker cần Redis pub/sub.
