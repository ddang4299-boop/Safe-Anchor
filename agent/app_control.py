"""
agent/app_control.py — Kiểm soát ứng dụng theo tên tiến trình + mã băm SHA-256 của tệp .exe.

Yêu cầu đề: F2 (BẮT BUỘC: đối chiếu tên + SHA-256; đổi tên notepad.exe -> game.exe vẫn
nhận diện đúng; khi chặn: kết thúc tiến trình VÀ hiện cửa sổ giải thích), F3 (app_start/app_stop).

Vì sao cần SHA-256? Tên tiến trình chỉ là tên tệp — trẻ đổi tên game.exe thành winword.exe
là qua mặt được bộ lọc theo tên. Mã băm phụ thuộc NỘI DUNG tệp nên đổi tên không đổi băm.
(Giới hạn: game cập nhật phiên bản => băm đổi; vì vậy luật chặn theo tên vẫn giữ song song.)

Băm theo khúc 1 MiB để không nạp cả tệp 2 GB vào RAM; cache theo (đường dẫn, kích thước,
mtime_ns): tệp không đổi thì không băm lại => mỗi vòng quét 2 giây chỉ tốn vài phép tra dict.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

log = logging.getLogger("ogk.apps")

CHUNK = 1024 * 1024

# Tiến trình hệ thống KHÔNG BAO GIỜ bị kết thúc (tránh làm sập Windows).
# CHÚ Ý BẢO MẬT: chỉ bảo vệ khi TÊN khớp VÀ tệp nằm trong %SystemRoot%. Nếu chỉ xét tên,
# trẻ đổi tên game.exe thành svchost.exe là thoát khỏi mọi kiểm soát.
PSEUDO_PROCESSES = {"system", "system idle process", "registry", "memcompression", "secure system"}
SYSTEM_BINARIES = {
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "conhost.exe", "lsaiso.exe", "logonui.exe",
}
SYSTEM_ROOT = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))


def is_protected(p: "ProcInfo", own_pids: frozenset = frozenset()) -> bool:
    if p.pid in own_pids:  # chính agent / Tray của ta (dev mode chạy bằng python.exe)
        return True
    name = (p.name or "").lower()
    if name in PSEUDO_PROCESSES:
        return True
    if name in SYSTEM_BINARIES:
        if not p.exe:  # SYSTEM cũng không đọc được exe của vài tiến trình lõi (csrss...)
            return True
        return os.path.normcase(p.exe).startswith(SYSTEM_ROOT + os.sep)
    return False


# Tiến trình nền không đáng ghi sự kiện app_start/app_stop (giảm nhiễu, tối thiểu hóa dữ liệu).
NOISE = PSEUDO_PROCESSES | SYSTEM_BINARIES | {"python.exe", "pythonw.exe", "ogk-agent.exe", "ogk-kids.exe",
    "dllhost.exe", "backgroundtaskhost.exe", "audiodg.exe", "spoolsv.exe", "wmiprvse.exe",
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe", "msmpeng.exe",
    "nissrv.exe", "securityhealthservice.exe", "smartscreen.exe", "textinputhost.exe",
    "applicationframehost.exe", "systemsettingsbroker.exe", "useroobebroker.exe",
    "lockapp.exe", "widgets.exe", "widgetservice.exe", "phoneexperiencehost.exe",
    "crashpad_handler.exe", "werfault.exe", "consent.exe", "cmd.exe", "powershell.exe",
}


@dataclass
class ProcInfo:
    pid: int
    name: str
    exe: str | None = None


class FileHasher:
    def __init__(self):
        self._cache: dict[tuple[str, int, int], str] = {}

    def sha256(self, path: str) -> str | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = (os.path.normcase(path), st.st_size, st.st_mtime_ns)
        h = self._cache.get(key)
        if h:
            return h
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK):
                    digest.update(chunk)
        except OSError:
            return None
        h = digest.hexdigest()
        if len(self._cache) > 4096:
            self._cache.clear()
        self._cache[key] = h
        return h


@dataclass
class AppRules:
    block_names: set = field(default_factory=set)
    block_sha256: set = field(default_factory=set)
    allow_names: set = field(default_factory=set)
    allow_sha256: set = field(default_factory=set)
    categories: dict = field(default_factory=dict)  # tên exe hoặc sha256 -> nhóm (games, education...)

    @classmethod
    def from_policy(cls, policy: dict) -> "AppRules":
        r = policy.get("app_rules", {}) or {}
        low = lambda xs: {x.lower() for x in xs or []}
        return cls(low(r.get("block_names")), low(r.get("block_sha256")), low(r.get("allow_names")),
                   low(r.get("allow_sha256")), {k.lower(): v for k, v in (r.get("categories") or {}).items()})

    def classify(self, name: str, sha: str | None) -> tuple[str, str | None, str]:
        """Trả (hành_động, nhóm, lý_do). Mã băm là danh tính mạnh hơn tên nên được xét trước:
        block_sha > allow_sha > block_name > allow_name."""
        name = name.lower()
        sha = (sha or "").lower()
        cat = self.categories.get(sha) or self.categories.get(name)
        if sha and sha in self.block_sha256:
            return "block", cat, "sha256"
        if sha and sha in self.allow_sha256:
            return "allow", cat, "sha256"
        if name in self.block_names:
            return "block", cat, "name"
        if name in self.allow_names:
            return "allow", cat, "name"
        return "none", cat, ""


@dataclass
class ScanResult:
    to_kill: list = field(default_factory=list)  # [(ProcInfo, lý_do, nhóm)]
    started: list = field(default_factory=list)  # [ProcInfo]
    stopped: list = field(default_factory=list)  # [(tên, thời_lượng_giây)]
    running_categories: set = field(default_factory=set)


class AppController:
    def __init__(self, rules: AppRules | None = None, hasher: FileHasher | None = None,
                 mono: Callable[[], float] = time.monotonic, own_pids: frozenset = frozenset()):
        self.rules = rules or AppRules()
        self.hasher = hasher or FileHasher()
        self._mono = mono
        self.own_pids = own_pids
        self._seen: dict[int, tuple[str, float]] = {}  # pid -> (tên, mono lúc thấy lần đầu)

    def scan(self, procs: Iterable[ProcInfo], exhausted_categories: frozenset = frozenset()) -> ScanResult:
        res = ScanResult()
        now = self._mono()
        alive: set[int] = set()
        for p in procs:
            name = (p.name or "").lower()
            if not name or is_protected(p, self.own_pids):
                continue
            alive.add(p.pid)
            sha = self.hasher.sha256(p.exe) if p.exe else None
            action, cat, why = self.rules.classify(name, sha)
            if action == "block":
                res.to_kill.append((p, why, cat))
                continue
            if cat and cat in exhausted_categories and action != "allow":
                res.to_kill.append((p, "budget", cat))
                continue
            if cat:
                res.running_categories.add(cat)
            if p.pid not in self._seen and name not in NOISE:
                self._seen[p.pid] = (name, now)
                res.started.append(p)
        for pid in list(self._seen):
            if pid not in alive:
                name, t0 = self._seen.pop(pid)
                res.stopped.append((name, int(now - t0)))
        return res


def list_processes() -> list[ProcInfo]:
    """Liệt kê tiến trình bằng psutil (chạy dưới SYSTEM thì đọc được exe của mọi phiên)."""
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            out.append(ProcInfo(p.info["pid"], p.info["name"] or "", p.info.get("exe")))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def kill_process(pid: int, own_pids: frozenset = frozenset()) -> bool:
    import psutil
    try:
        p = psutil.Process(pid)
        try:
            exe = p.exe()
        except (psutil.AccessDenied, psutil.ZombieProcess):
            exe = None
        if is_protected(ProcInfo(pid, p.name(), exe), own_pids):
            return False
        p.kill()  # Windows: TerminateProcess
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
