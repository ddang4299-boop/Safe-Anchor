"""
agent/local_cache.py — Kho dữ liệu cục bộ của agent (SQLite, chế độ WAL).

Yêu cầu đề: §4.2 (bản sao chính sách gần nhất + hàng đợi sự kiện, trong ProgramData với ACL
chỉ SYSTEM/Administrators ghi được), §4.3 (ngoại tuyến: đệm sự kiện, đồng bộ theo lô với
idempotency key), F3 (nút xóa dữ liệu xóa cả bộ đệm agent).

Bảng:
  kv(key, value)                 chính sách đã ký, token (đã bọc DPAPI), snapshot bộ đếm...
  event_queue(idem_key, body)    sự kiện CHƯA được server xác nhận
  applied_commands(command_id)   lệnh khẩn đã áp dụng => cùng một lệnh đến từ cả WebSocket và
                                 heartbeat cũng chỉ áp dụng MỘT lần (INSERT OR IGNORE)

Vì sao WAL (Write-Ahead Logging)? Ghi chỉ nối thêm vào tệp -wal, người đọc không bị khóa bởi
người ghi => thread IPC đọc trạng thái trong khi vòng sync đang ghi hàng đợi vẫn trơn tru;
và khi mất điện giữa chừng, giao dịch hoặc vào đủ hoặc không vào (atomic).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_queue (
    idem_key TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS applied_commands (command_id TEXT PRIMARY KEY, applied_at REAL NOT NULL);
"""

MAX_QUEUE = 50_000  # chặn trên để mất mạng nhiều tuần cũng không làm đầy ổ đĩa


class LocalCache:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)

    # ---- kv ----
    def get(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (key, json.dumps(value, ensure_ascii=False)))

    def delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE key=?", (key,))

    # ---- hàng đợi sự kiện ----
    def enqueue_event(self, event: dict) -> str:
        """Gắn idempotency key (UUID4) NGAY KHI tạo sự kiện. Gửi lại bao nhiêu lần thì server
        vẫn chỉ lưu một bản nhờ UNIQUE(idem_key) + INSERT ... ON CONFLICT DO NOTHING."""
        key = event.get("idem_key") or str(uuid.uuid4())
        event = {**event, "idem_key": key}
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO event_queue(idem_key, body, created_at) VALUES(?,?,?)",
                             (key, json.dumps(event, ensure_ascii=False), time.time()))
            n = self._db.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0]
            if n > MAX_QUEUE:  # bỏ bớt sự kiện CŨ NHẤT loại domain_query (ít giá trị nhất)
                self._db.execute("DELETE FROM event_queue WHERE idem_key IN (SELECT idem_key FROM event_queue "
                                 "WHERE body LIKE '%\"domain_query\"%' ORDER BY created_at LIMIT ?)", (n - MAX_QUEUE,))
        return key

    def peek_events(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM event_queue ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def ack_events(self, keys: list[str]) -> int:
        """Chỉ xóa khỏi hàng đợi SAU KHI server xác nhận (at-least-once delivery)."""
        if not keys:
            return 0
        with self._lock:
            cur = self._db.executemany("DELETE FROM event_queue WHERE idem_key=?", [(k,) for k in keys])
            return cur.rowcount

    def queue_size(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0]

    # ---- lệnh đã áp dụng ----
    def mark_command_applied(self, command_id: str) -> bool:
        """True nếu đây là LẦN ĐẦU thấy command_id (=> được phép áp dụng)."""
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO applied_commands(command_id, applied_at) VALUES(?, ?)",
                                   (command_id, time.time()))
            self._db.execute("DELETE FROM applied_commands WHERE applied_at < ?", (time.time() - 30 * 86400,))
            return cur.rowcount == 1

    # ---- xóa dữ liệu theo yêu cầu phụ huynh ----
    def purge_child_data(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM event_queue")
            for k in ("core_snapshot", "today_report", "audit_cache"):
                self._db.execute("DELETE FROM kv WHERE key=?", (k,))

    def close(self) -> None:
        with self._lock:
            self._db.close()
