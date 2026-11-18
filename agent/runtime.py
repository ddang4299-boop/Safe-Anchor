"""
agent/runtime.py — AgentRuntime: lắp ráp các module lõi + lớp vỏ thành agent chạy được.

Dùng chung cho Windows Service (service.py) và chế độ console để chạy thử (run_agent.py).

Các tác vụ asyncio chạy song song trong MỘT event loop:
    tick_loop      1 giây   AgentCore.tick() -> thực thi Action (sự kiện, khóa, thông báo)
    app_loop       2 giây   quét tiến trình, SHA-256, kết thúc ứng dụng bị chặn
    DnsProxy       sự kiện  UDP/TCP 127.0.0.1:53
    SyncLoop       60 giây  heartbeat + Cristian + chính sách + lô sự kiện
    ws_loop        luôn mở  lệnh khẩn
    persist_loop   10 giây  lưu bộ đếm xuống SQLite (chịu được mất điện / khởi động lại)
    guard_loop     30 giây  watchdog Tray, kiểm tra DNS card mạng
Named Pipe chạy ở thread riêng (API chặn của Windows), gọi vào core qua khóa threading.RLock.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from . import app_control, netguard, winsys
from .app_control import AppController, AppRules
from .clock import TrustedClock
from .config import ROOT, AgentConfig
from .core import DEFAULT_POLICY, Action, AgentCore
from .dns_proxy import DnsProxy, Upstream, flush_windows_dns_cache
from .domain_rules import DnsPolicyEngine, registrable_domain
from .ipc import IpcDispatcher, NamedPipeServer, ensure_token, start_tcp_server
from .local_cache import LocalCache
from .policy_verify import PolicyRejected, PolicyVerifier
from .sync import NotEnrolled, ServerClient, SyncLoop

log = logging.getLogger("ogk.runtime")

DOMAIN_EVENT_INTERVAL = 600  # mỗi tên miền chỉ ghi 1 sự kiện domain_query / 10 phút (tối thiểu hóa dữ liệu)
TOAST_INTERVAL = 30  # mỗi tên miền chỉ hiện toast "chưa mở" tối đa 1 lần / 30 giây
RELOCK_AFTER = 30  # đang LOCKED mà trẻ mở khóa màn hình: cho 30 giây đọc giải thích / xin thêm giờ rồi khóa lại


class AgentRuntime:
    def __init__(self, cfg: AgentConfig, service_mode: bool = False):
        self.cfg = cfg
        self.service_mode = service_mode
        self.data_dir = Path(cfg.data_dir)
        self.cache = LocalCache(self.data_dir / "agent.db")
        self.clock = TrustedClock()
        self.core = AgentCore(self.clock, dict(DEFAULT_POLICY))
        self.client = ServerClient(cfg, self.cache)
        self.sync = SyncLoop(self.client, self, interval=cfg.heartbeat_sec)
        self.apps = AppController(own_pids=frozenset({os.getpid(), os.getppid()}))
        self.engine = DnsPolicyEngine.from_policy(self.core.policy)
        self.dns: DnsProxy | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ws_connected = False
        self.tray_watchdog = winsys.TrayWatchdog()
        self._integrity: list[dict] = []
        self._domain_last: dict[str, float] = {}
        self._toast_last: dict[str, float] = {}
        self._requests: dict[int, str] = {}
        self._locked_seen_unlock: float | None = None
        self.verifier: PolicyVerifier | None = None

    # ================================================================== khởi tạo
    def _load_verifier(self) -> None:
        enr = self.cache.get("enrollment")
        if not enr:
            return
        hmac_key = None
        if enr["policy_alg"] == "hmac-sha256":
            import base64
            hmac_key = base64.b64decode(winsys.unprotect(self.cache.get("hmac_key")))
        self.verifier = PolicyVerifier(enr["device_id"], enr["policy_alg"], enr.get("policy_public_key"), hmac_key)

    def _load_cached_policy(self) -> None:
        env = self.cache.get("policy_envelope")
        if env and self.verifier:
            try:  # kiểm lại chữ ký cả bản trong cache: trẻ (nếu là admin) sửa tệp DB cũng bị phát hiện
                body = self.verifier.verify(env, current_version=-1)
                self._set_policy(body)
                log.info("Đã nạp chính sách cache phiên bản %s", body.get("version"))
            except PolicyRejected as exc:
                log.error("Chính sách trong cache KHÔNG hợp lệ (%s) — dùng mặc định an toàn", exc)
                self._integrity.append({"kind": "policy_cache_tampered", "detail": str(exc)})
        self.core.restore(self.cache.get("core_snapshot") or {})

    def _set_policy(self, body: dict) -> None:
        self.core.set_policy(body)
        self.apps.rules = AppRules.from_policy(body)
        self._rebuild_engine()

    def _rebuild_engine(self) -> None:
        self.engine = DnsPolicyEngine.from_policy(self.core.policy, exhausted=self.core.exhausted)
        if self.dns:
            self.dns.flush_cache()
        flush_windows_dns_cache()  # bản ghi cũ trong Dnscache của Windows có thể vẫn trỏ tới trang vừa chặn

    async def apply_policy_envelope(self, env: dict) -> None:
        if not self.verifier:
            self._load_verifier()
        try:
            body = self.verifier.verify(env, current_version=int(self.core.policy.get("version", 0)))
        except PolicyRejected as exc:
            if "không mới hơn" in str(exc):
                return
            log.error("Từ chối chính sách: %s", exc)
            self._integrity.append({"kind": "policy_rejected", "detail": str(exc)})
            return
        self.cache.set("policy_envelope", env)
        self._set_policy(body)
        self.core.push_notification("policy_updated", version=body.get("version"))
        log.info("Áp dụng chính sách phiên bản %s", body.get("version"))

    # ================================================================== thực thi Action từ core
    def apply_actions(self, actions: list[Action]) -> None:
        for a in actions:
            if a.kind == "event":
                self.queue_event(a.data["type"], a.data["subject"], a.data.get("duration_sec", 0))
            elif a.kind == "lock_session":
                self._lock_now()
            elif a.kind == "integrity":
                self._integrity.append({**a.data, "ts": time.time()})
            elif a.kind == "budgets_changed":
                self._rebuild_engine()
            elif a.kind == "sync_policy":
                self.sync.wake()
            elif a.kind == "purge":
                self.cache.purge_child_data()
                self.core.used_by_cat = {}
                log.info("Đã xóa bộ đệm dữ liệu của trẻ theo yêu cầu phụ huynh")

    def queue_event(self, etype: str, subject: str, duration: int = 0) -> None:
        enr = self.cache.get("enrollment") or {}
        self.cache.enqueue_event({"ts": self.clock.now(), "type": etype, "subject": subject[:253],
                                  "duration_sec": int(duration), "policy_id": self.core.policy.get("policy_id"),
                                  "device_id": enr.get("device_id"), "child_id": enr.get("child_id")})

    def take_integrity(self) -> list[dict]:
        items, self._integrity = self._integrity[:50], self._integrity[50:]
        return items

    def _lock_now(self) -> None:
        self._locked_seen_unlock = None
        if self.cfg.enforce and not self.tray_watchdog.suspended:
            winsys.lock_session(self.service_mode)
        else:
            log.info("[enforce=False] Sẽ khóa phiên (lý do: %s)", self.core.lock_reason)

    async def handle_command(self, cmd: dict) -> None:
        """Lệnh có thể đến từ WebSocket VÀ heartbeat: applied_commands đảm bảo áp dụng đúng MỘT lần."""
        cid = str(cmd.get("command_id", ""))
        if not cid or not self.cache.mark_command_applied(cid):
            return
        try:
            self.apply_actions(self.core.apply_command(cmd.get("cmd", ""), cmd.get("payload") or {}))
            log.info("Áp dụng lệnh %s (%s)", cmd.get("cmd"), cid)
        except ValueError as exc:
            log.warning("Bỏ qua lệnh lạ: %s", exc)

    def update_requests(self, reqs: list[dict]) -> None:
        """Trạng thái yêu cầu cho Tray: Đã gửi -> Ba/Mẹ đang xem -> Đồng ý/Để lần sau.
        (Lời nhắn khi duyệt/từ chối đến qua lệnh add_time / request_denied.)"""
        for r in reqs:
            self._requests[r["id"]] = r["status"]

    # ================================================================== DNS
    def on_dns_event(self, kind: str, q, decision) -> None:
        now = time.monotonic()
        reg = registrable_domain(q.name)
        if kind == "blocked":
            if now - self._toast_last.get(reg, -1e9) >= TOAST_INTERVAL:
                self._toast_last[reg] = now
                self.queue_event("blocked_domain", reg)
                if not decision.is_system:  # DoH/canary là hạ tầng, không làm phiền trẻ
                    self.core.push_notification("blocked_domain", domain=reg, reason=decision.reason,
                                                category=decision.category)
        elif kind == "query":
            if now - self._domain_last.get(reg, -1e9) >= DOMAIN_EVENT_INTERVAL:
                self._domain_last[reg] = now
                self.queue_event("domain_query", reg)

    # ================================================================== IPC (gọi từ thread pipe)
    def ipc_status(self, since: int) -> dict:
        self.tray_watchdog.contact(time.monotonic())
        st = self.core.status(since)
        st["online"] = self.client.online
        st["ws"] = self.ws_connected
        st["enrolled"] = bool(self.cache.get("enrollment"))
        st["queue"] = self.cache.queue_size()
        st["requests"] = [{"id": k, "status": v} for k, v in list(self._requests.items())[-3:]]
        return st

    def _run_on_loop(self, coro, timeout: float = 8.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def ipc_today(self) -> dict:
        try:
            data = self._run_on_loop(self.client.call("GET", "/api/today")).json()
            self.cache.set("today_report", data)
            return data
        except Exception:
            return self.cache.get("today_report") or {}  # ngoại tuyến: trả bản đã lưu

    def ipc_audit(self) -> dict:
        try:
            data = self._run_on_loop(self.client.call("GET", "/api/audit")).json()
            self.cache.set("audit_cache", data)
            return data
        except Exception:
            return self.cache.get("audit_cache") or {"items": []}

    def ipc_request_more_time(self, minutes: int, reason: str) -> dict:
        try:
            data = self._run_on_loop(self.client.call("POST", "/api/unlock-requests",
                                                      json={"minutes": minutes, "reason": reason})).json()
            self._requests[data["id"]] = "pending"  # sự kiện unlock_request do server tự ghi
            return {"sent": True, "request_id": data["id"]}
        except Exception as exc:
            return {"sent": False, "error": "offline", "detail": type(exc).__name__}

    # ================================================================== vòng lặp
    async def tick_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.apply_actions(self.core.tick())
            # Đang LOCKED mà phiên vẫn mở (trẻ vừa đăng nhập lại): cho 30 giây với màn hình giải thích
            # + nút "Xin thêm giờ", sau đó khóa lại.
            if self.core.phase == "locked" and not self.core.session_locked:
                now = time.monotonic()
                if self._locked_seen_unlock is None:
                    self._locked_seen_unlock = now
                elif now - self._locked_seen_unlock > RELOCK_AFTER:
                    self._lock_now()
            await asyncio.sleep(1.0)

    async def app_loop(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                procs = await loop.run_in_executor(None, app_control.list_processes)
                res = self.apps.scan(procs, self.core.exhausted)
                self.core.set_running_categories(res.running_categories)
                for p in res.started:
                    self.queue_event("app_start", p.name)
                for name, dur in res.stopped:
                    self.queue_event("app_stop", name, dur)
                for p, why, cat in res.to_kill:
                    killed = app_control.kill_process(p.pid, self.apps.own_pids) if self.cfg.enforce else False
                    key = f"app:{p.name.lower()}"
                    now = time.monotonic()
                    if now - self._toast_last.get(key, -1e9) >= TOAST_INTERVAL:
                        self._toast_last[key] = now
                        self.queue_event("blocked_app", p.name)
                        # Không chặn im lặng: Tray hiện cửa sổ giải thích của Khiên Xanh
                        self.core.push_notification("blocked_app", app=p.name, reason=why, category=cat, killed=killed)
            except Exception:
                log.exception("app_loop lỗi")
            await asyncio.sleep(self.cfg.app_scan_sec)

    async def persist_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.cache.set("core_snapshot", self.core.snapshot())
            await asyncio.sleep(10)

    async def guard_loop(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            if self.cfg.manage_network and sys.platform == "win32":
                fixed = await loop.run_in_executor(None, netguard.ensure_dns_loopback)
                for f in fixed:  # trẻ tự đổi DNS card mạng (vd 8.8.8.8) => đặt lại + báo phụ huynh
                    self._integrity.append({"kind": "dns_changed", "detail": f, "ts": time.time()})
            if self.service_mode:
                mono = time.monotonic()
                decision = self.tray_watchdog.decide(mono, winsys.active_console_session() is not None)
                if decision == "launch":
                    ok = winsys.launch_in_user_session(self.cfg.resolved_tray_command(), cwd=str(ROOT))
                    self.tray_watchdog.launch_result(ok, mono)
                elif decision == "suspend":
                    self._integrity.append({"kind": "tray_unavailable", "ts": time.time()})
                    log.error("Không hiển thị được Tray sau %d lần — TẠM DỪNG KIỂM SOÁT (không chế độ ẩn)",
                              winsys.TrayWatchdog.MAX_FAILS)
            await asyncio.sleep(30)

    async def run(self, stop: asyncio.Event) -> None:
        self.loop = asyncio.get_running_loop()
        self._load_verifier()
        self._load_cached_policy()
        tasks = [self.tick_loop(stop), self.app_loop(stop), self.persist_loop(stop), self.guard_loop(stop)]
        if self.cfg.dns_enabled:
            self.dns = DnsProxy(lambda: self.engine, Upstream([(u, 53) for u in self.cfg.upstreams]),
                                host=self.cfg.dns_host, port=self.cfg.dns_port, on_event=self.on_dns_event)
            try:
                await self.dns.start()
            except OSError as exc:
                log.error("Không mở được DNS proxy %s:%s (%s) — cổng đang bận hoặc thiếu quyền",
                          self.cfg.dns_host, self.cfg.dns_port, exc)
                self.dns = None
        dispatcher = IpcDispatcher(self)
        pipe = None
        if sys.platform == "win32":
            try:
                pipe = NamedPipeServer(dispatcher)
                pipe.start()
            except Exception as exc:
                log.warning("Named pipe lỗi (%r), chỉ dùng TCP dự phòng", exc)
        tcp = None
        if not self.service_mode:
            tcp = await start_tcp_server(dispatcher, self.cfg.ipc_tcp_port, ensure_token(self.data_dir))
        if self.cache.get("enrollment"):
            from .ws_client import ws_loop
            tasks += [self.sync.run(stop), ws_loop(self, stop)]
        else:
            log.warning("Chưa ghép đôi: chạy 'python -m agent.run_agent enroll --code XXXX-XXXX' trước")
        log.info("OGK Agent đang chạy (enforce=%s, service=%s)", self.cfg.enforce, self.service_mode)
        try:
            await asyncio.gather(*tasks)
        finally:
            self.cache.set("core_snapshot", self.core.snapshot())
            if self.dns:
                await self.dns.stop()
            if tcp:
                tcp.close()
            if pipe:
                pipe.stop()
            await self.client.close()
