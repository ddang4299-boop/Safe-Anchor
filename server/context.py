"""server/context.py — Đối tượng dùng chung toàn ứng dụng (khóa, bộ ký, hub WebSocket, rate limiter)."""
from __future__ import annotations

from fastapi import Request

from .config import Settings
from .security import FieldCipher, RateLimiter
from .signing import PolicySigner
from .ws_hub import Hub


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cipher = FieldCipher(settings.data_key)
        self.signer = PolicySigner(settings.signing_seed)
        self.hub = Hub()
        self.login_limiter = RateLimiter(10, 60)  # 10 lần đăng nhập / phút / IP
        self.enroll_limiter = RateLimiter(5, 60)  # 5 lần thử mã ghép / phút / IP (theo đề)
        self.refresh_limiter = RateLimiter(30, 60)
        self.request_limiter = RateLimiter(6, 600)  # trẻ gửi tối đa 6 yêu cầu thêm giờ / 10 phút / máy


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""
