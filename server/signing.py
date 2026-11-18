"""
server/signing.py — Ký chính sách: Ed25519 (mặc định) hoặc HMAC-SHA256 theo từng thiết bị.

Yêu cầu đề: F4 (chính sách có số phiên bản + ký hiệu toàn vẹn HMAC hoặc chữ ký).
Agent kiểm bằng agent/policy_verify.py (cùng hàm canonical_json).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical_json(obj) -> bytes:
    """PHẢI giống hệt agent/policy_verify.canonical_json (có test đối chiếu)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class PolicySigner:
    def __init__(self, ed25519_seed: bytes):
        self._sk = Ed25519PrivateKey.from_private_bytes(ed25519_seed)
        self.public_key_b64 = base64.b64encode(
            self._sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()

    def sign(self, body: dict, alg: str = "ed25519", hmac_key: bytes | None = None) -> dict:
        msg = canonical_json(body)
        if alg == "ed25519":
            sig = self._sk.sign(msg)
        elif alg == "hmac-sha256":
            if not hmac_key:
                raise ValueError("thiếu khóa HMAC của thiết bị")
            sig = hmac.new(hmac_key, msg, hashlib.sha256).digest()
        else:
            raise ValueError("thuật toán không hỗ trợ")
        return {"alg": alg, "body": body, "sig": base64.b64encode(sig).decode()}
