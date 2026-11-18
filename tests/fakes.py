"""Đồng hồ giả dùng chung cho test (điều khiển riêng monotonic và wall)."""
from datetime import datetime, timedelta, timezone

VN = timezone(timedelta(hours=7))


class FakeClock:
    def __init__(self, wall_dt: datetime):
        self.m = 1000.0
        self.w = wall_dt.timestamp()

    def mono(self):
        return self.m

    def wall(self):
        return self.w

    def advance(self, sec: float):
        self.m += sec
        self.w += sec

    def set_wall_offset(self, delta: float):
        """Người dùng chỉnh giờ hệ thống: chỉ wall đổi, monotonic giữ nguyên."""
        self.w += delta


def vn(y, mo, d, h=10, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=VN)
