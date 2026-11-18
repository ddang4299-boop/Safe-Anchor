"""
agent/service.py — OGK-Agent dưới dạng Windows Service chạy bằng LocalSystem.

Yêu cầu đề: §4.2 (chạy dưới LocalSystem; pywin32 win32serviceutil; khởi động lại bằng Service
Recovery Options của SCM), F1 (không tính giờ khi máy khóa — WTS session lock/unlock).

Cài đặt (PowerShell quyền Administrator, xem agent/INSTALL.md):
    python agent\\service.py --startup auto install
    sc.exe failure OGKAgent reset= 86400 actions= restart/5000/restart/5000/restart/5000
    python agent\\service.py start

SCM (Service Control Manager) gửi thông báo đổi phiên (SERVICE_CONTROL_SESSIONCHANGE) khi ta khai báo
SERVICE_ACCEPT_SESSIONCHANGE: WTS_SESSION_LOCK (7) / WTS_SESSION_UNLOCK (8) => ngừng/tiếp tục đếm giờ.
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # chạy trực tiếp bằng pythonservice.exe

import servicemanager  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from agent.config import AgentConfig, default_data_dir  # noqa: E402
from agent import winsys  # noqa: E402

WTS_SESSION_LOGON, WTS_SESSION_LOGOFF, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 5, 6, 7, 8


class OGKAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "OGKAgent"
    _svc_display_name_ = "OpenGuard Kids Agent"
    _svc_description_ = ("Hỗ trợ cha mẹ quản lý thời gian dùng máy của trẻ (minh bạch, có biểu tượng khay). "
                         "Công cụ đồng hành, không phải phần mềm theo dõi lén.")

    def __init__(self, args):
        super().__init__(args)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_evt: asyncio.Event | None = None
        self.runtime = None

    def GetAcceptedControls(self):
        return super().GetAcceptedControls() | win32service.SERVICE_ACCEPT_SESSIONCHANGE

    def SvcOtherEx(self, control, event_type, data):
        if control == win32service.SERVICE_CONTROL_SESSIONCHANGE and self.runtime:
            if event_type in (WTS_SESSION_LOCK, WTS_SESSION_LOGOFF):
                self.runtime.core.set_session_locked(True)
            elif event_type in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON):
                self.runtime.core.set_session_locked(False)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.loop and self.stop_evt:
            self.loop.call_soon_threadsafe(self.stop_evt.set)

    def SvcDoRun(self):
        from agent.runtime import AgentRuntime
        data_dir = default_data_dir(service_mode=True)
        winsys.harden_data_dir(data_dir)  # ACL: chỉ SYSTEM + Administrators
        logfile = data_dir / "agent.log"
        handler = logging.handlers.RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        cfg = AgentConfig.load(data_dir)
        self.runtime = AgentRuntime(cfg, service_mode=True)
        servicemanager.LogInfoMsg("OGK Agent khởi động")

        async def main():
            self.loop = asyncio.get_running_loop()
            self.stop_evt = asyncio.Event()
            await self.runtime.run(self.stop_evt)

        asyncio.run(main())
        servicemanager.LogInfoMsg("OGK Agent đã dừng")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(OGKAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(OGKAgentService)
