"""
server/routers/agent_api.py — API cho OGK-Agent (Bearer token thiết bị), tiền tố /api.

Yêu cầu đề: §4.3 (ghép đôi, heartbeat 60s, lệnh khẩn WebSocket, ngoại tuyến + idempotency),
F3 (sự kiện 7 trường), F4 (chính sách có version + chữ ký), F5 (token 15 phút + refresh xoay vòng).

    POST /api/enroll                 mã 8 ký tự + fingerprint -> device_id + token + khóa công khai
    POST /api/token/refresh          xoay vòng refresh token, phát hiện dùng lại (reuse)
    GET  /api/policy                 phong bì chính sách đã ký riêng cho thiết bị
    POST /api/heartbeat              trạng thái -> giờ server + version mới nhất + lệnh chờ
    POST /api/events                 lô <= 200 sự kiện, INSERT ... ON CONFLICT(idem_key) DO NOTHING
    POST /api/commands/{id}/ack      xác nhận đã áp dụng lệnh
    POST /api/unlock-requests        trẻ "Xin thêm giờ"
    GET  /api/today | /api/audit     dữ liệu minh bạch cho Tray
    WS   /api/ws                     kênh lệnh khẩn
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from agent.domain_rules import registrable_domain

from .. import audit
from ..access import children_of  # noqa: F401  (giữ import cho tài liệu)
from ..context import AppContext, client_ip, get_ctx
from .. import db as dbmod
from ..db import get_db
from ..models import (EVENT_TYPES, Child, Command, DailyUsage, Device, Event, IntegrityAlert, PairingCode,
                      RefreshToken, UnlockRequest)
from ..policy_service import build_envelope, current_policy
from ..reports import child_report
from ..security import (TokenError, make_access_token, normalize_pairing_code, parse_access_token,
                        random_token, sha256_hex)

router = APIRouter(prefix="/api", tags=["agent"])

UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,36}$")
MAX_BATCH = 200


# ------------------------------------------------------------------ xác thực thiết bị
def device_from_token(db: Session, ctx: AppContext, token: str) -> Device:
    try:
        device_id = parse_access_token(ctx.settings.secret, token)
    except TokenError as exc:
        raise HTTPException(401, detail=str(exc))
    dev = db.get(Device, device_id)
    if dev is None or dev.revoked:  # thu hồi tức thì dù access token chưa hết hạn
        raise HTTPException(401, detail="thiết bị đã bị gỡ")
    return dev


def current_device(request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)) -> Device:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, detail="thiếu Bearer token")
    return device_from_token(db, ctx, auth[7:].strip())


def _issue_tokens(db: Session, ctx: AppContext, device: Device, family_id: str | None = None,
                  rotated_from: int | None = None) -> dict:
    refresh = random_token(32)
    now = time.time()
    db.add(RefreshToken(device_id=device.id, token_hash=sha256_hex(refresh), family_id=family_id or str(uuid.uuid4()),
                        rotated_from=rotated_from, created_at=now, expires_at=now + ctx.settings.refresh_ttl))
    return {"access_token": make_access_token(ctx.settings.secret, device.id, ctx.settings.access_ttl),
            "access_expires_in": ctx.settings.access_ttl, "refresh_token": refresh}


# ------------------------------------------------------------------ ghép đôi
class EnrollIn(BaseModel):
    code: str = Field(max_length=16)
    fingerprint: str = Field(min_length=16, max_length=128)  # SHA-256(MachineGuid + serial ổ đĩa)
    hostname: str = Field(default="", max_length=64)


@router.post("/enroll")
def enroll(body: EnrollIn, request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    ip = client_ip(request)
    if not ctx.enroll_limiter.allow(f"enroll:{ip}"):
        raise HTTPException(429, detail="Thử quá nhiều lần, chờ 1 phút")
    code = normalize_pairing_code(body.code)
    now = time.time()
    pc = db.scalar(select(PairingCode).where(PairingCode.code_hash == sha256_hex(code)))
    # Cùng một thông báo lỗi cho mọi trường hợp (không tồn tại / hết hạn / đã dùng) => không lộ thông tin.
    if pc is None or pc.used_at is not None or pc.expires_at < now:
        raise HTTPException(400, detail="Mã ghép không hợp lệ hoặc đã hết hạn")
    # Dùng MỘT LẦN, nguyên tử: UPDATE có điều kiện used_at IS NULL. Hai agent gửi cùng mã đồng thời
    # thì chỉ một UPDATE đổi được 1 hàng (rowcount == 1), agent kia nhận lỗi.
    res = db.execute(update(PairingCode).where(PairingCode.id == pc.id, PairingCode.used_at.is_(None))
                     .values(used_at=now))
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(400, detail="Mã ghép không hợp lệ hoặc đã hết hạn")
    child = db.get(Child, pc.child_id)
    alg = ctx.settings.policy_alg
    hmac_key_b64 = base64.b64encode(os.urandom(32)).decode() if alg == "hmac-sha256" else None
    dev = Device(id=str(uuid.uuid4()), child_id=child.id, fingerprint_hash=sha256_hex(body.fingerprint),
                 hostname_enc=ctx.cipher.encrypt(body.hostname, "devices.hostname"), created_at=now,
                 last_seen=now, last_ip=ip, policy_alg=alg,
                 hmac_key_enc=ctx.cipher.encrypt(hmac_key_b64, "devices.hmac_key") if hmac_key_b64 else None)
    db.add(dev)
    db.flush()
    tokens = _issue_tokens(db, ctx, dev)
    audit.record(db, actor_type="device", actor_id=dev.id, actor_label="Máy tính", ip=ip, child_id=child.id,
                 entity="device", action="enroll", new={"device_id": dev.id, "consent_at": now, "ip": ip})
    db.commit()
    return {"device_id": dev.id, "child_id": child.id, **tokens, "policy_alg": alg,
            "policy_public_key": ctx.signer.public_key_b64, "hmac_key": hmac_key_b64,
            "server_time": time.time(), "heartbeat_sec": ctx.settings.heartbeat_sec}


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=128)


@router.post("/token/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    ip = client_ip(request)
    if not ctx.refresh_limiter.allow(f"refresh:{ip}"):
        raise HTTPException(429, detail="Quá nhiều yêu cầu")
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(body.refresh_token)))
    now = time.time()
    if rt is None:
        raise HTTPException(401, detail="refresh token không hợp lệ")
    if rt.revoked:
        # PHÁT HIỆN DÙNG LẠI: token đã xoay vòng mà vẫn có người dùng => có thể bị đánh cắp.
        # Thu hồi CẢ HỌ token (family) => kẻ trộm lẫn máy thật đều phải ghép đôi lại.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == rt.family_id).values(revoked=True))
        dev = db.get(Device, rt.device_id)
        audit.record(db, actor_type="system", ip=ip, child_id=dev.child_id if dev else None,
                     entity="token", action="reuse", new={"device_id": rt.device_id})
        db.commit()
        raise HTTPException(401, detail="refresh token đã được dùng — phiên bị thu hồi")
    dev = db.get(Device, rt.device_id)
    if rt.expires_at < now or dev is None or dev.revoked:
        raise HTTPException(401, detail="refresh token hết hạn hoặc thiết bị đã bị gỡ")
    rt.revoked = True  # xoay vòng: token cũ chết ngay khi đổi
    tokens = _issue_tokens(db, ctx, dev, family_id=rt.family_id, rotated_from=rt.id)
    db.commit()
    return tokens


# ------------------------------------------------------------------ chính sách
@router.get("/policy")
def get_policy(dev: Device = Depends(current_device), db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    child = db.get(Child, dev.child_id)
    return build_envelope(ctx, db, dev, child)


# ------------------------------------------------------------------ heartbeat
class HeartbeatIn(BaseModel):
    policy_version: int = 0
    client_time: float = 0
    state: dict = Field(default_factory=dict)
    integrity: list[dict] = Field(default_factory=list, max_length=50)


def _pending_commands(db: Session, device_id: str) -> list[dict]:
    cmds = db.scalars(select(Command).where(Command.device_id == device_id, Command.status.in_(("pending", "sent")))
                      .order_by(Command.created_at)).all()
    return [{"command_id": c.id, "cmd": c.type, "payload": json.loads(c.payload_json)} for c in cmds]


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, request: Request, dev: Device = Depends(current_device),
              db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    now = time.time()
    dev.last_seen = now
    dev.last_ip = client_ip(request)
    dev.policy_version = body.policy_version
    dev.clock_skew = (body.client_time - now) if body.client_time else 0.0
    st = body.state or {}
    dev.last_state_json = json.dumps({k: st.get(k) for k in ("phase", "lock_reason", "remaining_sec", "used_sec",
                                                              "quota_min", "day", "stale")}, ensure_ascii=False)
    day = str(st.get("day") or "")[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        used = max(0, min(int(st.get("used_sec") or 0), 86400))
        cats = {str(k)[:20]: max(0, min(float(v), 86400)) for k, v in (st.get("by_category") or {}).items()}
        du = db.get(DailyUsage, (dev.id, day))
        if du is None:
            db.add(DailyUsage(device_id=dev.id, day=day, child_id=dev.child_id, used_sec=used,
                              by_category_json=json.dumps(cats), updated_at=now))
        else:  # bộ đếm trong ngày chỉ tăng: lấy max để chống báo lùi
            du.used_sec = max(du.used_sec, used)
            old = json.loads(du.by_category_json or "{}")
            du.by_category_json = json.dumps({c: max(old.get(c, 0), cats.get(c, 0)) for c in set(old) | set(cats)})
            du.updated_at = now
    for alert in body.integrity[:50]:
        db.add(IntegrityAlert(device_id=dev.id, child_id=dev.child_id, ts=now, kind=str(alert.get("kind", ""))[:32],
                              detail_json=json.dumps(alert, ensure_ascii=False)[:1000]))
    pol = current_policy(db, dev.child_id)
    reqs = db.scalars(select(UnlockRequest).where(UnlockRequest.device_id == dev.id)
                      .order_by(UnlockRequest.created_at.desc()).limit(3)).all()
    db.commit()
    return {
        "server_time": time.time(),  # dùng cho thuật toán Cristian phía agent
        "policy_version": pol.version if pol else 0,
        "commands": _pending_commands(db, dev.id),
        "requests": [{"id": r.id, "status": r.status, "minutes": r.minutes,
                      "note": ctx.cipher.decrypt(r.note_enc, "unlock_requests.note")} for r in reqs],
        "heartbeat_sec": ctx.settings.heartbeat_sec,
    }


# ------------------------------------------------------------------ sự kiện (idempotent)
class EventIn(BaseModel):
    idem_key: str = Field(max_length=36)
    ts: float
    type: str
    subject: str = Field(default="", max_length=253)
    duration_sec: int = 0
    policy_id: int | None = None


class EventsIn(BaseModel):
    events: list[EventIn] = Field(max_length=MAX_BATCH)


@router.post("/events")
def post_events(body: EventsIn, dev: Device = Depends(current_device), db: Session = Depends(get_db)):
    now = time.time()
    rows, rejected = [], []
    for e in body.events:
        err = None
        if not UUID_RE.match(e.idem_key):
            err = "idem_key"
        elif e.type not in EVENT_TYPES:
            err = "type"
        elif not (now - 100 * 86400 <= e.ts <= now + 86400):
            err = "ts"
        elif not 0 <= e.duration_sec <= 86400:
            err = "duration"
        if err:
            rejected.append({"idem_key": e.idem_key, "error": err})
            continue
        subject = e.subject.strip()
        if e.type in ("domain_query", "blocked_domain"):
            subject = registrable_domain(subject)  # server cũng ép tên miền cấp hai (P2), không tin agent
        # device_id/child_id lấy từ TOKEN, không lấy từ body => agent không ghi hộ thiết bị khác được.
        rows.append({"idem_key": e.idem_key, "ts": e.ts, "device_id": dev.id, "child_id": dev.child_id,
                     "type": e.type, "subject": subject[:253], "duration_sec": e.duration_sec, "policy_id": e.policy_id})
    inserted = 0
    if rows:
        keys = [r["idem_key"] for r in rows]
        existing = set(db.scalars(select(Event.idem_key).where(Event.idem_key.in_(keys))))
        # INSERT ... ON CONFLICT(idem_key) DO NOTHING: gửi lại lô cũ (do mất ACK) không tạo bản sao.
        stmt = sqlite_insert(Event).values(rows).on_conflict_do_nothing(index_elements=["idem_key"])
        db.execute(stmt)
        db.commit()
        inserted = len(set(keys) - existing)
    # ACK cả sự kiện trùng lẫn sự kiện bị loại => agent xóa khỏi hàng đợi, tránh "thông điệp độc" lặp mãi.
    acked = [r["idem_key"] for r in rows] + [r["idem_key"] for r in rejected]
    return {"acked": acked, "inserted": inserted, "duplicates": len(rows) - inserted, "rejected": rejected}


# ------------------------------------------------------------------ lệnh
@router.post("/commands/{command_id}/ack")
def ack_command(command_id: str, dev: Device = Depends(current_device), db: Session = Depends(get_db)):
    _ack(db, dev.id, command_id)
    return {"ok": True}


def _ack(db: Session, device_id: str, command_id: str) -> bool:
    # điều kiện device_id trong WHERE: thiết bị chỉ ack được lệnh CỦA MÌNH
    res = db.execute(update(Command).where(Command.id == command_id, Command.device_id == device_id,
                                           Command.status != "acked").values(status="acked", acked_at=time.time()))
    db.commit()
    return res.rowcount == 1


# ------------------------------------------------------------------ yêu cầu thêm giờ
class UnlockReqIn(BaseModel):
    minutes: int
    reason: str = Field(default="", max_length=200)


@router.post("/unlock-requests")
def create_unlock_request(body: UnlockReqIn, dev: Device = Depends(current_device), db: Session = Depends(get_db),
                          ctx: AppContext = Depends(get_ctx)):
    if body.minutes not in (15, 30, 60):
        raise HTTPException(422, detail="Chỉ xin 15, 30 hoặc 60 phút")
    pending = db.scalar(select(UnlockRequest).where(UnlockRequest.device_id == dev.id, UnlockRequest.status == "pending"))
    if pending:  # đã có yêu cầu đang chờ => trả lại yêu cầu đó, không tạo thêm (chống spam)
        return {"id": pending.id, "status": "pending", "duplicate": True}
    if not ctx.request_limiter.allow(dev.id):
        raise HTTPException(429, detail="Con đã gửi nhiều yêu cầu, chờ ba mẹ trả lời nhé")
    now = time.time()
    req = UnlockRequest(child_id=dev.child_id, device_id=dev.id, minutes=body.minutes, created_at=now,
                        reason_enc=ctx.cipher.encrypt(body.reason.strip(), "unlock_requests.reason"))
    db.add(req)
    pol = current_policy(db, dev.child_id)
    db.add(Event(idem_key=str(uuid.uuid4()), ts=now, device_id=dev.id, child_id=dev.child_id, type="unlock_request",
                 subject="request", duration_sec=body.minutes * 60, policy_id=pol.id if pol else None))
    db.commit()
    return {"id": req.id, "status": "pending"}


# ------------------------------------------------------------------ minh bạch cho Tray
@router.get("/today")
def today(dev: Device = Depends(current_device), db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    rep = child_report(db, dev.child_id, cipher=ctx.cipher)
    return {k: rep[k] for k in ("today_minutes", "cats_today", "top_apps", "top_domains", "daily")}


@router.get("/audit")
def audit_for_kid(dev: Device = Depends(current_device), db: Session = Depends(get_db)):
    from ..models import AuditLog
    entries = db.scalars(select(AuditLog).where(AuditLog.child_id == dev.child_id)
                         .order_by(AuditLog.ts.desc()).limit(30)).all()
    return {"items": [{"when": audit.when_text(e.ts), "lines": audit.humanize(e)} for e in entries]}


# ------------------------------------------------------------------ WebSocket lệnh khẩn
@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Giao thức: agent mở kết nối -> tin nhắn ĐẦU TIÊN {"type":"auth","access_token":...} (không đặt
    token trên URL vì URL hay bị ghi vào log proxy) -> server đẩy lệnh chờ -> agent gửi ack theo command_id."""
    ctx: AppContext = ws.app.state.ctx
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except Exception:
        await ws.close(code=4401)
        return
    db = dbmod.SessionLocal()
    try:
        try:
            dev = device_from_token(db, ctx, str(first.get("access_token", ""))) if first.get("type") == "auth" else None
        except HTTPException:
            dev = None
        if dev is None:
            await ws.close(code=4401)
            return
        device_id = dev.id
        await ctx.hub.register(device_id, ws)
        await ws.send_json({"type": "auth_ok", "server_time": time.time()})
        for c in _pending_commands(db, device_id):  # đẩy bù lệnh phát sinh lúc agent mất kết nối
            await ws.send_json({"type": "command", **c})
    finally:
        db.close()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ack" and msg.get("command_id"):
                db = dbmod.SessionLocal()
                try:
                    _ack(db, device_id, str(msg["command_id"]))
                finally:
                    db.close()
            elif msg.get("type") == "ping":
                await ws.send_json({"type": "pong", "server_time": time.time()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ctx.hub.unregister(device_id, ws)
