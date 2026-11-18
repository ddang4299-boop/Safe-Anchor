"""
server/routers/dashboard.py — Web dashboard phụ huynh (Jinja2 + HTMX, mobile-first).

Yêu cầu đề: F1/F2 (cấu hình quota, lịch 7×48, danh sách ứng dụng/miền), F3 (báo cáo, xuất CSV,
xóa toàn bộ dữ liệu), F4 (lệnh khẩn, duyệt yêu cầu, audit), §4.3 (tạo mã ghép 8 ký tự 10 phút).

Mọi route có {child_id}/{device_id}/{request_id} đều đi qua server/access.py (điều kiện sở hữu
nằm trong WHERE) => phụ huynh B nhận 404 khi đụng vào dữ liệu của con phụ huynh A.
Mọi thao tác GHI đều qua form_with_csrf().
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from agent import schedule as sch
from agent.domain_rules import normalize

from .. import audit
from ..access import children_of, owned_child, owned_device, owned_request
from ..context import AppContext, client_ip, get_ctx
from ..db import get_db
from ..models import (AuditLog, Child, Command, DailyUsage, Device, Event, IntegrityAlert, KidLink, PairingCode,
                      UnlockRequest)
from ..policy_service import create_policy_version, current_policy, default_policy_body, school_schedule
from ..reports import child_report
from ..security import format_pairing_code, new_pairing_code, random_token, sha256_hex
from ..web import WebCtx, current_web, form_with_csrf, render

router = APIRouter(tags=["dashboard"])

CATEGORY_CHOICES = ["education", "entertainment", "social", "games", "inappropriate", "uncategorized"]
NOTE_SUGGESTIONS = ["Con làm bài xong rồi chơi tiếp nhé!", "Chơi vui nhưng nhớ nghỉ mắt nha con.",
                    "Hôm nay mình nghỉ sớm, mai chơi tiếp nhé.", "Ba mẹ thương con!"]


# ------------------------------------------------------------------ tiện ích
def nick(ctx: AppContext, child: Child) -> str:
    return ctx.cipher.decrypt(child.nickname_enc, "children.nickname")


def device_view(ctx: AppContext, dev: Device) -> dict:
    st = json.loads(dev.last_state_json or "{}")
    online_ws = ctx.hub.is_online(dev.id)
    fresh = dev.last_seen and time.time() - dev.last_seen < ctx.settings.offline_after_sec
    if dev.revoked:
        status, label = "revoked", "Đã gỡ"
    elif not (online_ws or fresh):
        status, label = "offline", "Ngoại tuyến"
    elif st.get("phase") == "locked":
        status, label = "locked", "Đang tạm nghỉ"
    elif st.get("phase") == "grace":
        status, label = "grace", "Sắp tạm nghỉ"
    else:
        status, label = "active", "Đang dùng"
    return {"id": dev.id, "hostname": ctx.cipher.decrypt(dev.hostname_enc, "devices.hostname") or "Máy tính",
            "status": status, "label": label, "online_ws": online_ws, "last_seen": dev.last_seen,
            "remaining_min": round((st.get("remaining_sec") or 0) / 60), "used_min": round((st.get("used_sec") or 0) / 60),
            "quota_min": st.get("quota_min"), "policy_version": dev.policy_version, "revoked": dev.revoked,
            "skew": round(dev.clock_skew or 0), "stale": st.get("stale")}


def child_card(db: Session, ctx: AppContext, child: Child) -> dict:
    devs = [device_view(ctx, d) for d in child.devices if not d.revoked]
    pending = db.scalar(select(func.count()).select_from(UnlockRequest)
                        .where(UnlockRequest.child_id == child.id, UnlockRequest.status == "pending")) or 0
    pol = current_policy(db, child.id)
    alerts = db.scalar(select(func.count()).select_from(IntegrityAlert)
                       .where(IntegrityAlert.child_id == child.id, IntegrityAlert.ts > time.time() - 86400)) or 0
    return {"id": child.id, "nickname": nick(ctx, child), "avatar": child.avatar_key, "devices": devs,
            "pending": pending, "policy_version": pol.version if pol else 0, "alerts": alerts,
            "age": datetime.now().year - child.birth_year}


def pending_requests(db: Session, ctx: AppContext, parent_id: int) -> list[dict]:
    rows = db.execute(select(UnlockRequest, Child).join(Child, UnlockRequest.child_id == Child.id)
                      .where(Child.parent_id == parent_id, UnlockRequest.status == "pending")
                      .order_by(UnlockRequest.created_at)).all()
    return [{"id": r.id, "minutes": r.minutes, "created_at": r.created_at, "child": nick(ctx, c),
             "reason": ctx.cipher.decrypt(r.reason_enc, "unlock_requests.reason")} for r, c in rows]


async def issue_command(ctx: AppContext, db: Session, dev: Device, ctype: str, payload: dict) -> bool:
    """Lưu lệnh (bền vững) TRƯỚC, rồi mới thử đẩy qua WebSocket. Đẩy hụt thì heartbeat sẽ chở lệnh."""
    cmd = Command(id=str(uuid.uuid4()), device_id=dev.id, type=ctype, payload_json=json.dumps(payload, ensure_ascii=False),
                  status="pending", created_at=time.time())
    db.add(cmd)
    db.commit()
    delivered = await ctx.hub.send(dev.id, {"type": "command", "command_id": cmd.id, "cmd": ctype, "payload": payload})
    if delivered:
        cmd.status, cmd.sent_at = "sent", time.time()
        db.commit()
    return delivered


async def save_policy(db: Session, ctx: AppContext, web: WebCtx, child: Child, ip: str, mutate) -> tuple[bool, str]:
    pol = current_policy(db, child.id)
    old = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    new = json.loads(json.dumps(old))
    mutate(new)
    old_d, new_d = audit.policy_diff(old, new)
    if not new_d:
        return True, "Không có gì thay đổi."
    try:
        p = create_policy_version(db, child.id, new)
    except ValueError as exc:
        db.rollback()
        return False, str(exc)
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label, ip=ip,
                 child_id=child.id, entity="policy", action="update", old=old_d, new=new_d)
    db.commit()
    # Báo agent tải chính sách NGAY (≪ 60 giây); heartbeat lệch version là đường dự phòng.
    for d in child.devices:
        if not d.revoked:
            await ctx.hub.send(d.id, {"type": "policy_changed", "version": p.version})
    return True, f"Đã lưu (phiên bản {p.version}). Máy của con sẽ cập nhật trong vài giây."


def lines(text: str, pattern: str | None = None, limit: int = 500) -> list[str]:
    out = []
    for raw in re.split(r"[\s,;]+", text or ""):
        v = raw.strip().lower()
        if not v:
            continue
        if pattern and not re.fullmatch(pattern, v):
            continue
        if v not in out:
            out.append(v)
    return out[:limit]


DOMAIN_RE = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+"
EXE_RE = r"[a-z0-9 _.\-]{1,64}\.exe"
SHA_RE = r"[0-9a-f]{64}"


# ------------------------------------------------------------------ tổng quan
@router.get("/", response_class=HTMLResponse)
def overview(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
             ctx: AppContext = Depends(get_ctx)):
    kids = [child_card(db, ctx, c) for c in children_of(db, web.parent.id)]
    return render(request, "overview.html", {"web": web, "kids": kids, "page": "overview", "ctx": ctx,
                                             "requests": pending_requests(db, ctx, web.parent.id),
                                             "notes": NOTE_SUGGESTIONS})


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                     ctx: AppContext = Depends(get_ctx)):
    kids = [child_card(db, ctx, c) for c in children_of(db, web.parent.id)]
    return render(request, "_overview_cards.html", {"web": web, "kids": kids})


@router.get("/partials/requests", response_class=HTMLResponse)
def requests_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                     ctx: AppContext = Depends(get_ctx)):
    return render(request, "_requests.html", {"web": web, "requests": pending_requests(db, ctx, web.parent.id),
                                              "notes": NOTE_SUGGESTIONS})


@router.get("/partials/badge", response_class=HTMLResponse)
def badge_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                  ctx: AppContext = Depends(get_ctx)):
    n = len(pending_requests(db, ctx, web.parent.id))
    return HTMLResponse(f'<span class="badge" aria-label="{n} yêu cầu đang chờ">{n}</span>' if n else "")


# ------------------------------------------------------------------ trẻ
@router.get("/children/new", response_class=HTMLResponse)
def child_new_page(request: Request, web: WebCtx = Depends(current_web)):
    return render(request, "child_new.html", {"web": web, "page": "family", "error": None})


@router.post("/children")
async def child_create(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                       ctx: AppContext = Depends(get_ctx)):
    form = await form_with_csrf(request, web, ctx)
    nickname = str(form.get("nickname", "")).strip()[:20]
    pronoun = str(form.get("self_pronoun", "con"))
    try:
        birth_year = int(form.get("birth_year", 0))
    except ValueError:
        birth_year = 0
    if not nickname or pronoun not in ("con", "em", "mình", "cháu") or not 2005 <= birth_year <= datetime.now().year:
        return render(request, "child_new.html", {"web": web, "page": "family",
                                                  "error": "Vui lòng nhập tên gọi, cách xưng hô và năm sinh hợp lệ."}, 400)
    child = Child(parent_id=web.parent.id, nickname_enc=ctx.cipher.encrypt(nickname, "children.nickname"),
                  self_pronoun=pronoun, birth_year=birth_year, avatar_key=str(form.get("avatar_key", "tictac"))[:16],
                  created_at=time.time())
    db.add(child)
    db.flush()
    create_policy_version(db, child.id, default_policy_body(birth_year))
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=child.id, entity="child", action="create")
    db.commit()
    return RedirectResponse(f"/children/{child.id}?tab=devices", status_code=303)


@router.get("/children/{child_id}", response_class=HTMLResponse)
def child_page(child_id: int, request: Request, tab: str = "report", web: WebCtx = Depends(current_web),
               db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    pol = current_policy(db, child.id)
    body = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    data = {"web": web, "page": "child", "tab": tab, "child": child_card(db, ctx, child), "child_obj": child,
            "policy": body, "policy_version": pol.version if pol else 0, "categories": CATEGORY_CHOICES,
            "msg": request.query_params.get("msg")}
    if tab == "report":
        data["report"] = child_report(db, child.id, cipher=ctx.cipher)
        data["audience"] = "parent"
    elif tab == "audit":
        entries = db.scalars(select(AuditLog).where(AuditLog.child_id == child.id).order_by(AuditLog.ts.desc()).limit(100)).all()
        data["entries"] = [{"e": e, "lines": audit.humanize(e), "when": audit.when_text(e.ts)} for e in entries]
        data["alerts"] = db.scalars(select(IntegrityAlert).where(IntegrityAlert.child_id == child.id)
                                    .order_by(IntegrityAlert.ts.desc()).limit(20)).all()
    elif tab == "devices":
        data["devices"] = [device_view(ctx, d) for d in child.devices]
    elif tab == "time":
        data["school_template"] = school_schedule()
    return render(request, "child.html", data)


@router.post("/children/{child_id}/profile")
async def child_profile_update(child_id: int, request: Request, web: WebCtx = Depends(current_web),
                               db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    nickname = str(form.get("nickname", "")).strip()[:20]
    pronoun = str(form.get("self_pronoun", child.self_pronoun))
    if nickname and pronoun in ("con", "em", "mình", "cháu"):
        old = {"nickname": nick(ctx, child), "self_pronoun": child.self_pronoun}
        child.nickname_enc = ctx.cipher.encrypt(nickname, "children.nickname")
        child.self_pronoun = pronoun
        audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                     ip=client_ip(request), child_id=child.id, entity="child", action="update", old=old,
                     new={"nickname": nickname, "self_pronoun": pronoun})
        db.commit()
        for d in child.devices:  # hồ sơ nằm trong chính sách đã ký => báo agent tải lại
            await ctx.hub.send(d.id, {"type": "policy_changed"})
    return RedirectResponse(f"/children/{child.id}?tab=devices&msg=Đã+lưu+hồ+sơ", status_code=303)


# ------------------------------------------------------------------ chính sách
def _msg_html(ok: bool, msg: str) -> HTMLResponse:
    cls = "toast ok" if ok else "toast warn"
    icon = "✓" if ok else "!"
    return HTMLResponse(f'<div class="{cls}" role="status"><span aria-hidden="true">{icon}</span> {msg}</div>',
                        status_code=200 if ok else 400)


def _int(form, key, lo, hi, default):
    try:
        return max(lo, min(hi, int(form.get(key, default))))
    except (TypeError, ValueError):
        return default


@router.post("/children/{child_id}/policy/time", response_class=HTMLResponse)
async def policy_time(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                      ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)

    def mutate(p):
        p["quota"]["weekday_min"] = _int(form, "weekday_min", 0, 1440, 90)
        p["quota"]["weekend_min"] = _int(form, "weekend_min", 0, 1440, 150)
        budgets = {}
        for cat in ("games", "entertainment"):
            v = str(form.get(f"budget_{cat}", "")).strip()
            if v:
                budgets[cat] = _int(form, f"budget_{cat}", 0, 1440, 45)
        p["category_budgets"] = budgets

    return _msg_html(*await save_policy(db, ctx, web, child, client_ip(request), mutate))


@router.post("/children/{child_id}/policy/schedule", response_class=HTMLResponse)
async def policy_schedule(child_id: int, request: Request, web: WebCtx = Depends(current_web),
                          db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    s = str(form.get("schedule", ""))
    if not sch.validate(s):  # server KIỂM TRA LẠI chuỗi 336 ký tự, không tin JavaScript phía client
        return _msg_html(False, "Lịch không hợp lệ (cần đúng 336 ô 0/1).")

    def mutate(p):
        p["schedule"] = s

    return _msg_html(*await save_policy(db, ctx, web, child, client_ip(request), mutate))


@router.post("/children/{child_id}/policy/filter", response_class=HTMLResponse)
async def policy_filter(child_id: int, request: Request, web: WebCtx = Depends(current_web),
                        db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)

    def mutate(p):
        p["dns"]["blocked_categories"] = [c for c in form.getlist("blocked_categories") if c in CATEGORY_CHOICES]
        p["dns"]["safesearch"] = form.get("safesearch") == "on"
        p["dns"]["block_doh"] = form.get("block_doh") == "on"
        p["dns"]["block"] = [normalize(d) for d in lines(str(form.get("dns_block", "")), DOMAIN_RE)]
        p["dns"]["allow"] = [normalize(d) for d in lines(str(form.get("dns_allow", "")), DOMAIN_RE)]
        p["app_rules"]["block_names"] = lines(str(form.get("app_block_names", "")), EXE_RE)
        p["app_rules"]["block_sha256"] = lines(str(form.get("app_block_sha256", "")), SHA_RE)
        p["app_rules"]["allow_names"] = lines(str(form.get("app_allow_names", "")), EXE_RE)

    return _msg_html(*await save_policy(db, ctx, web, child, client_ip(request), mutate))


# ------------------------------------------------------------------ ghép đôi & thiết bị
@router.post("/children/{child_id}/pairing-code", response_class=HTMLResponse)
async def pairing_code(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                       ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    await form_with_csrf(request, web, ctx)
    code = new_pairing_code()
    now = time.time()
    ip = client_ip(request)
    db.add(PairingCode(child_id=child.id, code_hash=sha256_hex(code), created_at=now,
                       expires_at=now + ctx.settings.pairing_ttl, created_ip=ip))
    # Tạo mã = hành động "phụ huynh đồng ý" (Nghị định 13/2023): ghi ai, lúc nào, từ IP nào.
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label, ip=ip,
                 child_id=child.id, entity="pairing", action="create", new={"expires_at": now + ctx.settings.pairing_ttl})
    db.commit()
    return render(request, "_pairing.html", {"code": format_pairing_code(code), "ttl": ctx.settings.pairing_ttl,
                                             "child": nick(ctx, child)})


@router.post("/devices/{device_id}/command", response_class=HTMLResponse)
async def device_command(device_id: str, request: Request, web: WebCtx = Depends(current_web),
                         db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    dev = owned_device(db, web.parent.id, device_id)
    form = await form_with_csrf(request, web, ctx)
    ctype = str(form.get("cmd", ""))
    if ctype not in ("lock_now", "unlock", "add_time"):
        raise HTTPException(400, detail="Lệnh không hợp lệ")
    payload = {"by": web.actor_label}
    if ctype == "add_time":
        payload["minutes"] = _int(form, "minutes", 5, 120, 15)
    if ctype == "unlock":
        payload["minutes"] = _int(form, "minutes", 0, 240, 30)
    delivered = await issue_command(ctx, db, dev, ctype, payload)
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=dev.child_id, entity="command", action=ctype, new=payload)
    db.commit()
    if delivered:
        return _msg_html(True, "Đã gửi tức thì tới máy của con.")
    return _msg_html(True, "Máy đang ngoại tuyến — lệnh sẽ được áp dụng ngay khi máy kết nối lại.")


@router.post("/devices/{device_id}/revoke", response_class=HTMLResponse)
async def device_revoke(device_id: str, request: Request, web: WebCtx = Depends(current_web),
                        db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    dev = owned_device(db, web.parent.id, device_id)
    await form_with_csrf(request, web, ctx)
    from ..models import RefreshToken
    from sqlalchemy import update
    dev.revoked = True
    db.execute(update(RefreshToken).where(RefreshToken.device_id == dev.id).values(revoked=True))
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=dev.child_id, entity="device", action="revoke", new={"device_id": dev.id})
    db.commit()
    return _msg_html(True, "Đã gỡ thiết bị và thu hồi toàn bộ token.")


@router.post("/children/{child_id}/kid-link", response_class=HTMLResponse)
async def kid_link(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                   ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    await form_with_csrf(request, web, ctx)
    token = random_token(24)
    db.add(KidLink(token_hash=sha256_hex(token), child_id=child.id, created_at=time.time()))
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=child.id, entity="kidlink", action="create")
    db.commit()
    from html import escape
    url = escape(str(request.base_url).rstrip("/") + f"/kid/{token}")  # Host header do client gửi => phải escape
    return HTMLResponse(f'<div class="toast ok">Link cho con (chỉ đọc): <a href="{url}" target="_blank" rel="noopener">{url}</a></div>')


# ------------------------------------------------------------------ duyệt yêu cầu
@router.post("/requests/{request_id}/{decision}", response_class=HTMLResponse)
async def decide_request(request_id: int, decision: str, request: Request, web: WebCtx = Depends(current_web),
                         db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    if decision not in ("approve", "deny"):
        raise HTTPException(404)
    req = owned_request(db, web.parent.id, request_id)
    form = await form_with_csrf(request, web, ctx)
    if req.status != "pending":
        return render(request, "_requests.html", {"web": web, "requests": pending_requests(db, ctx, web.parent.id),
                                                  "notes": NOTE_SUGGESTIONS})
    note = str(form.get("note", "")).strip()[:200]
    minutes = _int(form, "minutes", 5, 120, req.minutes)
    req.status = "approved" if decision == "approve" else "denied"
    req.decided_at = time.time()
    req.decided_by = web.actor_label
    req.note_enc = ctx.cipher.encrypt(note, "unlock_requests.note")
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=req.child_id, entity="request", action=decision,
                 new={"minutes": minutes if decision == "approve" else 0, "request_id": req.id})
    db.commit()
    dev = db.get(Device, req.device_id)
    if dev and not dev.revoked:
        payload = {"by": web.actor_label, "note": note, "request_id": req.id}
        if decision == "approve":
            await issue_command(ctx, db, dev, "add_time", {**payload, "minutes": minutes})
        else:
            await issue_command(ctx, db, dev, "request_denied", payload)
    return render(request, "_requests.html", {"web": web, "requests": pending_requests(db, ctx, web.parent.id),
                                              "notes": NOTE_SUGGESTIONS})


# ------------------------------------------------------------------ xuất CSV & xóa dữ liệu
@router.get("/children/{child_id}/export.csv")
def export_csv(child_id: int, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
               ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    tz = timezone(timedelta(minutes=420))
    since = time.time() - 7 * 86400
    buf = io.StringIO()
    buf.write("﻿")  # BOM để Excel đọc đúng tiếng Việt UTF-8
    w = csv.writer(buf)
    w.writerow(["ngay", "phut_su_dung"])
    for day, used in db.execute(select(DailyUsage.day, func.sum(DailyUsage.used_sec)).where(
            DailyUsage.child_id == child.id).group_by(DailyUsage.day).order_by(DailyUsage.day.desc()).limit(7)):
        w.writerow([day, round(used / 60)])
    w.writerow([])
    w.writerow(["thoi_diem", "loai", "doi_tuong", "thoi_luong_giay"])
    for e in db.scalars(select(Event).where(Event.child_id == child.id, Event.ts >= since).order_by(Event.ts)):
        w.writerow([datetime.fromtimestamp(e.ts, tz).strftime("%Y-%m-%d %H:%M"), e.type, e.subject, e.duration_sec])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ogk-bao-cao-tuan-{child.id}.csv"'})


@router.post("/children/{child_id}/purge", response_class=HTMLResponse)
async def purge(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    if str(form.get("confirm", "")).strip() != nick(ctx, child):  # xác nhận 2 bước: gõ đúng tên gọi của con
        return _msg_html(False, "Tên xác nhận chưa khớp — dữ liệu chưa bị xóa.")
    counts = {}
    for model in (Event, DailyUsage, UnlockRequest, IntegrityAlert):
        counts[model.__tablename__] = db.execute(delete(model).where(model.child_id == child.id)).rowcount
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=child.id, entity="data", action="purge", new=counts)
    db.commit()
    for d in child.devices:  # xóa cả bộ đệm trên agent
        if not d.revoked:
            await issue_command(ctx, db, d, "purge_data", {})
    return _msg_html(True, f"Đã xóa: {counts.get('events', 0)} sự kiện, {counts.get('daily_usage', 0)} bản tổng kết ngày. "
                           "Lệnh xóa bộ đệm đã gửi tới máy của con.")


@router.get("/family", response_class=HTMLResponse)
def family(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
           ctx: AppContext = Depends(get_ctx)):
    kids = [child_card(db, ctx, c) for c in children_of(db, web.parent.id)]
    guardians = [{"id": g.id, "display": ctx.cipher.decrypt(g.display_name_enc, "guardians.display_name"),
                  "call": ctx.cipher.decrypt(g.call_name_enc, "guardians.call_name"), "relation": g.relation}
                 for g in web.guardians]
    return render(request, "family.html", {"web": web, "page": "family", "kids": kids, "guardians": guardians})
