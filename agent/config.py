"""
agent/config.py — Cấu hình agent, lưu tại <data_dir>/config.json.

data_dir: %ProgramData%\\OGK khi chạy dịch vụ (ACL chỉ SYSTEM + Administrators),
          .ogk_agent/ trong thư mục dự án khi chạy thử ở chế độ console.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_data_dir(service_mode: bool = False) -> Path:
    if service_mode and sys.platform == "win32":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OGK"
    return ROOT / ".ogk_agent"


@dataclass
class AgentConfig:
    server_url: str = "http://127.0.0.1:8000"
    dns_enabled: bool = True
    dns_host: str = "127.0.0.1"
    dns_port: int = 53
    # Upstream: lấy từ DNS gốc của card mạng lúc cài đặt. Khuyến nghị resolver "gia đình" (vd 1.1.1.3)
    # để kể cả khi trẻ hỏi thẳng upstream thì nội dung người lớn vẫn bị lọc ở tầng thứ hai.
    upstreams: list = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])
    ca_file: str | None = None  # CA phòng lab: chỉ tin CA này (ghim CA)
    pin_sha256: str | None = None  # SHA-256 chứng chỉ server (ghim lá)
    enforce: bool = False  # True: thật sự kết thúc tiến trình + khóa phiên (dịch vụ thật bật True)
    manage_network: bool = False  # True: ép DNS card mạng = 127.0.0.1, luật firewall, policy trình duyệt
    ipc_tcp_port: int = 47653  # kênh IPC dự phòng 127.0.0.1 (có token)
    app_scan_sec: float = 2.0
    heartbeat_sec: int = 60
    # Lệnh mở Tray trong phiên trẻ (dịch vụ chạy dưới pythonservice.exe nên không dùng sys.executable được)
    tray_command: str = ""
    data_dir: str = ""

    def resolved_tray_command(self) -> str:
        if self.tray_command:
            return self.tray_command
        pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        return f'"{pyw}" -m agent.tray.app'

    @classmethod
    def load(cls, data_dir: Path) -> "AgentConfig":
        p = Path(data_dir) / "config.json"
        cfg = cls(data_dir=str(data_dir))
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            cfg.data_dir = str(data_dir)
        return cfg

    def save(self) -> None:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "config.json").write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def ws_url(self) -> str:
        return self.server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/api/ws"
