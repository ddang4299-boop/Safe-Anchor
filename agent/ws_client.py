"""
agent/ws_client.py — Kênh lệnh khẩn qua WebSocket (khóa ngay / mở khóa / +15 phút, < 5 giây).

Yêu cầu đề: §4.3. Agent CHỦ ĐỘNG mở kết nối ra ngoài (đi xuyên NAT của mạng gia đình), xác thực
bằng tin nhắn đầu tiên, ping 20 giây (giữ NAT/proxy không cắt kết nối "rảnh"), ack theo command_id,
tự nối lại bằng exponential backoff có jitter 1 -> 30 giây.

Vì sao cần JITTER? Server khởi động lại => hàng nghìn agent mất kết nối CÙNG LÚC. Nếu tất cả thử lại
đúng 1s, 2s, 4s... chúng sẽ dồn thành từng "đợt sóng" (thundering herd) đè sập server. Nhân ngẫu
nhiên hệ số [0.5, 1.0] làm các lần thử rải đều ra.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random

log = logging.getLogger("ogk.ws")

BASE_DELAY = 1.0
MAX_DELAY = 30.0


def backoff_delay(attempt: int, rnd: random.Random = random) -> float:
    """Equal jitter: một nửa cố định + một nửa ngẫu nhiên => không bao giờ quá dồn, không bao giờ quá ngắn."""
    cap = min(MAX_DELAY, BASE_DELAY * (2 ** attempt))
    return cap / 2 + rnd.uniform(0, cap / 2)


async def ws_loop(runtime, stop: asyncio.Event) -> None:
    import websockets

    cfg = runtime.cfg
    attempt = 0
    ssl_ctx = runtime.client.ssl if cfg.ws_url.startswith("wss://") else None
    while not stop.is_set():
        try:
            token = await runtime.client.access_token()
            async with websockets.connect(cfg.ws_url, ssl=ssl_ctx, ping_interval=20, ping_timeout=20,
                                          open_timeout=10, close_timeout=5) as ws:
                await ws.send(json.dumps({"type": "auth", "access_token": token}))
                first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if first.get("type") != "auth_ok":
                    raise ConnectionError("WS auth thất bại")
                attempt = 0
                runtime.ws_connected = True
                log.info("WebSocket lệnh khẩn đã kết nối")
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "command":
                        await runtime.handle_command(msg)
                        await ws.send(json.dumps({"type": "ack", "command_id": msg["command_id"]}))
                    elif msg.get("type") == "policy_changed":
                        runtime.sync.wake()  # tải chính sách mới ngay, không đợi nhịp 60 giây
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("WS lỗi: %r", exc)
        runtime.ws_connected = False
        delay = backoff_delay(attempt)
        attempt = min(attempt + 1, 10)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
