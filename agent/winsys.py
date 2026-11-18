"""
agent/winsys.py — Lớp vỏ Windows: DPAPI, ACL ProgramData, khóa phiên, vân tay máy, chạy Tray trong phiên trẻ.

Yêu cầu đề: F5 (agent bọc bí mật bằng DPAPI; thư mục cấu hình ACL chỉ SYSTEM + Administrators;
"nếu không thể hiển thị biểu tượng, agent phải tự dừng"), §4.3 (device fingerprint).

Mọi import pywin32/ctypes.windll nằm TRONG HÀM => module import được trên Linux/macOS để test.

Về CÔ LẬP ĐẶC QUYỀN (Session 0 isolation, từ Windows Vista):
  * Dịch vụ chạy dưới LocalSystem trong PHIÊN 0 — phiên không có màn hình tương tác.
  * Trẻ đăng nhập ở phiên 1, 2... với token người dùng thường (không thuộc Administrators).
  => Dịch vụ KHÔNG vẽ được cửa sổ cho trẻ, không gọi được LockWorkStation() thay trẻ, không đọc
     được GetLastInputInfo() của phiên trẻ. Vì vậy cần Tray (chạy trong phiên trẻ) + IPC.
  => Ngược lại trẻ không dừng được dịch vụ, không đọc/sửa được %ProgramData%\\OGK (ACL), không
     kill được tiến trình SYSTEM qua Task Manager ("Access is denied").
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("ogk.winsys")
IS_WIN = sys.platform == "win32"

SID_SYSTEM = "S-1-5-18"
SID_ADMINS = "S-1-5-32-544"


# ------------------------------------------------------------------ DPAPI
def protect(data: bytes) -> str:
    """Bọc bí mật (refresh token, khóa HMAC) bằng DPAPI phạm vi TÀI KHOẢN đang chạy.
    Dịch vụ chạy dưới SYSTEM => chỉ tiến trình SYSTEM giải mã được. Không phải ta tự giữ khóa:
    khóa chính do Windows quản lý (dẫn xuất từ bí mật của tài khoản/máy)."""
    import base64
    if not IS_WIN:
        return "plain:" + base64.b64encode(data).decode()  # chế độ dev trên Linux/macOS
    import win32crypt
    blob = win32crypt.CryptProtectData(data, "OGK", None, None, None, 0)
    return "dpapi:" + base64.b64encode(blob).decode()


def unprotect(token: str) -> bytes:
    import base64
    kind, _, b64 = token.partition(":")
    raw = base64.b64decode(b64)
    if kind == "plain":
        return raw
    import win32crypt
    return win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1]


# ------------------------------------------------------------------ ACL
def harden_data_dir(path: Path) -> bool:
    """%ProgramData%\\OGK: bỏ kế thừa quyền, chỉ SYSTEM và Administrators toàn quyền.
    Dùng SID thay vì tên nhóm vì tên nhóm bị bản địa hóa (Windows tiếng Việt: "Quản trị viên")."""
    if not IS_WIN:
        return False
    path.mkdir(parents=True, exist_ok=True)
    cmd = ["icacls", str(path), "/inheritance:r", "/grant:r",
           f"*{SID_SYSTEM}:(OI)(CI)F", f"*{SID_ADMINS}:(OI)(CI)F"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("icacls lỗi: %s", r.stderr.strip())
    return r.returncode == 0


# ------------------------------------------------------------------ vân tay máy
def machine_fingerprint() -> str:
    """SHA-256(MachineGuid + serial ổ C:). Gửi BĂM chứ không gửi giá trị gốc (tối thiểu hóa dữ liệu)."""
    guid, serial = "unknown", "0"
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                guid = winreg.QueryValueEx(k, "MachineGuid")[0]
        except OSError:
            pass
        try:
            import win32api
            serial = str(win32api.GetVolumeInformation("C:\\")[1])
        except Exception:
            pass
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(p):
                guid = Path(p).read_text().strip()
    return hashlib.sha256(f"{guid}|{serial}".encode()).hexdigest()


def hostname() -> str:
    import socket
    return socket.gethostname()[:64]


# ------------------------------------------------------------------ phiên & khóa
def active_console_session() -> int | None:
    if not IS_WIN:
        return None
    import ctypes
    sid = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    return None if sid == 0xFFFFFFFF else sid


def lock_session(service_mode: bool) -> bool:
    """Khóa phiên của trẻ.
    - Chế độ dịch vụ (phiên 0): WTSDisconnectSession ngắt phiên console => về màn hình đăng nhập/khóa.
      (LockWorkStation chỉ có tác dụng với phiên của chính tiến trình gọi.)
    - Chế độ console (dev): LockWorkStation()."""
    if not IS_WIN:
        log.info("[giả lập] khóa phiên")
        return False
    import ctypes
    if not service_mode:
        return bool(ctypes.windll.user32.LockWorkStation())
    try:
        import win32ts
        sid = active_console_session()
        if sid is None:
            return False
        win32ts.WTSDisconnectSession(win32ts.WTS_CURRENT_SERVER_HANDLE, sid, False)
        return True
    except Exception as exc:
        log.warning("WTSDisconnectSession lỗi: %r", exc)
        return False


def launch_in_user_session(cmdline: str, cwd: str | None = None) -> bool:
    """Từ dịch vụ SYSTEM, chạy Tray trong phiên của trẻ: WTSQueryUserToken (lấy token người dùng
    của phiên console — chỉ SYSTEM được phép gọi) + CreateProcessAsUser trên desktop winsta0\\default.
    Tray vì thế chạy với quyền CỦA TRẺ, không phải SYSTEM (nguyên tắc đặc quyền tối thiểu)."""
    if not IS_WIN:
        return False
    try:
        import win32con
        import win32process
        import win32profile
        import win32ts
        sid = active_console_session()
        if sid is None:
            return False
        token = win32ts.WTSQueryUserToken(sid)
        env = win32profile.CreateEnvironmentBlock(token, False)
        si = win32process.STARTUPINFO()
        si.lpDesktop = "winsta0\\default"
        win32process.CreateProcessAsUser(token, None, cmdline, None, None, False,
                                         win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_NEW_CONSOLE,
                                         env, cwd, si)
        return True
    except Exception as exc:
        log.warning("CreateProcessAsUser lỗi: %r", exc)
        return False


def idle_seconds() -> float:
    """Số giây kể từ lần chạm phím/chuột cuối (GetLastInputInfo) — CHỈ đúng khi gọi từ phiên trẻ (Tray)."""
    if not IS_WIN:
        return 0.0
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    # GetTickCount quay vòng sau 49.7 ngày: phép trừ modulo 2^32 vẫn đúng
    return ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


class TrayWatchdog:
    """Chính sách "không hiện được biểu tượng thì tự dừng" mà KHÔNG thành lỗ hổng "kill Tray là thoát":
      - Tray im lặng > SILENT_SEC khi có phiên người dùng => dịch vụ tự chạy lại Tray (trẻ kill thì Tray sống lại).
      - Chỉ khi chạy lại THẤT BẠI liên tiếp MAX_FAILS lần (máy không có giao diện, lỗi hệ thống...) mới
        tạm dừng kiểm soát + ghi cảnh báo gửi phụ huynh => không bao giờ "kiểm soát vô hình"."""
    SILENT_SEC = 20.0
    MAX_FAILS = 3

    def __init__(self):
        self.last_contact: float | None = None
        self.fails = 0
        self.suspended = False

    def contact(self, mono: float) -> None:
        self.last_contact = mono
        self.fails = 0
        self.suspended = False

    def decide(self, mono: float, session_active: bool) -> str:
        """Trả: 'ok' | 'launch' | 'suspend'."""
        if not session_active:
            return "ok"
        if self.last_contact is not None and mono - self.last_contact < self.SILENT_SEC:
            return "ok"
        if self.fails >= self.MAX_FAILS:
            self.suspended = True
            return "suspend"
        return "launch"

    def launch_result(self, ok: bool, mono: float) -> None:
        if ok:
            self.last_contact = mono  # cho Tray thời gian khởi động
        else:
            self.fails += 1
