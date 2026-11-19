"""
agent/sync.py — Kênh agent ↔ server qua HTTPS: ghép đôi, heartbeat 60 giây, đẩy sự kiện theo lô,
làm mới token, ghim chứng chỉ.

Yêu cầu đề: §4.3 (heartbeat 60s; lệch version thì GET /policy; ngoại tuyến: đệm sự kiện, đồng bộ
theo lô có idempotency key), F5 (TLS 1.2+, agent ghim chứng chỉ và từ chối khi không khớp;
access 15 phút + refresh), M6 (đối chiếu giờ server mỗi nhịp tim — Cristian).

Ghim chứng chỉ hai lớp:
  1) Ghim CA: SSLContext chỉ nạp CA của phòng lab (không dùng kho CA hệ thống) => kẻ MITM có
     chứng chỉ hợp lệ do CA công cộng cấp cũng bị từ chối NGAY TRONG BẮT TAY TLS, trước khi
     có byte dữ liệu nào (kể cả token) được gửi.
  2) Ghim lá: so SHA-256 của chứng chỉ server (DER) với giá trị cấu hình; lệch => ngắt.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import ssl
import time

import httpx

from .config import AgentConfig
from .local_cache import LocalCache
from . import winsys

log = logging.getLogger("ogk.sync")


class PinMismatch(Exception):
    pass


class NotEnrolled(Exception):
    pass


def make_ssl_context(cfg: AgentConfig):
    if not cfg.server_url.startswith("https://"):
        return True  # HTTP trong máy để chạy thử; triển khai thật bắt buộc HTTPS
    ctx = ssl.create_default_context(cafile=cfg.ca_file) if cfg.ca_file else ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2  # đề: TLS 1.2+
    return ctx


class ServerClient:
    def __init__(self, cfg: AgentConfig, cache: LocalCache):
        self.cfg = cfg
        self.cache = cache
        self.ssl = make_ssl_context(cfg)
        self.http = httpx.AsyncClient(base_url=cfg.server_url.rstrip("/"), verify=self.ssl, timeout=10.0)
        self._refresh_lock = asyncio.Lock()
        self.online = False

    # ---- bí mật (bọc DPAPI trong local cache) ----
    def _secret(self, key: str) -> str | None:
        v = self.cache.get(key)
        return winsys.unprotect(v).decode() if v else None

    def _store_secret(self, key: str, value: str) -> None:
        self.cache.set(key, winsys.protect(value.encode()))

    @property
    def enrollment(self) -> dict | None:
        return self.cache.get("enrollment")

    def _check_pin(self, resp: httpx.Response) -> None:
        if not (self.cfg.pin_sha256 and self.cfg.server_url.startswith("https://")):
            return
        stream = resp.extensions.get("network_stream")
        sslobj = stream.get_extra_info("ssl_object") if stream else None
        der = sslobj.getpeercert(binary_form=True) if sslobj else None
        if not der or hashlib.sha256(der).hexdigest().lower() != self.cfg.pin_sha256.lower().replace(":", ""):
            raise PinMismatch("chứng chỉ server không khớp giá trị đã ghim — từ chối kết nối")

    # ---- ghép đôi ----
    async def enroll(self, code: str) -> dict:
        r = await self.http.post("/api/enroll", json={"code": code, "fingerprint": winsys.machine_fingerprint(),
                                                      "hostname": winsys.hostname()})
        self._check_pin(r)
        r.raise_for_status()
        data = r.json()
        self.cache.set("enrollment", {"device_id": data["device_id"], "child_id": data["child_id"],
                                      "policy_alg": data["policy_alg"], "policy_public_key": data["policy_public_key"]})
        if data.get("hmac_key"):
            self._store_secret("hmac_key", data["hmac_key"])
        self._store_tokens(data)
        return data

    def _store_tokens(self, data: dict) -> None:
        self._store_secret("access_token", data["access_token"])
        self._store_secret("refresh_token", data["refresh_token"])
        self.cache.set("access_exp", time.time() + int(data.get("access_expires_in", 900)) - 30)

    async def access_token(self) -> str:
        if not self.enrollment:
            raise NotEnrolled()
        if time.time() >= (self.cache.get("access_exp") or 0):
            await self.refresh()
        return self._secret("access_token")

    async def refresh(self) -> None:
        # Khóa: chỉ MỘT lần làm mới tại một thời điểm. Hai lần làm mới song song cùng một refresh token
        # sẽ bị server coi là "dùng lại token" và thu hồi cả họ token.
        async with self._refresh_lock:
            if time.time() < (self.cache.get("access_exp") or 0):
                return
            rt = self._secret("refresh_token")
            r = await self.http.post("/api/token/refresh", json={"refresh_token": rt})
            self._check_pin(r)
            if r.status_code == 401:
                raise NotEnrolled("refresh token bị từ chối — cần ghép đôi lại")
            r.raise_for_status()
            self._store_tokens(r.json())

    async def call(self, method: str, path: str, **kw) -> httpx.Response:
        tok = await self.access_token()
        r = await self.http.request(method, path, headers={"Authorization": f"Bearer {tok}"}, **kw)
        self._check_pin(r)
        if r.status_code == 401:  # access hết hạn sớm (vd đồng hồ lệch) => làm mới rồi thử lại MỘT lần
            self.cache.set("access_exp", 0)
            tok = await self.access_token()
            r = await self.http.request(method, path, headers={"Authorization": f"Bearer {tok}"}, **kw)
            self._check_pin(r)
        r.raise_for_status()
        self.online = True
        return r

    async def close(self) -> None:
        await self.http.aclose()


class SyncLoop:
    """Heartbeat định kỳ + đẩy sự kiện. `wake()` để đồng bộ ngay (vd khi WS báo policy_changed)."""

    def __init__(self, client: ServerClient, runtime, interval: int = 60):
        self.client = client
        self.rt = runtime
        self.interval = interval
        self._wake = asyncio.Event()
        self.last_ok: float | None = None

    def wake(self) -> None:
        self._wake.set()

    async def heartbeat_once(self) -> dict:
        core, clock = self.rt.core, self.rt.clock
        st = core.status()
        body = {"policy_version": core.policy.get("version", 0), "client_time": time.time(),
                "state": {**{k: st[k] for k in ("phase", "lock_reason", "remaining_sec", "used_sec", "quota_min", "day", "stale",
                                                "lock_until")},
                          "by_category": {c: round(v) for c, v in core.used_by_cat.items()},
                          # chỉ gửi NHÓM đang chạy (học tập/trò chơi...) để dashboard hiện "Đang học tập", không gửi tên ứng dụng
                          "running": sorted(core.running_categories)},
                "integrity": self.rt.take_integrity()}
        t0 = clock._mono()
        r = await self.client.call("POST", "/api/heartbeat", json=body)
        t1 = clock._mono()
        data = r.json()
        skew = clock.sync_cristian(float(data["server_time"]), t0, t1)  # Cristian: + RTT/2
        if abs(skew) > 120:
            log.info("Giờ máy lệch giờ server %.0f giây (đếm giờ vẫn đúng nhờ đồng hồ tin cậy)", skew)
        core.server_contact()
        if int(data.get("policy_version", 0)) != int(core.policy.get("version", 0)):
            await self.fetch_policy()
        for cmd in data.get("commands", []):  # kênh dự phòng cho lệnh khẩn
            await self.rt.handle_command(cmd)
        self.rt.update_requests(data.get("requests", []))
        self.last_ok = time.time()
        return data

    async def fetch_policy(self) -> None:
        r = await self.client.call("GET", "/api/policy")
        await self.rt.apply_policy_envelope(r.json())

    async def flush_events(self) -> int:
        sent = 0
        while True:
            batch = self.rt.cache.peek_events(200)
            if not batch:
                break
            r = await self.client.call("POST", "/api/events", json={"events": batch})
            acked = r.json().get("acked", [])
            self.rt.cache.ack_events(acked)  # chỉ xóa những gì server xác nhận
            sent += len(acked)
            if len(batch) < 200 or not acked:
                break
        return sent

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.heartbeat_once()
                await self.flush_events()
            except NotEnrolled:
                log.warning("Thiết bị chưa ghép đôi / bị gỡ — chỉ áp chính sách đã lưu")
            except PinMismatch as exc:
                log.error("%s", exc)
                self.client.online = False
            except Exception as exc:
                self.client.online = False
                log.info("Mất kết nối server (%s) — tiếp tục áp chính sách cache, đệm sự kiện", type(exc).__name__)
            # Ngủ tới nhịp kế tiếp (±10% jitter để nhiều máy không dồn cùng giây) hoặc tới khi bị đánh thức.
            delay = self.interval * random.uniform(0.9, 1.1)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
