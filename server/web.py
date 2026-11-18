"""
server/web.py — Phiên đăng nhập phía server, CSRF, Jinja2 cho web dashboard.

Yêu cầu đề: F5 (cookie HttpOnly; Secure; SameSite=Lax, hạn 12 giờ, đăng xuất hủy phiên phía
máy chủ, chống CSRF cho mọi thao tác ghi).

Cookie `ogk_session` chỉ chứa chuỗi ngẫu nhiên 256 bit. DB lưu SHA-256 của chuỗi đó => lộ DB
cũng không dùng lại được cookie. HttpOnly: JavaScript (kể cả mã XSS) không đọc được cookie.
SameSite=Lax: trình duyệt KHÔNG gửi cookie trong POST xuyên trang => lớp chống CSRF thứ nhất;
CSRF token (HMAC theo phiên) trong header X-CSRF-Token là lớp thứ hai.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .audit import CATEGORY_VI, when_text
from .config import DASHBOARD_DIR
from .context import AppContext, get_ctx
from .db import get_db
from .models import Guardian, Parent, WebSession
from .security import csrf_token, random_token, sha256_hex, verify_csrf

COOKIE = "ogk_session"

templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))


def _mins(m) -> str:
    m = int(m or 0)
    if m < 60:
        return f"{m} phút"
    h, r = divmod(m, 60)
    return f"{h} giờ" + (f" {r} phút" if r else "")


def _hhmm(ts, offset=420) -> str:
    return datetime.fromtimestamp(ts, timezone(timedelta(minutes=offset))).strftime("%H:%M %d/%m") if ts else ""


templates.env.filters.update(mins=_mins, when=when_text, cat_vi=lambda c: CATEGORY_VI.get(c, c), hhmm=_hhmm)


class LoginRequired(Exception):
    pass


@dataclass
class WebCtx:
    parent: Parent
    session: WebSession
    csrf: str
    actor_label: str  # tên người giám hộ đang thao tác, dùng cho audit "Mẹ đã đổi..."
    guardians: list


def create_session(db: Session, ctx: AppContext, parent: Parent, ip: str) -> str:
    raw = random_token(32)
    now = time.time()
    g = db.scalar(select(Guardian).where(Guardian.parent_id == parent.id).order_by(Guardian.id).limit(1))
    db.add(WebSession(id_hash=sha256_hex(raw), parent_id=parent.id, guardian_id=g.id if g else None,
                      created_at=now, expires_at=now + ctx.settings.session_hours * 3600, ip=ip))
    db.commit()
    return raw


def set_session_cookie(resp, raw: str, ctx: AppContext) -> None:
    resp.set_cookie(COOKIE, raw, max_age=ctx.settings.session_hours * 3600, httponly=True,
                    secure=ctx.settings.cookie_secure, samesite="lax", path="/")


def destroy_session(db: Session, raw: str | None) -> None:
    if raw:
        db.execute(delete(WebSession).where(WebSession.id_hash == sha256_hex(raw)))
        db.commit()


def current_web(request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)) -> WebCtx:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise LoginRequired()
    sess = db.get(WebSession, sha256_hex(raw))
    if sess is None or sess.expires_at < time.time():
        raise LoginRequired()
    parent = db.get(Parent, sess.parent_id)
    if parent is None:
        raise LoginRequired()
    guardians = list(db.scalars(select(Guardian).where(Guardian.parent_id == parent.id).order_by(Guardian.id)))
    label = "Ba mẹ"
    for g in guardians:
        if g.id == sess.guardian_id:
            label = ctx.cipher.decrypt(g.call_name_enc, "guardians.call_name")
    return WebCtx(parent, sess, csrf_token(ctx.settings.secret, sess.id_hash), label, guardians)


async def form_with_csrf(request: Request, web: WebCtx, ctx: AppContext):
    """Đọc form và bắt buộc CSRF token (header X-CSRF-Token do HTMX gửi, hoặc trường ẩn csrf_token)."""
    form = await request.form()
    token = request.headers.get("x-csrf-token") or form.get("csrf_token")
    if not verify_csrf(ctx.settings.secret, web.session.id_hash, token):
        raise HTTPException(403, detail="CSRF token không hợp lệ")
    return form


def render(request: Request, name: str, ctx_dict: dict, status_code: int = 200):
    return templates.TemplateResponse(request, name, ctx_dict, status_code=status_code)
