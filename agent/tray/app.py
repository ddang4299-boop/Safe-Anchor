"""
agent/tray/app.py — OGK Kids: ứng dụng khay hệ thống cho trẻ (PySide6). Chạy với QUYỀN CỦA TRẺ.

Yêu cầu đề: §4.2 Tray UI (thời gian còn lại, lý do bị chặn, gửi yêu cầu), F1 (cảnh báo 10/5/1,
ân hạn 60 giây), F2 (khi chặn: hiện cửa sổ giải thích), F3 ("Hôm nay em đã dùng gì"), NT5 (xem nhật
ký "Ai đã đổi gì"), F5 (không chế độ ẩn: biểu tượng khay LUÔN hiện).

Giao diện "Modern Tactile + Bento": nền gradient #F8FAFC -> #EEF2FF -> #F5F3FF, thẻ trắng bo 24px với bóng
mềm ánh xanh tím, nút "xúc giác" (viền dưới đậm 4px, bấm thì lún xuống), mascot SVG có gradient tự chớp mắt.
  - Viên HUD nổi: Tíc-Tắc + số phút in đậm + thanh tiến trình đổi màu mượt Mint -> Vàng nắng -> Cam ấm.
  - Màn chặn: thẻ trung tâm, mascot nhô khỏi mép trên (nhấp nhô nhẹ), bong bóng thoại, chip xin giờ nhanh.
  - "Hôm nay em đã dùng gì": lưới Bento (thời gian, học tập, giải trí, huy hiệu đúng giờ).

Tray chỉ HIỂN THỊ và CHUYỂN LỜI: mọi quyết định (đếm giờ, khóa, chặn) nằm ở dịch vụ SYSTEM.
Trẻ tắt Tray => dịch vụ vẫn kiểm soát và tự mở lại Tray (TrayWatchdog).

    python -m agent.tray.app                 # nối với agent đang chạy (Named Pipe / TCP 127.0.0.1)
    python -m agent.tray.app --demo          # chạy thử giao diện với dữ liệu giả, không cần agent
    python -m agent.tray.app --screenshots docs/screenshots   # xuất ảnh từng màn hình (offscreen)
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from agent.app_names import app_display

from . import messages_vi as M
from . import view_logic as V

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

CAT_VI = {"education": "Học tập", "entertainment": "Giải trí", "social": "Mạng xã hội", "games": "Trò chơi",
          "inappropriate": "Chưa phù hợp", "uncategorized": "Khác"}
CAT_COLOR = {"education": ("#6EE7B7", "#10B981"), "entertainment": ("#FDE68A", "#FBBF24"),
             "games": ("#FDBA74", "#FF8E53"), "social": ("#C4B5FD", "#8B5CF6"), "uncategorized": ("#CBD5E1", "#94A3B8")}
INK, MUTED, TRACK = "#1E1B4B", "#64748B", "#E6E8F7"

QSS = """
* { font-family: "Nunito", "Segoe UI", sans-serif; color: #1E1B4B; font-size: 15px; }
#Main, #Dialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FAFC, stop:0.5 #EEF2FF, stop:1 #F5F3FF); }
#Card { background: #FFFFFF; border: 1px solid #E9EBF8; border-radius: 24px; }
#TileIndigo { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EEF2FF, stop:1 #E0E7FF); border: 1px solid #DCE2FD; border-radius: 24px; }
#TileMint { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ECFDF5, stop:1 #D1FAE5); border: 1px solid #CFF5E4; border-radius: 24px; }
#TileSun { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFFBEB, stop:1 #FEF3C7); border: 1px solid #FBEFC2; border-radius: 24px; }
#TileGrape { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F5F3FF, stop:1 #EDE9FE); border: 1px solid #E7E0FD; border-radius: 24px; }
#TileCoral { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFF4EE, stop:1 #FFE4DA); border: 1px solid #FFDCCF; border-radius: 24px; }
#BlockCard { background: #FFFFFF; border: 1px solid #E9EBF8; border-radius: 32px; }
#PillBody, #ToastBody { background: rgba(255, 255, 255, 238); border: 1px solid rgba(255, 255, 255, 255); border-radius: 36px; }
#ToastBody { border-radius: 26px; }
QLabel { background: transparent; }
QLabel#Title { font-size: 22px; font-weight: 900; }
QLabel#Big { font-size: 38px; font-weight: 900; }
QLabel#Num { font-size: 34px; font-weight: 900; }
QLabel#Muted { color: #64748B; }
QLabel#Eyebrow { color: #94A3B8; font-size: 12px; font-weight: 900; }
QLabel#Speech { background: #EEF2FF; border-radius: 22px; padding: 14px 18px; font-size: 16px; font-weight: 700; }
QLabel#Step { background: #F6F7FE; border: 1px solid #E9EBF8; border-radius: 15px; padding: 5px 12px; font-size: 14px; font-weight: 800; }
QLabel#Brand { font-size: 18px; font-weight: 900; }
QPushButton { border: none; border-radius: 23px; min-height: 42px; padding: 0 22px; font-size: 15px; font-weight: 900;
              background: #6366F1; color: #FFFFFF; border-bottom: 4px solid #4338CA; }
QPushButton:hover { background: #7578F4; }
QPushButton:pressed { border-bottom: 1px solid #4338CA; margin-top: 3px; }
QPushButton:disabled { background: #C7CBF5; border-bottom-color: #AEB3EE; }
QPushButton#Mint { background: #10B981; border-bottom-color: #059669; }
QPushButton#Mint:hover { background: #1BC48C; }
QPushButton#Mint:pressed { border-bottom: 1px solid #059669; margin-top: 3px; }
QPushButton#Ghost { background: #FFFFFF; color: #4338CA; border: 1px solid #E0E7FF; border-bottom: 4px solid #DADDF2; }
QPushButton#Ghost:hover { background: #F6F7FE; }
QPushButton#Ghost:pressed { border-bottom: 1px solid #DADDF2; margin-top: 3px; }
QPushButton#Chip { background: #FFFFFF; color: #1E1B4B; border: 1px solid #E0E7FF; border-bottom: 3px solid #DADDF2;
                   border-radius: 18px; min-height: 34px; padding: 0 14px; font-size: 14px; font-weight: 800; }
QPushButton#Chip:hover { border-color: #A5B4FC; background: #F6F7FE; }
QPushButton#Chip:pressed { border-bottom: 1px solid #DADDF2; margin-top: 2px; }
QPushButton#Nav { background: transparent; color: #64748B; text-align: left; border: none; border-radius: 18px;
                  min-height: 46px; padding: 0 16px; font-size: 15px; }
QPushButton#Nav:hover { background: rgba(255, 255, 255, 160); color: #1E1B4B; }
QPushButton#Nav:checked { background: #FFFFFF; color: #4338CA; border-bottom: 3px solid #E0E7FF; }
QPushButton#Choice { background: #FFFFFF; color: #1E1B4B; border: 2px solid #E0E7FF; border-bottom: 4px solid #DADDF2; min-width: 90px; }
QPushButton#Choice:checked { background: #EEF2FF; color: #4338CA; border-color: #6366F1; border-bottom-color: #4338CA; }
QLineEdit { border: 2px solid #E9EBF8; border-radius: 16px; padding: 10px 14px; font-size: 15px; background: #F6F7FE; }
QLineEdit:focus { border-color: #6366F1; background: #FFFFFF; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
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


# ======================================================================== tiện ích giao diện
def soft_shadow(w: QWidget, blur: int = 34, dy: int = 10, alpha: int = 40) -> None:
    """Bóng mềm ánh xanh tím (không dùng bóng đen cứng)."""
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(99, 102, 241, alpha))
    w.setGraphicsEffect(eff)


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, name: str | None = None, slot=None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


class Mascot(QSvgWidget):
    """Mascot SVG tự CHỚP MẮT: mỗi ~5 giây đổi sang khung *_blink.svg trong 140 ms (Qt không chạy được
    hoạt ảnh CSS bên trong SVG như trình duyệt, nên tạo chuyển động bằng cách luân phiên khung hình)."""

    def __init__(self, kind: str, mood: str, size: int, blink: bool = True):
        super().__init__()
        self.setFixedSize(size, size)
        self.kind, self.mood = kind, mood
        self.load(str(ASSETS / f"{kind}_{mood}.svg"))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._blink)
        if blink:
            self._timer.start(4200 + random.randint(0, 1800))

    def set(self, kind: str, mood: str) -> None:
        if (kind, mood) != (self.kind, self.mood):
            self.kind, self.mood = kind, mood
            self.load(str(ASSETS / f"{kind}_{mood}.svg"))

    def _blink(self) -> None:
        if self.mood in ("happy", "encourage", "remind") and self.isVisible():
            self.load(str(ASSETS / f"{self.kind}_blink.svg"))
            QTimer.singleShot(140, lambda: self.load(str(ASSETS / f"{self.kind}_{self.mood}.svg")))


def mascot(kind: str, mood: str, size: int) -> Mascot:
    return Mascot(kind, mood, size)


class TimeBar(QWidget):
    """Thanh thời gian bo tròn hoàn toàn: màu chuyển MƯỢT Mint -> Vàng nắng -> Cam ấm theo phút còn lại
    (kèm chữ số phút ở nơi khác — không chỉ dùng màu)."""

    def __init__(self, height: int = 14):
        super().__init__()
        self.ratio, self.color = 1.0, V.MINT
        self.setFixedHeight(height)

    def set(self, remaining: int, quota_min: int):
        total = max(1, quota_min * 60)
        self.ratio = max(0.0, min(1.0, remaining / total))
        self.color = V.smooth_time_color(remaining)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(r, rad, rad)
        w = r.width() * self.ratio
        if w > 0:
            fill = QRectF(0, 0, max(w, r.height()), r.height())
            g = QLinearGradient(0, 0, fill.width(), 0)
            g.setColorAt(0, QColor(self.color).lighter(125))
            g.setColorAt(1, QColor(self.color))
            p.setBrush(g)
            p.drawRoundedRect(fill, rad, rad)
            p.setBrush(QColor(255, 255, 255, 70))  # vệt sáng phía trên: cảm giác "khối"
            p.drawRoundedRect(QRectF(rad / 2, 2, max(0.0, fill.width() - rad), r.height() / 3), rad / 3, rad / 3)


class RoundBar(QWidget):
    """Thanh tiến trình bo tròn một màu (thẻ Bento học tập / giải trí)."""

    def __init__(self, colors: tuple[str, str], height: int = 16):
        super().__init__()
        self.colors, self.ratio = colors, 0.0
        self.setFixedHeight(height)

    def set(self, ratio: float):
        self.ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawRoundedRect(r, rad, rad)
        if self.ratio > 0:
            fill = QRectF(0, 0, max(r.height(), r.width() * self.ratio), r.height())
            g = QLinearGradient(0, 0, fill.width(), 0)
            g.setColorAt(0, QColor(self.colors[0]))
            g.setColorAt(1, QColor(self.colors[1]))
            p.setBrush(g)
            p.drawRoundedRect(fill, rad, rad)


class DayTimeline(QWidget):
    """Dải thời gian cả ngày: khúc xanh = được dùng, xám = giờ nghỉ, mũi tên = bây giờ (biết trước, không bất ngờ)."""

    def __init__(self):
        super().__init__()
        self.segments, self.now_slot = [], 0
        self.setMinimumHeight(58)

    def set(self, segments, now_slot):
        self.segments, self.now_slot = segments or [], now_slot
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cell = w / 48
        p.setPen(Qt.NoPen)
        for a, b, ok in self.segments:
            r = QRectF(a * cell + 1.5, 18, (b - a) * cell - 3, 18)
            if ok:
                g = QLinearGradient(0, r.top(), 0, r.bottom())
                g.setColorAt(0, QColor("#34D399"))
                g.setColorAt(1, QColor("#10B981"))
                p.setBrush(g)
            else:
                p.setBrush(QColor(TRACK))
            p.drawRoundedRect(r, 9, 9)
        x = (self.now_slot + 0.5) * cell
        p.setBrush(QColor("#6366F1"))
        path = QPainterPath()
        path.moveTo(x - 7, 1)
        path.lineTo(x + 7, 1)
        path.lineTo(x, 13)
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(QColor(MUTED))
        f = QFont("Nunito", 8, QFont.Bold)
        p.setFont(f)
        for h in (0, 6, 12, 18, 24):
            p.drawText(QRectF(min(h * 2 * cell, w - 30), 40, 30, 16), Qt.AlignLeft, f"{h}h")


class Ring(QWidget):
    """Vòng đếm ngược ân hạn: mềm, KHÔNG nhấp nháy (an toàn cho trẻ nhạy cảm ánh sáng)."""

    def __init__(self, size: int = 120):
        super().__init__()
        self.left, self.total = 60, 60
        self.setFixedSize(size, size)

    def set(self, left, total=60):
        self.left, self.total = left, total
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(9, 9, self.width() - 18, self.height() - 18)
        p.setPen(QPen(QColor(TRACK), 12))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(V.smooth_time_color(self.left * 10)), 12, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * self.left / max(1, self.total)))
        p.setPen(QColor(INK))
        p.setFont(QFont("Nunito", 22, QFont.Black))
        p.drawText(self.rect(), Qt.AlignCenter, f"{self.left}s")


class CategoryBars(QWidget):
    """Thanh nhóm (Học tập/Trò chơi...) bo tròn, tô gradient theo màu nhóm."""

    def __init__(self):
        super().__init__()
        self.items = []
        self.setMinimumHeight(40)

    def set(self, cats: dict):
        self.items = list(cats.items())[:6]
        self.setMinimumHeight(40 * max(1, len(self.items)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(v for _, v in self.items) or 1
        for i, (c, v) in enumerate(self.items):
            y = i * 40
            p.setPen(QColor(INK))
            p.setFont(QFont("Nunito", 11, QFont.Black))
            p.drawText(QRectF(0, y, 110, 28), Qt.AlignVCenter, CAT_VI.get(c, c))
            bw = self.width() - 200
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(115, y + 6, bw, 16), 8, 8)
            a, b = CAT_COLOR.get(c, ("#A5B4FC", "#6366F1"))
            fw = max(16.0, bw * v / total)
            g = QLinearGradient(115, 0, 115 + fw, 0)
            g.setColorAt(0, QColor(a))
            g.setColorAt(1, QColor(b))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(115, y + 6, fw, 16), 8, 8)
            p.setPen(QColor(MUTED))
            p.setFont(QFont("Nunito", 10, QFont.Bold))
            p.drawText(QRectF(self.width() - 76, y, 76, 28), Qt.AlignVCenter | Qt.AlignRight, f"{v} phút")


# ======================================================================== viên HUD nổi
class Pill(QWidget):
    """Widget thời gian nổi trên màn hình: viên thuốc kính mờ, Tíc-Tắc bên trái, số phút in đậm."""
    clicked = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(326, 100)
        self.body = QFrame(self)
        self.body.setObjectName("PillBody")
        self.body.setGeometry(12, 8, 302, 76)
        soft_shadow(self.body, blur=30, dy=8, alpha=70)
        lay = QHBoxLayout(self.body)
        lay.setContentsMargins(10, 8, 20, 10)
        lay.setSpacing(10)
        self.icon = Mascot("tictac", "happy", 58)
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        top = QHBoxLayout()
        self.label = label("Đang kết nối…")
        self.label.setStyleSheet("font-size:19px;font-weight:900")
        self.sub = label("", "Muted")
        self.sub.setStyleSheet("font-size:12px;font-weight:800")
        top.addWidget(self.label)
        top.addStretch(1)
        top.addWidget(self.sub)
        self.bar = TimeBar(12)
        col.addLayout(top)
        col.addWidget(self.bar)
        lay.addLayout(col, 1)
        self._drag: QPoint | None = None
        self._moved = False

    def update_status(self, st: dict):
        rem = st.get("remaining_sec", 0)
        if st.get("phase") == "locked":
            self.label.setText("☾ Tạm nghỉ")
            self.sub.setText(f"đến {st['lock_until']}" if st.get("lock_until") else "nghỉ chút nhé")
            self.icon.set("tictac", "sleepy")
        else:
            self.label.setText(f"{V.time_icon(rem)} {V.format_remaining(rem, 'mam')}")
            self.sub.setText("còn lại hôm nay")
            self.icon.set("tictac", "remind" if rem <= 600 else "happy")
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
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("Xin thêm giờ")
        self.setMinimumWidth(600)
        self.bridge, self.profile = bridge, profile
        call = profile.get("guardian_call", "Ba Mẹ")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 24)
        lay.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(Mascot("sao", "encourage", 86))
        t = label(f"{profile.get('nickname', 'Bạn nhỏ')} muốn xin {call} thêm bao lâu?", "Title", True)
        top.addWidget(t, 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        self.group = QButtonGroup(self)
        for m in (15, 30, 60):
            b = button(f"{m} phút", "Choice")
            b.setCheckable(True)
            self.group.addButton(b, m)
            row.addWidget(b)
        self.group.button(15).setChecked(True)
        lay.addLayout(row)
        lay.addWidget(label("Chọn nhanh lý do:", "Eyebrow"))
        chips = QGridLayout()
        chips.setSpacing(8)
        for k, r in enumerate(V.quick_reasons(profile)):
            chips.addWidget(button(r, "Chip", lambda _=False, r=r: self.reason.setText(r)), k // 2, k % 2)
        lay.addLayout(chips)
        self.reason = QLineEdit()
        self.reason.setMaxLength(200)
        self.reason.setPlaceholderText(f"Hoặc tự viết: vì sao {profile.get('self_pronoun', 'con')} cần thêm giờ? (không bắt buộc)")
        lay.addWidget(self.reason)
        self.msg = label("", None, True)
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        btns.addWidget(button("Thôi", "Ghost", self.reject))
        btns.addStretch(1)
        self.send = button(f"🙋 Gửi {call}", None, self._send)
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
    """Thẻ trung tâm nổi bật, mascot đứng NHÔ khỏi mép trên thẻ và nhấp nhô nhẹ; bong bóng thoại ấm áp;
    chip xin thêm giờ nhanh. Luôn trả lời đủ 3 câu hỏi: chuyện gì — vì sao — bây giờ làm gì (view_logic)."""
    W, H, TOP = 800, 640, 104

    def __init__(self, bridge: Bridge, open_request):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.bridge, self.open_request = bridge, open_request
        self.profile: dict = {}
        self.resize(self.W, self.H)
        self.card = QFrame(self)
        self.card.setObjectName("BlockCard")
        self.card.setGeometry(28, self.TOP, self.W - 56, self.H - self.TOP - 28)
        soft_shadow(self.card, blur=48, dy=16, alpha=70)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(36, 84, 36, 28)
        lay.setSpacing(12)
        self.what = label("", "Title", True)
        self.what.setAlignment(Qt.AlignCenter)
        self.what.setStyleSheet("font-size:26px")
        lay.addWidget(self.what)
        mid = QHBoxLayout()
        self.why = label("", "Speech", True)
        mid.addWidget(self.why, 1)
        self.ring = Ring(116)
        mid.addWidget(self.ring, 0, Qt.AlignVCenter)
        lay.addLayout(mid)
        lay.addWidget(label("BÂY GIỜ MÌNH CÓ THỂ", "Eyebrow"))
        self.steps_row = QHBoxLayout()
        self.steps_row.setSpacing(8)
        lay.addLayout(self.steps_row)
        self.steps = label("")  # giữ thuộc tính cũ (văn bản đầy đủ) cho trình đọc màn hình
        self.steps.setVisible(False)
        self.quick_title = label("XIN THÊM GIỜ NHANH", "Eyebrow")
        lay.addWidget(self.quick_title)
        self.quick_row = QHBoxLayout()
        self.quick_row.setSpacing(8)
        self.quick: list[QPushButton] = []
        for _ in range(3):
            b = button("", "Chip")
            b.clicked.connect(lambda _=False, b=b: self._quick(b.text()))
            self.quick.append(b)
            self.quick_row.addWidget(b)
        self.quick_row.addStretch(1)
        lay.addLayout(self.quick_row)
        self.msg = label("", "Muted", True)
        lay.addWidget(self.msg)
        lay.addStretch(1)
        btns = QHBoxLayout()
        self.ack = button("💾 Nghỉ thôi, lưu bài nào", "Mint", self._ack)
        self.req = button("🙋 Xin thêm giờ", None, lambda: self.open_request())
        self.close_btn = button("Mình hiểu rồi", "Ghost", self.hide)
        btns.addWidget(self.ack)
        btns.addStretch(1)
        btns.addWidget(self.req)
        btns.addWidget(self.close_btn)
        lay.addLayout(btns)
        # mascot là con của CỬA SỔ (không phải của thẻ) => đứng đè lên mép trên thẻ
        self.icon = Mascot("tictac", "sleepy", 168)
        self.icon.setParent(self)
        self._base_y = self.TOP - 112
        self.icon.move((self.W - 168) // 2, self._base_y)
        self.icon.raise_()
        self.bob = QVariantAnimation(self)
        self.bob.setStartValue(0.0)
        self.bob.setEndValue(2 * math.pi)
        self.bob.setDuration(3400)
        self.bob.setLoopCount(-1)
        self.bob.valueChanged.connect(lambda v: self.icon.move(self.icon.x(), int(self._base_y - 6 * math.sin(v))))
        self.current_key = None

    def _set_steps(self, steps: list[str]):
        while self.steps_row.count():
            it = self.steps_row.takeAt(0)
            if it.widget():
                it.widget().hide()  # ẩn NGAY (deleteLater chỉ xóa khi vòng lặp sự kiện chạy tới)
                it.widget().deleteLater()
        for s in steps:
            lb = label(f"✓ {s}", "Step")
            self.steps_row.addWidget(lb)
            lb.show()  # thêm vào cửa sổ đang hiện: Qt chỉ tự show qua sự kiện xếp hàng => gọi trực tiếp cho chắc
        self.steps_row.addStretch(1)

    def show_screen(self, s: V.BlockScreen, profile: dict, key: str):
        self.profile = profile
        if key != self.current_key:
            self.msg.setText("")
            for b in self.quick:
                b.setEnabled(True)
        self.current_key = key
        self.icon.set(s.mascot, s.mood)
        self.what.setText(s.what)
        self.why.setText(s.why)
        self.steps.setText("\n".join(f"• {x}" for x in s.next_steps))
        self._set_steps(s.next_steps)
        self.ring.setVisible(s.countdown > 0)
        self.ring.set(s.countdown)
        self.ack.setVisible(s.can_ack_break)
        call = profile.get("guardian_call", "Ba Mẹ")
        mam = profile.get("age_mode") == "mam"
        self.req.setText("🙋 Xin giờ" if mam else f"🙋 Xin {call} thêm giờ")
        self.req.setVisible(s.can_request)
        for b, r in zip(self.quick, V.quick_reasons(profile)):
            b.setText(r)
            b.setVisible(s.can_request)
        self.quick_title.setVisible(s.can_request)
        self.close_btn.setVisible(not s.can_ack_break and key.startswith("app:"))
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center() - self.rect().center())
            self.show()
            self.bob.start()
        self.raise_()

    def _quick(self, reason: str):
        """Chip xin giờ nhanh: gửi luôn 15 phút kèm lý do đã chọn (trẻ nhỏ không phải gõ)."""
        r = self.bridge.call("request_more_time", minutes=15, reason=reason)
        sent = r.get("ok") and r.get("sent")
        self.msg.setText(M.render("request_sent" if sent else "request_offline", self.profile))
        if sent:
            for b in self.quick:
                b.setEnabled(False)

    def _ack(self):
        self.bridge.call("ack_break")
        self.ack.setEnabled(False)

    def hideEvent(self, e):
        self.bob.stop()
        super().hideEvent(e)


# ======================================================================== toast
class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 22)
        self.body = QFrame()
        self.body.setObjectName("ToastBody")
        soft_shadow(self.body, blur=30, dy=8, alpha=70)
        outer.addWidget(self.body)
        lay = QHBoxLayout(self.body)
        lay.setContentsMargins(12, 10, 20, 10)
        self.icon = Mascot("khien", "happy", 64)
        self.text = label("", None, True)
        self.text.setStyleSheet("font-size:15px;font-weight:800")
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def pop(self, text: str, kind: str):
        m, mood = V.mascot_for(kind)
        self.icon.set(m, mood)
        self.text.setText(text)
        self.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 12, scr.bottom() - self.height() - 80)
        self.show()
        self.raise_()
        self.timer.start(7000)


# ======================================================================== cửa sổ chính
class MainWindow(QWidget):
    def __init__(self, bridge: Bridge, open_request):
        super().__init__()
        self.setObjectName("Main")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("SafeAnchor")
        self.setWindowIcon(QIcon(str(ASSETS / "tictac_happy.svg")))
        self.resize(940, 660)
        self.bridge, self.open_request = bridge, open_request
        self._profile: dict = {}
        self._today: dict = {}
        self._today_at = 0.0
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)
        nav = QVBoxLayout()
        nav.setSpacing(6)
        brand = QHBoxLayout()
        brand.addWidget(Mascot("khien", "happy", 44))
        brand.addWidget(label("SafeAnchor", "Brand"))
        brand.addStretch(1)
        nav.addLayout(brand)
        nav.addSpacing(10)
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        for i, text in enumerate(["⏰  Hôm nay", "🧩  Đã khám phá gì", "📜  Ai đã đổi gì", "🛡️  Về SafeAnchor"]):
            b = button(text, "Nav", lambda _=False, i=i: self.go(i))
            b.setCheckable(True)
            b.setMinimumWidth(200)
            self.nav_group.addButton(b, i)
            nav.addWidget(b)
        nav.addStretch(1)
        nav.addWidget(Mascot("sao", "happy", 96), 0, Qt.AlignHCenter)
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

    @staticmethod
    def _tile(name: str = "Card", shadow: bool = True) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName(name)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        if shadow:
            soft_shadow(f)
        return f, lay

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 14)
        lay.setSpacing(14)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(page)
        self.stack.addWidget(sc)
        return page, lay

    # ---- Hôm nay (Bento) ----
    def _build_today(self):
        _, lay = self._page()
        grid = QGridLayout()
        grid.setSpacing(14)
        big, bl = self._tile("TileIndigo")
        top = QHBoxLayout()
        self.t_icon = Mascot("tictac", "happy", 112)
        top.addWidget(self.t_icon)
        col = QVBoxLayout()
        self.t_hello = label("Chào bạn!", "Title")
        self.t_big = label("—", "Big")
        self.t_info = label("", "Muted", True)
        col.addWidget(self.t_hello)
        col.addWidget(self.t_big)
        col.addWidget(self.t_info)
        top.addLayout(col, 1)
        bl.addLayout(top)
        self.t_bar = TimeBar(20)
        bl.addWidget(self.t_bar)
        bl.addWidget(label("HÔM NAY CỦA MÌNH — xanh là giờ được dùng, xám là giờ nghỉ", "Eyebrow"))
        self.t_line = DayTimeline()
        bl.addWidget(self.t_line)
        grid.addWidget(big, 0, 0, 1, 2)

        st_tile, sl = self._tile("TileMint")
        sl.addWidget(label("📚  HỌC TẬP", "Eyebrow"))
        self.t_study = label("0 phút", "Num")
        self.t_study_bar = RoundBar(("#6EE7B7", "#10B981"))
        sl.addWidget(self.t_study)
        sl.addWidget(self.t_study_bar)
        grid.addWidget(st_tile, 1, 0)
        fun_tile, fl = self._tile("TileSun")
        fl.addWidget(label("🎮  GIẢI TRÍ", "Eyebrow"))
        self.t_fun = label("0 phút", "Num")
        self.t_fun_bar = RoundBar(("#FDE68A", "#FBBF24"))
        fl.addWidget(self.t_fun)
        fl.addWidget(self.t_fun_bar)
        grid.addWidget(fun_tile, 1, 1)

        badge, gl = self._tile("TileGrape")
        row = QHBoxLayout()
        self.t_badge_icon = Mascot("sao", "celebrate", 92)
        row.addWidget(self.t_badge_icon)
        bcol = QVBoxLayout()
        self.t_badge = label("", "Title", True)
        self.t_badge.setStyleSheet("font-size:19px")
        self.t_badge_sub = label("", "Muted", True)
        bcol.addWidget(self.t_badge)
        bcol.addWidget(self.t_badge_sub)
        row.addLayout(bcol, 1)
        self.t_btn = button("🙋 Xin thêm giờ", None, lambda: self.open_request())
        row.addWidget(self.t_btn, 0, Qt.AlignVCenter)
        gl.addLayout(row)
        grid.addWidget(badge, 2, 0, 1, 2)
        lay.addLayout(grid)
        lay.addStretch(1)

    def _today_data(self) -> dict:
        """Số phút theo nhóm hôm nay (get_today) — hỏi agent tối đa mỗi 20 giây, không phải mỗi lần cập nhật."""
        if time.monotonic() - self._today_at > 20:
            r = self.bridge.call("get_today")
            self._today = r.get("today", {}) if r.get("ok") else self._today
            self._today_at = time.monotonic()
        return self._today

    def update_today(self, st: dict):
        prof = st.get("profile", {})
        mode = prof.get("age_mode", "choi")
        call = prof.get("guardian_call", "Ba Mẹ")
        xung = prof.get("self_pronoun", "con")
        self.t_hello.setText(f"Chào {prof.get('nickname', 'bạn')}!")
        rem = st.get("remaining_sec", 0)
        locked = st.get("phase") == "locked"
        self.t_big.setText("Máy đang tạm nghỉ ☾" if locked else f"{V.time_icon(rem)} {V.format_remaining(rem, 'choi')}")
        self.t_big.setStyleSheet(f"font-size:{42 if mode == 'mam' else 36}px")
        self.t_icon.set("tictac", "sleepy" if locked else ("remind" if rem <= 600 else "happy"))
        self.t_bar.set(rem, st.get("quota_min", 60))
        self.t_line.set(st.get("segments"), st.get("now_slot", 0))
        info = [f"Hôm nay {xung} đã dùng {st.get('used_sec', 0) // 60} / {st.get('quota_min', 0)} phút."]
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
        tiles = V.today_tiles(st, self._today_data())
        used = max(1, tiles["used"])
        self.t_study.setText(f"{tiles['study']} phút")
        self.t_study_bar.set(tiles["study"] / used)
        self.t_fun.setText(f"{tiles['fun']} phút")
        self.t_fun_bar.set(tiles["fun"] / used)
        if tiles["on_time"]:
            self.t_badge_icon.set("sao", "celebrate")
            self.t_badge.setText("Huy hiệu “Ngôi Sao Đúng Giờ”!")
            self.t_badge_sub.setText(f"{xung[:1].upper() + xung[1:]} đang dùng máy trong giờ cho phép. Sao Nhỏ tự hào lắm!")
        else:
            self.t_badge_icon.set("sao", "encourage")
            self.t_badge.setText("Huy hiệu đang chờ " + xung)
            self.t_badge_sub.setText(f"Nghỉ ngơi một chút, ngày mai {xung} lấy huy hiệu nhé!")
        self.t_btn.setText("🙋 Xin giờ" if mode == "mam" else f"🙋 Xin {call} thêm giờ")

    # ---- Đã khám phá gì ----
    def _build_explore(self):
        _, lay = self._page()
        card, cl = self._tile("Card")
        self.e_title = label("Hôm nay mình đã khám phá gì", "Title")
        cl.addWidget(self.e_title)
        self.e_total = label("")
        cl.addWidget(self.e_total)
        self.e_bars = CategoryBars()
        cl.addWidget(self.e_bars)
        lay.addWidget(card)
        apps, al = self._tile("TileMint")
        al.addWidget(label("🎒  ỨNG DỤNG", "Eyebrow"))
        self.e_apps = label("", None, True)
        self.e_apps.setTextFormat(Qt.RichText)
        al.addWidget(self.e_apps)
        doms, dl = self._tile("TileSun")
        dl.addWidget(label("🌐  TRANG WEB", "Eyebrow"))
        self.e_doms = label("", None, True)
        self.e_doms.setTextFormat(Qt.RichText)
        dl.addWidget(self.e_doms)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(apps, 1)
        row.addWidget(doms, 1)
        lay.addLayout(row)
        self.e_promise = label("", "Speech", True)
        lay.addWidget(self.e_promise)
        lay.addStretch(1)

    @staticmethod
    def _chips(names: list[str]) -> str:
        if not names:
            return "<span style='color:#64748B'>Chưa có</span>"
        return " ".join(f"<span style='background:#FFFFFF;border-radius:10px'>&nbsp;{n}&nbsp;</span>&nbsp;" for n in names)

    def load_explore(self):
        r = self.bridge.call("get_today")
        d = r.get("today", {}) if r.get("ok") else {}
        prof = self._profile
        xung = prof.get("self_pronoun", "con")
        self.e_title.setText(f"Hôm nay {xung} đã khám phá gì")
        self.e_total.setText(f"Tổng cộng: <b>{d.get('today_minutes', 0)} phút</b>")
        self.e_bars.set(d.get("cats_today") or {})
        self.e_apps.setText(self._chips([app_display(a["name"]) for a in (d.get("top_apps") or [])[:6]]))
        self.e_doms.setText(self._chips([x["name"] for x in (d.get("top_domains") or [])[:6]]))
        self.e_promise.setText(f"👀 {prof.get('guardian_call', 'Ba Mẹ')} cũng thấy đúng những thông tin này, không hơn.")

    # ---- Ai đã đổi gì ----
    def _build_audit(self):
        _, lay = self._page()
        card, cl = self._tile("Card")
        cl.addWidget(label("Ai đã đổi gì", "Title"))
        cl.addWidget(label("Mỗi khi ba mẹ đổi cài đặt, Khiên Xanh ghi lại ở đây để bạn biết.", "Muted", True))
        self.a_list = label("", None, True)
        self.a_list.setTextFormat(Qt.RichText)
        cl.addWidget(self.a_list)
        lay.addWidget(card)
        lay.addStretch(1)

    def load_audit(self):
        r = self.bridge.call("get_audit")
        items = (r.get("audit") or {}).get("items", []) if r.get("ok") else []
        html = "".join(f"<p style='margin:10px 0'><span style='color:#10B981;font-size:18px'>●</span>&nbsp; "
                       f"<b style='color:#4338CA'>{i['when']}</b> — {'; '.join(i['lines'])}</p>" for i in items)
        self.a_list.setText(html or "Chưa có thay đổi nào.")

    # ---- Về OGK ----
    def _build_about(self):
        _, lay = self._page()
        head, hl = self._tile("TileIndigo")
        row = QHBoxLayout()
        row.addWidget(Mascot("khien", "happy", 110))
        row.addWidget(label("Tớ là Khiên Xanh — bạn đồng hành của SafeAnchor. Biểu tượng của tớ luôn ở góc màn hình.", "Title", True), 1)
        hl.addLayout(row)
        lay.addWidget(head)
        yes, yl = self._tile("TileMint")
        yl.addWidget(label("✅  TỚ BIẾT", "Eyebrow"))
        yl.addWidget(label("Tên ứng dụng bạn mở\nTên trang web (không có nội dung)\nThời gian dùng máy", None, True))
        no, nl = self._tile("TileCoral")
        nl.addWidget(label("✖  TỚ KHÔNG", "Eyebrow"))
        nl.addWidget(label("Đọc tin nhắn\nChụp màn hình\nNghe micro, bật camera", None, True))
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(yes, 1)
        row2.addWidget(no, 1)
        lay.addLayout(row2)
        lay.addWidget(label("Ba mẹ và bạn cùng thấy một bảng thông tin. Dữ liệu tự xóa sau 90 ngày.", "Speech", True))
        lay.addStretch(1)


# ======================================================================== onboarding 4 bước
class Onboarding(QDialog):
    def __init__(self, profile: dict):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        self.setObjectName("Dialog")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("Làm quen với SafeAnchor")
        self.resize(620, 400)
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
        lay.setContentsMargins(30, 28, 30, 26)
        card, cl = MainWindow._tile("Card")
        row = QHBoxLayout()
        self.icon = Mascot("tictac", "happy", 160)
        self.text = label("", "Speech", True)
        self.text.setStyleSheet("font-size:19px")
        row.addWidget(self.icon)
        row.addWidget(self.text, 1)
        cl.addLayout(row)
        lay.addWidget(card, 1)
        btns = QHBoxLayout()
        btns.addWidget(button("Bỏ qua", "Ghost", self.accept))
        btns.addStretch(1)
        self.dots = label("", "Muted")
        self.dots.setStyleSheet("font-size:18px;color:#6366F1")
        btns.addWidget(self.dots)
        btns.addStretch(1)
        self.next = button("Tiếp →", None, self._next)
        btns.addWidget(self.next)
        lay.addLayout(btns)
        self._show()

    def _show(self):
        m, mood, t = self.pages[self.i]
        self.icon.set(m, mood)
        self.text.setText(t)
        self.dots.setText(" ".join("●" if k == self.i else "○" for k in range(len(self.pages))))
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
        for text, fn in (("Mở SafeAnchor", self.open_main), ("🙋 Xin thêm giờ", self.open_request),
                         ("🧩 Hôm nay mình đã dùng gì", lambda: self.open_main(1)),
                         ("📜 Ai đã đổi gì", lambda: self.open_main(2))):
            a = QAction(text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        # Không có mục "Thoát": Tray là cam kết minh bạch, luôn hiện (trẻ tắt thì dịch vụ mở lại).
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_main() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("SafeAnchor")
        self.tray.show()
        if show_pill:
            scr = QApplication.primaryScreen().availableGeometry()
            self.pill.move(scr.right() - self.pill.width() - 8, scr.top() + 8)
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
            self.pill.label.setText("🔌 Đang kết nối…")
            self.pill.sub.setText("")
            self.tray.setToolTip("SafeAnchor — đang kết nối dịch vụ")
            return
        self.status = st
        prof = st.get("profile", {})
        self.main._profile = prof
        self.pill.update_status(st)
        self.tray.setToolTip(f"SafeAnchor — {V.format_remaining(st.get('remaining_sec', 0))}")
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
            "requests": [{"id": 1, "status": "pending"}], "lock_until": None}


def demo_call(op: str, **kw) -> dict:
    if op == "get_today":
        return {"ok": True, "today": {"today_minutes": 67, "cats_today": {"education": 35, "games": 22, "entertainment": 10},
                                      "top_apps": [{"name": "scratch 3.exe"}, {"name": "minecraft.exe"}, {"name": "winword.exe"}],
                                      "top_domains": [{"name": "khanacademy.org"}, {"name": "olm.vn"}, {"name": "youtube.com"}]}}
    if op == "get_audit":
        return {"ok": True, "audit": {"items": [{"when": "hôm qua, 20:15", "lines": ["Mẹ đã đổi giờ dùng cuối tuần từ 150 phút thành 120 phút"]},
                                                {"when": "17/11, 08:02", "lines": ["Mẹ đã tạo mã ghép máy tính (ba mẹ đồng ý sử dụng SafeAnchor)"]}]}}
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
    for name, rem in (("pill", 23 * 60), ("pill_low", 8 * 60), ("pill_out", 60)):
        pill.update_status(demo_status(0, remaining=rem))
        pill.grab().save(str(out / f"kids_{name}.png"))
    block = BlockWindow(bridge, lambda: None)
    for name, st, note in (("grace", demo_status(0, "grace", 0), None),
                           ("locked", {**demo_status(0, "locked", 0), "lock_reason": "schedule"}, None),
                           ("break", {**demo_status(0, "locked", 0), "lock_reason": "parent", "lock_until": "16:30"}, None),
                           ("blocked_app", demo_status(0), {"kind": "blocked_app", "app": "game.exe"})):
        block.show_screen(V.block_screen(st, note), DEMO_PROFILE, key=f"app:{name}" if note else name)
        block.grab().save(str(out / f"kids_block_{name}.png"))
    toast = Toast()
    toast.pop(V.toast_text({"kind": "blocked_domain", "domain": "tiktok.com"}, DEMO_PROFILE), "blocked_domain")
    toast.grab().save(str(out / "kids_toast.png"))
    dlg = RequestDialog(bridge, DEMO_PROFILE)
    dlg.adjustSize()
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
        print("Không có khay hệ thống — SafeAnchor không thể hiển thị biểu tượng.")
    _tray = TrayApp(Bridge(data_dir, args.port, demo=args.demo))  # noqa: F841 (giữ tham chiếu)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
