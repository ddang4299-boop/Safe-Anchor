"""
server/security.py — Các khối mật mã và bảo mật dùng chung.

Yêu cầu đề: F5 (scrypt, so sánh thời gian hằng, khóa 15 phút sau 5 lần sai, rate limit theo IP,
CSRF, AES-GCM cho trường nhạy cảm, token 15 phút + refresh, băm bí mật thiết bị), §4.3 (mã ghép).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ------------------------------------------------------------------ mật khẩu (scrypt)
# scrypt là hàm băm "tốn bộ nhớ" (memory-hard): N=2^15, r=8 => mỗi lần băm cần ~32 MiB RAM.
# Kẻ tấn công dùng GPU/ASIC để dò mật khẩu sẽ bị giới hạn bởi băng thông bộ nhớ, không chỉ tốc độ tính.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSWORD_LEN = 10


def hash_password(password: str) -> str:
    salt = os.urandom(16)  # muối ngẫu nhiên: hai người cùng mật khẩu vẫn ra băm khác nhau
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                        maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p),
                            maxmem=64 * 1024 * 1024, dklen=32)
        # So sánh THỜI GIAN HẰNG: không dừng sớm ở byte sai đầu tiên => không lộ thông tin qua thời gian.
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


# Băm giả để đăng nhập email không tồn tại cũng tốn thời gian như thật (chống dò email).
DUMMY_HASH = None


def dummy_verify(password: str) -> None:
    global DUMMY_HASH
    if DUMMY_HASH is None:
        DUMMY_HASH = hash_password("dummy-password-xx")
    verify_password(password, DUMMY_HASH)


# ------------------------------------------------------------------ băm & token ngẫu nhiên
def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ------------------------------------------------------------------ AES-256-GCM cho trường nhạy cảm
class FieldCipher:
    """Mã hóa trường (tên gọi của trẻ, hostname, lời nhắn...). AAD = "bảng.cột".

    AES-GCM là mã hóa XÁC THỰC: ngoài bí mật còn có thẻ 16 byte chống sửa. AAD (dữ liệu
    liên kết) không bị mã hóa nhưng được xác thực: bản mã của children.nickname đem dán sang
    cột devices.hostname sẽ giải mã THẤT BẠI => chống tấn công tráo đổi bản mã giữa các cột.
    Nonce 12 byte ngẫu nhiên mỗi lần mã hóa — KHÔNG BAO GIỜ dùng lại nonce với cùng khóa.
    """

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("cần khóa 32 byte cho AES-256")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str, aad: str) -> str:
        if plaintext is None:
            plaintext = ""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), aad.encode())
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, token: str, aad: str) -> str:
        if not token:
            return ""
        raw = base64.b64decode(token)
        return self._aes.decrypt(raw[:12], raw[12:], aad.encode()).decode("utf-8")


# ------------------------------------------------------------------ access token thiết bị
class TokenError(Exception):
    pass


def make_access_token(secret: bytes, device_id: str, ttl: int, now: float | None = None) -> str:
    """Token ngắn hạn KHÔNG TRẠNG THÁI: payload.chữ_ký_HMAC. Server không cần tra DB để kiểm chữ ký,
    nhưng vẫn kiểm cờ revoked của thiết bị (thu hồi tức thì khi phụ huynh gỡ thiết bị)."""
    now = time.time() if now is None else now
    payload = _b64u(json.dumps({"sub": device_id, "exp": int(now + ttl), "typ": "access"}, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(secret, b"access." + payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def parse_access_token(secret: bytes, token: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    try:
        payload, sig = token.split(".")
    except ValueError as exc:
        raise TokenError("định dạng token sai") from exc
    expected = _b64u(hmac.new(secret, b"access." + payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise TokenError("chữ ký token sai")
    data = json.loads(_b64u_dec(payload))
    if data.get("typ") != "access" or data.get("exp", 0) < now:
        raise TokenError("token hết hạn")
    return data["sub"]


# ------------------------------------------------------------------ CSRF
def csrf_token(secret: bytes, session_hash: str) -> str:
    """CSRF token = HMAC(secret, id phiên). Không cần lưu DB; trang của kẻ tấn công không đọc
    được token (Same-Origin Policy) nên không giả được header X-CSRF-Token."""
    return _b64u(hmac.new(secret, b"csrf." + session_hash.encode(), hashlib.sha256).digest())


def verify_csrf(secret: bytes, session_hash: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(csrf_token(secret, session_hash), token)


# ------------------------------------------------------------------ mã ghép đôi
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 ký tự, bỏ 0 O 1 I dễ nhầm
assert len(PAIRING_ALPHABET) == 32


def new_pairing_code() -> str:
    """8 ký tự × 5 bit = 40 bit entropy (~1,1 nghìn tỷ tổ hợp). Hạn 10 phút + 5 lần thử/phút/IP
    => xác suất đoán trúng trong 10 phút ≈ 50 / 2^40 ≈ 4.5e-11."""
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))


def normalize_pairing_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch in PAIRING_ALPHABET)


def format_pairing_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


# ------------------------------------------------------------------ rate limit (cửa sổ trượt)
class RateLimiter:
    """Giới hạn N yêu cầu / cửa sổ W giây cho mỗi khóa (thường là IP). Lưu trong RAM:
    đủ cho 1 tiến trình server; chạy nhiều worker thì cần Redis (ghi trong DECISIONS.md)."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
