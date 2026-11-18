"""
agent/policy_verify.py — Kiểm tra toàn vẹn chính sách: chữ ký + device_id + version tăng ngặt.

Yêu cầu đề: F4 (BẮT BUỘC: chính sách có đánh số phiên bản và ký hiệu toàn vẹn — HMAC hoặc
chữ ký — để agent từ chối chính sách bị sửa đổi).

Phong bì (envelope) chính sách do server gửi:
    {"alg": "ed25519" | "hmac-sha256", "body": {...}, "sig": "<base64>"}
Chữ ký tính trên CANONICAL JSON của body: sắp xếp khóa, không khoảng trắng, UTF-8.
Lý do: JSON {"a":1,"b":2} và {"b": 2, "a": 1} cùng nghĩa nhưng khác byte; nếu không chuẩn hóa
thì chỉ cần server và agent serialize khác nhau một dấu cách là chữ ký sai.

Hai thuật toán được hỗ trợ (chọn lúc ghép đôi, agent KHÔNG cho phép hạ cấp thuật toán):
  * ed25519 (mặc định, khuyến nghị): server giữ khóa bí mật, agent chỉ có KHÓA CÔNG KHAI.
    Trẻ có toàn quyền đọc ổ đĩa cũng không giả mạo được chính sách (nguyên tắc P6).
  * hmac-sha256: khóa đối xứng riêng cho từng thiết bị (cấp lúc ghép đôi, bọc DPAPI + ACL).
    Nhanh, đơn giản, nhưng ai đọc được khóa trên máy trẻ là ký được chính sách giả.
Ba kiểm tra bắt buộc:
  1) chữ ký đúng            -> chống SỬA NỘI DUNG
  2) body.device_id == mình -> chống lấy chính sách của máy khác (lỏng hơn) đem áp
  3) body.version > hiện tại -> chống PHÁT LẠI (replay) chính sách cũ
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


class PolicyRejected(Exception):
    pass


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hmac_sign(key: bytes, body: dict) -> str:
    return base64.b64encode(hmac.new(key, canonical_json(body), hashlib.sha256).digest()).decode()


class PolicyVerifier:
    def __init__(self, device_id: str, alg: str, public_key_b64: str | None = None, hmac_key: bytes | None = None):
        if alg not in ("ed25519", "hmac-sha256"):
            raise ValueError("thuật toán không hỗ trợ")
        self.device_id = device_id
        self.alg = alg
        self._pub = None
        if alg == "ed25519":
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            self._pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        self._hmac_key = hmac_key

    def verify(self, envelope: dict, current_version: int) -> dict:
        if not isinstance(envelope, dict) or "body" not in envelope or "sig" not in envelope:
            raise PolicyRejected("phong bì không hợp lệ")
        if envelope.get("alg") != self.alg:
            # Chống tấn công hạ cấp: kẻ giả mạo đổi alg sang thuật toán yếu hơn.
            raise PolicyRejected("sai thuật toán ký")
        body = envelope["body"]
        msg = canonical_json(body)
        try:
            sig = base64.b64decode(envelope["sig"], validate=True)
        except Exception as exc:
            raise PolicyRejected("chữ ký không phải base64") from exc
        if self.alg == "ed25519":
            from cryptography.exceptions import InvalidSignature
            try:
                self._pub.verify(sig, msg)
            except InvalidSignature as exc:
                raise PolicyRejected("chữ ký Ed25519 sai — chính sách bị sửa") from exc
        else:
            expected = hmac.new(self._hmac_key, msg, hashlib.sha256).digest()
            # compare_digest: so sánh thời gian hằng, chống tấn công đo thời gian (timing attack)
            if not hmac.compare_digest(expected, sig):
                raise PolicyRejected("HMAC sai — chính sách bị sửa")
        if body.get("device_id") != self.device_id:
            raise PolicyRejected("chính sách dành cho thiết bị khác")
        version = int(body.get("version", -1))
        if version <= current_version:
            raise PolicyRejected(f"phiên bản {version} không mới hơn {current_version} (phát lại?)")
        return body
