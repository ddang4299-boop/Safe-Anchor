"""
server/jobs.py — Tác vụ nền: xóa dữ liệu quá 90 ngày, dọn phiên/mã ghép/lệnh hết hạn.

Yêu cầu đề: F3 (BẮT BUỘC: lưu 90 ngày, có tác vụ tự động xóa).
Chạy một lần lúc khởi động rồi lặp lại mỗi 6 giờ (đủ "hằng đêm" mà không cần cron ngoài).
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import delete
from sqlalchemy.orm import Session

from . import db as dbmod
from .models import (AuditLog, Command, DailyUsage, Event, IntegrityAlert, PairingCode, RefreshToken,
                     UnlockRequest, WebSession)

log = logging.getLogger("ogk.jobs")


def purge_expired(db: Session, retention_days: int = 90, now: float | None = None) -> dict:
    now = now or time.time()
    cutoff = now - retention_days * 86400
    day_cutoff = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
    counts = {
        "events": db.execute(delete(Event).where(Event.ts < cutoff)).rowcount,
        "daily_usage": db.execute(delete(DailyUsage).where(DailyUsage.day < day_cutoff)).rowcount,
        "unlock_requests": db.execute(delete(UnlockRequest).where(UnlockRequest.created_at < cutoff)).rowcount,
        "integrity_alerts": db.execute(delete(IntegrityAlert).where(IntegrityAlert.ts < cutoff)).rowcount,
        "audit_log": db.execute(delete(AuditLog).where(AuditLog.ts < now - 365 * 86400)).rowcount,
        "sessions": db.execute(delete(WebSession).where(WebSession.expires_at < now)).rowcount,
        "pairing_codes": db.execute(delete(PairingCode).where(PairingCode.expires_at < now - 86400)).rowcount,
        "refresh_tokens": db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now)).rowcount,
        "commands": db.execute(delete(Command).where(Command.created_at < now - 7 * 86400)).rowcount,
    }
    db.commit()
    return counts


async def retention_loop(retention_days: int, interval: float = 6 * 3600) -> None:
    while True:
        try:
            with dbmod.SessionLocal() as db:
                counts = purge_expired(db, retention_days)
            log.info("Dọn dữ liệu quá hạn: %s", counts)
        except Exception:
            log.exception("job dọn dữ liệu lỗi")
        await asyncio.sleep(interval)
