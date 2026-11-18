"""
server/models.py — Mô hình dữ liệu (SQLAlchemy 2.x).

Yêu cầu đề: F4 (1 phụ huynh : n trẻ : m thiết bị), F3 (sự kiện đúng 7 trường), F4 (audit),
F5 (băm bí mật thiết bị, mã hóa trường nhạy cảm — cột *_enc là AES-256-GCM).

    Parent 1 ──< n Child 1 ──< m Device
       │            │             ├──< RefreshToken (xoay vòng, thu hồi)
       │            │             ├──< Command (lệnh khẩn)
       │            │             └──< DailyUsage
       │            ├──< Policy (version tăng ngặt, UNIQUE(child_id, version))
       │            ├──< Event (7 trường + idem_key UNIQUE)
       │            └──< UnlockRequest
       └──< Guardian (Ba, Mẹ...: tên gọi để ký lời nhắn, ghi "ai đã đổi")
Mọi thời điểm lưu dạng epoch giây (REAL, UTC) để không phụ thuộc múi giờ máy chủ.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EVENT_TYPES = ("app_start", "app_stop", "domain_query", "blocked_app", "blocked_domain",
               "quota_warning", "locked", "unlock_request", "override_granted")


class Base(DeclarativeBase):
    pass


class Parent(Base):
    __tablename__ = "parents"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    pw_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="parent")  # parent | admin
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[float] = mapped_column(Float)
    children: Mapped[list["Child"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    guardians: Mapped[list["Guardian"]] = relationship(back_populates="parent", cascade="all, delete-orphan")


class Guardian(Base):
    __tablename__ = "guardians"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id", ondelete="CASCADE"), index=True)
    display_name_enc: Mapped[str] = mapped_column(Text)  # "Mẹ Lan"
    call_name_enc: Mapped[str] = mapped_column(Text)  # con gọi là "Mẹ"
    relation: Mapped[str] = mapped_column(String(10), default="khác")
    parent: Mapped[Parent] = relationship(back_populates="guardians")


class WebSession(Base):
    """Phiên đăng nhập lưu PHÍA SERVER: cookie chỉ chứa chuỗi ngẫu nhiên, DB lưu băm SHA-256 của nó."""
    __tablename__ = "sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id", ondelete="CASCADE"), index=True)
    guardian_id: Mapped[int | None] = mapped_column(ForeignKey("guardians.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    ip: Mapped[str] = mapped_column(String(64), default="")


class Child(Base):
    __tablename__ = "children"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id", ondelete="CASCADE"), index=True)
    nickname_enc: Mapped[str] = mapped_column(Text)
    self_pronoun: Mapped[str] = mapped_column(String(10), default="con")
    birth_year: Mapped[int] = mapped_column(Integer)
    avatar_key: Mapped[str] = mapped_column(String(32), default="tictac")
    created_at: Mapped[float] = mapped_column(Float)
    parent: Mapped[Parent] = relationship(back_populates="children")
    devices: Mapped[list["Device"]] = relationship(back_populates="child", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64))
    hostname_enc: Mapped[str] = mapped_column(Text, default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    last_state_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_version: Mapped[int] = mapped_column(Integer, default=0)
    clock_skew: Mapped[float] = mapped_column(Float, default=0.0)
    policy_alg: Mapped[str] = mapped_column(String(16), default="ed25519")
    hmac_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    child: Mapped[Child] = relationship(back_populates="devices")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    rotated_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)


class PairingCode(Base):
    __tablename__ = "pairing_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)  # chỉ lưu BĂM của mã
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    used_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_ip: Mapped[str] = mapped_column(String(64), default="")


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("child_id", "version", name="uq_policy_child_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)


class Category(Base):
    __tablename__ = "categories"
    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    category: Mapped[str] = mapped_column(String(20))


class Event(Base):
    """ĐÚNG 7 trường nghiệp vụ theo đề + 2 cột kỹ thuật (id tự tăng, idem_key chống trùng)."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_child_ts", "child_id", "ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    idem_key: Mapped[str] = mapped_column(String(36), unique=True)
    ts: Mapped[float] = mapped_column(Float)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(253))
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    policy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    device_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    used_sec: Mapped[int] = mapped_column(Integer, default=0)
    by_category_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[float] = mapped_column(Float)


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | sent | acked
    created_at: Mapped[float] = mapped_column(Float)
    sent_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    acked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class UnlockRequest(Base):
    __tablename__ = "unlock_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(36))
    minutes: Mapped[int] = mapped_column(Integer)
    reason_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | denied
    created_at: Mapped[float] = mapped_column(Float)
    decided_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    note_enc: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(64), default="")


class AuditLog(Base):
    """Nhật ký kiểm toán: ai — lúc nào — IP — giá trị cũ — giá trị mới. Trẻ xem được (NT5)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    actor_type: Mapped[str] = mapped_column(String(10))  # parent | device | system | child
    actor_id: Mapped[str] = mapped_column(String(64), default="")
    actor_label: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    child_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    entity: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    old_json: Mapped[str] = mapped_column(Text, default="null")
    new_json: Mapped[str] = mapped_column(Text, default="null")


class IntegrityAlert(Base):
    """Cảnh báo toàn vẹn (chỉnh đồng hồ, chính sách bị từ chối...). Bảng riêng để không
    phá lược đồ 7 trường của bảng events (quyết định ghi trong docs/DECISIONS.md)."""
    __tablename__ = "integrity_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    ts: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(32))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")


class KidLink(Base):
    __tablename__ = "kid_links"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
