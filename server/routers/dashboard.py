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
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from agent import schedule as sch
from agent.domain_rules import CategoryMap, normalize

from .. import audit
from ..access import children_of, owned_child, owned_device, owned_request
from ..context import AppContext, client_ip, get_ctx
from ..db import get_db
from ..models import (AuditLog, Child, Command, DailyUsage, Device, Event, IntegrityAlert, KidLink, PairingCode,
                      UnlockRequest)
from ..policy_service import (DEFAULT_APP_CATEGORIES, age_mode, categories_map, create_policy_version, current_policy,
                              default_policy_body, school_schedule)
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


ACTIVITY = {"education": "Đang học tập", "games": "Đang chơi trò chơi", "entertainment": "Đang giải trí",
            "social": "Đang dùng mạng xã hội"}
WEEKDAY_FULL = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
REST_NOTE = "Con nghỉ ngơi một chút cho đỡ mỏi mắt nhé, lát nữa mình tính tiếp!"


def today_text() -> str:
    d = datetime.now(timezone(timedelta(minutes=420)))
    return f"{WEEKDAY_FULL[d.weekday()]}, {d.strftime('%d/%m/%Y')}"


def device_view(ctx: AppContext, dev: Device) -> dict:
    st = json.loads(dev.last_state_json or "{}")
    online_ws = ctx.hub.is_online(dev.id)
    fresh = dev.last_seen and time.time() - dev.last_seen < ctx.settings.offline_after_sec
    activity = ""
    if dev.revoked:
        status, label = "revoked", "Đã gỡ"
    elif not (online_ws or fresh):
        status, label = "offline", "Ngoại tuyến"
    elif st.get("phase") == "locked":
        status, label = "locked", (f"Tạm nghỉ đến {st['lock_until']}" if st.get("lock_until") else "Đang tạm nghỉ")
    elif st.get("phase") == "grace":
        status, label = "grace", "Sắp tạm nghỉ"
    else:
        # Chỉ biết NHÓM đang chạy (agent không gửi tên ứng dụng): "Online · Đang học tập".
        running = st.get("running") or []
        status, label = "active", "Online"
        activity = next((ACTIVITY[c] for c in ("education", "games", "entertainment", "social") if c in running),
                        "Đang dùng máy")
    return {"id": dev.id, "hostname": ctx.cipher.decrypt(dev.hostname_enc, "devices.hostname") or "Máy tính",
            "short_id": dev.id[:8] + "…", "activity": activity,
            "status": status, "label": label, "online_ws": online_ws, "last_seen": dev.last_seen,
            "remaining_min": round((st.get("remaining_sec") or 0) / 60), "used_min": round((st.get("used_sec") or 0) / 60),
            "quota_min": st.get("quota_min"), "policy_version": dev.policy_version, "revoked": dev.revoked,
            "skew": round(dev.clock_skew or 0), "stale": st.get("stale")}


AGE_GROUP = {"mam": "Mầm 6–8", "choi": "Chồi 9–11"}
PRONOUNS = ("con", "em", "mình", "cháu")
AVATARS = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}  # bạn đồng hành của con trên máy

# Trạng thái GỘP của một con (cho thanh chọn hồ sơ): máy "đang dùng" được ưu tiên hiển thị.
KID_STATUS = (("active", "Đang dùng"), ("grace", "Sắp tạm nghỉ"), ("locked", "Tạm nghỉ"), ("offline", "Ngoại tuyến"))

# Biểu tượng (Lucide) cho mỗi nhóm nội dung: "icon ứng dụng" trong Top ứng dụng / Top tên miền.
# Không tải favicon thật của trang web: làm vậy là để trình duyệt phụ huynh gọi tới bên thứ ba
# (lộ IP + danh sách trang con đã vào) và vi phạm CSP 'self'.
CAT_ICON = {"education": "graduation-cap", "games": "gamepad-2", "entertainment": "clapperboard",
            "social": "message-circle", "inappropriate": "shield", "uncategorized": "app-window"}
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe"}
# Thứ tự 6 thẻ nhóm nội dung (mỗi nhóm một màu pastel cố định, khớp màu lát biểu đồ tròn)
CAT_ORDER = ["education", "entertainment", "games", "social", "uncategorized", "inappropriate"]


def kid_status(devs: list[dict]) -> dict:
    states = {d["status"] for d in devs}
    for key, label in KID_STATUS:
        if key in states:
            return {"status": key, "label": label}
    return {"status": "none", "label": "Chưa ghép máy"}


def quota_for(day_iso: str, body: dict) -> int:
    """Hạn mức của MỘT ngày theo chính sách hiện hành (thứ 7, CN dùng weekend_min)."""
    q = body.get("quota") or {}
    wd = datetime.fromisoformat(day_iso).weekday()
    return int(q.get("weekend_min" if wd >= 5 else "weekday_min") or 0)


def child_card(db: Session, ctx: AppContext, child: Child, with_report: bool = False) -> dict:
    """Dữ liệu một thẻ "con" trên trang tổng quan. with_report=True: kèm báo cáo 7 ngày (biểu đồ, top
    ứng dụng/tên miền, số lần bị chặn) để phụ huynh thấy ngay mà không phải bấm vào từng con (Hình 6)."""
    devs = [device_view(ctx, d) for d in child.devices if not d.revoked]
    pending = db.scalar(select(func.count()).select_from(UnlockRequest)
                        .where(UnlockRequest.child_id == child.id, UnlockRequest.status == "pending")) or 0
    pol = current_policy(db, child.id)
    body = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    alerts = db.scalar(select(func.count()).select_from(IntegrityAlert)
                       .where(IntegrityAlert.child_id == child.id, IntegrityAlert.ts > time.time() - 86400)) or 0
    card = {"id": child.id, "nickname": nick(ctx, child), "avatar": child.avatar_key, "devices": devs,
            "pending": pending, "policy_version": pol.version if pol else 0, "alerts": alerts,
            "age": datetime.now().year - child.birth_year, "group": AGE_GROUP[age_mode(child.birth_year)],
            "birth_year": child.birth_year, "self_pronoun": child.self_pronoun, "state": kid_status(devs)}
    if with_report:
        card["report"] = enrich_report(db, child_report(db, child.id, cipher=ctx.cipher), body)
    return card


def enrich_report(db: Session, r: dict, body: dict) -> dict:
    """Thêm phần hiển thị cho PHỤ HUYNH: hạn mức từng ngày (đường "giới hạn cho phép" trên biểu đồ 7 ngày,
    ngày thường/cuối tuần khác nhau) và nhóm + biểu tượng cho từng ứng dụng / tên miền trong bảng Top."""
    for d in r["daily"]:
        d["quota"] = quota_for(d["day"], body)
    r["over_days"] = sum(1 for d in r["daily"] if d["quota"] and d["minutes"] > d["quota"])
    r["today_quota"] = r["daily"][-1]["quota"]
    app_cats = {**DEFAULT_APP_CATEGORIES, **((body.get("app_rules") or {}).get("categories") or {})}
    for a in r["top_apps"]:
        a["cat"] = app_cats.get(a["name"], "uncategorized")
        a["icon"] = "globe" if a["name"] in BROWSERS else CAT_ICON.get(a["cat"], "app-window")
    cmap = CategoryMap(categories_map(db))
    for dom in r["top_domains"]:
        dom["cat"] = cmap.category(dom["name"])
        dom["icon"] = "globe" if dom["cat"] == "uncategorized" else CAT_ICON.get(dom["cat"], "globe")

    # Gom theo NHÓM nội dung cho "xem chi tiết khi cần" (progressive disclosure): mặc định phụ huynh chỉ thấy
    # thẻ tổng của từng nhóm; bấm vào thẻ (hoặc lát biểu đồ tròn) mới mở ứng dụng / tên miền / nhật ký của nhóm đó.
    def cat_of(kind: str, subject: str) -> str:
        return app_cats.get(subject, "uncategorized") if kind in ("app_stop", "blocked_app") else cmap.category(subject)

    groups = {c: {"key": c, "minutes": r["cats_week"].get(c, 0), "apps": [], "domains": [], "blocked": [], "log": []}
              for c in CAT_ORDER}
    for c, m in r["cats_week"].items():
        groups.setdefault(c, {"key": c, "minutes": m, "apps": [], "domains": [], "blocked": [], "log": []})
    for a in r["top_apps"]:
        groups.get(a["cat"], groups["uncategorized"])["apps"].append(a)
    for dom in r["top_domains"]:
        groups.get(dom["cat"], groups["uncategorized"])["domains"].append(dom)
    for b in r["blocked"]:
        b["cat"] = cat_of(b["type"], b["name"])
        b["icon"] = "app-window" if b["type"] == "blocked_app" else "globe"
        groups.get(b["cat"], groups["uncategorized"])["blocked"].append(b)
    for e in r["recent"]:
        g = groups.get(cat_of(e["type"], e["subject"]), groups["uncategorized"])
        if len(g["log"]) < 12:
            g["log"].append(e)
    total = sum(r["cats_week"].values())
    for g in groups.values():
        g["share"] = round(100 * g["minutes"] / total) if total else 0
        g["blocked_n"] = sum(b["count"] for b in g["blocked"])
        g["icon"] = CAT_ICON.get(g["key"], "app-window")
    r["groups"] = list(groups.values())

    # Số liệu tóm tắt cho dải "con số" dưới biểu đồ 7 ngày
    r["avg_day"] = round(r["week_minutes"] / 7)
    r["peak"] = max(r["daily"], key=lambda d: d["minutes"])
    r["edu_share"] = round(100 * r["cats_week"].get("education", 0) / total) if total else 0
    return r


def requests_ctx(db: Session, ctx: AppContext, web: WebCtx) -> dict:
    """Dữ liệu cho _requests.html khi trả về qua HTMX. oob_counts: kèm số yêu cầu chờ của TỪNG con
    (hx-swap-oob) => huy hiệu trên thanh chọn hồ sơ tự cập nhật cùng lúc với danh sách yêu cầu."""
    return {"web": web, "requests": pending_requests(db, ctx, web.parent.id), "notes": NOTE_SUGGESTIONS,
            "oob_counts": True, "kid_ids": [c.id for c in children_of(db, web.parent.id)]}


def pending_requests(db: Session, ctx: AppContext, parent_id: int) -> list[dict]:
    rows = db.execute(select(UnlockRequest, Child).join(Child, UnlockRequest.child_id == Child.id)
                      .where(Child.parent_id == parent_id, UnlockRequest.status == "pending")
                      .order_by(UnlockRequest.created_at)).all()
    return [{"id": r.id, "minutes": r.minutes, "created_at": r.created_at, "child": nick(ctx, c), "avatar": c.avatar_key,
             "child_id": c.id,
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
def overview(request: Request, con: int | None = None, web: WebCtx = Depends(current_web),
             db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    """Tổng quan: thanh chọn hồ sơ (?con=<id>) + một cụm Bento cho MỖI con. Mọi cụm đều có trong trang
    (tắt JS vẫn chuyển hồ sơ được bằng liên kết); app.js chỉ ẩn/hiện cụm => chuyển tức thì, không tải lại."""
    kids = [child_card(db, ctx, c, with_report=True) for c in children_of(db, web.parent.id)]
    selected = con if any(k["id"] == con for k in kids) else (kids[0]["id"] if kids else None)
    return render(request, "overview.html", {"web": web, "kids": kids, "page": "overview", "ctx": ctx,
                                             "selected": selected, "requests": pending_requests(db, ctx, web.parent.id),
                                             "notes": NOTE_SUGGESTIONS, "today_text": today_text(),
                                             "guide": guide_state(db, web, kids)})


def guide_state(db: Session, web: WebCtx, kids: list[dict]) -> dict:
    """Hướng dẫn nhanh 4 bước: đánh dấu bước đã xong từ dữ liệu thật của gia đình này."""
    links = db.scalar(select(func.count()).select_from(KidLink).join(Child, KidLink.child_id == Child.id)
                      .where(Child.parent_id == web.parent.id)) or 0
    g = {"kid": bool(kids), "device": any(k["devices"] for k in kids),
         "policy": any(k["policy_version"] > 1 for k in kids), "link": links > 0}
    g["done"] = sum(1 for v in g.values() if v)
    return g


@router.get("/huong-dan", response_class=HTMLResponse)
def help_page(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
              ctx: AppContext = Depends(get_ctx)):
    """Trang phụ "Hướng dẫn & hỏi đáp": 4 bước bắt đầu nhanh, lời nhắn minh bạch, câu hỏi thường gặp.
    Tách khỏi trang tổng quan để trang chính chỉ còn các khối dùng hằng ngày."""
    kids = [child_card(db, ctx, c) for c in children_of(db, web.parent.id)]
    return render(request, "help.html", {"web": web, "kids": kids, "page": "help", "guide": guide_state(db, web, kids)})


@router.get("/partials/status", response_class=HTMLResponse)
def status_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                   ctx: AppContext = Depends(get_ctx)):
    """Trạng thái thiết bị theo thời gian thực: trả về các thẻ thiết bị + nhãn trạng thái trên tab hồ sơ dạng
    hx-swap-oob => chỉ thay đúng các phần tử có cùng id, biểu đồ và ô đang gõ trên trang không bị vẽ lại."""
    kids = []
    for c in children_of(db, web.parent.id):
        devs = [device_view(ctx, d) for d in c.devices if not d.revoked]
        kids.append({"id": c.id, "devices": devs, "state": kid_status(devs)})
    return render(request, "_status.html", {"kids": kids, "devices": [d for k in kids for d in k["devices"]]})


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                     ctx: AppContext = Depends(get_ctx)):
    kids = [child_card(db, ctx, c, with_report=True) for c in children_of(db, web.parent.id)]
    return render(request, "_overview_cards.html", {"web": web, "kids": kids, "selected": kids[0]["id"] if kids else None})


@router.get("/partials/requests", response_class=HTMLResponse)
def requests_partial(request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                     ctx: AppContext = Depends(get_ctx)):
    return render(request, "_requests.html", requests_ctx(db, ctx, web))


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
    if not nickname or pronoun not in PRONOUNS or not 2005 <= birth_year <= datetime.now().year:
        return render(request, "child_new.html", {"web": web, "page": "family",
                                                  "error": "Vui lòng nhập tên gọi, cách xưng hô và năm sinh hợp lệ."}, 400)
    child = Child(parent_id=web.parent.id, nickname_enc=ctx.cipher.encrypt(nickname, "children.nickname"),
                  self_pronoun=pronoun, birth_year=birth_year, avatar_key=(a if (a := str(form.get("avatar_key", ""))) in AVATARS else "tictac"),
                  created_at=time.time())
    db.add(child)
    db.flush()
    create_policy_version(db, child.id, default_policy_body(birth_year))
    audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                 ip=client_ip(request), child_id=child.id, entity="child", action="create")
    db.commit()
    return RedirectResponse(f"/children/{child.id}#ghep-thiet-bi", status_code=303)


@router.get("/children/{child_id}", response_class=HTMLResponse)
def child_page(child_id: int, request: Request, web: WebCtx = Depends(current_web),
               db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    """MỘT trang cuộn cho mỗi con (theo Hình 7 của tài liệu hướng dẫn): chính sách + lịch 7×48, báo cáo,
    thiết bị, ghép máy/link cho con, nhật ký, xóa dữ liệu. Link cũ dạng ?tab=... vẫn mở được (tham số bị bỏ qua)."""
    child = owned_child(db, web.parent.id, child_id)
    pol = current_policy(db, child.id)
    body = json.loads(pol.body_json) if pol else default_policy_body(child.birth_year)
    entries = db.scalars(select(AuditLog).where(AuditLog.child_id == child.id)
                         .order_by(AuditLog.ts.desc()).limit(100)).all()
    data = {"web": web, "page": "child", "child": child_card(db, ctx, child), "child_obj": child,
            "policy": body, "policy_version": pol.version if pol else 0, "categories": CATEGORY_CHOICES,
            "msg": request.query_params.get("msg"),
            "report": enrich_report(db, child_report(db, child.id, cipher=ctx.cipher), body), "audience": "parent",
            "entries": [{"e": e, "who": audit.actor_text(e), "lines": audit.humanize(e)} for e in entries],
            "alerts": db.scalars(select(IntegrityAlert).where(IntegrityAlert.child_id == child.id)
                                 .order_by(IntegrityAlert.ts.desc()).limit(20)).all(),
            "devices": [device_view(ctx, d) for d in child.devices],
            "school_template": school_schedule()}
    return render(request, "child.html", data)


@router.post("/children/{child_id}/profile")
async def child_profile_update(child_id: int, request: Request, web: WebCtx = Depends(current_web),
                               db: Session = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    """Lưu "Hồ sơ của con" (bảng mở ra khi phụ huynh bấm vào TÊN con): tên gọi, năm sinh, cách xưng hô,
    bạn đồng hành. Quay về đúng trang đã mở bảng (back chỉ nhận 3 giá trị cố định => không có open redirect)."""
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    back = {"overview": f"/?con={child.id}", "family": "/family"}.get(str(form.get("back", "")), f"/children/{child.id}")
    sep = "&" if "?" in back else "?"
    nickname = str(form.get("nickname", "")).strip()[:20]
    pronoun = str(form.get("self_pronoun", child.self_pronoun))
    avatar = str(form.get("avatar_key", child.avatar_key))
    try:
        birth_year = int(form.get("birth_year", child.birth_year))
    except ValueError:
        birth_year = 0
    if (not nickname or pronoun not in PRONOUNS or avatar not in AVATARS
            or not 2005 <= birth_year <= datetime.now().year):
        return RedirectResponse(f"{back}{sep}saved=invalid", status_code=303)
    changed = [f for f, cur, val in (("nickname", nick(ctx, child), nickname), ("birth_year", child.birth_year, birth_year),
                                     ("self_pronoun", child.self_pronoun, pronoun), ("avatar_key", child.avatar_key, avatar))
               if cur != val]
    if changed:
        old = {"fields": changed, "birth_year": child.birth_year, "self_pronoun": child.self_pronoun, "avatar_key": child.avatar_key}
        child.nickname_enc = ctx.cipher.encrypt(nickname, "children.nickname")
        child.birth_year, child.self_pronoun, child.avatar_key = birth_year, pronoun, avatar
        # Nhật ký: ghi TRƯỜNG nào đổi; tên gọi được mã hóa nên KHÔNG chép tên cũ/mới dạng rõ vào audit_log
        audit.record(db, actor_type="parent", actor_id=str(web.parent.id), actor_label=web.actor_label,
                     ip=client_ip(request), child_id=child.id, entity="child", action="update", old=old,
                     new={"fields": changed, "birth_year": birth_year, "self_pronoun": pronoun, "avatar_key": avatar})
        db.commit()
        for d in child.devices:  # hồ sơ đi kèm chính sách đã ký (tuổi => chế độ Mầm/Chồi) => báo agent tải lại
            await ctx.hub.send(d.id, {"type": "policy_changed"})
    return RedirectResponse(f"{back}{sep}saved={'profile' if changed else 'nochange'}", status_code=303)


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


def _apply_time(form, p: dict) -> None:
    p["quota"]["weekday_min"] = _int(form, "weekday_min", 0, 1440, 90)
    p["quota"]["weekend_min"] = _int(form, "weekend_min", 0, 1440, 150)
    budgets = {}
    for cat in ("games", "entertainment"):
        if str(form.get(f"budget_{cat}", "")).strip():
            budgets[cat] = _int(form, f"budget_{cat}", 0, 1440, 45)
    p["category_budgets"] = budgets


def _apply_filter(form, p: dict) -> None:
    # Danh sách từ trình duyệt được LỌC LẠI bằng regex (tên miền/.exe/SHA-256): không tin dữ liệu phía client.
    p["dns"]["blocked_categories"] = [c for c in form.getlist("blocked_categories") if c in CATEGORY_CHOICES]
    p["dns"]["safesearch"] = form.get("safesearch") == "on"
    p["dns"]["block_doh"] = form.get("block_doh") == "on"
    p["dns"]["block"] = [normalize(d) for d in lines(str(form.get("dns_block", "")), DOMAIN_RE)]
    p["dns"]["allow"] = [normalize(d) for d in lines(str(form.get("dns_allow", "")), DOMAIN_RE)]
    p["app_rules"]["block_names"] = lines(str(form.get("app_block_names", "")), EXE_RE)
    p["app_rules"]["block_sha256"] = lines(str(form.get("app_block_sha256", "")), SHA_RE)
    p["app_rules"]["allow_names"] = lines(str(form.get("app_allow_names", "")), EXE_RE)


@router.post("/children/{child_id}/policy", response_class=HTMLResponse)
async def policy_all(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                     ctx: AppContext = Depends(get_ctx)):
    """Lưu cả chính sách bằng MỘT biểu mẫu (Hình 7): hạn mức + lịch 7×48 + nhóm nội dung + danh sách miền/ứng dụng.
    Mỗi lần lưu = một phiên bản mới, audit giá trị cũ/mới, đẩy policy_changed (trong save_policy)."""
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    s = str(form.get("schedule", ""))
    if not sch.validate(s):  # server KIỂM TRA LẠI chuỗi 336 ký tự, không tin JavaScript phía client
        return _msg_html(False, "Lịch không hợp lệ (cần đúng 336 ô 0/1).")

    def mutate(p):
        _apply_time(form, p)
        p["schedule"] = s
        _apply_filter(form, p)

    ok, msg = await save_policy(db, ctx, web, child, client_ip(request), mutate)
    resp = _msg_html(ok, msg)
    pol = current_policy(db, child.id)
    if ok and pol:
        # HTMX out-of-band swap: cập nhật nhãn "phiên bản N" ở đầu thẻ mà không tải lại trang.
        oob = f'<span class="ver" id="policy-ver" hx-swap-oob="true">phiên bản {pol.version}</span>'
        resp = HTMLResponse(resp.body.decode() + oob)
    return resp


@router.post("/children/{child_id}/policy/time", response_class=HTMLResponse)
async def policy_time(child_id: int, request: Request, web: WebCtx = Depends(current_web), db: Session = Depends(get_db),
                      ctx: AppContext = Depends(get_ctx)):
    child = owned_child(db, web.parent.id, child_id)
    form = await form_with_csrf(request, web, ctx)
    return _msg_html(*await save_policy(db, ctx, web, child, client_ip(request), lambda p: _apply_time(form, p)))


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
    return _msg_html(*await save_policy(db, ctx, web, child, client_ip(request), lambda p: _apply_filter(form, p)))


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
    if ctype == "lock_now" and str(form.get("minutes", "")).strip():
        payload["minutes"] = _int(form, "minutes", 5, 24 * 60, 120)  # "Tạm nghỉ 2h": agent tự mở khi hết hạn
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
    # Tạo link mới => link cũ HẾT HIỆU LỰC: lỡ lộ link cũ (gửi nhầm, lịch sử trình duyệt) thì chỉ cần tạo lại.
    db.execute(update(KidLink).where(KidLink.child_id == child.id, KidLink.revoked.is_(False)).values(revoked=True))
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
        return render(request, "_requests.html", requests_ctx(db, ctx, web))
    note = str(form.get("note", "")).strip()[:200]
    if decision == "deny" and not note:
        note = REST_NOTE  # "Nhắc bé nghỉ ngơi": luôn kèm lời nhắn dịu dàng, không từ chối "im lặng"
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
    return render(request, "_requests.html", requests_ctx(db, ctx, web))


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
