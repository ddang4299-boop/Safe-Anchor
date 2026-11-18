"""
server/config.py — Cấu hình server, mọi bí mật lấy từ BIẾN MÔI TRƯỜNG (không hardcode).

Yêu cầu đề: F5 (khóa lấy từ biến môi trường hoặc DPAPI, không hardcode).

Biến môi trường:
  OGK_SECRET         base64 >= 32 byte: khóa HMAC cho access token + CSRF
  OGK_DATA_KEY       base64 đúng 32 byte: khóa AES-256-GCM mã hóa trường nhạy cảm
  OGK_SIGNING_KEY    base64 32 byte (seed Ed25519): khóa ký chính sách
  OGK_POLICY_ALG     ed25519 (mặc định) | hmac-sha256
  OGK_DB_URL         mặc định sqlite:///server/instance/ogk.db
  OGK_COOKIE_SECURE  1 (mặc định) | 0 khi chạy http trong LAN để thử nghiệm
Chế độ phát triển: nếu thiếu khóa, server tự sinh và lưu vào server/instance/*.key (chỉ để
chạy thử; khi triển khai thật phải đặt biến môi trường). Thư mục instance/ nằm trong .gitignore.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("ogk.config")

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"
DATA_DIR = ROOT / "data"


def _key_from_env_or_file(env: str, path: Path, nbytes: int) -> bytes:
    val = os.environ.get(env)
    if val:
        raw = base64.b64decode(val)
        if len(raw) < nbytes:
            raise ValueError(f"{env} phải dài ít nhất {nbytes} byte")
        return raw[:nbytes]
    if path.exists():
        return base64.b64decode(path.read_text().strip())[:nbytes]
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(nbytes)
    path.write_text(base64.b64encode(raw).decode())
    log.warning("Chưa đặt %s — đã sinh khóa phát triển tại %s (KHÔNG dùng cho triển khai thật)", env, path)
    return raw


class Settings:
    def __init__(self):
        self.instance_dir = Path(os.environ.get("OGK_INSTANCE_DIR", ROOT / "server" / "instance"))
        self.db_url = os.environ.get("OGK_DB_URL", f"sqlite:///{(self.instance_dir / 'ogk.db').as_posix()}")
        self.secret = _key_from_env_or_file("OGK_SECRET", self.instance_dir / "secret.key", 32)
        self.data_key = _key_from_env_or_file("OGK_DATA_KEY", self.instance_dir / "data.key", 32)
        self.signing_seed = _key_from_env_or_file("OGK_SIGNING_KEY", self.instance_dir / "signing_ed25519.key", 32)
        self.policy_alg = os.environ.get("OGK_POLICY_ALG", "ed25519")
        if self.policy_alg not in ("ed25519", "hmac-sha256"):
            raise ValueError("OGK_POLICY_ALG phải là ed25519 hoặc hmac-sha256")
        self.cookie_secure = os.environ.get("OGK_COOKIE_SECURE", "1") != "0"
        self.session_hours = 12
        self.access_ttl = 15 * 60  # access token 15 phút
        self.refresh_ttl = 30 * 86400  # refresh token 30 ngày
        self.pairing_ttl = 10 * 60  # mã ghép 10 phút
        self.retention_days = 90
        self.heartbeat_sec = 60
        self.offline_after_sec = 150  # quá 2.5 nhịp tim không thấy => "Ngoại tuyến"


@lru_cache
def get_settings() -> Settings:
    return Settings()
