"""
server/ws_hub.py — Quản lý kết nối WebSocket của agent cho LỆNH KHẨN (< 5 giây).

Yêu cầu đề: §4.3 (lệnh khẩn qua WebSocket: khóa ngay, mở khóa, +15 phút, độ trễ < 5 giây).

Vì sao WebSocket mà không chỉ heartbeat 60 giây? Heartbeat là mô hình KÉO (pull): agent hỏi
mỗi 60 giây => trễ tối đa 60 giây. WebSocket là kết nối TCP dài hạn do AGENT MỞ RA (đi ra từ
mạng nhà, xuyên NAT/firewall dễ dàng), server ĐẨY (push) lệnh xuống ngay => trễ ≈ 1 RTT.
Heartbeat vẫn chở lệnh chờ làm dự phòng; agent khử trùng bằng command_id.

Giới hạn: hub lưu trong RAM của MỘT tiến trình. Chạy nhiều worker Uvicorn thì cần kênh
pub/sub chung (Redis) — ghi trong docs/DECISIONS.md.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("ogk.ws")


class Hub:
    def __init__(self):
        self._conns: dict = {}
        self._lock = asyncio.Lock()

    async def register(self, device_id: str, ws) -> None:
        async with self._lock:
            old = self._conns.get(device_id)
            self._conns[device_id] = ws
        if old is not None and old is not ws:
            try:  # một thiết bị chỉ giữ một kết nối: đóng kết nối cũ (vd agent khởi động lại)
                await old.close(code=4000)
            except Exception:
                pass

    async def unregister(self, device_id: str, ws) -> None:
        async with self._lock:
            if self._conns.get(device_id) is ws:
                del self._conns[device_id]

    def is_online(self, device_id: str) -> bool:
        return device_id in self._conns

    async def send(self, device_id: str, message: dict) -> bool:
        ws = self._conns.get(device_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception as exc:
            log.info("gửi WS tới %s lỗi: %r", device_id, exc)
            await self.unregister(device_id, ws)
            return False
