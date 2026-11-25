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


def time_mood(remaining_sec: int) -> str:
    """Nét mặt mascot Tíc-Tắc đi kèm màu (để trẻ mù màu vẫn biết sắp hết giờ): nhắc nhở khi còn <= 10 phút."""
    return "remind" if remaining_sec <= 600 else "happy"


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


MASCOT_NAMES = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}

# Nét mặt của khung ảnh 3D (atlas) theo "tâm trạng" của mascot SVG cũ => thay thế được tại chỗ
MOOD_TO_EXPR = {"happy": "happy", "encourage": "happy", "remind": "wow", "sleepy": "sleepy", "celebrate": "joy"}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def mascot_lines(kind: str, profile: dict | None, remaining_sec: int | None = None, phase: str | None = None,
                 study_min: int = 0, now=None) -> dict[str, list[str]]:
    """Lời thoại khi trẻ chạm vào mascot 3D (giống bản web, dùng số liệu thật của trẻ).

    Trả về {"poke": [...], "tickle": [...], "party": [...], "hint": [...]}. Chỉ nói điều tích cực / nhắc nhẹ:
    KHÔNG nhắc số lần bị chặn hay tên trang bị chặn (trẻ không cảm thấy bị theo dõi).
    """
    from datetime import datetime
    p = profile or {}
    name = (p.get("nickname") or "bạn").strip() or "bạn"
    me = (p.get("self_pronoun") or "con").strip() or "con"
    guardian = (p.get("guardian_call") or "ba mẹ").strip() or "ba mẹ"
    now = now or datetime.now()
    clock = f"{now.hour:02d}:{now.minute:02d}"
    if kind == "tictac":
        if phase == "locked":
            poke = [f"Máy đang tạm nghỉ, mình nghỉ ngơi chút nha {name}!", f"Ngủ ngon nha, Tíc-Tắc canh giờ cho {me} rồi."]
        elif remaining_sec is None:
            poke = [f"Bây giờ là {clock} nè!", f"Cứ 30 phút mình nghỉ mắt một chút nha {name}!"]
        elif remaining_sec <= 0:
            poke = [f"Hôm nay hết giờ rồi, mai mình chơi tiếp nha {name}!", f"Ngủ ngon nha, Tíc-Tắc canh giờ cho {me} rồi."]
        elif remaining_sec <= 600:
            left = max(1, round(remaining_sec / 60))
            poke = [f"Còn {left} phút thôi, {me} lưu bài trước nhé!", f"Reng reng! Sắp hết giờ rồi đó {name}."]
        else:
            poke = [f"Reng reng! Hôm nay {me} {format_remaining(remaining_sec)} nữa đó.", f"Bây giờ là {clock} nè!",
                    f"Cứ 30 phút mình nghỉ mắt một chút nha {name}!"]
    elif kind == "khien":
        poke = [f"Khiên Xanh luôn che chắn cho {name} khi lên mạng!", f"Gặp trang lạ thì hỏi {guardian} nha.",
                f"{_cap(me)} thấy rõ mọi quy tắc — không có gì bí mật đâu!", f"Đừng cho người lạ biết mật khẩu nha {name}!"]
    else:
        poke = [f"Hôm nay {me} học {study_min} phút rồi đó, tuyệt quá!" if study_min > 0 else "Học một chút là có thêm ngôi sao nè!",
                f"Sao Nhỏ tin {name} làm được mà!", "Mình cùng giữ đúng giờ để được huy hiệu nha!"]
    return {"poke": poke, "tickle": ["Hihi, nhột quá!", "Á á, đừng cù nữa mà!", "Hihihi!"],
            "party": [f"Cả nhà cùng nhảy với {name} nào!"], "hint": [f"Chạm vào tớ thử xem, {name}!"]}


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


# ============================================================================ giao diện mới (Child App 2026)
WEEKDAYS_VI = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")
FUN_NAMES = {"games": "trò chơi", "entertainment": "giải trí"}
# (nền, chữ) cho ảnh đại diện chữ cái — màu chọn theo CRC32 của tên => cố định giữa các lần chạy
# (không dùng hash() của Python: giá trị đổi theo từng tiến trình).
AVATAR_COLORS = (("#E0E7FF", "#4338CA"), ("#D1FAE5", "#047857"), ("#FEF3C7", "#B45309"),
                 ("#FFE4E6", "#BE123C"), ("#EDE9FE", "#6D28D9"), ("#E0F2FE", "#0369A1"))


def greeting(profile: dict | None, now=None) -> str:
    """Dòng chào trên thanh tiêu đề: "Chào Bin! Hôm nay là Thứ Sáu, 20/11"."""
    from datetime import datetime
    now = now or datetime.now()
    name = ((profile or {}).get("nickname") or "bạn").strip() or "bạn"
    return f"Chào {name}! Hôm nay là {WEEKDAYS_VI[now.weekday()]}, {now:%d/%m}"


def hero_time(status: dict) -> dict:
    """Thẻ chính tầng 1: MỘT thông điệp (còn bao lâu) + tỉ lệ đã dùng / hạn mức.

    Thời gian còn lại = min(hạn mức còn lại, thời gian tới giờ nghỉ kế tiếp) (agent/core.py). Khi khung giờ
    hết TRƯỚC hạn mức, ghi rõ "trong khung giờ này" để con không thắc mắc vì sao hai con số lệch nhau."""
    rem = max(0, int(status.get("remaining_sec", 0) or 0))
    used = max(0, int(status.get("used_sec", 0) or 0)) // 60
    quota = max(0, int(status.get("quota_min", 0) or 0))
    locked = status.get("phase") == "locked"
    if locked:
        until = status.get("lock_until") or status.get("next_allowed")
        eyebrow = f"TẠM NGHỈ ĐẾN {until}" if until else "MÁY ĐANG TẠM NGHỈ"
    elif quota and rem < (quota - used) * 60 - 60:
        eyebrow = "CÒN LẠI TRONG KHUNG GIỜ NÀY"
    else:
        eyebrow = "CÒN LẠI HÔM NAY"
    return {"locked": locked, "eyebrow": eyebrow,
            "big": "Nghỉ ngơi chút nha" if locked else format_remaining(rem, "mam"),
            "used": used, "quota": quota, "ratio": min(1.0, used / quota) if quota else 1.0,
            "ratio_text": f"Đã dùng {used} / {quota} phút", "low": not locked and rem <= 600}


def request_status(status: dict, profile: dict | None) -> tuple[str, str] | None:
    """Nhãn trạng thái dưới nút "Xin thêm giờ" (yêu cầu mới nhất): Đã gửi -> Ba/Mẹ đang xem -> Đồng ý / Lần sau."""
    reqs = status.get("requests") or []
    if not reqs:
        return None
    call = ((profile or {}).get("guardian_call") or "Ba Mẹ").strip() or "Ba Mẹ"
    return {"pending": ("pending", f"Đã gửi — {call} đang xem…"),
            "approved": ("approved", f"✓ {call} đã đồng ý thêm giờ"),
            "denied": ("denied", f"{call} hẹn để lần sau nhé")}.get(reqs[-1].get("status"))


def study_note(minutes: int) -> str:
    """Nhãn tích cực cho Góc Học Tập. Học KHÔNG có giới hạn riêng nhưng VẪN tính vào thời gian cả ngày
    (agent/core.py cộng mọi phút vào used_sec) => không ghi "Không giới hạn" trơn để khỏi hiểu lầm."""
    return "Không giới hạn riêng — Cố lên nhé!" if minutes > 0 else "Mở bài học cùng Sao Nhỏ nhé!"


def fun_card(status: dict, today: dict | None) -> dict:
    """Góc Giải Trí: dùng ngân sách theo nhóm (đếm trực tiếp trên máy) nếu ba mẹ có đặt; nếu không thì
    chỉ hiện số phút từ báo cáo của server, không vẽ thanh (không có mốc để so)."""
    budgets = status.get("budgets") or {}
    cats = [c for c in ("games", "entertainment") if c in budgets]
    if cats:
        used = round(sum(float(budgets[c].get("used_min", 0) or 0) for c in cats))
        limit = sum(int(budgets[c].get("limit_min", 0) or 0) for c in cats)
        names = " + ".join(FUN_NAMES[c] for c in cats)
        left = max(0, limit - used)
        note = f"Còn {left} phút {names} hôm nay" if left else f"Hết giờ {names} hôm nay rồi — mai chơi tiếp nhé!"
        return {"big": f"{used} / {limit} phút", "ratio": min(1.0, used / limit) if limit else 1.0, "note": note,
                "used": used, "limit": limit}
    c = (today or {}).get("cats_today") or {}
    used = int(c.get("games", 0) or 0) + int(c.get("entertainment", 0) or 0)
    return {"big": f"{used} phút", "ratio": None, "note": "Chơi 30 phút thì nghỉ mắt một chút nhé!", "used": used, "limit": None}


def now_minute(status: dict) -> int:
    """Phút trong ngày cho kim "bây giờ" (đồng hồ của agent — đã đồng bộ với server, không phải đồng hồ Windows)."""
    if status.get("now_min") is not None:
        return max(0, min(1439, int(status["now_min"])))
    return int(status.get("now_slot", 0) or 0) * 30 + 15


def avatar_colors(key: str) -> tuple[str, str]:
    import zlib
    return AVATAR_COLORS[zlib.crc32((key or "").lower().encode("utf-8")) % len(AVATAR_COLORS)]


def explore_rows(today: dict | None, n: int = 6) -> dict[str, list[dict]]:
    """Danh sách "Đã khám phá gì": tên thân thiện + thanh độ dài. Ứng dụng đo bằng PHÚT; trang web đo bằng
    LƯỢT GHÉ (agent ghi mỗi tên miền tối đa 1 lần / 10 phút — tối thiểu hóa dữ liệu, không có số phút)."""
    from agent.app_names import app_display
    t = today or {}
    apps = [a for a in (t.get("top_apps") or []) if a.get("name")][:n]
    doms = [d for d in (t.get("top_domains") or []) if d.get("name")][:n]
    amax = max([int(a.get("minutes") or 0) for a in apps] + [1])
    dmax = max([int(d.get("count") or 0) for d in doms] + [1])
    out_apps = []
    for a in apps:
        title = a.get("display") or app_display(a["name"])
        m = int(a.get("minutes") or 0)
        out_apps.append({"title": title, "value": f"{m} phút" if m else "dưới 1 phút", "ratio": m / amax,
                         "initial": title[:1].upper(), "colors": avatar_colors(a["name"])})
    out_doms = [{"title": d["name"], "value": f"{int(d.get('count') or 0)} lần ghé",
                 "ratio": int(d.get("count") or 0) / dmax, "initial": d["name"][:1].upper(),
                 "colors": avatar_colors(d["name"])} for d in doms]
    return {"apps": out_apps, "domains": out_doms}


def audit_chat(items: list[dict], profile: dict | None) -> list[dict]:
    """Nhật ký "Ai đã đổi gì" thành dòng trò chuyện: "19:50 hôm nay — Mẹ đã đồng ý tặng thêm 15 phút cho Bin".

    items: [{"when": "hôm nay, 19:50", "lines": [...]}] (server/audit.py). Mỗi câu một bong bóng; người nói
    lấy từ đầu câu (tên gọi người giám hộ / Con / Máy tính / Hệ thống)."""
    import re
    p = profile or {}
    call = (p.get("guardian_call") or "").strip()
    name = (p.get("nickname") or "").strip()
    out = []
    for it in items or []:
        when = str(it.get("when", ""))
        day, _, hm = when.partition(", ")
        stamp = f"{hm} {day}".strip() if hm else when
        for line in it.get("lines") or []:
            line = str(line)
            if line.startswith("Con "):
                who = "child"
            elif line.startswith(("Máy tính", "Hệ thống", "Phát hiện")):
                who = "system"
            else:
                who = "guardian"
            if who == "guardian" and name and re.search(r"thêm \d+ phút$", line):
                line = line.replace("đồng ý cho thêm", "đồng ý tặng thêm") + f" cho {name}"
            low = line.lower()
            kind = ("ask" if who == "child" else "gift" if "thêm" in low and "phút" in low
                    else "rest" if "tạm nghỉ" in low or "mở lại" in low
                    else "time" if "giờ" in low or "phút" in low else "shield" if who == "system" else "edit")
            speaker = (call if who == "guardian" and call and line.startswith(call)
                       else name if who == "child" and name else line.split(" đã ")[0])
            out.append({"stamp": stamp, "text": line, "who": who, "kind": kind,
                        "initial": (speaker[:1] or "?").upper()})
    return out
