# PRIVACY — Dữ liệu OGK thu thập

Nguyên tắc: chỉ lưu thứ có mục đích rõ ràng; trẻ thấy đúng những gì phụ huynh thấy (NT5); không có chế độ ẩn.
Không bao giờ thu: URL đầy đủ, nội dung trang, tin nhắn, ảnh/video màn hình, phím gõ, micro, camera, vị trí.

| Bảng.trường | Mục đích | Thời hạn | Ai xem được |
|---|---|---|---|
| `parents.email` | Đăng nhập, khôi phục | Đến khi xóa tài khoản | Phụ huynh |
| `parents.pw_hash` (scrypt) | Xác thực | Như trên | Không ai (chỉ băm) |
| `guardians.display_name_enc`, `call_name_enc` (AES-GCM) | Ký lời nhắn, ghi "ai đã đổi gì" bằng lời | Như trên | Phụ huynh, trẻ |
| `children.nickname_enc` (AES-GCM) | Mascot gọi trẻ thân mật | Như trên | Phụ huynh, trẻ |
| `children.self_pronoun`, `birth_year` (chỉ năm), `avatar_key` | Xưng hô; chọn chính sách & chế độ Mầm/Chồi theo tuổi; hình đại diện mascot | Như trên | Phụ huynh, trẻ |
| `devices.fingerprint_hash` (SHA-256 của băm) | Nhận diện thiết bị khi ghép | Đến khi gỡ thiết bị | Không hiển thị |
| `devices.hostname_enc` (AES-GCM) | Phân biệt máy trong dashboard | Như trên | Phụ huynh |
| `devices.last_seen, last_ip, last_state_json, clock_skew` | Hiển thị Đang dùng/Ngoại tuyến, thời gian còn lại, cảnh báo lệch giờ | Ghi đè liên tục | Phụ huynh |
| `events.ts, device_id, child_id, type, subject, duration_sec, policy_id` | Báo cáo thời lượng, top ứng dụng/tên miền (cấp hai), số lần chặn | **90 ngày** (job tự xóa) | Phụ huynh, trẻ (trẻ không thấy số lần chặn) |
| `events.idem_key` (cột kỹ thuật) | Chống đếm trùng khi gửi lại lô | Cùng sự kiện | Không hiển thị |
| `daily_usage` | Biểu đồ ngày/tuần, phân bổ theo nhóm | 90 ngày | Phụ huynh, trẻ |
| `unlock_requests.reason_enc`, `note_enc` (AES-GCM) | Trẻ xin thêm giờ, phụ huynh trả lời | 90 ngày | Phụ huynh, trẻ |
| `integrity_alerts` | Báo chỉnh đồng hồ / đổi DNS / Tray không hiện | 90 ngày | Phụ huynh |
| `audit_log` (ai, lúc nào, IP, cũ, mới) | Minh bạch & trách nhiệm (đề F4) | 365 ngày | Phụ huynh, trẻ (dạng lời) |
| `sessions`, `refresh_tokens`, `pairing_codes` (chỉ băm) | Bảo mật phiên/thiết bị | Đến khi hết hạn | Không hiển thị |
| Agent: `event_queue`, `core_snapshot` trong `%ProgramData%\OGK` | Hoạt động khi mất mạng | Đến khi server xác nhận / qua ngày | Không hiển thị |

"Xóa toàn bộ dữ liệu của con tôi": xóa `events`, `daily_usage`, `unlock_requests`, `integrity_alerts` trên server và gửi lệnh `purge_data` xóa hàng đợi + bộ đệm trên agent. `audit_log` giữ lại bản ghi của chính thao tác xóa (trách nhiệm giải trình).
