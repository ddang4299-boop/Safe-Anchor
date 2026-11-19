"""
agent/core.py — AgentCore: bộ não đếm giờ và quyết định khóa (logic thuần, không I/O).

Yêu cầu đề: F1 (quota, lịch 7×48, đếm thời gian thực, cảnh báo 10/5/1, ân hạn 60 giây,
chống chỉnh đồng hồ, ngân sách theo nhóm), F4 (lệnh khẩn), §4.3 (chính sách hết hạn).

Máy trạng thái:

        còn thời gian                    hết thời gian (quota hoặc lịch)
   +------------------+   remaining<=0  +------------------+  hết 60s / trẻ bấm "Nghỉ thôi"
   |      ACTIVE      | --------------> |      GRACE       | ------------------------------+
   +------------------+                 +------------------+                               |
         ^    ^   được thêm giờ / mở khóa / vào khung giờ        |                               v
         |    +---------------------------------------------+   |                     +------------------+
         +--------------------------------------------------+---+-------------------- |      LOCKED      |
                                                                                        +------------------+
   Phụ huynh "Khóa ngay": nhảy thẳng LOCKED (không ân hạn), mascot vẫn nói lý do và ai khóa.

Lớp này KHÔNG gọi Windows API. Mỗi tick trả về danh sách Action; lớp vỏ (runtime.py) thực thi:
khóa phiên, hiện thông báo trên Tray, ghi sự kiện vào hàng đợi... => test được bằng đồng hồ giả.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

from . import schedule as sch
from .clock import TrustedClock, to_local

IDLE_LIMIT_SEC = 300  # rảnh > 5 phút thì không tính giờ
MAX_TICK_DT = 5.0  # tick trễ quá 5 giây (máy ngủ/treo) thì chỉ tính tối đa 5 giây
GRACE_SEC = 60
WARN_THRESHOLDS = (10, 5, 1)  # phút

DEFAULT_POLICY: dict = {
    "version": 0,
    "policy_id": None,
    "tz_offset_min": 420,
    "quota": {"weekday_min": 120, "weekend_min": 120},
    "schedule": sch.daily_window("06:00", "21:00"),
    "category_budgets": {},
    "app_rules": {},
    "dns": {"block": [], "allow": [], "blocked_categories": ["inappropriate"], "safesearch": True, "block_doh": True},
    "categories": {},
    "profile": {"nickname": "bạn nhỏ", "self_pronoun": "con", "guardian_call": "Ba Mẹ", "age_mode": "choi"},
    "fail_mode": {"offline_days": 7, "fallback_quota_min": 120, "fallback_window": ["06:00", "21:00"]},
}


@dataclass
class Action:
    kind: str  # "notify" | "event" | "lock_session" | "unlock_session" | "integrity" | "budgets_changed" | "sync_policy" | "purge"
    data: dict = field(default_factory=dict)


class AgentCore:
    def __init__(self, clock: TrustedClock, policy: dict | None = None):
        self.clock = clock
        self.policy = policy or dict(DEFAULT_POLICY)
        self.lock = threading.RLock()  # pipe IPC chạy ở thread khác => khóa khi đọc/ghi trạng thái
        self.day: str | None = None
        self.used_sec = 0.0
        self.used_by_cat: dict[str, float] = {}
        self.bonus_min = 0
        self.warned: set[int] = set()
        self.phase = "active"
        self.lock_reason: str | None = None
        self.grace_deadline: float | None = None
        self.self_ack = False
        self.parent_lock = False
        self.parent_lock_by = ""
        # Khóa CÓ HẠN ("Tạm nghỉ 2h"): mốc hết hạn theo epoch TIN CẬY (clock.now()), không theo giờ máy =>
        # lùi đồng hồ không kéo dài/rút ngắn được; lưu trong snapshot nên khởi động lại máy vẫn giữ.
        self.parent_lock_until: float | None = None
        self.override_until: float | None = None
        self.session_locked = False
        self.idle_sec = 0.0
        self.running_categories: set[str] = set()
        self.exhausted: frozenset = frozenset()
        self.last_mono: float | None = None
        self.last_server_contact: float | None = None  # epoch tin cậy lần cuối nói chuyện được với server
        self.integrity_flag_day: str | None = None
        self.stale_notified = False
        self._seq = 0
        self.notifications: deque = deque(maxlen=50)
        self.remaining_sec = 0.0

    # ------------------------------------------------------------------ chính sách
    def set_policy(self, policy: dict) -> None:
        with self.lock:
            self.policy = policy
            self.clock.tz_offset_min = int(policy.get("tz_offset_min", 420))

    def is_stale(self) -> bool:
        """Mất kết nối server quá N ngày (đo bằng giờ tin cậy, không phải giờ máy)."""
        if self.last_server_contact is None:
            return False
        days = self.policy.get("fail_mode", {}).get("offline_days", 7)
        return self.clock.now() - self.last_server_contact > days * 86400

    def time_policy(self) -> dict:
        """Chính sách THỜI GIAN thực dùng. Quá N ngày offline => FAIL-OPEN CÓ GIỚI HẠN:
        quay về mặc định an toàn (120 phút/ngày, 6:00–21:00) thay vì khóa cứng máy của trẻ.
        Lọc nội dung KHÔNG đi qua hàm này => vẫn FAIL-CLOSED (giữ danh sách chặn cuối)."""
        if not self.is_stale():
            return self.policy
        fm = self.policy.get("fail_mode", DEFAULT_POLICY["fail_mode"])
        q = int(fm.get("fallback_quota_min", 120))
        start, end = fm.get("fallback_window", ["06:00", "21:00"])
        return {**self.policy, "quota": {"weekday_min": q, "weekend_min": q},
                "schedule": sch.daily_window(start, end), "category_budgets": {}, "grants": []}

    # ------------------------------------------------------------------ đầu vào từ vỏ
    def set_session_locked(self, locked: bool) -> None:
        with self.lock:
            self.session_locked = locked

    def report_idle(self, seconds: float) -> None:
        with self.lock:
            self.idle_sec = max(0.0, float(seconds))

    def set_running_categories(self, cats: set[str]) -> None:
        with self.lock:
            self.running_categories = set(cats)

    def server_contact(self) -> None:
        with self.lock:
            self.last_server_contact = self.clock.now()
            self.stale_notified = False

    def ack_break(self) -> bool:
        """Trẻ bấm "Nghỉ thôi, lưu bài nào" trong lúc ân hạn => khóa ngay, ghi locked/self."""
        with self.lock:
            if self.phase == "grace":
                self.self_ack = True
                return True
            return False

    # ------------------------------------------------------------------ vòng tick
    def tick(self, now_mono: float | None = None) -> list[Action]:
        with self.lock:
            return self._tick(self.clock._mono() if now_mono is None else now_mono)

    def _tick(self, mono: float) -> list[Action]:
        acts: list[Action] = []

        # 1) Phát hiện chỉnh đồng hồ tường. Quota KHÔNG bị ảnh hưởng vì ta đếm bằng monotonic.
        jump = self.clock.check_wall_jump()
        if jump:
            self.integrity_flag_day = self.day
            acts.append(Action("integrity", {"kind": "clock_jump", "delta_sec": round(jump.delta_sec, 1)}))

        # 2) Bước thời gian thực trôi, chặn trên để máy ngủ/treo không bị tính oan.
        dt = 0.0 if self.last_mono is None else min(max(0.0, mono - self.last_mono), MAX_TICK_DT)
        self.last_mono = mono

        # 3) Sang ngày mới CHỈ KHI ngày tin cậy TĂNG (lùi đồng hồ không bao giờ reset quota).
        local = self.clock.local_datetime()
        today = local.strftime("%Y-%m-%d")
        if self.day is None:
            self.day = today
        elif today > self.day:
            acts += self._rollover(today)

        pol = self.time_policy()
        if self.is_stale() and not self.stale_notified:
            self.stale_notified = True
            acts.append(self._notify("offline_stale"))

        # 4) Đếm giờ: không tính khi khóa màn hình, rảnh > 5 phút, hoặc đang LOCKED.
        counting = (not self.session_locked) and self.idle_sec < IDLE_LIMIT_SEC and self.phase != "locked"
        if counting and dt > 0:
            self.used_sec += dt
            for cat in self.running_categories:
                self.used_by_cat[cat] = self.used_by_cat.get(cat, 0.0) + dt

        # 5) Ngân sách theo nhóm (vd games 45 phút) — bộ đếm độc lập với quota tổng.
        budgets = pol.get("category_budgets", {}) or {}
        exhausted = frozenset(c for c, lim in budgets.items()
                              if lim is not None and self.used_by_cat.get(c, 0.0) >= int(lim) * 60)
        if exhausted != self.exhausted:
            newly = exhausted - self.exhausted
            self.exhausted = exhausted
            acts.append(Action("budgets_changed", {"exhausted": sorted(exhausted)}))
            for c in newly:
                acts.append(self._notify("budget_exhausted", category=c))

        # 6) Còn lại bao nhiêu = min(quota còn lại, thời gian tới ô lịch '0' kế tiếp).
        quota_sec = (sch.quota_minutes(pol, local) + self.bonus_min) * 60
        rem_quota = quota_sec - self.used_sec
        rem_sched = sch.seconds_until_block(pol["schedule"], local)
        if self.override_until is not None and mono < self.override_until:
            remaining, reason = self.override_until - mono, "override"
        else:
            self.override_until = None
            remaining = min(rem_quota, rem_sched)
            reason = "schedule" if rem_sched <= rem_quota else "quota"
        self.remaining_sec = max(0.0, remaining)

        # 6b) Hết hạn "tạm nghỉ" do phụ huynh đặt => tự mở, KHÔNG cần mạng (đã ghi sẵn mốc trong lệnh).
        if self.parent_lock and self.parent_lock_until is not None and self.clock.now() >= self.parent_lock_until:
            self.parent_lock, self.parent_lock_until = False, None
            if self.phase == "locked" and self.lock_reason == "parent":
                self.phase, self.lock_reason = "active", None  # để bước 7 xét lại: còn giờ => dùng tiếp, hết => ân hạn
                acts.append(Action("unlock_session", {}))
                acts.append(self._notify("break_over", by=self.parent_lock_by))

        # 7) Chuyển trạng thái.
        if self.parent_lock:
            if self.phase != "locked" or self.lock_reason != "parent":
                self.phase, self.lock_reason = "locked", "parent"
                acts.append(Action("lock_session", {"reason": "parent"}))
                acts.append(self._event("locked", "parent"))
                acts.append(self._notify("parent_lock", by=self.parent_lock_by))
        elif remaining <= 0:
            if self.phase == "active":
                self.phase, self.lock_reason = "grace", reason
                self.grace_deadline = mono + GRACE_SEC
                self.self_ack = False
                acts.append(self._notify("grace", reason=reason, seconds=GRACE_SEC))
            elif self.phase == "grace" and (self.self_ack or mono >= self.grace_deadline):
                self.phase = "locked"
                acts.append(Action("lock_session", {"reason": self.lock_reason}))
                acts.append(self._event("locked", "self" if self.self_ack else self.lock_reason))
                acts.append(self._notify("locked", reason=self.lock_reason, self_ack=self.self_ack))
        else:
            if self.phase in ("grace", "locked"):
                self.phase, self.lock_reason, self.grace_deadline = "active", None, None
                acts.append(Action("unlock_session", {}))
                acts.append(self._notify("unlocked"))
            # Cảnh báo 10/5/1: mỗi ngưỡng đúng 1 lần; nhiều ngưỡng bị vượt cùng lúc vẫn ghi đủ.
            crossed = [t for t in WARN_THRESHOLDS if remaining <= t * 60 and t not in self.warned]
            for t in crossed:
                self.warned.add(t)
                acts.append(self._event("quota_warning", reason, int(remaining)))
            if crossed:
                acts.append(self._notify("warn", minutes=min(crossed), reason=reason))
            # Được thêm giờ => "nạp lại" các ngưỡng ở phía trên thời gian còn lại.
            self.warned = {t for t in self.warned if remaining <= t * 60}
        return acts

    def _rollover(self, today: str) -> list[Action]:
        prev = self.day
        self.day = today
        self.used_sec = 0.0
        self.used_by_cat = {}
        self.bonus_min = 0
        self.warned = set()
        self.override_until = None
        if not self.parent_lock:
            self.phase, self.lock_reason = "active", None
        return [Action("day_rollover", {"prev": prev, "day": today}), self._notify("good_morning")]

    # ------------------------------------------------------------------ lệnh từ phụ huynh
    def apply_command(self, ctype: str, payload: dict | None = None, mono: float | None = None) -> list[Action]:
        """Áp dụng lệnh khẩn. Chống áp dụng 2 lần do lớp gọi (local_cache.applied_commands) đảm nhận."""
        payload = payload or {}
        mono = self.clock._mono() if mono is None else mono
        with self.lock:
            acts: list[Action] = []
            if ctype == "lock_now":
                self.parent_lock = True
                self.parent_lock_by = payload.get("by", "")
                minutes = int(payload.get("minutes") or 0)  # có minutes = tạm nghỉ có hạn (vd 120 phút)
                self.parent_lock_until = (self.clock.now() + min(minutes, 24 * 60) * 60) if minutes > 0 else None
            elif ctype == "unlock":
                self.parent_lock = False
                self.parent_lock_until = None
                minutes = int(payload.get("minutes", 30))
                if minutes > 0:
                    self.override_until = mono + minutes * 60
                    acts.append(self._event("override_granted", "unlock", minutes * 60))
                acts.append(self._notify("unlocked", by=payload.get("by", "")))
            elif ctype == "add_time":
                minutes = max(1, min(int(payload.get("minutes", 15)), 240))
                self.bonus_min += minutes
                acts.append(self._event("override_granted", "add_time", minutes * 60))
                acts.append(self._notify("request_approved", minutes=minutes, note=payload.get("note", ""),
                                         by=payload.get("by", "")))
            elif ctype == "request_denied":
                acts.append(self._notify("request_denied", note=payload.get("note", ""), by=payload.get("by", "")))
            elif ctype == "policy_changed":
                acts.append(Action("sync_policy", {}))
            elif ctype == "purge_data":
                acts.append(Action("purge", {}))
            else:
                raise ValueError(f"lệnh không hỗ trợ: {ctype}")
            acts += self._tick(mono)
            return acts

    # ------------------------------------------------------------------ tiện ích
    def _event(self, etype: str, subject: str, duration: int = 0) -> Action:
        return Action("event", {"type": etype, "subject": subject, "duration_sec": int(duration)})

    def _notify(self, kind: str, **data) -> Action:
        self._seq += 1
        n = {"seq": self._seq, "kind": kind, **data}
        self.notifications.append(n)
        return Action("notify", n)

    def push_notification(self, kind: str, **data) -> dict:
        with self.lock:
            return self._notify(kind, **data).data

    def status(self, since_seq: int = 0) -> dict:
        """Ảnh chụp trạng thái cho Tray (qua IPC get_status)."""
        with self.lock:
            pol = self.time_policy()
            local = self.clock.local_datetime()
            budgets = {c: {"used_min": round(self.used_by_cat.get(c, 0) / 60, 1), "limit_min": int(lim)}
                       for c, lim in (pol.get("category_budgets") or {}).items() if lim is not None}
            nxt = sch.next_allowed_start(pol["schedule"], local)
            return {
                "phase": self.phase,
                "lock_reason": self.lock_reason,
                "remaining_sec": int(self.remaining_sec),
                "used_sec": int(self.used_sec),
                "quota_min": sch.quota_minutes(pol, local) + self.bonus_min,
                "grace_left": max(0, int(self.grace_deadline - self.last_mono))
                if self.phase == "grace" and self.grace_deadline and self.last_mono else 0,
                "day": self.day,
                "now_slot": local.hour * 2 + local.minute // 30,
                "segments": sch.day_segments(pol["schedule"], local),
                "next_allowed": nxt.strftime("%H:%M") if nxt and nxt.date() == local.date() else None,
                "lock_until": to_local(self.parent_lock_until, self.clock.tz_offset_min).strftime("%H:%M")
                if self.parent_lock and self.parent_lock_until else None,
                "budgets": budgets,
                "exhausted": sorted(self.exhausted),
                "profile": self.policy.get("profile", DEFAULT_POLICY["profile"]),
                "policy_version": self.policy.get("version", 0),
                "stale": self.is_stale(),
                "clock_synced": self.clock.is_synced,
                "notifications": [n for n in self.notifications if n["seq"] > since_seq],
            }

    # ------------------------------------------------------------------ lưu/khôi phục
    def snapshot(self) -> dict:
        with self.lock:
            return {"day": self.day, "used_sec": self.used_sec, "used_by_cat": self.used_by_cat,
                    "bonus_min": self.bonus_min, "warned": sorted(self.warned),
                    "parent_lock": self.parent_lock, "parent_lock_by": self.parent_lock_by,
                    "parent_lock_until": self.parent_lock_until,
                    "last_trusted_epoch": self.clock.now(), "last_server_contact": self.last_server_contact,
                    "integrity_flag_day": self.integrity_flag_day}

    def restore(self, snap: dict) -> None:
        """Khôi phục sau khởi động lại. Ngày tin cậy chỉ tăng: nếu snapshot là 'tương lai'
        (giờ máy bị lùi), ta giữ ngày và số giờ đã dùng của snapshot."""
        with self.lock:
            if not snap:
                return
            self.clock.restore_floor(float(snap.get("last_trusted_epoch") or 0))
            self.last_server_contact = snap.get("last_server_contact")
            self.parent_lock = bool(snap.get("parent_lock"))
            self.parent_lock_by = snap.get("parent_lock_by", "")
            self.parent_lock_until = snap.get("parent_lock_until")
            self.integrity_flag_day = snap.get("integrity_flag_day")
            today = self.clock.trusted_day()
            if snap.get("day") and snap["day"] >= today:
                self.day = snap["day"]
                self.used_sec = float(snap.get("used_sec", 0))
                self.used_by_cat = dict(snap.get("used_by_cat", {}))
                self.bonus_min = int(snap.get("bonus_min", 0))
                self.warned = set(snap.get("warned", []))
