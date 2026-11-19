"""
server/reports.py — Tổng hợp báo cáo. DÙNG CHUNG cho dashboard phụ huynh, trang trẻ /kid/{token}
và màn hình "Hôm nay em đã dùng gì" trên Tray => trẻ thấy đúng những gì ba mẹ thấy (NT5).

Yêu cầu đề: F3 (biểu đồ ngày/tuần, top 10 ứng dụng, top 10 tên miền, số lần bị chặn, yêu cầu).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.app_names import app_display

from .models import DailyUsage, Event, UnlockRequest

WEEKDAY_VI = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

# Tên hiển thị thân thiện ("winword.exe" -> "Microsoft Word"): dùng chung với Tray, xem agent/app_names.py



def _tz(offset_min: int):
    return timezone(timedelta(minutes=offset_min))


def child_report(db: Session, child_id: int, tz_offset_min: int = 420, now: float | None = None,
                 cipher=None) -> dict:
    now = now or time.time()
    tz = _tz(tz_offset_min)
    today = datetime.fromtimestamp(now, tz).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    day_keys = [d.isoformat() for d in days]

    # ---- thời lượng theo ngày (từ tổng kết heartbeat) ----
    rows = db.execute(select(DailyUsage.day, DailyUsage.used_sec, DailyUsage.by_category_json)
                      .where(DailyUsage.child_id == child_id, DailyUsage.day >= (today - timedelta(days=27)).isoformat())).all()
    per_day: dict[str, int] = {}
    cats_today: dict[str, float] = {}
    cats_week: dict[str, float] = {}
    for day, used, cats_json in rows:
        per_day[day] = per_day.get(day, 0) + int(used)
        cats = json.loads(cats_json or "{}")
        if day in day_keys:
            for c, s in cats.items():
                cats_week[c] = cats_week.get(c, 0) + s
        if day == today.isoformat():
            for c, s in cats.items():
                cats_today[c] = cats_today.get(c, 0) + s
    daily = [{"day": k, "label": WEEKDAY_VI[d.weekday()], "date": d.strftime("%d/%m"),
              "minutes": round(per_day.get(k, 0) / 60)} for k, d in zip(day_keys, days)]
    monday = today - timedelta(days=today.weekday())
    weekly = []
    for w in range(3, -1, -1):
        start = monday - timedelta(weeks=w)
        total = sum(per_day.get((start + timedelta(days=i)).isoformat(), 0) for i in range(7))
        weekly.append({"label": "Tuần này" if w == 0 else f"{w} tuần trước", "start": start.strftime("%d/%m"),
                       "minutes": round(total / 60)})

    # ---- sự kiện 7 ngày ----
    since = datetime.combine(days[0], datetime.min.time(), tz).timestamp()
    base = (Event.child_id == child_id, Event.ts >= since)
    top_apps = db.execute(select(Event.subject, func.sum(Event.duration_sec).label("sec"), func.count())
                          .where(*base, Event.type == "app_stop").group_by(Event.subject)
                          .order_by(func.sum(Event.duration_sec).desc()).limit(10)).all()
    top_domains = db.execute(select(Event.subject, func.count().label("n"))
                             .where(*base, Event.type == "domain_query").group_by(Event.subject)
                             .order_by(func.count().desc()).limit(10)).all()
    blocked = db.execute(select(Event.type, Event.subject, func.count().label("n"))
                         .where(*base, Event.type.in_(("blocked_app", "blocked_domain")))
                         .group_by(Event.type, Event.subject).order_by(func.count().desc())).all()
    reqs = db.scalars(select(UnlockRequest).where(UnlockRequest.child_id == child_id)
                      .order_by(UnlockRequest.created_at.desc()).limit(10)).all()

    def dec(v, aad):
        return cipher.decrypt(v, aad) if cipher and v else ""

    max_day = max([d["minutes"] for d in daily] + [1])
    max_week = max([w["minutes"] for w in weekly] + [1])
    return {
        "today_minutes": daily[-1]["minutes"],
        "week_minutes": sum(d["minutes"] for d in daily),
        "daily": daily, "max_day": max_day,
        "weekly": weekly, "max_week": max_week,
        "cats_today": {c: round(s / 60) for c, s in sorted(cats_today.items(), key=lambda x: -x[1])},
        "cats_week": {c: round(s / 60) for c, s in sorted(cats_week.items(), key=lambda x: -x[1])},
        "top_apps": [{"name": s, "display": app_display(s), "minutes": round((sec or 0) / 60), "count": n}
                     for s, sec, n in top_apps],
        "top_domains": [{"name": s, "count": n} for s, n in top_domains],
        "blocked_total": sum(n for _, _, n in blocked),
        "blocked": [{"type": t, "name": s, "count": n,
                     "display": app_display(s) if t == "blocked_app" else s} for t, s, n in blocked[:10]],
        "requests": [{"id": r.id, "minutes": r.minutes, "status": r.status, "created_at": r.created_at,
                      "reason": dec(r.reason_enc, "unlock_requests.reason"),
                      "note": dec(r.note_enc, "unlock_requests.note")} for r in reqs],
    }
