"""
agent/schedule.py — Lịch tuần 7×48 và hạn mức (quota) ngày thường / cuối tuần.

Yêu cầu đề: F1 (quota riêng ngày thường/cuối tuần, lịch tuần độ phân giải 30 phút).

Lịch được lưu thành CHUỖI 336 KÝ TỰ '0'/'1' (7 ngày × 48 ô 30 phút):
    chỉ số ô = thứ * 48 + giờ * 2 + (phút // 30)      (thứ: Thứ Hai = 0 ... Chủ Nhật = 6)
    '1' = được dùng, '0' = giờ nghỉ.
Lý do chọn chuỗi: gọn (336 byte), so sánh/ký/diff dễ, kiểm tra hợp lệ bằng 1 regex,
JSON hóa trực tiếp; ma trận 2 chiều chỉ là cách hiển thị.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

SLOTS_PER_DAY = 48
SLOTS = 7 * SLOTS_PER_DAY  # 336
_VALID = re.compile(r"^[01]{336}$")


def validate(schedule: str) -> bool:
    return bool(_VALID.match(schedule or ""))


def slot_index(dt: datetime) -> int:
    return dt.weekday() * SLOTS_PER_DAY + dt.hour * 2 + dt.minute // 30


def is_allowed(schedule: str, dt: datetime) -> bool:
    return schedule[slot_index(dt)] == "1"


def make_schedule(windows: dict[int, list[tuple[str, str]]]) -> str:
    """Dựng chuỗi từ {thứ: [("06:00","21:00"), ...]} (giờ kết thúc không tính)."""
    cells = ["0"] * SLOTS
    for day, ranges in windows.items():
        for start, end in ranges:
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
            a = sh * 2 + sm // 30
            b = eh * 2 + em // 30
            for i in range(a, b):
                cells[day * SLOTS_PER_DAY + i] = "1"
    return "".join(cells)


def daily_window(start: str = "06:00", end: str = "21:00") -> str:
    return make_schedule({d: [(start, end)] for d in range(7)})


def seconds_until_block(schedule: str, dt: datetime, horizon_slots: int = SLOTS) -> float:
    """Số giây từ dt tới lúc bắt đầu ô '0' kế tiếp (0 nếu đang ở ô '0')."""
    if not is_allowed(schedule, dt):
        return 0.0
    idx = slot_index(dt)
    slot_start = dt.replace(minute=(dt.minute // 30) * 30, second=0, microsecond=0)
    for k in range(1, horizon_slots + 1):
        if schedule[(idx + k) % SLOTS] == "0":
            return ((slot_start + timedelta(minutes=30 * k)) - dt).total_seconds()
    return float("inf")  # cả tuần đều được dùng


def next_allowed_start(schedule: str, dt: datetime) -> datetime | None:
    """Thời điểm sớm nhất được dùng lại (để Tray nói "15:00 được dùng tiếp")."""
    if is_allowed(schedule, dt):
        return dt
    idx = slot_index(dt)
    slot_start = dt.replace(minute=(dt.minute // 30) * 30, second=0, microsecond=0)
    for k in range(1, SLOTS + 1):
        if schedule[(idx + k) % SLOTS] == "1":
            return slot_start + timedelta(minutes=30 * k)
    return None


def is_weekend(dt: datetime) -> bool:
    return dt.weekday() >= 5


def quota_minutes(policy: dict, dt: datetime) -> int:
    """Quota của ngày dt: cuối tuần (T7, CN) dùng weekend_min, còn lại weekday_min.
    Cộng thêm các 'grant' theo ngày (vd đổi điểm lấy 1 giờ chơi thứ Bảy)."""
    q = policy.get("quota", {})
    base = int(q.get("weekend_min" if is_weekend(dt) else "weekday_min", 120))
    day = dt.strftime("%Y-%m-%d")
    extra = sum(int(g.get("minutes", 0)) for g in policy.get("grants", []) if g.get("date") == day)
    return base + extra


def day_segments(schedule: str, dt: datetime) -> list[tuple[int, int, bool]]:
    """Gộp 48 ô của ngày dt thành các đoạn (ô_bắt_đầu, ô_kết_thúc, được_dùng) cho dải thời gian trên Tray."""
    base = dt.weekday() * SLOTS_PER_DAY
    day = schedule[base:base + SLOTS_PER_DAY]
    segs: list[tuple[int, int, bool]] = []
    start = 0
    for i in range(1, SLOTS_PER_DAY + 1):
        if i == SLOTS_PER_DAY or day[i] != day[start]:
            segs.append((start, i, day[start] == "1"))
            start = i
    return segs
