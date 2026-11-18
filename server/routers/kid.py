"""
server/routers/kid.py — Trang minh bạch CHỈ ĐỌC cho trẻ: /kid/{token}.

Yêu cầu đề: F3 (màn hình "Hôm nay em đã dùng gì": cùng dữ liệu, ngôn ngữ đơn giản, hình minh họa),
F4/NT5 (trẻ xem được nhật ký thay đổi). Không có bất kỳ thao tác ghi nào.
Dùng CHUNG partial _report.html với dashboard phụ huynh (audience="kid" chỉ đổi câu chữ).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..context import AppContext, get_ctx
from ..db import get_db
from ..models import AuditLog, Child, KidLink
from ..policy_service import child_profile
from ..reports import child_report
from ..security import sha256_hex
from ..web import render

router = APIRouter(tags=["kid"])


@router.get("/kid/{token}", response_class=HTMLResponse)
def kid_page(token: str, request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    link = db.get(KidLink, sha256_hex(token))
    if link is None or link.revoked:
        raise HTTPException(404)
    child = db.get(Child, link.child_id)
    entries = db.scalars(select(AuditLog).where(AuditLog.child_id == child.id).order_by(AuditLog.ts.desc()).limit(20)).all()
    resp = render(request, "kid.html", {
        "profile": child_profile(ctx, db, child),
        "report": child_report(db, child.id, cipher=None),  # trẻ không cần xem lý do/lời nhắn đã mã hóa ở đây
        "audience": "kid",
        "audit": [{"when": audit.when_text(e.ts), "lines": audit.humanize(e)} for e in entries],
    })
    resp.headers["Referrer-Policy"] = "no-referrer"  # token nằm trên URL: không để lộ qua Referer
    return resp
