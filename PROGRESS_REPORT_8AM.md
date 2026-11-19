# Báo cáo tiến độ — 8:00 sáng 19/11/2026

> **Cập nhật đêm 19/11 — đổi tên thành SafeAnchor + dựng lại UI/UX phụ huynh theo bố cục `newlayout.png`.** **87/87 test đạt** (thêm 1 test).
>
> | Phần | Thay đổi | Đã kiểm chứng |
> |---|---|---|
> | Thương hiệu | Tên hiển thị **SafeAnchor** ở mọi trang (tiêu đề tab, đầu trang, chân trang, đăng nhập/đăng ký, trang lỗi, trang của trẻ), chuỗi trong Tray, nhật ký ("ba mẹ đồng ý sử dụng SafeAnchor"), tiêu đề API. Tên nội bộ (biến `OGK_*`, cookie, tên dịch vụ Windows, luật firewall `OGK-`) **giữ nguyên** để không phá cài đặt. Mascot chính lấy từ `mascot.jpg`: `tools/make_brand_assets.py` tách nền ô caro giả trong suốt (đóng khe nét vẽ tay rồi loang) → `dashboard/static/brand/mascot.png` + favicon 32/64/180 px; dùng cho logo, favicon, thẻ chào mừng, trạng thái trống. Mascot riêng của từng con (Tíc-Tắc/Khiên Xanh/Sao Nhỏ) vẫn là avatar | ảnh chụp trên nền navy/xám/cam: viền sạch |
> | Bố cục (theo ảnh mẫu) | Trang dài gồm các **dải băng** toàn chiều ngang: dải navy `#000056` trên cùng + thanh trắng có logo/menu/nút xanh → phần mở đầu nền `#EEF1F8` (tiêu đề rất đậm, dòng nhấn xanh `#0070C9`, nút chính + liên kết mũi tên, mascot trên "chồng sách" + ruy băng xanh + mặt trời vàng) → **dải số liệu nổi** chồng lên mép (hồ sơ + 4 KPI) → yêu cầu của các con → 6 thẻ pastel viền màu phía trên → dải xám với biểu đồ + 4 con số lớn → dải navy "Thiết bị" → dải xanh trời "4 bước" + thẻ navy → hỏi đáp dạng accordion → lời kêu gọi navy → chân trang navy 4 cột. Stylesheet mới `safeanchor.css` (trang của trẻ giữ `ogk.css`) | ảnh 1280 + 390 px đặt cạnh ảnh mẫu cùng tỉ lệ; không cuộn ngang ở 390 px |
> | Dữ liệu dễ hiểu | Bảng "nhật ký thay đổi" → **dòng thời gian** (6 mục mới nhất, phần cũ hơn trong "Xem thêm"); bảng "bị chặn nhiều nhất" → thanh xếp hạng; KPI + thanh tiến độ hạn mức + biểu đồ tròn | ảnh chụp |
> | Xem chi tiết khi cần | Mặc định chỉ hiện **tổng của 6 nhóm nội dung**. Bấm thẻ nhóm **hoặc một lát biểu đồ tròn** mới mở bảng: ứng dụng, trang web, đã chặn, **nhật ký gần đây** (giờ · tên miền/ứng dụng · Truy cập/Dùng/Đã chặn) của đúng nhóm đó. Server gom nhóm trong `enrich_report()` (`groups`); tắt JS vẫn mở được nhờ liên kết `#cd-<con>-<nhóm>` + CSS `:target` | test mới `test_overview_groups_details_by_category_and_has_guide_faq`; thử bấm thật trên Edge (thẻ và lát biểu đồ đều mở đúng nhóm) |
> | Hướng dẫn + hỏi đáp | **4 bước bắt đầu nhanh** tự đánh dấu "Đã xong" từ dữ liệu thật (có hồ sơ / đã ghép máy / chính sách đã tùy chỉnh / đã tạo link cho con); **9 câu hỏi thường gặp** cho phụ huynh — nội dung đối chiếu với code (90 ngày, AES-256-GCM, rảnh 5 phút, nhắc 10-5-1 phút) | test + ảnh chụp |
>
> ⚠ `mascot.jpg` là nhân vật **Hachiware (Chiikawa) — có bản quyền**. Dùng trong demo nội bộ của lớp thì ít rủi ro, nhưng repo Safe-Anchor đang **công khai**: cần nhóm quyết định trước khi đẩy `dashboard/static/brand/*.png` lên (hoặc thay bằng hình tự vẽ — chỉ cần chạy lại `tools/make_brand_assets.py <ảnh mới>`).
>
> **Cập nhật tối 19/11 — tinh chỉnh dashboard phụ huynh ("Modern SaaS / Bento 2026") + mascot phong cách mới.** **86/86 test đạt.**
>
> | Phần | Thay đổi | Đã kiểm chứng |
> |---|---|---|
> | Bố cục | **Thanh chọn hồ sơ** dạng viên thuốc ngay dưới lời chào (`[Bin · Đang dùng]` `[Na · Ngoại tuyến]` `[+ Thêm con]`, có huy hiệu số yêu cầu chờ): bấm là đổi cả cụm Bento tại chỗ (không tải lại), phím ←/→, URL `?con=<id>`; tắt JS vẫn chuyển được bằng liên kết. Lưới 12 cột **bất đối xứng**: hồ sơ 4 + 4 thẻ số × 2 / biểu đồ 8 + thiết bị 4 / top ứng dụng 5 + top tên miền 4 + theo nhóm 3; khung rộng 1280px | thử trên Edge: chuyển tab, phím mũi tên, cập nhật OOB, 0 lỗi JS, không trùng id |
> | Bề mặt | Nền `#F8FAFC` + bóng tán xạ siêu nhẹ kèm viền 1px; tác vụ phụ thành **nút nhạt (soft-tinted)**, chỉ `[✓ Đồng ý +Np]` là nút đặc; thẻ yêu cầu nền trắng + dải san hô `#FF6B6B` bên trái, xếp ngang | ảnh 1280 / 390 px |
> | Biểu đồ | Cột 7 ngày mảnh (≤ 28px), gradient Indigo→tím nhạt, hôm nay san hô→cam; **đường giới hạn đứt nét** theo hạn mức từng ngày (ngày thường/cuối tuần) + nhãn "Giới hạn 1h 30p" + chú giải "N ngày vượt mức" + tooltip "Vượt giới hạn 13p"; biểu đồ tròn có tổng ở giữa. Top ứng dụng/tên miền: **biểu tượng bo tròn theo nhóm** (học tập, trò chơi, giải trí, mạng xã hội — không tải favicon thật vì sẽ lộ IP + danh sách trang con vào cho bên thứ ba) và số cụ thể ở cuối thanh (`4h 28p`, `15 lượt`) | ảnh chụp |
> | Thẻ thiết bị | **Khóa khẩn cấp** tách riêng góc phải (icon ổ khóa); **Nghỉ 2h / 15 phút / Mở khóa** gom vào thanh công cụ mini; thanh thời gian = phần đã dùng, có sọc chéo chạy + đầu sáng khi máy online | ảnh chụp |
> | Chữ + vi tương tác | **Plus Jakarta Sans** (tự lưu, OFL) cho tiêu đề + số lớn, `tabular-nums`; 4 thẻ số liệu nổi nhẹ khi rê chuột, icon nền pastel ở góc, kèm biểu đồ mini (thanh hạn mức, cột 7 ngày, tỉ lệ học tập, chặn web/ứng dụng) | ảnh chụp |
> | Mascot | Vẽ lại theo **phong cách chibi nét vẽ tay** (viền nâu đậm, mắt to có đốm sáng, má hồng gạch chéo, miệng ω, tay chân ngắn) — chỉ lấy phong cách từ ảnh tham khảo, **không** chép nhân vật có bản quyền; vẫn là Tíc-Tắc, Khiên Xanh, Sao Nhỏ (đội mũ tốt nghiệp) với màu nhận diện cũ, 6 biểu cảm, áp dụng cả web lẫn Tray | `tools/gen_mascots.py`, ảnh Tray |
>
> **Cập nhật chiều 19/11 — đại tu giao diện (Modern Tactile + Bento + mascot vector động).**
> Ảnh chụp thật của giao diện mới: [`docs/screenshots/`](docs/screenshots/).
>
> | Phần | Thay đổi | Đã kiểm chứng |
> |---|---|---|
> | Hệ thống thị giác | Nền gradient `#F8FAFC→#EEF2FF→#F5F3FF`, bóng nhiều lớp ánh xanh tím, kính mờ cho thanh điều hướng, thẻ bo 24px, nút "xúc giác" (viền dưới 4px, rê phóng 1.02, bấm lún 4px), icon Lucide nét 2.2, phông Nunito + Inter **tự lưu trên server** (không gọi Google Fonts: không lộ IP phụ huynh, hợp CSP, chạy trong LAN không Internet) | ảnh chụp 1280 px và 390 px |
> | Mascot | Vẽ lại bằng SVG có gradient + điểm sáng: Tíc-Tắc (cam san hô, kim đồng hồ quay), Khiên Xanh (vẫy tay, cầm biển nhắc), Sao Nhỏ (tím + bút chì mint); thở/chớp mắt/vẫy tay bằng CSS `@keyframes` ngay trong tệp SVG; Tray tự chớp mắt bằng khung `*_blink.svg` | `tools/gen_mascots.py` |
> | Dashboard phụ huynh | Bento: thẻ yêu cầu viền sáng `[Đồng ý +15p]` / `[Nhắc bé nghỉ ngơi]`; mỗi con: chỉ số nhanh, biểu đồ 7 ngày, thiết bị có chấm xanh nhấp nháy "Online · Đang học tập" + nút **Khóa khẩn cấp / Tạm nghỉ 2h / +15 phút / Mở khóa**; Chart.js 4.4.1 (tự lưu, cột bo tròn đầu) cho 7 ngày, top ứng dụng/tên miền, phân bổ nhóm; trang của con: một biểu mẫu chính sách duy nhất, lưới lịch 7×48 ô bo góc kéo-tô; thanh tab dưới đáy trên điện thoại | 4 test mới + ảnh chụp |
> | Trang của trẻ `/kid/...` | Phần đầu kiểu ảnh mẫu (chữ khổng lồ, nhãn chéo, nút cam, sân khấu mascot) + Bento "Hôm nay": vòng thời gian, học tập, giải trí, huy hiệu "Ngôi Sao Đúng Giờ" + chuỗi 7 ngày; không hiện "số lần bị chặn" (không đếm lỗi trên màn hình của trẻ) | test + ảnh chụp |
> | Tray (PySide6) | HUD viên thuốc kính mờ (thanh đổi màu mượt Mint→Vàng→Cam), màn chặn có mascot nhô khỏi mép thẻ + bong bóng thoại + chip xin giờ nhanh, "Hôm nay" dạng Bento + huy hiệu | ảnh xuất offscreen + test `view_logic` |
> | Chức năng mới phía sau | **Tạm nghỉ có hạn** (`lock_now` + `minutes`): agent tự mở khi hết hạn, không cần mạng, mốc theo đồng hồ tin cậy và giữ qua khởi động lại; heartbeat gửi **nhóm** đang chạy (không gửi tên ứng dụng); tạo link mới cho con thì link cũ hết hiệu lực; trạng thái thiết bị làm mới riêng bằng `hx-swap-oob` (biểu đồ không vẽ lại) | 2 test mới |
>
> Thử nhanh giao diện Tray không cần agent: `.venv\Scripts\python.exe -m agent.tray.app --demo`.

**Tóm tắt:** nền tảng 3 khối (`/agent`, `/server`, `/dashboard`) đã chạy thật trên máy này, end-to-end:
dashboard → server → agent → DNS proxy `127.0.0.1:53` → Tray của trẻ. **81/81 test đạt** (`pytest`, ~8 giây).
Phần cần quyền Administrator / máy Windows sạch (cài dịch vụ, ép DNS card mạng, firewall) đã viết nhưng **chưa kiểm chứng**.

---

## 1. Đã hoàn chỉnh và đã chạy thật

| Module | Bằng chứng |
|---|---|
| **DNS proxy** UDP+TCP `127.0.0.1:53`: chặn miền + mọi miền con (so khớp hậu tố theo nhãn), NXDOMAIN giữ đúng ID, SERVFAIL khi upstream chết, TC→TCP, cache TTL+LRU, asyncio | `nslookup` thật: `tiktok.com`/`m.facebook.com`/`dns.google`/`adult-sim-03…` → NXDOMAIN; `notfacebook.com`, `khanacademy.org` → phân giải bình thường; 9 test tích hợp với upstream giả |
| **SafeSearch** bằng CNAME | `nslookup www.google.com 127.0.0.1` → `forcesafesearch.google.com` / 216.239.38.120 |
| **Chống DoH cơ bản**: NXDOMAIN điểm cuối DoH + canary Firefox | thật + test |
| Tỉ lệ chặn bộ dữ liệu đề | **50/50 (100%)** miền cần chặn; **0/20** dương tính giả miền giáo dục |
| **Đồng hồ đơn điệu + Cristian + phát hiện chỉnh giờ**; lùi giờ 3h không tăng quota | 17 test `test_time_core.py` |
| Quota thường/cuối tuần, lịch 7×48, cảnh báo 10/5/1, ân hạn 60 s, ngân sách nhóm, fail-mode N=7 | test |
| **Kiểm soát ứng dụng SHA-256** (đổi tên `.exe` vẫn nhận ra; đổi tên thành `svchost.exe` cũng không thoát) | test |
| **Hàng đợi sự kiện SQLite** khi mất mạng + lô ≤ 200 + idempotency key | test + thật (agent gửi lô, server ACK) |
| **Server FastAPI**: `/api/enroll` (mã 8 ký tự, 10 phút, 1 lần, rate-limit), `/api/token/refresh` (xoay vòng + phát hiện dùng lại), `/api/policy` (version + **chữ ký**), `/api/heartbeat`, `/api/events` (`ON CONFLICT DO NOTHING`), `/api/commands/{id}/ack`, `WS /api/ws`, báo cáo, audit | 17 test tích hợp TestClient + chạy thật |
| Mô hình **1 phụ huynh : n trẻ : m thiết bị**, **chống IDOR trong câu truy vấn** (404) | test 6 route chéo phụ huynh |
| **Lệnh khẩn WebSocket** (khóa ngay / mở khóa / +15 phút), áp dụng đúng 1 lần dù đến qua cả WS và heartbeat | đo thật: dashboard → agent áp dụng **5–10 ms** (n=10) |
| **IPC Named Pipe** (DACL SY/BA/IU) + TCP loopback có token; danh sách trắng thao tác | thật: Tray đọc trạng thái qua pipe; thao tác `set_policy` bị từ chối |
| **Dashboard** (Jinja2 + HTMX, mobile-first, dark mode): tổng quan tự cập nhật 10 s, duyệt yêu cầu thời gian thực (5 s), quota, **lịch 7×48 kéo-tô bằng Pointer Events**, lọc web/ứng dụng, biểu đồ 7 ngày/4 tuần, top 10 app/miền, số lần chặn, nhật ký kiểm toán, xuất CSV, mã ghép có đếm ngược, xóa toàn bộ dữ liệu (2 bước) | test render mọi trang; ảnh chụp Edge headless ở 496 px không tràn ngang |
| **Trang minh bạch cho trẻ** `/kid/{token}` (dùng chung partial báo cáo) | chạy thật |
| **OGK Kids (Tray, PySide6)**: viên HUD Tíc-Tắc + thanh thời gian (mint→vàng→san hô kèm chữ), cửa sổ chính 4 thẻ (Hôm nay + dải thời gian cả ngày / Đã khám phá gì / Ai đã đổi gì / Về OGK), **màn hình chặn nhẹ nhàng** (trả lời *chuyện gì – vì sao – làm gì*, vòng ân hạn, nút **"Nghỉ thôi, lưu bài nào"** + **"Xin thêm giờ"**), toast, hộp thoại xin giờ 15/30/60, onboarding 4 bước, chế độ Mầm/Chồi | ảnh chụp offscreen từng màn hình; `--demo` chạy không cần agent |
| **Mascot gốc SVG** 3 nhân vật × 5 biểu cảm (Tíc-Tắc, Khiên Xanh, Sao Nhỏ) theo phong cách khối hình học + mắt to trong ảnh tham khảo | `tools/gen_mascots.py` |
| Đo thử hiệu năng — **chưa đạt chuẩn M4** | DNS qua agent lượt nóng p50 **0,32 ms** (n=60); lượt lạnh chậm hơn hỏi thẳng ~1 ms (n=20); agent rảnh CPU p50 0,00% (max 0,19%), RAM ≈ 56 MB (n=30). Đề đòi **mỗi phép đo ≥ 30 mẫu** và đo cả lúc **cao điểm**: lượt lạnh (n=20) và lệnh khẩn (n=10) chưa đủ mẫu, chưa đo cao điểm → nhóm đo lại trên máy demo bằng `tools/measure_*.py` (mặc định đã ≥ 30 mẫu) |

## 2. Đã viết nhưng CHƯA kiểm chứng (cần Admin / máy ảo sạch)
- `agent/service.py` — Windows Service LocalSystem, nhận WTS lock/unlock từ SCM. Dịch vụ pywin32 trong venv đôi khi cần `pywin32_postinstall`; thử theo `agent/INSTALL.md`.
- `agent/install.ps1` — ACL ProgramData bằng SID, recovery SCM (restart 5 s ×3), ép DNS card mạng, firewall 53/853/DoH-IP, policy HKLM tắt DoH trình duyệt, Tray tự chạy.
- `winsys.lock_session` (WTSDisconnectSession), `launch_in_user_session` (CreateProcessAsUser), `TrayWatchdog` (logic đã test, phần gọi Windows chưa).
- `--enforce` (thật sự kill app/khóa máy) — **chưa bật trên máy này** để không làm phiền máy phát triển.
- Chế độ console không nhận sự kiện khóa màn hình (chỉ dịch vụ mới nhận từ SCM) → thử "không đếm khi khóa máy" phải chạy dạng dịch vụ.
- HTTPS + ghim chứng chỉ: code + `tools/gen_lab_ca.py` có, mới chạy HTTP trong máy.

## 3. Chưa làm
- Tính năng mở rộng **Điểm thưởng "Sao chăm ngoan"** (đề không bắt buộc; bạn không yêu cầu trong nhiệm vụ đêm nay).
- `OGK-Kids-Setup.exe` (PyInstaller + Inno Setup), trình gỡ yêu cầu mật khẩu phụ huynh, TOTP.
- **Khung `docs/BaoCaoKyThuatMang.md` (phụ lục M1–M6, bản nộp là `.pdf`)** — đề gọi đây là *"hạng mục trọng tâm chấm điểm"* và *"thiếu mục nào trừ điểm mục đó"*. Công cụ đo M4 đã có trong `tools/`, khung báo cáo thì chưa. **Nên làm trước tiên.**
- Tài liệu khác: `PROTOCOL.md` riêng (đề mục 4.3 bắt buộc đặc tả giao thức; nội dung hiện nằm ở `BACKEND_AND_NETWORK_GUIDE.md` §1), `PRIVACY_TRE_EM.md`, `UX_TEST.md`, kịch bản video demo.
- Alembic migration (đang dùng `create_all`).

## 4. Một điểm lệch so với yêu cầu — cần bạn quyết
Bạn ghi "`/policy` kèm ký hiệu toàn vẹn **HMAC**". Tôi cài **cả hai**: Ed25519 (mặc định) và HMAC-SHA256 (khóa riêng từng máy). Lý do chọn Ed25519 mặc định: với HMAC, khóa *kiểm* cũng là khóa *ký* và phải nằm trên máy trẻ — trái nguyên tắc P6 trong `OGK_PROMPT_BUILD.md` (bản prompt đó cũng yêu cầu Ed25519). Muốn dùng HMAC: đặt `OGK_POLICY_ALG=hmac-sha256` trước khi chạy server rồi ghép đôi lại agent. Lập luận đầy đủ để bảo vệ: `docs/BACKEND_AND_NETWORK_GUIDE.md` §2.2 và câu 10.

---

## 5. Hướng dẫn kiểm tra lúc 8:00 (khoảng 15 phút)

Mở PowerShell tại `d:\FILE CODE\Mạng máy tính` (venv `.venv` Python 3.14 đã cài đủ thư viện).

**Bước 1 — Test tự động**
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
Kỳ vọng: `86 passed` (dòng cảnh báo `httpx2` là của thư viện Starlette, không ảnh hưởng).

**Bước 2 — Chạy toàn hệ thống**
```powershell
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```
Kỳ vọng: 3 cửa sổ (SafeAnchor Server, SafeAnchor Agent, SafeAnchor Kids) + trình duyệt mở `http://127.0.0.1:8000`. Viên HUD Tíc-Tắc nổi góc phải trên màn hình; lần đầu có onboarding 4 bước.
- Windows Firewall hỏi quyền cho Python → bấm *Allow* nếu muốn mở dashboard từ điện thoại (`http://<IP máy>:8000`).
- Cửa sổ Agent báo cổng 53 bận → chạy lại: `.\run_demo.ps1 -NoReset -DnsPort 15353`.

**Bước 3 — Dashboard** (đăng nhập `demo@ogk.local` / `OgkDemo@2026`)
- Tổng quan: mục "Yêu cầu của các con" (thẻ trắng viền cam bên trái) có yêu cầu mẫu "Con sắp xong màn chơi ạ" (gắn với máy mẫu nên duyệt xong lệnh sẽ "chờ máy kết nối lại"); phần của Bin: dải số liệu nổi, 6 thẻ nhóm nội dung (bấm một thẻ hoặc một lát biểu đồ tròn để mở chi tiết), biểu đồ 7 ngày, dải navy **Thiết bị** có `PC-cua-Bin` (máy mẫu, "Ngoại tuyến") và **máy này** (tên máy thật, chấm xanh nhấp nháy "Online · Đang dùng máy" — mở Word/Scratch thì đổi thành "Đang học tập" sau ≤ 60 giây).
- Mục "Đang xem" dưới lời chào: bấm **Na** → toàn bộ số liệu đổi sang Na ngay, URL thành `?con=2` (thử cả phím ←/→).
- Cuộn xuống cuối trang: **Bắt đầu nhanh** (4 bước, bước đã làm có dấu "Đã xong") và **Câu hỏi thường gặp** (bấm từng câu để mở).
- Bấm **15 phút** (thanh công cụ nhỏ) ở thẻ **máy này** → "Đã gửi tức thì" → viên HUD trên máy cộng giờ, toast Sao Nhỏ "Mẹ đã đồng ý…".
- **Cài đặt chi tiết** (trang của Bin, một trang cuộn): đổi hạn mức, bật/tắt chip nhóm nội dung, kéo-tô lưới 7×48 hoặc bấm "Mẫu ngày đi học" → **Lưu chính sách** → "Đã lưu (phiên bản N)", nhãn phiên bản tự tăng; cuộn xuống **Nhật ký thay đổi**: "Mẹ đã đổi … từ X thành Y".
- Thu nhỏ trình duyệt về bề rộng điện thoại (F12 → Ctrl+Shift+M): thanh điều hướng chuyển xuống đáy màn hình, lưới lịch cuộn ngang trong thẻ.
- Trang của trẻ: mở `http://127.0.0.1:8000/kid/xem-cua-bin-demo-token-2026` (hoặc bấm **Tạo link cho con** — link cũ sẽ hết hiệu lực).

**Bước 4 — DNS (PowerShell mới)**
```powershell
nslookup tiktok.com 127.0.0.1            # *** Non-existent domain
nslookup m.facebook.com 127.0.0.1        # *** Non-existent domain (tên miền con)
nslookup notfacebook.com 127.0.0.1       # có địa chỉ (không chặn nhầm)
nslookup www.google.com 127.0.0.1        # Name: forcesafesearch.google.com
nslookup dns.google 127.0.0.1            # *** Non-existent domain (DoH)
nslookup -vc example.com 127.0.0.1       # qua TCP
.\.venv\Scripts\python.exe tools\measure_dns.py --samples 80
```
(Nếu dùng `-DnsPort 15353` thì thêm `-port=15353` vào nslookup và `--proxy 127.0.0.1:15353`.) Sau vài giây, Tray của trẻ hiện toast Khiên Xanh "Trang tiktok.com chưa mở cho Bin…".

**Bước 5 — Xin thêm giờ (luồng trẻ → phụ huynh, thời gian thực)**
Trên Tray của trẻ (SafeAnchor): bấm viên HUD → **🙋 Xin giờ** → chọn 30 phút, bấm một chip lý do (hoặc tự gõ) → **Gửi Mẹ**. Trên dashboard, trong ≤ 5 giây yêu cầu hiện ở mục "Yêu cầu của các con" (thẻ trắng viền cam bên trái) → (tùy chọn) "Đổi số phút hoặc gửi lời nhắn riêng" → **Đồng ý +30p** → trên máy toast "Mẹ đã đồng ý cho Bin thêm 30 phút rồi đó! Mẹ nhắn: …". Thử thêm **Nhắc con nghỉ ngơi** → toast kèm lời nhắn dịu dàng mặc định.

**Bước 6 — Khóa ngay / màn hình chặn**
Dashboard → **Khóa khẩn cấp** (xác nhận) → Tray của trẻ hiện màn chặn: Tíc-Tắc buồn ngủ nhô khỏi mép thẻ, "Máy đang tạm nghỉ", chip xin giờ nhanh (agent đang `enforce=False` nên **không** khóa Windows thật; cửa sổ Agent ghi "[enforce=False] Sẽ khóa phiên"). **Mở khóa** để quay lại. Thử **Nghỉ 2h** → màn chặn ghi "Máy tạm nghỉ đến HH:MM", dashboard hiện "Tạm nghỉ đến HH:MM"; hết hạn agent tự mở (không cần mạng).

**Bước 7 (tùy chọn, cần Admin) — chống lùi đồng hồ**
Lùi giờ hệ thống 3 tiếng (`Set-Date (Get-Date).AddHours(-3)` trong PowerShell Admin) → số phút đã dùng **không reset**, thời gian còn lại **không tăng**; heartbeat kế tiếp → Dashboard thẻ Bin hiện "⏰ … cảnh báo đồng hồ máy bị chỉnh". Nhớ đặt lại giờ (`w32tm /resync`).
⚠ Khi server chạy **cùng máy**, lùi giờ cũng lùi luôn giờ của server → heartbeat sau đó đồng bộ agent theo giờ server đã sai (lịch 7×48 có thể tính sang 05:00 = ngoài khung giờ). Bài thử chuẩn là đặt server ở **máy khác/máy ảo**; còn trên một máy, bằng chứng là 3 test `test_clock_rollback_3h…`, `test_clock_forward_to_tomorrow…`, `test_restart_after_rollback…`.

**Bước 8 — Đọc tài liệu ôn bảo vệ:** `docs/BACKEND_AND_NETWORK_GUIDE.md` (luồng gói tin, phân tích code, khái niệm mạng/HĐH, 18 câu vấn đáp có gợi ý trả lời).

**Dừng mọi thứ:** đóng 3 cửa sổ PowerShell (Ctrl+C rồi đóng). Không có thay đổi nào với DNS/firewall/registry của máy này.

---

## 6. Ghi chú kỹ thuật
- Lúc chạy thử đêm qua (02:46) agent vào trạng thái "ân hạn → tạm nghỉ" là **đúng**: lịch của Bin là 06:00–22:00. Lúc 8:00 nằm trong khung giờ.
- Khóa phát triển (`OGK_SECRET`, `OGK_DATA_KEY`, `OGK_SIGNING_KEY`) tự sinh trong `server/instance/` — đã có trong `.gitignore`, không commit.
- Cổng 5353 trên máy này do Opera giữ (mDNS) — đừng dùng cổng đó cho thử nghiệm.
- Tray dùng font Nunito TTF (`agent/tray/assets/fonts`, giấy phép OFL); web dùng Nunito/Inter WOFF2 cục bộ; HTMX 2.0.4 cục bộ (CSP `script-src 'self'`).
- Ảnh tham khảo thứ 2 (thỏ, gấu pastel) là nhân vật có bản quyền → chỉ lấy cảm hứng chung (pastel, má hồng), không sao chép.
