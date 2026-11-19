"""
agent/tray/messages_vi.py — Mẫu câu tiếng Việt theo tình huống, cá nhân hóa bằng tên gọi.

Biến: {con} tên gọi của trẻ, {xung} cách trẻ tự xưng, {ba_me} cách trẻ gọi người giám hộ,
      {phut}, {gio}, {ten_mien}, {ung_dung}, {loi_nhan}.
Mỗi tình huống có 2–3 biến thể (chọn ngẫu nhiên để không lặp). Mỗi biến thể ghi độ tuổi phù hợp:
  "mam"  = Chế độ Mầm 6–8 tuổi (câu <= 10 từ, một ý), "choi" = Chế độ Chồi 9–11 tuổi, "all" = cả hai.
Quy tắc viết: không dùng "vi phạm", "cấm", "phạt", "lỗi của con", "bị bắt", "theo dõi";
dùng "chưa mở", "tạm nghỉ", "để lần sau". Mascot xưng "tớ", không bao giờ đe dọa hay chê trách.
"""
from __future__ import annotations

import random

MESSAGES: dict[str, list[tuple[str, str]]] = {
    "good_morning": [
        ("all", "Chào buổi sáng {con}! Hôm nay mình cùng học vui nha."),
        ("choi", "Chào {con}! Hôm nay {xung} có {phut} phút dùng máy, mình dùng thật khéo nhé."),
    ],
    "warn_10": [
        ("mam", "{con} ơi, còn 10 phút nữa nha!"),
        ("choi", "{con} ơi, còn 10 phút nữa là hết giờ dùng máy hôm nay rồi nè."),
        ("choi", "Còn khoảng nửa tập phim hoạt hình (10 phút) nữa thôi {con} ơi!"),
    ],
    "warn_5": [
        ("mam", "Còn 5 phút! {xung} lưu bài dần nha."),
        ("choi", "{con} ơi, còn 5 phút nữa là hết giờ rồi nè. {xung} lưu bài lại dần nha!"),
    ],
    "warn_1": [
        ("mam", "Còn 1 phút! Mình cất đồ thôi."),
        ("choi", "Chỉ còn 1 phút thôi {con} ơi, {xung} lưu bài ngay nhé!"),
    ],
    "grace_quota": [
        ("mam", "Hết giờ chơi rồi! Tíc-Tắc đếm 60 giây nha."),
        ("choi", "Tíc-Tắc đếm ngược 60 giây để {con} cất đồ đạc gọn gàng nhé."),
    ],
    "grace_schedule": [
        ("mam", "Tới giờ nghỉ rồi! Mình lưu bài nha."),
        ("choi", "Tới giờ nghỉ theo lịch rồi {con} ơi. Tíc-Tắc cho {xung} 60 giây để lưu bài nhé."),
    ],
    "locked_quota": [
        ("mam", "Máy đi ngủ rồi. Mai chơi tiếp nha!"),
        ("choi", "Hôm nay {con} dùng đủ giờ rồi. Máy tạm nghỉ, mai mình gặp lại nhé!"),
    ],
    "locked_schedule": [
        ("mam", "Giờ nghỉ rồi. {when} chơi tiếp nha!"),
        ("choi", "Bây giờ là giờ nghỉ theo lịch {ba_me} đặt. {when} {con} dùng tiếp được nha."),
    ],
    "parent_lock": [
        ("all", "{ba_me} muốn {con} nghỉ một chút bây giờ. {xung} lưu bài rồi ra chơi với {ba_me} nhé!"),
        ("choi", "{ba_me} đã cho máy tạm nghỉ ngay lúc này. Có gì {con} hỏi {ba_me} nha."),
    ],
    "blocked_app": [
        ("mam", "{ung_dung} chưa mở cho {con}. Mình chơi trò khác nha!"),
        ("choi", "Ứng dụng {ung_dung} {ba_me} chưa mở cho {con} dùng. {xung} thử chọn một trò học tập, hoặc nhắn {ba_me} hỏi thêm nhé!"),
    ],
    "budget_exhausted": [
        ("mam", "Hết giờ trò chơi hôm nay rồi. Mai chơi tiếp nha!"),
        ("choi", "Giờ chơi trò chơi hôm nay hết rồi {con} ơi. {xung} vẫn có thể học hoặc vẽ tranh nhé!"),
    ],
    "blocked_domain": [
        ("mam", "Trang {ten_mien} chưa mở cho {con} nha."),
        ("choi", "Trang {ten_mien} chưa mở cho {con}. Mình thử trang học tập khác nhé?"),
        ("choi", "Khiên Xanh giữ trang {ten_mien} lại vì chưa hợp lứa tuổi. {con} muốn mở thì hỏi {ba_me} nha."),
    ],
    "request_sent": [
        ("all", "Đã gửi tới {ba_me} rồi! Đợi {ba_me} trả lời chút nha."),
    ],
    "request_waiting_long": [
        ("all", "Có thể {ba_me} đang bận, {xung} thử hỏi trực tiếp nhé."),
    ],
    "request_offline": [
        ("all", "Chưa gửi được vì máy đang mất mạng. {con} hỏi trực tiếp {ba_me} nhé!"),
    ],
    "request_approved": [
        ("all", "{ba_me} đã đồng ý cho {con} thêm {phut} phút rồi đó!"),
        ("choi", "Tuyệt! {ba_me} cho {con} thêm {phut} phút. Dùng thật vui nha!"),
    ],
    "request_denied": [
        ("all", "{ba_me} muốn {con} nghỉ ngơi bây giờ. Mai mình chơi tiếp nha."),
        ("choi", "Lần này {ba_me} hẹn để lần sau. {con} ra vận động một chút nhé!"),
    ],
    "unlocked": [
        ("all", "Máy đã sẵn sàng rồi {con} ơi!"),
    ],
    "break_over": [
        ("all", "Hết giờ tạm nghỉ rồi! Máy sẵn sàng cho {con} rồi nè."),
        ("choi", "Giờ nghỉ {ba_me} hẹn đã xong. {con} dùng máy tiếp được rồi nhé!"),
    ],
    "policy_updated": [
        ("all", "{ba_me} vừa cập nhật cài đặt. {con} xem ở mục \"Ai đã đổi gì\" nhé."),
    ],
    "offline_stale": [
        ("all", "Máy lâu rồi chưa kết nối mạng, nên tạm dùng giờ mặc định 2 tiếng mỗi ngày nhé."),
    ],
    "eye_break": [
        ("all", "Nhìn ra xa 20 giây cùng Tíc-Tắc nào!"),
    ],
}

NOTE_SUFFIX = " {ba_me} nhắn: \"{loi_nhan}\""


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def render(situation: str, profile: dict, mode: str | None = None, rnd: random.Random | None = None, **vars) -> str:
    """Chọn một biến thể phù hợp độ tuổi và điền tên gọi. Viết hoa đầu câu (kể cả khi {con} đứng đầu)."""
    rnd = rnd or random
    mode = mode or profile.get("age_mode", "choi")
    options = [t for m, t in MESSAGES.get(situation, []) if m in ("all", mode)] or \
              [t for _, t in MESSAGES.get(situation, [("all", "")])]
    tpl = rnd.choice(options)
    if vars.get("loi_nhan"):
        tpl += NOTE_SUFFIX
    values = {"con": profile.get("nickname") or "bạn nhỏ", "xung": profile.get("self_pronoun") or "con",
              "ba_me": profile.get("guardian_call") or "Ba Mẹ", "phut": "", "gio": "", "ten_mien": "",
              "ung_dung": "", "loi_nhan": "", "when": "Lát nữa", **{k: v for k, v in vars.items() if v is not None}}
    text = tpl.format(**values)
    # viết hoa đầu mỗi câu
    parts = [p for p in text.split(". ")]
    return ". ".join(_cap(p) for p in parts)


FORBIDDEN_WORDS = ("vi phạm", "cấm", "phạt", "lỗi của con", "bị bắt", "theo dõi")
