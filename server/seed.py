"""
server/seed.py — Tạo dữ liệu mẫu để chạy thử ngay.

    python -m server.seed            # XÓA và tạo lại DB mẫu, in mã ghép + link cho trẻ
    python -m server.seed --code     # chỉ in một mã ghép mới cho bé Bin (hạn 10 phút)

Tài khoản demo: demo@ogk.local / OgkDemo@2026
"""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agent import schedule as sch

from . import audit, db as dbmod
from .config import get_settings
from .main import create_app
from .models import (AuditLog, Base, Child, DailyUsage, Device, Event, Guardian, IntegrityAlert, KidLink, PairingCode,
                     Parent, UnlockRequest)
from .policy_service import create_policy_version, default_policy_body, load_categories_csv
from .security import FieldCipher, format_pairing_code, hash_password, new_pairing_code, sha256_hex

DEMO_EMAIL = "demo@ogk.local"
DEMO_PASSWORD = "OgkDemo@2026"
KID_TOKEN_BIN = "xem-cua-bin-demo-token-2026"
VN = timezone(timedelta(hours=7))

APPS = {  # tên exe -> (nhóm, trọng số)
    "minecraft.exe": ("games", 3), "winword.exe": ("education", 2), "scratch 3.exe": ("education", 2),
    "chrome.exe": ("uncategorized", 4), "mspaint.exe": ("education", 1), "vlc.exe": ("entertainment", 1),
}
DOMAINS = [("khanacademy.org", 6), ("olm.vn", 5), ("wikipedia.org", 4), ("youtube.com", 6), ("pbskids.org", 2),
           ("roblox.com", 3), ("poki.com", 2), ("google.com", 7), ("hocmai.vn", 3), ("duolingo.com", 3),
           ("vnexpress.net", 1), ("scratch.mit.edu", 2)]
BLOCKED = [("tiktok.com", 3), ("facebook.com", 2), ("instagram.com", 1), ("dns.google", 1)]


def new_pairing(db, child_id: int, ttl: int) -> str:
    code = new_pairing_code()
    now = time.time()
    db.add(PairingCode(child_id=child_id, code_hash=sha256_hex(code), created_at=now, expires_at=now + ttl))
    audit.record(db, actor_type="parent", actor_label="Mẹ", ip="127.0.0.1", child_id=child_id, entity="pairing",
                 action="create", new={"expires_at": now + ttl})
    db.commit()
    return format_pairing_code(code)


def seed(reset: bool = True) -> dict:
    settings = get_settings()
    create_app(settings, start_jobs=False)
    engine = dbmod.get_engine()
    if reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    cipher = FieldCipher(settings.data_key)
    rnd = random.Random(2026)
    now = time.time()
    with dbmod.SessionLocal() as db:
        load_categories_csv(db)
        parent = Parent(email=DEMO_EMAIL, pw_hash=hash_password(DEMO_PASSWORD), created_at=now - 30 * 86400)
        db.add(parent)
        db.flush()
        me = Guardian(parent_id=parent.id, relation="mẹ", display_name_enc=cipher.encrypt("Mẹ Lan", "guardians.display_name"),
                      call_name_enc=cipher.encrypt("Mẹ", "guardians.call_name"))
        ba = Guardian(parent_id=parent.id, relation="ba", display_name_enc=cipher.encrypt("Ba Hùng", "guardians.display_name"),
                      call_name_enc=cipher.encrypt("Ba", "guardians.call_name"))
        db.add_all([me, ba])
        kids = []
        for name, year, pronoun, avatar in (("Bin", 2018, "con", "tictac"), ("Na", 2016, "em", "sao")):
            c = Child(parent_id=parent.id, nickname_enc=cipher.encrypt(name, "children.nickname"), self_pronoun=pronoun,
                      birth_year=year, avatar_key=avatar, created_at=now - 20 * 86400)
            db.add(c)
            db.flush()
            kids.append((c, name))
        bin_child, na_child = kids[0][0], kids[1][0]

        # Chính sách: Bin dùng khung rộng 06:00–22:00 để demo buổi sáng không bị khóa ngay;
        # Na dùng mẫu "Ngày đi học" mặc định.
        b_pol = default_policy_body(2018)
        b_pol["schedule"] = sch.daily_window("06:00", "22:00")
        create_policy_version(db, bin_child.id, default_policy_body(2018))
        p_bin = create_policy_version(db, bin_child.id, b_pol)
        p_na = create_policy_version(db, na_child.id, default_policy_body(2016))
        audit.record(db, actor_type="parent", actor_label="Mẹ", ip="192.168.1.10", child_id=bin_child.id,
                     entity="policy", action="update", old={"schedule": "…"}, new={"schedule": "…"})
        db.flush()

        devices = {}
        for child, host, pol in ((bin_child, "PC-cua-Bin", p_bin), (na_child, "Laptop-cua-Na", p_na)):
            d = Device(id=f"seed-{child.id}-{uuid.uuid4().hex[:8]}", child_id=child.id,
                       fingerprint_hash=sha256_hex(host), hostname_enc=cipher.encrypt(host, "devices.hostname"),
                       created_at=now - 14 * 86400, last_seen=now - 3 * 3600, policy_version=pol.version,
                       last_state_json=json.dumps({"phase": "active", "remaining_sec": 1800, "used_sec": 2400}))
            db.add(d)
            devices[child.id] = (d, pol)
            audit.record(db, actor_type="device", actor_label="Máy tính", ip="192.168.1.23", child_id=child.id,
                         entity="device", action="enroll", new={"device_id": d.id})
        db.flush()

        # 14 ngày dữ liệu sự kiện + tổng kết ngày
        today = datetime.fromtimestamp(now, VN).date()
        for child, _ in kids:
            dev, pol = devices[child.id]
            for back in range(13, -1, -1):
                day = today - timedelta(days=back)
                weekend = day.weekday() >= 5
                total_min = rnd.randint(70, 140) if weekend else rnd.randint(35, 95)
                if back == 0:
                    total_min = rnd.randint(25, 45)
                start = datetime(day.year, day.month, day.day, 16 if not weekend else 9, 0, tzinfo=VN).timestamp()
                cats: dict[str, float] = {}
                t, left = start, total_min * 60
                names, weights = zip(*APPS.items())
                while left > 300:
                    app = rnd.choices(names, weights=[w for _, w in weights])[0]
                    dur = min(left, rnd.randint(8, 35) * 60)
                    cat = APPS[app][0]
                    cats[cat] = cats.get(cat, 0) + dur
                    for etype, ts in (("app_start", t), ("app_stop", t + dur)):
                        db.add(Event(idem_key=str(uuid.uuid4()), ts=ts, device_id=dev.id, child_id=child.id, type=etype,
                                     subject=app, duration_sec=dur if etype == "app_stop" else 0, policy_id=pol.id))
                    t += dur + rnd.randint(1, 10) * 60
                    left -= dur
                for _ in range(rnd.randint(8, 20)):
                    dom = rnd.choices([d for d, _ in DOMAINS], weights=[w for _, w in DOMAINS])[0]
                    db.add(Event(idem_key=str(uuid.uuid4()), ts=start + rnd.randint(0, 7200), device_id=dev.id,
                                 child_id=child.id, type="domain_query", subject=dom, duration_sec=0, policy_id=pol.id))
                for _ in range(rnd.randint(0, 3)):
                    dom = rnd.choices([d for d, _ in BLOCKED], weights=[w for _, w in BLOCKED])[0]
                    db.add(Event(idem_key=str(uuid.uuid4()), ts=start + rnd.randint(0, 7200), device_id=dev.id,
                                 child_id=child.id, type="blocked_domain", subject=dom, duration_sec=0, policy_id=pol.id))
                if rnd.random() < 0.3:
                    db.add(Event(idem_key=str(uuid.uuid4()), ts=start + 3600, device_id=dev.id, child_id=child.id,
                                 type="locked", subject=rnd.choice(["quota", "self", "schedule"]), duration_sec=0,
                                 policy_id=pol.id))
                db.add(DailyUsage(device_id=dev.id, day=day.isoformat(), child_id=child.id, used_sec=total_min * 60,
                                  by_category_json=json.dumps(cats), updated_at=start + total_min * 60))

        # Yêu cầu thêm giờ đang chờ + một yêu cầu đã duyệt hôm qua
        bdev = devices[bin_child.id][0]
        db.add(UnlockRequest(child_id=bin_child.id, device_id=bdev.id, minutes=15, created_at=now - 300,
                             reason_enc=cipher.encrypt("Con sắp xong màn chơi ạ", "unlock_requests.reason")))
        db.add(UnlockRequest(child_id=bin_child.id, device_id=bdev.id, minutes=30, created_at=now - 86400,
                             status="approved", decided_at=now - 86000, decided_by="Mẹ",
                             reason_enc=cipher.encrypt("Con làm bài tập Scratch", "unlock_requests.reason"),
                             note_enc=cipher.encrypt("Làm xong nhớ nghỉ mắt nha con!", "unlock_requests.note")))
        ndev = devices[na_child.id][0]
        db.add(IntegrityAlert(device_id=ndev.id, child_id=na_child.id, ts=now - 2 * 86400, kind="clock_jump",
                              detail_json=json.dumps({"kind": "clock_jump", "delta_sec": -10800})))
        db.add(KidLink(token_hash=sha256_hex(KID_TOKEN_BIN), child_id=bin_child.id, created_at=now))
        db.commit()
        code = new_pairing(db, bin_child.id, settings.pairing_ttl)
        return {"bin_id": bin_child.id, "na_id": na_child.id, "pairing_code": code}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", action="store_true", help="chỉ in mã ghép mới cho bé Bin")
    args = ap.parse_args()
    if args.code:
        settings = get_settings()
        create_app(settings, start_jobs=False)
        with dbmod.SessionLocal() as db:
            parent = db.scalar(select(Parent).where(Parent.email == DEMO_EMAIL))
            child = db.scalar(select(Child).where(Child.parent_id == parent.id).order_by(Child.id))
            code = new_pairing(db, child.id, settings.pairing_ttl)
            print(f"Mã ghép cho bé Bin (hạn 10 phút): {code}")
            print(f"PAIRING_CODE={code}")  # dòng ASCII cho script tự động đọc
        return
    info = seed()
    print("=" * 60)
    print(" ĐÃ TẠO DỮ LIỆU MẪU OGK")
    print(f" Đăng nhập dashboard : {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f" Trang minh bạch Bin : /kid/{KID_TOKEN_BIN}")
    print(f" Mã ghép cho Bin     : {info['pairing_code']}  (hạn 10 phút — tạo mã mới: python -m server.seed --code)")
    print("=" * 60)


if __name__ == "__main__":
    main()
