"""
server/db.py — Kết nối SQLite qua SQLAlchemy, bật chế độ WAL.

Yêu cầu đề: §4.2 (SQLite với WAL).

PRAGMA được đặt cho MỖI kết nối mới:
  journal_mode=WAL   người đọc (dashboard) không bị chặn bởi người ghi (agent đẩy sự kiện)
  synchronous=NORMAL an toàn với WAL, nhanh hơn FULL nhiều lần
  foreign_keys=ON    SQLite mặc định TẮT ràng buộc khóa ngoại!
  busy_timeout=5000  khi có người đang ghi, chờ tối đa 5 giây thay vì lỗi "database is locked"
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_engine = None
SessionLocal: sessionmaker | None = None


def init_engine(url: str):
    global _engine, SessionLocal
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine():
    return _engine


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
