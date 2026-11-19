"""
agent/tray/view_logic.py — Logic hiển thị THUẦN của OGK Kids (không cần Qt => test được headless).

Yêu cầu: §11.4 (màu thanh thời gian mint -> vàng <= 10 phút -> san hô <= 1 phút, kèm chữ; không
chỉ dùng màu), §11.4b (màn hình chặn trả lời đủ 3 câu hỏi: Chuyện gì xảy ra? Vì sao? Bây giờ làm gì?).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import messages_vi as M

MINT, SUN, CORAL, PRIMARY = "#10B981", "#FBBF24", "#FF6B6B", "#2563EB"
ORANGE = "#FF8E53"  # cam ấm (cuối dải màu thời gian)


def _mix(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def smooth_time_color(remaining_sec: int) -> str:
    """Màu thanh thời gian chuyển MƯỢT: Mint (>= 20 phút) -> Vàng nắng (10 phút) -> Cam ấm (0 phút).
    Luôn đi kèm chữ số phút (không chỉ dùng màu — cho trẻ mù màu)."""
    m = max(0.0, remaining_sec / 60)
    if m >= 20:
        return MINT
    if m >= 10:
        return _mix(SUN, MINT, (m - 10) / 10)
    return _mix(ORANGE, SUN, m / 10)


def quick_reasons(profile: dict) -> list[str]:
    """Chip chọn nhanh lý do xin thêm giờ (trẻ nhỏ không phải gõ). Mỗi câu <= 200 ký tự (giới hạn IPC)."""
    xung = profile.get("self_pronoun", "con")
    x = xung[:1].upper() + xung[1:]
    return [f"{x} đang làm nốt bài tập", f"Cho {xung} xin thêm 15 phút nữa nhé", f"{x} sắp lưu bài xong ạ"]


def today_tiles(status: dict, today: dict | None) -> dict:
    """Số liệu cho Bento "Hôm nay": học tập, giải trí, huy hiệu đúng giờ (dùng máy trong hạn mức)."""
    cats = (today or {}).get("cats_today") or {}
    used = int(status.get("used_sec", 0)) // 60
    quota = int(status.get("quota_min", 0) or 0)
    return {"used": used, "quota": quota, "study": int(cats.get("education", 0)),
            "fun": int(cats.get("games", 0)) + int(cats.get("entertainment", 0)),
            "on_time": quota > 0 and used <= quota and status.get("phase") != "locked"}


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
        "offline_stale": ("khien", "remind"), "break_over": ("sao", "happy"),
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
            until = status.get("lock_until")  # "Tạm nghỉ 2h": báo trước giờ mở lại => trẻ không bị bất ngờ
            return BlockScreen("tictac", "sleepy", what=f"Máy tạm nghỉ đến {until}." if until else "Máy đang tạm nghỉ.",
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
    if kind in ("unlocked", "policy_updated", "good_morning", "offline_stale", "budget_exhausted", "break_over"):
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
