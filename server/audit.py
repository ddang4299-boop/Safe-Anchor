"""
server/audit.py — Ghi và "dịch sang lời" nhật ký kiểm toán.

Yêu cầu đề: F4 (BẮT BUỘC: audit mọi thay đổi — ai, lúc nào, IP, giá trị cũ, giá trị mới;
trẻ được quyền xem — NT5, hiển thị bằng lời dễ hiểu).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import AuditLog

FIELD_LABELS = {
    "quota.weekday_min": ("giờ dùng ngày thường", "phút"),
    "quota.weekend_min": ("giờ dùng cuối tuần", "phút"),
    "category_budgets.games": ("giờ chơi trò chơi mỗi ngày", "phút"),
    "category_budgets.entertainment": ("giờ giải trí mỗi ngày", "phút"),
    "schedule": ("lịch giờ được dùng trong tuần", ""),
    "dns.block": ("danh sách trang web tạm chưa mở", ""),
    "dns.allow": ("danh sách trang web luôn được mở", ""),
    "dns.blocked_categories": ("các nhóm trang web tạm chưa mở", ""),
    "dns.safesearch": ("chế độ Tìm kiếm an toàn", ""),
    "dns.block_doh": ("chống đường vòng DNS-over-HTTPS", ""),
    "app_rules.block_names": ("danh sách ứng dụng tạm chưa mở", ""),
    "app_rules.block_sha256": ("danh sách ứng dụng tạm chưa mở (theo mã băm)", ""),
    "app_rules.allow_names": ("danh sách ứng dụng luôn được mở", ""),
}

CATEGORY_VI = {"education": "Học tập", "entertainment": "Giải trí", "social": "Mạng xã hội",
               "games": "Trò chơi", "inappropriate": "Chưa phù hợp lứa tuổi", "uncategorized": "Khác"}


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and k not in ("categories",):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def policy_diff(old: dict, new: dict) -> tuple[dict, dict]:
    fo, fn = flatten(old or {}), flatten(new or {})
    keys = [k for k in sorted(set(fo) | set(fn)) if fo.get(k) != fn.get(k)]
    return {k: fo.get(k) for k in keys}, {k: fn.get(k) for k in keys}


def record(db: Session, *, actor_type: str, actor_id: str = "", actor_label: str = "", ip: str = "",
           child_id: int | None, entity: str, action: str, old=None, new=None) -> AuditLog:
    entry = AuditLog(ts=time.time(), actor_type=actor_type, actor_id=str(actor_id), actor_label=actor_label,
                     ip=ip, child_id=child_id, entity=entity, action=action,
                     old_json=json.dumps(old, ensure_ascii=False), new_json=json.dumps(new, ensure_ascii=False))
    db.add(entry)
    return entry


def _fmt(v, unit: str) -> str:
    if isinstance(v, bool):
        return "bật" if v else "tắt"
    if isinstance(v, list):
        if not v:
            return "(trống)"
        return ", ".join(CATEGORY_VI.get(x, x) for x in v[:5]) + (" …" if len(v) > 5 else "")
    if v is None:
        return "(chưa có)"
    return f"{v} {unit}".strip()


def when_text(ts: float, tz_offset_min: int = 420, now: float | None = None) -> str:
    tz = timezone(timedelta(minutes=tz_offset_min))
    d = datetime.fromtimestamp(ts, tz)
    today = datetime.fromtimestamp(now or time.time(), tz).date()
    if d.date() == today:
        day = "hôm nay"
    elif d.date() == today - timedelta(days=1):
        day = "hôm qua"
    else:
        day = d.strftime("%d/%m")
    return f"{day}, {d.strftime('%H:%M')}"


def actor_text(e: AuditLog) -> str:
    """Ai đã làm: tên gọi người giám hộ ("Mẹ"), hoặc "Máy tính"/"Hệ thống"/"Con"."""
    return e.actor_label or {"parent": "Ba mẹ", "device": "Máy tính", "system": "Hệ thống",
                             "child": "Con"}.get(e.actor_type, "Ai đó")


def humanize(e: AuditLog) -> list[str]:
    """Trả về các câu dễ hiểu (một thay đổi có thể sinh nhiều câu)."""
    who = actor_text(e)
    old = json.loads(e.old_json or "null") or {}
    new = json.loads(e.new_json or "null") or {}
    key = f"{e.entity}.{e.action}"
    if key == "policy.update":
        lines = []
        for path, nv in new.items():
            label, unit = FIELD_LABELS.get(path, (None, ""))
            if label is None:
                continue
            if path == "schedule":
                lines.append(f"{who} đã đổi {label}")
            else:
                lines.append(f"{who} đã đổi {label} từ {_fmt(old.get(path), unit)} thành {_fmt(nv, unit)}")
        return lines or [f"{who} đã cập nhật cài đặt"]
    if key == "child.update" and "fields" in new:
        # Tên gọi là dữ liệu mã hóa => nhật ký chỉ ghi "đã đổi tên gọi", KHÔNG lưu tên cũ/mới dạng rõ
        lines = []
        if "nickname" in new["fields"]:
            lines.append(f"{who} đã đổi tên gọi ở nhà của con")
        if "birth_year" in new["fields"]:
            lines.append(f"{who} đã đổi năm sinh của con từ {old.get('birth_year')} thành {new.get('birth_year')}")
        if "self_pronoun" in new["fields"]:
            lines.append(f"{who} đã đổi cách con tự xưng từ “{old.get('self_pronoun', '')}” thành “{new.get('self_pronoun', '')}”")
        if "avatar_key" in new["fields"]:
            av = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}
            lines.append(f"{who} đã đổi bạn đồng hành từ {av.get(old.get('avatar_key'), '?')} thành {av.get(new.get('avatar_key'), '?')}")
        return lines or [f"{who} đã lưu hồ sơ (không có gì thay đổi)"]
    simple = {
        "policy.create": f"{who} đã tạo cài đặt ban đầu",
        "command.lock_now": (f"{who} đã cho máy tạm nghỉ {new.get('minutes')} phút" if new.get("minutes")
                             else f"{who} đã cho máy tạm nghỉ ngay"),
        "command.unlock": f"{who} đã mở lại máy",
        "command.add_time": f"{who} đã tặng thêm {new.get('minutes', 15)} phút",
        "request.approve": f"{who} đã đồng ý cho thêm {new.get('minutes', '')} phút",
        "request.deny": f"{who} đã hẹn để lần sau",
        "request.create": f"Con đã xin thêm {new.get('minutes', '')} phút",
        "pairing.create": f"{who} đã tạo mã ghép máy tính (ba mẹ đồng ý sử dụng SafeAnchor)",
        "device.enroll": f"Máy tính đã được ghép với gia đình",
        "device.revoke": f"{who} đã gỡ một máy tính khỏi gia đình",
        "data.purge": f"{who} đã xóa toàn bộ dữ liệu hoạt động",
        "child.create": f"{who} đã tạo hồ sơ cho con",
        "child.update": f"{who} đã đổi hồ sơ (tên gọi, cách xưng hô)",
        "kidlink.create": f"{who} đã tạo đường link để con xem bảng thông tin",
        "token.reuse": "Phát hiện token cũ bị dùng lại — đã khóa phiên của máy để an toàn",
    }
    return [simple.get(key, f"{who}: {e.entity} {e.action}")]
