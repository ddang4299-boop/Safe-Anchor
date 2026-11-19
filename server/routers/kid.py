"""
server/routers/kid.py — Trang minh bạch CHỈ ĐỌC cho trẻ: /kid/{token}.

Yêu cầu đề: F3 (màn hình "Hôm nay em đã dùng gì": cùng dữ liệu, ngôn ngữ đơn giản, hình minh họa),
F4/NT5 (trẻ xem được nhật ký thay đổi). Không có bất kỳ thao tác ghi nào.
Mọi con số lấy từ reports.child_report() — CÙNG hàm với dashboard phụ huynh — và phần báo cáo dùng CHUNG
partial _report.html (audience="kid" chỉ đổi câu chữ/"lớp da"). Thẻ Bento riêng của trẻ (vòng thời gian,
huy hiệu đúng giờ) chỉ là cách trình bày khác của chính dữ liệu đó + hạn mức trong chính sách hiện hành.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..context import AppContext, get_ctx
from ..db import get_db
from ..models import AuditLog, Child, KidLink
from ..policy_service import child_profile, current_policy, default_policy_body
from ..reports import child_report
from ..security import sha256_hex
from ..web import render

router = APIRouter(tags=["kid"])


def kid_view(report: dict, policy: dict) -> dict:
    """Số liệu cho các thẻ Bento của trẻ: vòng thời gian hôm nay, học tập/giải trí, huy hiệu + chuỗi ngày đúng giờ."""
    quota = policy.get("quota", {})

    def quota_for(day_iso: str) -> int:
        return int(quota.get("weekend_min" if date.fromisoformat(day_iso).weekday() >= 5 else "weekday_min", 90))

    days = [{"date": d["date"], "label": d["label"], "minutes": d["minutes"],
             "ok": d["minutes"] <= quota_for(d["day"])} for d in report["daily"]]
    streak = 0
    for d in reversed(days):  # số ngày LIÊN TIẾP (tính đến hôm nay) dùng máy trong hạn mức
        if not d["ok"]:
            break
        streak += 1
    q_today = quota_for(report["daily"][-1]["day"])
    used = report["today_minutes"]
    cats = report["cats_today"]
    return {"quota_today": q_today, "used": used, "left": max(0, q_today - used),
            "pct": min(100, round(100 * used / q_today)) if q_today else 100,
            "on_time": days[-1]["ok"], "streak": streak, "days": days,
            "study": cats.get("education", 0), "fun": cats.get("games", 0) + cats.get("entertainment", 0),
            "weekday_min": quota.get("weekday_min"), "weekend_min": quota.get("weekend_min")}


@router.get("/kid/{token}", response_class=HTMLResponse)
def kid_page(token: str, request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    link = db.get(KidLink, sha256_hex(token))
    if link is None or link.revoked:
        raise HTTPException(404)
    child = db.get(Child, link.child_id)
    pol = current_policy(db, child.id)
    body = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    report = child_report(db, child.id, cipher=None)  # trẻ không cần xem lý do/lời nhắn đã mã hóa ở đây
    entries = db.scalars(select(AuditLog).where(AuditLog.child_id == child.id).order_by(AuditLog.ts.desc()).limit(20)).all()
    resp = render(request, "kid.html", {
        "profile": child_profile(ctx, db, child),
        "report": report,
        "kv": kid_view(report, body),
        "audience": "kid",
        "audit": [{"when": audit.when_text(e.ts), "lines": audit.humanize(e)} for e in entries],
    })
    resp.headers["Referrer-Policy"] = "no-referrer"  # token nằm trên URL: không để lộ qua Referer
    return resp
