"""
agent/tray/view_logic.py — Logic hiển thị THUẦN của OGK Kids (không cần Qt => test được headless).

Yêu cầu: §11.4 (màu thanh thời gian mint -> vàng <= 10 phút -> san hô <= 1 phút, kèm chữ; không
chỉ dùng màu), §11.4b (màn hình chặn trả lời đủ 3 câu hỏi: Chuyện gì xảy ra? Vì sao? Bây giờ làm gì?).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import messages_vi as M

MINT, SUN, CORAL, PRIMARY = "#10B981", "#FBBF24", "#FF6B6B", "#2563EB"


def time_color(remaining_sec: int) -> str:
    m = remaining_sec / 60
    if m <= 1:
        return CORAL
    if m <= 10:
        return SUN
    return MINT


def time_icon(remaining_sec: int) -> str:
    """Biểu tượng đi kèm màu (cho trẻ mù màu)."""
    m = remaining_sec / 60
    return "⏰" if m <= 1 else ("⏳" if m <= 10 else "🙂")


def format_remaining(remaining_sec: int, mode: str = "choi") -> str:
    m = max(0, int(round(remaining_sec / 60)))
    if m >= 60:
        h, r = divmod(m, 60)
        s = f"{h} giờ {r} phút" if r else f"{h} giờ"
    else:
        s = f"{m} phút"
    return s if mode == "mam" else f"còn {s}"


def mascot_for(kind: str) -> tuple[str, str]:
    """(nhân vật, biểu cảm). Không bao giờ giận dữ: nhắc nhở dùng 'remind'/'sleepy'/'encourage'."""
    return {
        "warn": ("tictac", "remind"), "grace": ("tictac", "remind"), "locked": ("tictac", "sleepy"),
        "parent_lock": ("tictac", "sleepy"), "blocked_app": ("khien", "encourage"),
        "blocked_domain": ("khien", "happy"), "budget_exhausted": ("tictac", "encourage"),
        "request_approved": ("sao", "celebrate"), "request_denied": ("sao", "encourage"),
        "unlocked": ("sao", "happy"), "good_morning": ("tictac", "happy"), "policy_updated": ("khien", "happy"),
        "offline_stale": ("khien", "remind"),
    }.get(kind, ("tictac", "happy"))


@dataclass
class BlockScreen:
    """Nội dung màn hình chặn: luôn trả lời đủ 3 câu hỏi của trẻ."""
    mascot: str
    mood: str
    what: str  # Chuyện gì xảy ra?
    why: str  # Vì sao?
    next_steps: list = field(default_factory=list)  # Bây giờ mình làm gì được?
    countdown: int = 0
    can_request: bool = True
    can_ack_break: bool = False


def block_screen(status: dict, notification: dict | None = None) -> BlockScreen | None:
    profile = status.get("profile", {})
    mode = profile.get("age_mode", "choi")
    call = profile.get("guardian_call", "Ba Mẹ")
    phase = status.get("phase")
    reason = status.get("lock_reason")
    when = status.get("next_allowed")
    if notification and notification.get("kind") == "blocked_app":
        app = notification.get("app", "Ứng dụng")
        return BlockScreen("khien", "encourage",
                           what=f"{app} vừa được đóng lại.",
                           why=M.render("blocked_app", profile, mode, ung_dung=app),
                           next_steps=["Chọn một trò học tập", "Vẽ tranh hoặc đọc sách", f"Nhắn {call} hỏi thêm"],
                           can_request=False)
    if phase == "grace":
        sit = "grace_schedule" if reason == "schedule" else "grace_quota"
        return BlockScreen("tictac", "remind", what="Sắp tới giờ nghỉ rồi.",
                           why=M.render(sit, profile, mode),
                           next_steps=["Lưu bài đang làm", f"Xin {call} thêm giờ"],
                           countdown=int(status.get("grace_left", 60)), can_ack_break=True)
    if phase == "locked":
        if reason == "parent":
            return BlockScreen("tictac", "sleepy", what="Máy đang tạm nghỉ.",
                               why=M.render("parent_lock", profile, mode),
                               next_steps=[f"Ra nói chuyện với {call}", "Uống nước, vận động một chút"])
        sit = "locked_schedule" if reason == "schedule" else "locked_quota"
        when_txt = f"{when}" if when else "Ngày mai"
        return BlockScreen("tictac", "sleepy", what="Máy đang tạm nghỉ.",
                           why=M.render(sit, profile, mode, when=when_txt),
                           next_steps=[f"Xin {call} thêm giờ", "Đọc sách, vẽ tranh, chơi ngoài trời"])
    return None


def toast_text(n: dict, profile: dict) -> str | None:
    kind = n.get("kind")
    mode = profile.get("age_mode", "choi")
    if kind == "warn":
        return M.render(f"warn_{int(n.get('minutes', 10))}", profile, mode)
    if kind == "blocked_domain":
        return M.render("blocked_domain", profile, mode, ten_mien=n.get("domain", ""))
    if kind == "request_approved":
        return M.render("request_approved", profile, mode, phut=n.get("minutes", 15), loi_nhan=n.get("note") or None)
    if kind == "request_denied":
        return M.render("request_denied", profile, mode, loi_nhan=n.get("note") or None)
    if kind in ("unlocked", "policy_updated", "good_morning", "offline_stale", "budget_exhausted"):
        return M.render(kind, profile, mode, phut=status_quota(profile))
    return None


def status_quota(profile: dict) -> str:
    return str(profile.get("quota_min", ""))


def timeline(segments: list, now_slot: int) -> list[dict]:
    """Dải thời gian cả ngày cho thẻ "Hôm nay": [{start, end, allowed, label}], kèm vị trí "bây giờ"."""
    out = []
    for a, b, ok in segments:
        out.append({"start": a, "end": b, "allowed": bool(ok),
                    "label": f"{a // 2:02d}:{(a % 2) * 30:02d}–{b // 2:02d}:{(b % 2) * 30:02d}", "now": a <= now_slot < b})
    return out
