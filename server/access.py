"""
server/access.py — Kiểm tra quyền sở hữu NGAY TRONG CÂU TRUY VẤN (chống IDOR).

Yêu cầu đề: F5 (bắt buộc kiểm tra quyền sở hữu ở tầng truy vấn, không chỉ ẩn nút).

IDOR (Insecure Direct Object Reference): phụ huynh B sửa URL /children/1 (con của A) và đọc
được dữ liệu. Cách SAI: lấy Child theo id rồi mới "if child.parent_id != me" (dễ quên ở một
route). Cách ĐÚNG ở đây: điều kiện parent_id nằm TRONG mệnh đề WHERE — không sở hữu thì truy
vấn không trả về gì => 404 (không phải 403, để không tiết lộ "id này có tồn tại").
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Child, Device, UnlockRequest


def owned_child(db: Session, parent_id: int, child_id: int) -> Child:
    child = db.scalar(select(Child).where(Child.id == child_id, Child.parent_id == parent_id))
    if child is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    return child


def owned_device(db: Session, parent_id: int, device_id: str) -> Device:
    dev = db.scalar(select(Device).join(Child, Device.child_id == Child.id)
                    .where(Device.id == device_id, Child.parent_id == parent_id))
    if dev is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    return dev


def owned_request(db: Session, parent_id: int, request_id: int) -> UnlockRequest:
    req = db.scalar(select(UnlockRequest).join(Child, UnlockRequest.child_id == Child.id)
                    .where(UnlockRequest.id == request_id, Child.parent_id == parent_id))
    if req is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    return req


def children_of(db: Session, parent_id: int) -> list[Child]:
    return list(db.scalars(select(Child).where(Child.parent_id == parent_id).order_by(Child.id)))
