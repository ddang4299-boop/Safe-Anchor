"""
agent/ipc.py — Giao tiếp liên tiến trình Service (SYSTEM, phiên 0) <-> Tray (quyền trẻ, phiên 1+).

Yêu cầu đề: §4.2 (Tray giao tiếp với service qua named pipe hoặc HTTP 127.0.0.1 có token cục bộ),
nguyên tắc P6 (máy trẻ không tin cậy: Tray KHÔNG được ra lệnh nguy hiểm).

Kênh chính: Named Pipe \\\\.\\pipe\\ogk-agent
  * Là đối tượng nhân (kernel object) có DESCRIPTOR BẢO MẬT => Windows tự kiểm quyền khi mở pipe.
    DACL (SDDL): D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)
        SY = SYSTEM toàn quyền, BA = Administrators toàn quyền, IU = người dùng đăng nhập tương tác
        (trẻ) chỉ ĐỌC/GHI dữ liệu — không đổi được quyền của pipe. Máy khác trên mạng (NU) không vào được.
  * Không mở cổng mạng => không bị quét cổng, không đụng firewall.
Kênh dự phòng (dev / máy không có pywin32): TCP 127.0.0.1 + token bí mật trong tệp chỉ người dùng
hiện tại đọc được; so sánh token bằng hmac.compare_digest.

Giao thức: mỗi yêu cầu là một JSON {"op": ..., "args": {...}}; phản hồi {"ok": bool, ...}.
DANH SÁCH TRẮNG: chỉ các thao tác vô hại bên dưới. Không có "tắt lọc", "đổi chính sách",
"dừng dịch vụ", "cộng giờ" — kể cả khi trẻ tự viết chương trình gửi thẳng vào pipe.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import sys
import threading
from pathlib import Path

log = logging.getLogger("ogk.ipc")

PIPE_NAME = r"\\.\pipe\ogk-agent"
PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)"
MAX_MSG = 64 * 1024

ALLOWED_OPS = {"ping", "get_status", "get_today", "get_audit", "request_more_time", "report_idle", "ack_break"}


class IpcDispatcher:
    """Kiểm tra & điều phối yêu cầu. Logic thuần => test được không cần Windows."""

    def __init__(self, runtime):
        self.rt = runtime

    def handle(self, req) -> dict:
        if not isinstance(req, dict):
            return {"ok": False, "error": "bad_request"}
        op = req.get("op")
        args = req.get("args") or {}
        if op not in ALLOWED_OPS or not isinstance(args, dict):
            log.warning("IPC từ chối thao tác ngoài danh sách trắng: %r", op)
            return {"ok": False, "error": "not_allowed"}
        try:
            if op == "ping":
                return {"ok": True}
            if op == "get_status":
                return {"ok": True, "status": self.rt.ipc_status(int(args.get("since", 0)))}
            if op == "get_today":
                return {"ok": True, "today": self.rt.ipc_today()}
            if op == "get_audit":
                return {"ok": True, "audit": self.rt.ipc_audit()}
            if op == "report_idle":
                sec = float(args.get("seconds", 0))
                if not 0 <= sec <= 7 * 86400:
                    return {"ok": False, "error": "bad_args"}
                self.rt.core.report_idle(sec)
                return {"ok": True}
            if op == "ack_break":
                return {"ok": True, "accepted": self.rt.core.ack_break()}
            if op == "request_more_time":
                minutes = int(args.get("minutes", 0))
                reason = str(args.get("reason", ""))
                if minutes not in (15, 30, 60) or len(reason) > 200:
                    return {"ok": False, "error": "bad_args"}
                return {"ok": True, **self.rt.ipc_request_more_time(minutes, reason)}
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_args"}
        return {"ok": False, "error": "not_allowed"}

    def handle_raw(self, data: bytes) -> bytes:
        try:
            req = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return b'{"ok": false, "error": "bad_json"}'
        return json.dumps(self.handle(req), ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------ Named Pipe (Windows)
class NamedPipeServer(threading.Thread):
    """Mỗi client một instance pipe; luồng riêng vì ConnectNamedPipe là lời gọi chặn."""

    def __init__(self, dispatcher: IpcDispatcher, on_contact=None):
        super().__init__(daemon=True, name="ogk-pipe")
        self.dispatcher = dispatcher
        self.on_contact = on_contact
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        try:  # mở một kết nối giả để gỡ ConnectNamedPipe đang chặn
            import win32file
            h = win32file.CreateFile(PIPE_NAME, 0xC0000000, 0, None, 3, 0, None)
            win32file.CloseHandle(h)
        except Exception:
            pass

    def run(self) -> None:
        import pywintypes
        import win32pipe
        import win32security

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            PIPE_SDDL, win32security.SDDL_REVISION_1)
        while not self._stop.is_set():
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME, win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT
                | win32pipe.PIPE_REJECT_REMOTE_CLIENTS,  # chặn client từ máy khác qua SMB
                win32pipe.PIPE_UNLIMITED_INSTANCES, MAX_MSG, MAX_MSG, 0, sa)
            try:
                win32pipe.ConnectNamedPipe(pipe, None)
            except pywintypes.error:
                pass
            if self._stop.is_set():
                pipe.Close()
                break
            threading.Thread(target=self._serve, args=(pipe,), daemon=True).start()

    def _serve(self, pipe) -> None:
        import pywintypes
        import win32file
        import win32pipe
        try:
            while True:
                hr, data = win32file.ReadFile(pipe, MAX_MSG)
                if self.on_contact:
                    self.on_contact()
                win32file.WriteFile(pipe, self.dispatcher.handle_raw(data))
        except pywintypes.error:
            pass  # client đóng pipe
        finally:
            try:
                win32pipe.DisconnectNamedPipe(pipe)
            except pywintypes.error:
                pass
            pipe.Close()


# ------------------------------------------------------------------ TCP 127.0.0.1 + token (dự phòng)
def token_path(data_dir: Path) -> Path:
    return Path(data_dir) / "ipc_token"


def ensure_token(data_dir: Path) -> str:
    p = token_path(data_dir)
    if p.exists():
        return p.read_text().strip()
    tok = secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok)
    return tok


async def start_tcp_server(dispatcher: IpcDispatcher, port: int, token: str, on_contact=None):
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if len(line) > MAX_MSG:
                return
            req = json.loads(line or b"{}")
            # Token so sánh thời gian hằng: tiến trình lạ trên máy không đoán dần được token.
            if not hmac.compare_digest(str(req.get("token", "")), token):
                writer.write(b'{"ok": false, "error": "bad_token"}\n')
            else:
                if on_contact:
                    on_contact()
                loop = asyncio.get_running_loop()
                # handle() có thể chờ việc chạy trên event loop (vd gửi yêu cầu lên server) => chạy ở thread
                resp = await loop.run_in_executor(None, dispatcher.handle, req)
                writer.write(json.dumps(resp, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    # CHỈ lắng nghe trên loopback: máy khác trong LAN không kết nối được.
    return await asyncio.start_server(serve, "127.0.0.1", port)


# ------------------------------------------------------------------ client (dùng bởi Tray)
class IpcClient:
    def __init__(self, data_dir: Path | None = None, port: int = 47653):
        self.data_dir = data_dir
        self.port = port

    def call(self, op: str, **args) -> dict:
        req = {"op": op, "args": args}
        if sys.platform == "win32":
            try:
                return self._call_pipe(req)
            except Exception:
                pass
        return self._call_tcp(req)

    def _call_pipe(self, req: dict) -> dict:
        import win32file
        import win32pipe
        h = win32file.CreateFile(PIPE_NAME, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                                 win32file.OPEN_EXISTING, 0, None)
        try:
            win32pipe.SetNamedPipeHandleState(h, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            win32file.WriteFile(h, json.dumps(req, ensure_ascii=False).encode())
            _, data = win32file.ReadFile(h, MAX_MSG)
            return json.loads(data.decode())
        finally:
            win32file.CloseHandle(h)

    def _call_tcp(self, req: dict) -> dict:
        import socket
        tok = token_path(self.data_dir).read_text().strip() if self.data_dir and token_path(self.data_dir).exists() else ""
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(json.dumps({**req, "token": tok}, ensure_ascii=False).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf or b"{}")
