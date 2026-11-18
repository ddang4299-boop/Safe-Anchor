# OpenGuard Kids (OGK)

**"Công cụ đồng hành, không phải phần mềm theo dõi lén."** Ứng dụng hỗ trợ cha mẹ quản lý việc dùng máy tính của trẻ 6–11 tuổi — đồ án Mạng máy tính (CSC10008).

- **Máy trẻ (Windows):** OGK Agent — dịch vụ LocalSystem: DNS proxy lọc web `127.0.0.1:53`, chặn ứng dụng theo SHA-256, đếm giờ chống chỉnh đồng hồ; **OGK Kids** — ứng dụng khay cho trẻ (PySide6).
- **Máy chủ:** OGK Server — FastAPI + SQLite (WAL) + SQLAlchemy.
- **Phụ huynh:** web dashboard (Jinja2 + HTMX), dùng tốt trên điện thoại.

## Phạm vi sử dụng hợp pháp
Chỉ dùng cho **con/người được giám hộ dưới 18 tuổi** trên thiết bị gia đình quản lý, với sự hiểu biết của trẻ. OGK **không có chế độ ẩn**: biểu tượng khay luôn hiện; nếu không hiển thị được biểu tượng, agent tự dừng kiểm soát. Cấm dùng để theo dõi người lớn. Dữ liệu thu thập: xem [docs/PRIVACY.md](docs/PRIVACY.md).

## Cài đặt nhanh (Windows, ~10 phút)
```powershell
py -3.14 -m venv .venv                      # Python 3.11+ đều được
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest        # 81 test
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```
`run_demo.ps1` tạo dữ liệu mẫu, mở server `:8000`, ghép đôi agent với bé Bin, chạy agent (DNS `127.0.0.1:53`) và OGK Kids, rồi mở dashboard.

**Tài khoản demo:** `demo@ogk.local` / `OgkDemo@2026` · Trang của trẻ: `/kid/xem-cua-bin-demo-token-2026`

Chạy từng phần thủ công:
```powershell
.\.venv\Scripts\python.exe -m server.seed                     # reset DB mẫu, in mã ghép
.\.venv\Scripts\python.exe -m server.main --host 0.0.0.0      # http://IP:8000 (đặt OGK_COOKIE_SECURE=0 khi chạy HTTP)
.\.venv\Scripts\python.exe -m agent.run_agent enroll --code XXXX-XXXX
.\.venv\Scripts\python.exe -m agent.run_agent run [--dns-port 15353] [--enforce]
.\.venv\Scripts\python.exe -m agent.tray.app [--demo]
```
HTTPS cho phòng lab: `python tools/gen_lab_ca.py --ip <IP server>` rồi `python -m server.main --host 0.0.0.0 --tls`. Cài agent thành dịch vụ: [agent/INSTALL.md](agent/INSTALL.md).

## Cấu trúc thư mục
```text
/agent        Agent (dns_wire, dns_proxy, domain_rules, clock, schedule, core, app_control, policy_verify,
              local_cache, sync, ws_client, ipc, winsys, netguard, runtime, service) + tray/ (OGK Kids)
/server       FastAPI: main, models, security, signing, policy_service, access (chống IDOR), reports,
              audit, jobs (xóa 90 ngày), seed, routers/{agent_api, auth, dashboard, kid}
/dashboard    templates Jinja2 + static (CSS tokens, HTMX, font Nunito/Inter, mascot SVG)
/tests        81 test: unit (DNS, đồng hồ, lịch, core, SHA-256, chữ ký, IPC...) + tích hợp (proxy thật, server)
/tools        measure_dns, measure_resources, measure_policy_latency, gen_lab_ca, hash_exe, gen_data, gen_mascots
/data         categories.csv (237 mục, 6 nhóm), test_domains.csv (50 cần chặn + 20 giáo dục + ...)
/docs         BACKEND_AND_NETWORK_GUIDE (ôn bảo vệ), DECISIONS, PRIVACY, THREATMODEL, AI_USAGE
```

## Biến môi trường (server)
`OGK_SECRET`, `OGK_DATA_KEY` (32 byte base64, AES-256-GCM), `OGK_SIGNING_KEY` (seed Ed25519), `OGK_POLICY_ALG` (`ed25519`|`hmac-sha256`), `OGK_DB_URL`, `OGK_COOKIE_SECURE`. Thiếu khóa thì server tự sinh khóa **phát triển** vào `server/instance/` (không dùng cho triển khai thật).
