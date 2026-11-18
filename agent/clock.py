"""
agent/clock.py — Đồng hồ tin cậy: đồng hồ đơn điệu + giờ server (thuật toán Cristian).

Yêu cầu đề: F1 (chống chỉnh đồng hồ: lùi 3 giờ không làm tăng quota, có ghi sự kiện), M6.

Hai loại đồng hồ trong hệ điều hành:
  * Đồng hồ tường (wall clock, time.time()): giờ "lịch", NGƯỜI DÙNG SỬA ĐƯỢC (Settings,
    lệnh `date`, hoặc NTP tự chỉnh). Có thể nhảy tới/lùi bất kỳ lúc nào.
  * Đồng hồ đơn điệu (monotonic, time.monotonic()): bộ đếm tăng đều kể từ lúc khởi động
    (Windows: QueryPerformanceCounter). KHÔNG BAO GIỜ đi lùi và KHÔNG bị chỉnh giờ ảnh
    hưởng. Không có ý nghĩa "mấy giờ", chỉ dùng để đo KHOẢNG thời gian.

=> Thời lượng sử dụng luôn đếm bằng hiệu monotonic. Giờ "tin cậy" (để biết hôm nay là
ngày nào, đang ở ô lịch nào) = điểm neo giờ server + thời gian đơn điệu đã trôi kể từ neo:

    trusted_now = server_time_at_anchor + (monotonic() - mono_at_anchor)

Đồng bộ kiểu Cristian (1989): agent ghi t0 (mono) trước khi gửi heartbeat, t1 sau khi nhận
phản hồi chứa server_time T. Giả định đường đi và về bằng nhau => lúc nhận, giờ server ≈
T + (t1 - t0)/2. Sai số tối đa ±(t1 - t0)/2 (một nửa RTT, thường vài chục ms trong LAN).

Phát hiện chỉnh giờ: đại lượng (wall - mono) phải gần như hằng số. Nếu nó đổi hơn 60 giây
giữa hai lần kiểm => ai đó vừa chỉnh đồng hồ tường => phát sinh cảnh báo toàn vẹn.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

JUMP_THRESHOLD_SEC = 60.0  # |Δ(wall - mono)| > 60 giây => coi là chỉnh giờ
SKEW_WARN_SEC = 120.0  # giờ máy lệch giờ server quá 120 giây => cảnh báo


@dataclass
class ClockJump:
    delta_sec: float  # dương: tua tới, âm: lùi lại
    wall_before: float
    wall_after: float


class TrustedClock:
    def __init__(self, mono: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 tz_offset_min: int = 420):
        self._mono = mono
        self._wall = wall
        self.tz_offset_min = tz_offset_min  # Việt Nam UTC+7 = 420 phút
        self._anchor_server: float | None = None  # epoch server tại điểm neo
        self._anchor_mono: float | None = None
        self.last_rtt: float | None = None
        self._baseline = self._wall() - self._mono()  # (wall - mono) tham chiếu
        # Mốc chặn dưới khi khởi động lại mà chưa có mạng (lưu xuống đĩa định kỳ).
        self._floor_epoch: float = 0.0

    # ---- đồng bộ ----
    def sync_cristian(self, server_time: float, t0_mono: float, t1_mono: float) -> float:
        """Neo đồng hồ theo phản hồi server. Trả độ lệch (wall - trusted) để báo cáo."""
        rtt = max(0.0, t1_mono - t0_mono)
        self.last_rtt = rtt
        self._anchor_server = server_time + rtt / 2.0
        self._anchor_mono = t1_mono
        return self.skew()

    def restore_floor(self, last_trusted_epoch: float) -> None:
        """Khởi động lại khi offline: giờ tin cậy không được nhỏ hơn giờ tin cậy cuối đã lưu.
        Nếu trẻ lùi đồng hồ rồi khởi động lại máy, ta vẫn neo vào mốc này."""
        self._floor_epoch = max(self._floor_epoch, last_trusted_epoch)
        if self._anchor_server is None and self._wall() < self._floor_epoch:
            self._anchor_server = self._floor_epoch
            self._anchor_mono = self._mono()

    @property
    def is_synced(self) -> bool:
        return self._anchor_server is not None

    # ---- đọc giờ ----
    def now(self) -> float:
        """Epoch tin cậy (giây, UTC)."""
        if self._anchor_server is None:
            return max(self._wall(), self._floor_epoch)
        return self._anchor_server + (self._mono() - self._anchor_mono)

    def local_datetime(self) -> datetime:
        tz = timezone(timedelta(minutes=self.tz_offset_min))
        return datetime.fromtimestamp(self.now(), tz)

    def trusted_day(self) -> str:
        return self.local_datetime().strftime("%Y-%m-%d")

    def skew(self) -> float:
        """Giờ máy - giờ tin cậy (giây). |skew| > 120 => cảnh báo lệch giờ."""
        return self._wall() - self.now()

    # ---- phát hiện chỉnh giờ ----
    def check_wall_jump(self) -> ClockJump | None:
        """Gọi mỗi giây. Nếu (wall - mono) đổi > 60s so với tham chiếu => trả ClockJump."""
        current = self._wall() - self._mono()
        delta = current - self._baseline
        if abs(delta) > JUMP_THRESHOLD_SEC:
            jump = ClockJump(delta, self._baseline + self._mono(), self._wall())
            self._baseline = current  # cập nhật tham chiếu để không báo lặp lại
            return jump
        # Trôi nhỏ (NTP chỉnh vài ms) thì hấp thụ dần vào tham chiếu.
        self._baseline = current
        return None


def to_local(epoch: float, tz_offset_min: int) -> datetime:
    return datetime.fromtimestamp(epoch, timezone(timedelta(minutes=tz_offset_min)))
