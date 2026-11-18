"""
agent/tray/app.py — OGK Kids: ứng dụng khay hệ thống cho trẻ (PySide6). Chạy với QUYỀN CỦA TRẺ.

Yêu cầu đề: §4.2 Tray UI (thời gian còn lại, lý do bị chặn, gửi yêu cầu), F1 (cảnh báo 10/5/1,
ân hạn 60 giây), F2 (khi chặn: hiện cửa sổ giải thích), F3 ("Hôm nay em đã dùng gì"), NT5 (xem nhật
ký "Ai đã đổi gì"), F5 (không chế độ ẩn: biểu tượng khay LUÔN hiện).

Tray chỉ HIỂN THỊ và CHUYỂN LỜI: mọi quyết định (đếm giờ, khóa, chặn) nằm ở dịch vụ SYSTEM.
Trẻ tắt Tray => dịch vụ vẫn kiểm soát và tự mở lại Tray (TrayWatchdog).

    python -m agent.tray.app                 # nối với agent đang chạy (Named Pipe / TCP 127.0.0.1)
    python -m agent.tray.app --demo          # chạy thử giao diện với dữ liệu giả, không cần agent
    python -m agent.tray.app --screenshots docs/screenshots   # xuất ảnh từng màn hình (offscreen)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QScrollArea, QStackedWidget, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from . import messages_vi as M
from . import view_logic as V

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ROOT = HERE.parent.parent
FONT_DIR = ROOT / "dashboard" / "static" / "fonts"

CAT_VI = {"education": "Học tập", "entertainment": "Giải trí", "social": "Mạng xã hội", "games": "Trò chơi",
          "inappropriate": "Chưa phù hợp", "uncategorized": "Khác"}
CAT_COLOR = {"education": "#10B981", "entertainment": "#FBBF24", "games": "#FF6B6B", "social": "#A78BFA",
             "uncategorized": "#94A3B8"}

QSS = """
* { font-family: "Nunito", "Segoe UI", sans-serif; color: #1F2937; }
#Card, #Main, #Block, #Toast, #Dialog { background: #FFFFFF; border-radius: 24px; }
#Main { background: #F3F0FF; }
#Block { background: #F3F0FF; }
QLabel#Title { font-size: 22px; font-weight: 800; }
QLabel#Big { font-size: 40px; font-weight: 900; }
QLabel#Muted { color: #6B7280; }
QLabel#Speech { background: #FFFFFF; border-radius: 20px; padding: 14px 18px; font-size: 16px; }
QPushButton { border-radius: 22px; min-height: 44px; padding: 0 22px; font-size: 15px; font-weight: 800;
              background: #2563EB; color: #FFFFFF; border: none; }
QPushButton:hover { background: #1D4ED8; }
QPushButton#Ghost { background: #FFFFFF; color: #2563EB; border: 2px solid #DBEAFE; }
QPushButton#Mint { background: #10B981; color: #062E22; }
QPushButton#Nav { background: transparent; color: #6B7280; text-align: left; border-radius: 14px; }
QPushButton#Nav:checked { background: #FFFFFF; color: #2563EB; }
QPushButton#Choice { background: #FFFFFF; color: #1F2937; border: 2px solid #E5E7EB; min-width: 90px; }
QPushButton#Choice:checked { background: #DBEAFE; border-color: #2563EB; }
QLineEdit { border: 2px solid #E5E7EB; border-radius: 14px; padding: 10px 14px; font-size: 15px; background: #FFFFFF; }
QScrollArea { border: none; background: transparent; }
"""


# ======================================================================== cầu nối IPC
class Bridge:
    def __init__(self, data_dir: Path | None, port: int, demo: bool = False):
        from agent.ipc import IpcClient
        self.client = IpcClient(data_dir, port)
        self.demo = demo
        self.since = 0
        self._demo_t0 = time.monotonic()

    def status(self) -> dict | None:
        if self.demo:
            return demo_status(self._demo_t0)
        try:
            r = self.client.call("get_status", since=self.since)
        except Exception:
            return None
        st = r.get("status") if r.get("ok") else None
        if st and st.get("notifications"):
            self.since = max(n["seq"] for n in st["notifications"])
        return st

    def call(self, op: str, **kw) -> dict:
        if self.demo:
            return demo_call(op, **kw)
        try:
            return self.client.call(op, **kw)
        except Exception:
            return {"ok": False, "error": "agent_unreachable"}


# ======================================================================== widget nhỏ
def mascot(kind: str, mood: str, size: int) -> QSvgWidget:
    w = QSvgWidget(str(ASSETS / f"{kind}_{mood}.svg"))
    w.setFixedSize(size, size)
    return w


class TimeBar(QWidget):
    """Thanh thời gian dạng viên thuốc: màu theo phút còn lại + vẫn có chữ (không chỉ dùng màu)."""

    def __init__(self, height=14):
        super().__init__()
        self.ratio, self.color = 1.0, V.MINT
        self.setFixedHeight(height)

    def set(self, remaining: int, quota_min: int):
        total = max(1, quota_min * 60)
        self.ratio = max(0.0, min(1.0, remaining / total))
        self.color = V.time_color(remaining)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E5E7EB"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        w = int(r.width() * self.ratio)
        if w > 0:
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(0, 0, max(w, r.height()), r.height(), r.height() / 2, r.height() / 2)


class DayTimeline(QWidget):
    """Dải thời gian cả ngày: khúc xanh = được dùng, xám = giờ nghỉ, mũi tên = bây giờ (biết trước, không bất ngờ)."""

    def __init__(self):
        super().__init__()
        self.segments, self.now_slot = [], 0
        self.setMinimumHeight(54)

    def set(self, segments, now_slot):
        self.segments, self.now_slot = segments or [], now_slot
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cell = w / 48
        for a, b, ok in self.segments:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(V.MINT if ok else "#D1D5DB"))
            p.drawRoundedRect(QRectF(a * cell + 1, 18, (b - a) * cell - 2, 16), 6, 6)
        x = (self.now_slot + 0.5) * cell
        p.setBrush(QColor("#2563EB"))
        path = QPainterPath()
        path.moveTo(x - 7, 2)
        path.lineTo(x + 7, 2)
        path.lineTo(x, 14)
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(QColor("#6B7280"))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        for h in (0, 6, 12, 18, 24):
            p.drawText(QRectF(min(h * 2 * cell, w - 30), 36, 30, 16), Qt.AlignLeft, f"{h}h")


class Ring(QWidget):
    """Vòng đếm ngược ân hạn: mềm, KHÔNG nhấp nháy (an toàn cho trẻ nhạy cảm ánh sáng)."""

    def __init__(self, size=150):
        super().__init__()
        self.left, self.total = 60, 60
        self.setFixedSize(size, size)

    def set(self, left, total=60):
        self.left, self.total = left, total
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(10, 10, self.width() - 20, self.height() - 20)
        p.setPen(QPen(QColor("#E5E7EB"), 12))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(V.SUN), 12, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * self.left / max(1, self.total)))
        p.setPen(QColor("#1F2937"))
        f = QFont("Nunito", 26, QFont.Black)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, f"{self.left}s")


class CategoryBars(QWidget):
    def __init__(self):
        super().__init__()
        self.items = []
        self.setMinimumHeight(40)

    def set(self, cats: dict):
        self.items = list(cats.items())[:6]
        self.setMinimumHeight(34 * max(1, len(self.items)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(v for _, v in self.items) or 1
        for i, (c, v) in enumerate(self.items):
            y = i * 34
            p.setPen(QColor("#1F2937"))
            p.drawText(QRectF(0, y, 110, 26), Qt.AlignVCenter, CAT_VI.get(c, c))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E5E7EB"))
            bw = self.width() - 190
            p.drawRoundedRect(QRectF(115, y + 8, bw, 12), 6, 6)
            p.setBrush(QColor(CAT_COLOR.get(c, "#2563EB")))
            p.drawRoundedRect(QRectF(115, y + 8, max(12, bw * v / total), 12), 6, 6)
            p.setPen(QColor("#6B7280"))
            p.drawText(QRectF(self.width() - 70, y, 70, 26), Qt.AlignVCenter | Qt.AlignRight, f"{v} phút")


# ======================================================================== viên HUD nổi
class Pill(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(270, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 16, 8)
        self.icon = mascot("tictac", "happy", 46)
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        self.label = QLabel("Đang kết nối…")
        self.label.setStyleSheet("font-weight:800;font-size:14px")
        self.bar = TimeBar(10)
        col.addWidget(self.label)
        col.addWidget(self.bar)
        lay.addLayout(col, 1)
        self._drag: QPoint | None = None
        self._moved = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 31, 31)

    def update_status(self, st: dict):
        mode = st.get("profile", {}).get("age_mode", "choi")
        rem = st.get("remaining_sec", 0)
        if st.get("phase") == "locked":
            text = "☾ Máy đang tạm nghỉ"
        else:
            text = f"{V.time_icon(rem)} {V.format_remaining(rem, mode)}"
        self.label.setText(text)
        self.bar.set(rem, st.get("quota_min", 60))

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            self._moved = True

    def mouseReleaseEvent(self, e):
        if not self._moved:
            self.clicked.emit()
        self._drag = None


# ======================================================================== hộp thoại xin thêm giờ
class RequestDialog(QDialog):
    def __init__(self, bridge: Bridge, profile: dict, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setObjectName("Dialog")
        self.setWindowTitle("Xin thêm giờ")
        self.bridge, self.profile = bridge, profile
        call = profile.get("guardian_call", "Ba Mẹ")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        top.addWidget(mascot("sao", "encourage", 72))
        t = QLabel(f"{profile.get('nickname', 'Bạn nhỏ')} muốn xin {call} thêm bao lâu?")
        t.setObjectName("Title")
        t.setWordWrap(True)
        top.addWidget(t, 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        self.group = QButtonGroup(self)
        for m in (15, 30, 60):
            b = QPushButton(f"{m} phút")
            b.setObjectName("Choice")
            b.setCheckable(True)
            self.group.addButton(b, m)
            row.addWidget(b)
        self.group.button(15).setChecked(True)
        lay.addLayout(row)
        self.reason = QLineEdit()
        self.reason.setMaxLength(200)
        self.reason.setPlaceholderText(f"Vì sao {profile.get('self_pronoun', 'con')} cần thêm giờ? (không bắt buộc)")
        lay.addWidget(self.reason)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        cancel = QPushButton("Thôi")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        self.send = QPushButton(f"🙋 Gửi {call}")
        self.send.clicked.connect(self._send)
        btns.addWidget(cancel)
        btns.addWidget(self.send)
        lay.addLayout(btns)

    def _send(self):
        r = self.bridge.call("request_more_time", minutes=self.group.checkedId(), reason=self.reason.text().strip())
        sent = r.get("ok") and r.get("sent")
        self.msg.setText(M.render("request_sent" if sent else "request_offline", self.profile))
        self.send.setEnabled(not sent)
        if sent:
            QTimer.singleShot(2500, self.accept)


# ======================================================================== màn hình chặn nhẹ nhàng
class BlockWindow(QWidget):
    def __init__(self, bridge: Bridge, open_request):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("Block")
        self.setAttribute(Qt.WA_StyledBackground)
        self.bridge, self.open_request = bridge, open_request
        self.resize(720, 460)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(36, 36, 36, 36)
        left = QVBoxLayout()
        self.icon = mascot("tictac", "sleepy", 170)
        left.addWidget(self.icon, 0, Qt.AlignHCenter)
        self.ring = Ring()
        left.addWidget(self.ring, 0, Qt.AlignHCenter)
        left.addStretch(1)
        lay.addLayout(left)
        right = QVBoxLayout()
        self.what = QLabel()
        self.what.setObjectName("Title")
        self.what.setWordWrap(True)
        self.why = QLabel()
        self.why.setObjectName("Speech")
        self.why.setWordWrap(True)
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        self.steps.setStyleSheet("font-size:15px")
        right.addWidget(self.what)
        right.addWidget(self.why)
        right.addWidget(QLabel("<b>Bây giờ mình có thể:</b>"))
        right.addWidget(self.steps)
        right.addStretch(1)
        btns = QHBoxLayout()
        self.ack = QPushButton("💾 Nghỉ thôi, lưu bài nào")
        self.ack.setObjectName("Mint")
        self.ack.clicked.connect(self._ack)
        self.req = QPushButton("🙋 Xin thêm giờ")
        self.req.clicked.connect(lambda: self.open_request())
        self.close_btn = QPushButton("Mình hiểu rồi")
        self.close_btn.setObjectName("Ghost")
        self.close_btn.clicked.connect(self.hide)
        for b in (self.ack, self.req, self.close_btn):
            btns.addWidget(b)
        right.addLayout(btns)
        lay.addLayout(right, 1)
        self.current_key = None

    def show_screen(self, s: V.BlockScreen, profile: dict, key: str):
        self.current_key = key
        self.icon.load(str(ASSETS / f"{s.mascot}_{s.mood}.svg"))
        self.what.setText(s.what)
        self.why.setText(s.why)
        self.steps.setText("\n".join(f"• {x}" for x in s.next_steps))
        self.ring.setVisible(s.countdown > 0)
        self.ring.set(s.countdown)
        self.ack.setVisible(s.can_ack_break)
        call = profile.get("guardian_call", "Ba Mẹ")
        mam = profile.get("age_mode") == "mam"
        self.req.setText("🙋 Xin giờ" if mam else f"🙋 Xin {call} thêm giờ")
        self.req.setVisible(s.can_request)
        self.close_btn.setVisible(not s.can_ack_break and key.startswith("app:"))
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center() - self.rect().center())
            self.show()
        self.raise_()

    def _ack(self):
        self.bridge.call("ack_break")
        self.ack.setEnabled(False)


# ======================================================================== toast
class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(380)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 18, 12)
        self.icon = mascot("khien", "happy", 56)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setStyleSheet("font-size:14px;font-weight:700")
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def pop(self, text: str, kind: str):
        m, mood = V.mascot_for(kind)
        self.icon.load(str(ASSETS / f"{m}_{mood}.svg"))
        self.text.setText(text)
        self.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 20, scr.bottom() - self.height() - 90)
        self.show()
        self.raise_()
        self.timer.start(7000)


# ======================================================================== cửa sổ chính
class MainWindow(QWidget):
    def __init__(self, bridge: Bridge, open_request):
        super().__init__()
        self.setObjectName("Main")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("OGK Kids")
        self.setWindowIcon(QIcon(str(ASSETS / "tictac_happy.svg")))
        self.resize(820, 560)
        self.bridge, self.open_request = bridge, open_request
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        nav = QVBoxLayout()
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        for i, label in enumerate(["⏰ Hôm nay", "🧩 Đã khám phá gì", "📜 Ai đã đổi gì", "🛡️ Về OGK"]):
            b = QPushButton(label)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            self.nav_group.addButton(b, i)
            nav.addWidget(b)
        nav.addStretch(1)
        nav.addWidget(mascot("khien", "happy", 64), 0, Qt.AlignHCenter)
        root.addLayout(nav)
        root.addWidget(self.stack, 1)
        self._build_today()
        self._build_explore()
        self._build_audit()
        self._build_about()
        self.go(0)

    def go(self, i: int):
        self.nav_group.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.load_explore()
        elif i == 2:
            self.load_audit()

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName("Card")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(22, 20, 22, 20)
        return f, lay

    # ---- Hôm nay ----
    def _build_today(self):
        page, lay = self._card()
        top = QHBoxLayout()
        self.t_icon = mascot("tictac", "happy", 96)
        top.addWidget(self.t_icon)
        col = QVBoxLayout()
        self.t_hello = QLabel("Chào bạn!")
        self.t_hello.setObjectName("Title")
        self.t_big = QLabel("—")
        self.t_big.setObjectName("Big")
        col.addWidget(self.t_hello)
        col.addWidget(self.t_big)
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.t_bar = TimeBar(18)
        lay.addWidget(self.t_bar)
        lay.addWidget(QLabel("<b>Hôm nay của mình</b> — xanh là giờ được dùng, xám là giờ nghỉ:"))
        self.t_line = DayTimeline()
        lay.addWidget(self.t_line)
        self.t_info = QLabel("")
        self.t_info.setObjectName("Muted")
        self.t_info.setWordWrap(True)
        lay.addWidget(self.t_info)
        lay.addStretch(1)
        self.t_btn = QPushButton("🙋 Xin thêm giờ")
        self.t_btn.clicked.connect(lambda: self.open_request())
        lay.addWidget(self.t_btn, 0, Qt.AlignLeft)
        self.stack.addWidget(page)

    def update_today(self, st: dict):
        prof = st.get("profile", {})
        mode = prof.get("age_mode", "choi")
        call = prof.get("guardian_call", "Ba Mẹ")
        self.t_hello.setText(f"Chào {prof.get('nickname', 'bạn')}!")
        rem = st.get("remaining_sec", 0)
        locked = st.get("phase") == "locked"
        self.t_big.setText("Máy đang tạm nghỉ ☾" if locked else f"{V.time_icon(rem)} {V.format_remaining(rem, 'choi')}")
        self.t_big.setStyleSheet(f"font-size:{44 if mode == 'mam' else 34}px")
        self.t_icon.load(str(ASSETS / ("tictac_sleepy.svg" if locked else
                                       ("tictac_remind.svg" if rem <= 600 else "tictac_happy.svg"))))
        self.t_bar.set(rem, st.get("quota_min", 60))
        self.t_line.set(st.get("segments"), st.get("now_slot", 0))
        info = [f"Hôm nay {prof.get('self_pronoun', 'con')} đã dùng {st.get('used_sec', 0) // 60} / {st.get('quota_min', 0)} phút."]
        for c, b in (st.get("budgets") or {}).items():
            info.append(f"{CAT_VI.get(c, c)}: {b['used_min']:.0f}/{b['limit_min']} phút.")
        reqs = st.get("requests") or []
        if reqs:
            last = reqs[-1]["status"]
            info.append({"pending": f"Yêu cầu: Đã gửi → {call} đang xem…", "approved": f"Yêu cầu: {call} đã đồng ý ✓",
                         "denied": "Yêu cầu: để lần sau"}.get(last, ""))
        if not st.get("online", True):
            info.append("📶 Máy đang mất mạng — mọi thứ vẫn hoạt động bình thường.")
        self.t_info.setText("  ".join(info))
        self.t_btn.setText("🙋 Xin giờ" if mode == "mam" else f"🙋 Xin {call} thêm giờ")

    # ---- Đã khám phá gì ----
    def _build_explore(self):
        page, lay = self._card()
        self.e_title = QLabel("Hôm nay mình đã khám phá gì")
        self.e_title.setObjectName("Title")
        lay.addWidget(self.e_title)
        self.e_total = QLabel("")
        lay.addWidget(self.e_total)
        self.e_bars = CategoryBars()
        lay.addWidget(self.e_bars)
        self.e_lists = QLabel("")
        self.e_lists.setWordWrap(True)
        self.e_lists.setTextFormat(Qt.RichText)
        lay.addWidget(self.e_lists)
        self.e_promise = QLabel("")
        self.e_promise.setObjectName("Speech")
        self.e_promise.setWordWrap(True)
        lay.addWidget(self.e_promise)
        lay.addStretch(1)
        self.stack.addWidget(page)
        self._profile = {}

    def load_explore(self):
        r = self.bridge.call("get_today")
        d = r.get("today", {}) if r.get("ok") else {}
        prof = self._profile
        xung = prof.get("self_pronoun", "con")
        self.e_title.setText(f"Hôm nay {xung} đã khám phá gì")
        self.e_total.setText(f"Tổng cộng: <b>{d.get('today_minutes', 0)} phút</b>")
        self.e_bars.set(d.get("cats_today") or {})
        apps = ", ".join(a["name"] for a in (d.get("top_apps") or [])[:5]) or "chưa có"
        doms = ", ".join(x["name"] for x in (d.get("top_domains") or [])[:5]) or "chưa có"
        self.e_lists.setText(f"📱 <b>Ứng dụng:</b> {apps}<br>🌐 <b>Trang web:</b> {doms}")
        self.e_promise.setText(f"👀 {prof.get('guardian_call', 'Ba Mẹ')} cũng thấy đúng những thông tin này, không hơn.")

    # ---- Ai đã đổi gì ----
    def _build_audit(self):
        page, lay = self._card()
        t = QLabel("Ai đã đổi gì")
        t.setObjectName("Title")
        lay.addWidget(t)
        self.a_list = QLabel("")
        self.a_list.setWordWrap(True)
        self.a_list.setTextFormat(Qt.RichText)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.a_list)
        lay.addWidget(sc, 1)
        self.stack.addWidget(page)

    def load_audit(self):
        r = self.bridge.call("get_audit")
        items = (r.get("audit") or {}).get("items", []) if r.get("ok") else []
        html = "".join(f"<p>{'<br>'.join(i['lines'])}<br><span style='color:#6B7280'>{i['when']}</span></p>" for i in items)
        self.a_list.setText(html or "Chưa có thay đổi nào.")

    # ---- Về OGK ----
    def _build_about(self):
        page, lay = self._card()
        t = QLabel("Tớ là Khiên Xanh — bạn đồng hành của OGK")
        t.setObjectName("Title")
        lay.addWidget(t)
        txt = QLabel("Tớ chỉ biết <b>tên ứng dụng</b> và <b>tên trang web</b> bạn dùng, cùng thời gian dùng máy.<br><br>"
                     "Tớ <b>không</b> đọc tin nhắn, <b>không</b> chụp màn hình, <b>không</b> nghe micro, "
                     "<b>không</b> bật camera.<br><br>Ba mẹ và bạn cùng thấy một bảng thông tin. "
                     "Biểu tượng của tớ luôn ở góc màn hình. Dữ liệu tự xóa sau 90 ngày.")
        txt.setWordWrap(True)
        txt.setTextFormat(Qt.RichText)
        txt.setStyleSheet("font-size:16px")
        lay.addWidget(txt)
        lay.addStretch(1)
        self.stack.addWidget(page)


# ======================================================================== onboarding 4 bước
class Onboarding(QDialog):
    def __init__(self, profile: dict):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        self.setObjectName("Dialog")
        self.setWindowTitle("Làm quen với OGK")
        self.resize(560, 360)
        con = profile.get("nickname", "bạn")
        call = profile.get("guardian_call", "Ba Mẹ")
        self.pages = [
            ("tictac", "happy", f"Chào {con}! Tớ là Tíc-Tắc. Tớ giúp {con} cân bằng giờ chơi và giờ nghỉ."),
            ("khien", "encourage", f"Tớ là Khiên Xanh. Tớ chỉ biết tên trang và tên ứng dụng {con} dùng, "
                                   "không đọc tin nhắn, không chụp màn hình, không nghe mic."),
            ("sao", "celebrate", f"Tớ là Sao Nhỏ! Tớ sẽ cổ vũ mỗi khi {con} dừng đúng giờ."),
            ("khien", "happy", f"{call} và {con} cùng thấy một bảng thông tin. Biểu tượng của bọn tớ luôn ở góc màn hình."),
        ]
        self.i = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        row = QHBoxLayout()
        self.icon = mascot("tictac", "happy", 140)
        self.text = QLabel()
        self.text.setObjectName("Speech")
        self.text.setWordWrap(True)
        self.text.setStyleSheet("font-size:18px")
        row.addWidget(self.icon)
        row.addWidget(self.text, 1)
        lay.addLayout(row, 1)
        btns = QHBoxLayout()
        skip = QPushButton("Bỏ qua")
        skip.setObjectName("Ghost")
        skip.clicked.connect(self.accept)
        self.next = QPushButton("Tiếp →")
        self.next.clicked.connect(self._next)
        btns.addWidget(skip)
        btns.addStretch(1)
        btns.addWidget(self.next)
        lay.addLayout(btns)
        self._show()

    def _show(self):
        m, mood, t = self.pages[self.i]
        self.icon.load(str(ASSETS / f"{m}_{mood}.svg"))
        self.text.setText(t)
        self.next.setText("Bắt đầu thôi!" if self.i == len(self.pages) - 1 else "Tiếp →")

    def _next(self):
        if self.i == len(self.pages) - 1:
            self.accept()
            return
        self.i += 1
        self._show()


# ======================================================================== ứng dụng
class TrayApp:
    def __init__(self, bridge: Bridge, show_pill: bool = True):
        self.bridge = bridge
        self.status: dict = {}
        self.main = MainWindow(bridge, self.open_request)
        self.pill = Pill()
        self.pill.clicked.connect(self.open_main)
        self.block = BlockWindow(bridge, self.open_request)
        self.toast = Toast()
        self.tray = QSystemTrayIcon(QIcon(str(ASSETS / "tictac_happy.svg")))
        menu = QMenu()
        for label, fn in (("Mở OGK Kids", self.open_main), ("🙋 Xin thêm giờ", self.open_request),
                          ("🧩 Hôm nay mình đã dùng gì", lambda: self.open_main(1)),
                          ("📜 Ai đã đổi gì", lambda: self.open_main(2))):
            a = QAction(label, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        # Không có mục "Thoát": Tray là cam kết minh bạch, luôn hiện (trẻ tắt thì dịch vụ mở lại).
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_main() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("OGK Kids")
        self.tray.show()
        if show_pill:
            scr = QApplication.primaryScreen().availableGeometry()
            self.pill.move(scr.right() - self.pill.width() - 16, scr.top() + 16)
            self.pill.show()
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)
        self.idle_timer = QTimer()
        self.idle_timer.timeout.connect(self.report_idle)
        self.idle_timer.start(15000)
        self.onboarded = False
        self.poll()

    def open_main(self, tab: int = 0):
        self.main._profile = self.status.get("profile", {})
        self.main.go(tab if isinstance(tab, int) else 0)
        self.main.show()
        self.main.raise_()
        self.main.activateWindow()

    def open_request(self):
        RequestDialog(self.bridge, self.status.get("profile", {})).exec()

    def report_idle(self):
        from agent import winsys
        self.bridge.call("report_idle", seconds=winsys.idle_seconds())

    def poll(self):
        st = self.bridge.status()
        if st is None:
            self.pill.label.setText("🔌 Đang kết nối OGK…")
            self.tray.setToolTip("OGK Kids — đang kết nối dịch vụ")
            return
        self.status = st
        prof = st.get("profile", {})
        self.main._profile = prof
        self.pill.update_status(st)
        self.tray.setToolTip(f"OGK Kids — {V.format_remaining(st.get('remaining_sec', 0))}")
        self.main.update_today(st)
        if not self.onboarded and not self.bridge.demo:
            self.onboarded = True
            flag = Path.home() / ".ogk_kids_onboarded"
            if not flag.exists():
                Onboarding(prof).exec()
                flag.write_text("1")
        app_note = None
        for n in st.get("notifications", []):
            if n.get("kind") == "blocked_app":
                app_note = n
                continue
            text = V.toast_text(n, prof)
            if text:
                self.toast.pop(text, n.get("kind", ""))
        screen = V.block_screen(st)
        if screen is not None:
            self.block.show_screen(screen, prof, key=f"{st.get('phase')}:{st.get('lock_reason')}")
        elif app_note is not None:
            self.block.show_screen(V.block_screen(st, app_note), prof, key=f"app:{app_note.get('app')}")
        elif self.block.isVisible() and not (self.block.current_key or "").startswith("app:"):
            self.block.hide()
            self.block.ack.setEnabled(True)


# ======================================================================== dữ liệu giả (demo/ảnh chụp)
DEMO_PROFILE = {"nickname": "Bin", "self_pronoun": "con", "guardian_call": "Mẹ", "age_mode": "mam"}


def demo_status(t0: float, phase: str = "active", remaining: int = 23 * 60) -> dict:
    from agent import schedule as sch
    from datetime import datetime
    now = datetime.now()
    s = sch.make_schedule({d: [("06:00", "07:00"), ("16:00", "21:00")] for d in range(7)})
    return {"phase": phase, "lock_reason": "quota" if phase != "active" else None, "remaining_sec": remaining,
            "used_sec": 67 * 60, "quota_min": 90, "grace_left": 42, "now_slot": now.hour * 2 + now.minute // 30,
            "segments": sch.day_segments(s, now), "next_allowed": "16:00", "profile": DEMO_PROFILE,
            "budgets": {"games": {"used_min": 30, "limit_min": 45}}, "online": True, "notifications": [],
            "requests": [{"id": 1, "status": "pending"}]}


def demo_call(op: str, **kw) -> dict:
    if op == "get_today":
        return {"ok": True, "today": {"today_minutes": 67, "cats_today": {"education": 35, "games": 22, "entertainment": 10},
                                      "top_apps": [{"name": "scratch 3.exe"}, {"name": "minecraft.exe"}, {"name": "winword.exe"}],
                                      "top_domains": [{"name": "khanacademy.org"}, {"name": "olm.vn"}, {"name": "youtube.com"}]}}
    if op == "get_audit":
        return {"ok": True, "audit": {"items": [{"when": "hôm qua, 20:15", "lines": ["Mẹ đã đổi giờ dùng cuối tuần từ 150 phút thành 120 phút"]},
                                                {"when": "17/11, 08:02", "lines": ["Mẹ đã tạo mã ghép máy tính (ba mẹ đồng ý sử dụng OGK)"]}]}}
    if op == "request_more_time":
        return {"ok": True, "sent": True, "request_id": 1}
    return {"ok": True}


def load_fonts() -> None:
    """Nunito đóng gói cục bộ (OFL) — hỗ trợ đủ tiếng Việt, không phụ thuộc mạng. Qt cần TTF (không đọc WOFF2)."""
    QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / "Nunito.ttf"))


def screenshots(out: Path) -> None:
    """Xuất ảnh từng màn hình (dùng cho báo cáo / UX_TEST) — chạy được offscreen."""
    out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(None, 0, demo=True)
    main = MainWindow(bridge, lambda: None)
    main._profile = DEMO_PROFILE
    main.update_today(demo_status(0))
    for i, name in enumerate(["today", "explore", "audit", "about"]):
        main.go(i)
        main.grab().save(str(out / f"kids_{name}.png"))
    pill = Pill()
    pill.update_status(demo_status(0, remaining=8 * 60))
    pill.grab().save(str(out / "kids_pill.png"))
    block = BlockWindow(bridge, lambda: None)
    for name, st, note in (("grace", demo_status(0, "grace", 0), None),
                           ("locked", {**demo_status(0, "locked", 0), "lock_reason": "schedule"}, None),
                           ("blocked_app", demo_status(0), {"kind": "blocked_app", "app": "game.exe"})):
        block.show_screen(V.block_screen(st, note), DEMO_PROFILE, key=f"app:{name}" if note else name)
        block.grab().save(str(out / f"kids_block_{name}.png"))
    toast = Toast()
    toast.pop(V.toast_text({"kind": "blocked_domain", "domain": "tiktok.com"}, DEMO_PROFILE), "blocked_domain")
    toast.grab().save(str(out / "kids_toast.png"))
    dlg = RequestDialog(bridge, DEMO_PROFILE)
    dlg.grab().save(str(out / "kids_request.png"))
    ob = Onboarding(DEMO_PROFILE)
    ob.grab().save(str(out / "kids_onboarding.png"))
    print(f"Đã xuất ảnh vào {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ogk-kids")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--port", type=int, default=47653)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--screenshots", default=None)
    args = ap.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    load_fonts()
    app.setStyleSheet(QSS)
    if args.screenshots:
        screenshots(Path(args.screenshots))
        return 0
    from agent.config import default_data_dir
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Không có khay hệ thống — OGK Kids không thể hiển thị biểu tượng.")
    _tray = TrayApp(Bridge(data_dir, args.port, demo=args.demo))  # noqa: F841 (giữ tham chiếu)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
