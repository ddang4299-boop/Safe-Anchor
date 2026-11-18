"""
server/policy_service.py — Tạo, đánh phiên bản và ký chính sách cho từng thiết bị.

Yêu cầu đề: F2 (chính sách mặc định 6–11 tuổi), F4 (version tăng ngặt + ký hiệu toàn vẹn,
đổi chính sách có hiệu lực ≤ 60 giây).

Chính sách lưu theo TRẺ (mọi máy của trẻ dùng chung), mỗi lần sửa = MỘT HÀNG MỚI với
version = max + 1 (UNIQUE(child_id, version) chặn hai yêu cầu đồng thời cùng ra một số).
Khi agent tải về, server dựng "body" gắn thêm device_id rồi ký RIÊNG cho thiết bị đó
=> chính sách của máy A không áp được lên máy B.
"""
from __future__ import annotations

import base64
import csv
import json
import time
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent import schedule as sch

from .config import DATA_DIR
from .models import Category, Child, Device, Guardian, Policy

DEFAULT_APP_CATEGORIES = {
    # Không xếp javaw.exe vào games: đó là trình chạy CHUNG của mọi ứng dụng Java (chặn nhầm công cụ học tập).
    "minecraft.exe": "games", "minecraftlauncher.exe": "games",
    "robloxplayerbeta.exe": "games", "steam.exe": "games", "epicgameslauncher.exe": "games",
    "leagueclient.exe": "games", "riotclientservices.exe": "games",
    "winword.exe": "education", "excel.exe": "education", "powerpnt.exe": "education",
    "geogebra.exe": "education", "scratch 3.exe": "education", "mspaint.exe": "education",
    "notepad.exe": "education", "spotify.exe": "entertainment", "vlc.exe": "entertainment",
    "discord.exe": "social", "zalo.exe": "social", "telegram.exe": "social",
}


def school_schedule() -> str:
    """Mẫu "Ngày đi học": T2–T6 06:00–07:00 và 16:00–21:00; T7–CN 07:00–21:30."""
    windows = {d: [("06:00", "07:00"), ("16:00", "21:00")] for d in range(5)}
    windows.update({d: [("07:00", "21:30")] for d in (5, 6)})
    return sch.make_schedule(windows)


def default_policy_body(birth_year: int | None = None) -> dict:
    """Chính sách mặc định cho trẻ 6–11 tuổi."""
    return {
        "tz_offset_min": 420,
        "quota": {"weekday_min": 90, "weekend_min": 150},
        "schedule": school_schedule(),
        "category_budgets": {"games": 45},
        "app_rules": {"block_names": [], "block_sha256": [], "allow_names": [], "allow_sha256": [],
                      "categories": DEFAULT_APP_CATEGORIES},
        "dns": {"block": [], "allow": [], "blocked_categories": ["social", "inappropriate"],
                "safesearch": True, "block_doh": True},
        "grants": [],
        "fail_mode": {"offline_days": 7, "fallback_quota_min": 120, "fallback_window": ["06:00", "21:00"]},
    }


def validate_policy_body(body: dict) -> list[str]:
    errs = []
    q = body.get("quota", {})
    for k in ("weekday_min", "weekend_min"):
        v = q.get(k)
        if not isinstance(v, int) or not 0 <= v <= 24 * 60:
            errs.append(f"quota.{k} phải trong 0..1440 phút")
    if not sch.validate(body.get("schedule", "")):
        errs.append("schedule phải là chuỗi đúng 336 ký tự 0/1")
    for cat, lim in (body.get("category_budgets") or {}).items():
        if not isinstance(lim, int) or not 0 <= lim <= 1440:
            errs.append(f"ngân sách {cat} không hợp lệ")
    return errs


def current_policy(db: Session, child_id: int) -> Policy | None:
    return db.scalar(select(Policy).where(Policy.child_id == child_id).order_by(Policy.version.desc()).limit(1))


def create_policy_version(db: Session, child_id: int, body: dict) -> Policy:
    errs = validate_policy_body(body)
    if errs:
        raise ValueError("; ".join(errs))
    latest = db.scalar(select(func.max(Policy.version)).where(Policy.child_id == child_id)) or 0
    pol = Policy(child_id=child_id, version=latest + 1, body_json=json.dumps(body, ensure_ascii=False),
                 created_at=time.time())
    db.add(pol)
    db.flush()
    return pol


# ------------------------------------------------------------------ bảng phân loại
_CATEGORY_CACHE: dict | None = None


def load_categories_csv(db: Session, path=None) -> int:
    path = path or (DATA_DIR / "categories.csv")
    if not path.exists():
        return 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row["domain"].strip().lower()
            if d and not db.get(Category, d):
                db.add(Category(domain=d, category=row["category"].strip()))
                n += 1
    db.commit()
    invalidate_categories()
    return n


def invalidate_categories() -> None:
    global _CATEGORY_CACHE
    _CATEGORY_CACHE = None


def categories_map(db: Session) -> dict:
    global _CATEGORY_CACHE
    if _CATEGORY_CACHE is None:
        _CATEGORY_CACHE = {c.domain: c.category for c in db.scalars(select(Category))}
    return _CATEGORY_CACHE


# ------------------------------------------------------------------ hồ sơ cá nhân hóa
def age_mode(birth_year: int, now: float | None = None) -> str:
    age = datetime.fromtimestamp(now or time.time()).year - birth_year
    return "mam" if age <= 8 else "choi"  # Mầm 6–8 tuổi, Chồi 9–11 tuổi


def child_profile(ctx, db: Session, child: Child) -> dict:
    g = db.scalar(select(Guardian).where(Guardian.parent_id == child.parent_id).order_by(Guardian.id).limit(1))
    call = ctx.cipher.decrypt(g.call_name_enc, "guardians.call_name") if g else "Ba Mẹ"
    return {"nickname": ctx.cipher.decrypt(child.nickname_enc, "children.nickname"),
            "self_pronoun": child.self_pronoun, "guardian_call": call,
            "age_mode": age_mode(child.birth_year), "avatar_key": child.avatar_key}


# ------------------------------------------------------------------ phong bì đã ký cho 1 thiết bị
def build_envelope(ctx, db: Session, device: Device, child: Child) -> dict:
    pol = current_policy(db, child.id)
    body = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    body.update({
        "policy_id": pol.id if pol else None,
        "version": pol.version if pol else 0,
        "child_id": child.id,
        "device_id": device.id,  # gắn thiết bị => chống đem chính sách sang máy khác
        "issued_at": int(time.time()),
        "categories": categories_map(db),
        "profile": child_profile(ctx, db, child),
    })
    hmac_key = None
    if device.policy_alg == "hmac-sha256":
        hmac_key = base64.b64decode(ctx.cipher.decrypt(device.hmac_key_enc, "devices.hmac_key"))
    return ctx.signer.sign(body, alg=device.policy_alg, hmac_key=hmac_key)
