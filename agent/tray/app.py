"""
agent/tray/app.py — SafeAnchor cho trẻ: ứng dụng khay hệ thống (PySide6). Chạy với QUYỀN CỦA TRẺ.

Yêu cầu đề: §4.2 Tray UI (thời gian còn lại, lý do bị chặn, gửi yêu cầu), F1 (cảnh báo 10/5/1,
ân hạn 60 giây), F2 (khi chặn: hiện cửa sổ giải thích), F3 ("Hôm nay em đã dùng gì"), NT5 (xem nhật
ký "Ai đã đổi gì"), F5 (không chế độ ẩn: biểu tượng khay LUÔN hiện).

Giao diện "Child App 2026" (trẻ 6–11 tuổi) — "Công cụ đồng hành, không phải phần mềm theo dõi lén":
  - Cửa sổ không viền hệ điều hành, bo góc, nền #F8FAFC -> #F3F0FF, bóng tím mềm nhiều lớp, thanh tiêu đề
    tích hợp (lời chào + nút thu nhỏ/đóng), điều hướng trái dạng viên có biểu tượng màu (ui_kit.py).
  - "Hôm nay" 3 tầng: (1) thẻ thời gian — MỘT thông điệp "còn bao lâu" + Bé Đồng Hồ 3D + thanh đã dùng +
    nút "Xin thêm giờ" và trạng thái yêu cầu; (2) Góc Học Tập / Góc Giải Trí; (3) lịch cả ngày có kim
    "bây giờ" và huy hiệu "Ngôi Sao Đúng Giờ" với Sao Nhỏ đội mũ tốt nghiệp lấp lánh.
  - "Đã khám phá gì": ứng dụng / trang web với biểu tượng lớn + thanh độ dài; "Ai đã đổi gì": dòng trò chuyện.
  - Viên HUD nổi: kính mờ (DWM, không chụp màn hình), rê chuột thì mở rộng để mở nhanh cửa sổ chính.

Tray chỉ HIỂN THỊ và CHUYỂN LỜI: mọi quyết định (đếm giờ, khóa, chặn) nằm ở dịch vụ SYSTEM.
Trẻ tắt Tray => dịch vụ vẫn kiểm soát và tự mở lại Tray (TrayWatchdog).

    python -m agent.tray.app                 # nối với agent đang chạy (Named Pipe / TCP 127.0.0.1)
    python -m agent.tray.app --demo          # chạy thử giao diện với dữ liệu giả, không cần agent
    python -m agent.tray.app --screenshots docs/screenshots   # xuất ảnh từng màn hình
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetricsF, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QBoxLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import messages_vi as M
from . import ui_kit as K
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
#Dialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FAFC, stop:0.5 #EEF2FF, stop:1 #F5F3FF); }
#BlockCard { background: #FFFFFF; border: 1px solid #E9EBF8; border-radius: 32px; }
#ToastBody { background: rgba(255, 255, 255, 238); border: 1px solid rgba(255, 255, 255, 255); border-radius: 26px; }
QLabel { background: transparent; }
QLabel#Title { font-size: 22px; font-weight: 900; }
QLabel#Hero { font-size: 46px; font-weight: 900; }
QLabel#Num { font-size: 34px; font-weight: 900; }
QLabel#CardTitle { font-size: 18px; font-weight: 900; }
QLabel#Muted { color: #64748B; }
QLabel#Ratio { color: #64748B; font-size: 14px; font-weight: 800; }
QLabel#Eyebrow { color: #94A3B8; font-size: 12px; font-weight: 900; }
QLabel#Speech { background: #EEF2FF; border-radius: 22px; padding: 14px 18px; font-size: 16px; font-weight: 700; }
QLabel#Step { background: #F6F7FE; border: 1px solid #E9EBF8; border-radius: 15px; padding: 5px 12px; font-size: 14px; font-weight: 800; }
QLabel#Brand { font-size: 18px; font-weight: 900; }
QLabel#WinTitle { font-size: 16px; font-weight: 900; }
QLabel#TitleNote { color: #64748B; font-size: 14px; font-weight: 800; padding-left: 18px; }
QLabel#NotePill { background: rgba(255, 255, 255, 200); color: #047857; border-radius: 14px; padding: 6px 12px;
                  font-size: 13px; font-weight: 900; }
QLabel#StatusChip { background: #EEF2FF; color: #4338CA; border-radius: 13px; padding: 5px 12px; font-size: 13px; font-weight: 900; }
QLabel#StatusChip[kind="approved"] { background: #D1FAE5; color: #047857; }
QLabel#StatusChip[kind="denied"] { background: #FFF1E6; color: #B45309; }
QLabel#Conn { background: rgba(209, 250, 229, 200); color: #047857; border-radius: 12px; padding: 5px 10px; font-size: 12px; font-weight: 900; }
QLabel#Conn[kind="off"] { background: #FEF3C7; color: #B45309; }
QLabel#Stamp { color: #94A3B8; font-size: 12px; font-weight: 900; }
QLabel#BubbleText { font-size: 15px; font-weight: 700; }
QLabel#Promise { color: #475569; font-size: 12px; font-weight: 800; }
QPushButton { border: none; border-radius: 23px; min-height: 42px; padding: 0 22px; font-size: 15px; font-weight: 900;
              background: #6366F1; color: #FFFFFF; border-bottom: 4px solid #4338CA; }
QPushButton:hover { background: #7578F4; }
QPushButton:pressed { border-bottom: 1px solid #4338CA; margin-top: 3px; }
QPushButton:disabled { background: #C7CBF5; border-bottom-color: #AEB3EE; }
QPushButton#Big { min-height: 56px; border-radius: 30px; padding: 0 30px; font-size: 18px;
                  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8285F8, stop:1 #5D60EC);
                  border-bottom: 5px solid #4338CA; }
QPushButton#Big:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8E91FA, stop:1 #696CF0); }
QPushButton#Big:pressed { border-bottom: 1px solid #4338CA; margin-top: 4px; }
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
QPushButton#HudGhost, QPushButton#HudPrimary { min-height: 32px; border-radius: 17px; padding: 0 14px; font-size: 13px; }
QPushButton#HudGhost { background: rgba(255, 255, 255, 215); color: #4338CA; border: 1px solid rgba(99, 102, 241, 45);
                       border-bottom: 3px solid rgba(99, 102, 241, 70); }
QPushButton#HudGhost:hover { background: #FFFFFF; }
QPushButton#HudGhost:pressed, QPushButton#HudPrimary:pressed { border-bottom-width: 1px; margin-top: 2px; }
QPushButton#HudPrimary { border-bottom: 3px solid #4338CA; }
QPushButton#Choice { background: #FFFFFF; color: #1E1B4B; border: 2px solid #E0E7FF; border-bottom: 4px solid #DADDF2; min-width: 90px; }
QPushButton#Choice:checked { background: #EEF2FF; color: #4338CA; border-color: #6366F1; border-bottom-color: #4338CA; }
QLineEdit { border: 2px solid #E9EBF8; border-radius: 16px; padding: 10px 14px; font-size: 15px; background: #F6F7FE; }
QLineEdit:focus { border-color: #6366F1; background: #FFFFFF; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 6px 2px; }
QScrollBar::handle:vertical { background: rgba(99, 102, 241, 60); border-radius: 3px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(99, 102, 241, 110); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
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
    """Bóng mềm ánh xanh tím cho màn chặn / toast (cửa sổ nổi riêng, không có mascot 3D bên trong)."""
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


def button(text: str, name: str | None = None, slot=None, sticker: str | None = None) -> QPushButton:
    b = QPushButton(f" {text}" if sticker else text)   # khoảng thở giữa nhãn dán và chữ
    if name:
        b.setObjectName(name)
    if sticker:  # nhãn dán vẽ tay đứng trước chữ (thay cho emoji)
        b.setIcon(K.sticker_icon(sticker))
        b.setIconSize(QSize(30, 30) if name == "Big" else QSize(24, 24))
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def set_kind(w: QWidget, kind: str) -> None:
    """Đổi thuộc tính "kind" (màu chip theo trạng thái) và áp lại QSS."""
    if w.property("kind") != kind:
        w.setProperty("kind", kind)
        w.style().unpolish(w)
        w.style().polish(w)


class Mascot(QSvgWidget):
    """Mascot SVG tự CHỚP MẮT: mỗi ~5 giây đổi sang khung *_blink.svg trong 140 ms (Qt không chạy được
    hoạt ảnh CSS bên trong SVG như trình duyệt, nên tạo chuyển động bằng cách luân phiên khung hình)."""

    def __init__(self, kind: str, mood: str, size: int, blink: bool = True):
        super().__init__()
        self.setFixedSize(size, size)
        self.kind, self.mood = kind, mood
        self.sparkle = False
        self.load(str(ASSETS / f"{kind}_{mood}.svg"))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._blink)
        if blink:
            self._timer.start(4200 + random.randint(0, 1800))

    def set(self, kind: str, mood: str) -> None:
        if (kind, mood) != (self.kind, self.mood):
            self.kind, self.mood = kind, mood
            self.load(str(ASSETS / f"{kind}_{mood}.svg"))

    def set_context(self, **_) -> None:
        """Mascot SVG không nói chuyện — giữ cùng API với Mascot3D."""

    def _blink(self) -> None:
        if self.mood in ("happy", "encourage", "remind") and self.isVisible():
            self.load(str(ASSETS / f"{self.kind}_blink.svg"))
            QTimer.singleShot(140, lambda: self.load(str(ASSETS / f"{self.kind}_{self.mood}.svg")))


def mascot(kind: str, mood: str, size: int) -> Mascot:
    return Mascot(kind, mood, size)


def live_mascot(kind: str, mood: str, size: int, hint: bool = False) -> QWidget:
    """Mascot 3D tương tác (ảnh atlas render sẵn từ mô hình three.js — xem agent/tray/mascot3d.py).
    Thiếu / hỏng ảnh atlas => quay về mascot SVG, Tray vẫn chạy bình thường."""
    try:
        from .mascot3d import Mascot3D
        if Mascot3D.available():
            return Mascot3D(kind, mood, size, hint=hint)
    except Exception:
        pass
    return Mascot(kind, mood, size)


def reduced_motion() -> bool:
    try:
        from .mascot3d import animations_enabled
        return not animations_enabled()
    except Exception:
        return False


class TimeBar(QWidget):
    """Thanh thời gian (viên HUD): màu chuyển MƯỢT Mint -> Vàng nắng -> Cam ấm theo phút còn lại
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
        p.setBrush(QColor(99, 102, 241, 28))
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


class UsageBar(QWidget):
    """Thanh viên thuốc LỚN của thẻ thời gian: phần ĐÃ DÙNG tô gradient Mint -> Vàng nắng trải theo cả chiều dài
    thanh (càng gần hạn mức, đầu thanh càng ngả vàng; còn <= 10 phút thì ngả cam ấm). Tỉ lệ chữ ở ngay dưới."""

    def __init__(self, height: int = 24):
        super().__init__()
        self.ratio, self.low = 0.0, False
        self.setFixedHeight(height)

    def set(self, ratio: float, low: bool = False):
        self.ratio, self.low = max(0.0, min(1.0, ratio)), low
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        h, rad = r.height(), r.height() / 2
        track = K.rounded(r, rad)
        p.fillPath(track, QColor("#ECEEFB"))
        inner = QLinearGradient(0, 0, 0, h)                      # bóng trong nhẹ: rãnh lõm xuống
        inner.setColorAt(0, QColor(30, 27, 75, 22))
        inner.setColorAt(0.5, QColor(30, 27, 75, 0))
        p.fillPath(track, inner)
        if self.ratio <= 0:
            return
        fw = max(h, r.width() * self.ratio)
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QColor("#6EE7B7"))
        g.setColorAt(0.55, QColor("#BEF264") if not self.low else QColor("#FCD34D"))
        g.setColorAt(1, QColor("#FCD34D") if not self.low else QColor("#FF9F5A"))
        fill = K.rounded(QRectF(0, 0, fw, h), rad)
        p.fillPath(fill, g)
        p.fillPath(K.rounded(QRectF(rad * 0.6, 3, max(0.0, fw - rad * 1.2), h * 0.3), h * 0.15), QColor(255, 255, 255, 95))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(fw - rad, h / 2), h * 0.22, h * 0.22)


class RoundBar(QWidget):
    """Thanh tiến trình bo tròn một màu (thẻ Góc Giải Trí, danh sách khám phá)."""

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
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawRoundedRect(QRectF(rad / 2, 2, max(0.0, fill.width() - rad), r.height() / 3), rad / 3, rad / 3)


class DayTimeline(QWidget):
    """Lịch cả ngày 0h–24h: khúc xanh bạc hà có mặt trời = giờ được dùng, khúc tím nhạt có mặt trăng = giờ nghỉ
    ngơi, KIM "bây giờ" có nhãn giờ (biết trước, không bất ngờ). Phần đã qua phủ trắng mờ."""
    TOP, BAR = 30, 28

    def __init__(self):
        super().__init__()
        self.segments, self.now_min = [], 0
        self.setMinimumHeight(self.TOP + self.BAR + 26)

    def set(self, segments, now_min: int):
        self.segments, self.now_min = segments or [], now_min
        free = [f"{a // 2:02d}:{(a % 2) * 30:02d}–{b // 2:02d}:{(b % 2) * 30:02d}" for a, b, ok in self.segments if ok]
        self.setAccessibleName(f"Bây giờ {now_min // 60:02d}:{now_min % 60:02d}. Giờ được dùng: {', '.join(free) or 'không có'}")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        track = QRectF(6, self.TOP, w - 12, self.BAR)
        cell = track.width() / 48
        path = K.rounded(track, self.BAR / 2)
        p.fillPath(path, QColor("#EEF0FB"))
        x_now = track.left() + track.width() * self.now_min / 1440
        p.save()
        p.setClipPath(path)
        for a, b, ok in self.segments:
            seg = QRectF(track.left() + a * cell, track.top(), (b - a) * cell, self.BAR)
            g = QLinearGradient(0, seg.top(), 0, seg.bottom())
            g.setColorAt(0, QColor("#86EFAC" if ok else "#E5E9FF"))
            g.setColorAt(1, QColor("#34D399" if ok else "#E3DCFF"))
            p.fillRect(seg, g)
            n = int(seg.width() // 70)
            if seg.width() >= 26:
                for k in range(max(1, n)):
                    cx = seg.left() + seg.width() * (k + 0.5) / max(1, n)
                    K.paint_sticker(p, "sun" if ok else "moon", QRectF(cx - 10, seg.center().y() - 10, 20, 20),
                                    1.0 if ok else 0.75)
            if a > 0:
                p.setPen(QPen(QColor(255, 255, 255, 220), 2))
                p.drawLine(QPointF(seg.left(), seg.top()), QPointF(seg.left(), seg.bottom()))
                p.setPen(Qt.NoPen)
        p.fillRect(QRectF(track.left(), track.top(), x_now - track.left(), self.BAR), QColor(255, 255, 255, 80))
        p.restore()
        f = K.font(12, QFont.ExtraBold)
        fm = QFontMetricsF(f)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        for hh in (0, 6, 12, 18, 24):
            x = track.left() + hh * 2 * cell
            t = f"{hh}h"
            tw = fm.horizontalAdvance(t)
            p.drawText(QRectF(max(0.0, min(w - tw, x - tw / 2)), track.bottom() + 6, tw + 1, 18), Qt.AlignLeft, t)
        # kim "bây giờ"
        ink = QColor("#4F46E5")
        p.setPen(QPen(ink, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x_now, self.TOP - 3), QPointF(x_now, track.bottom() + 4))
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.setBrush(ink)
        p.drawEllipse(QPointF(x_now, track.bottom() + 4), 4.5, 4.5)
        t = f"Bây giờ {self.now_min // 60:02d}:{self.now_min % 60:02d}"
        f = K.font(12, QFont.Black)
        p.setFont(f)
        bw = QFontMetricsF(f).horizontalAdvance(t) + 18
        bx = max(0.0, min(w - bw, x_now - bw / 2))
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(bx, 0, bw, 22), 11, 11)
        p.drawPolygon(QPolygonF([QPointF(x_now - 5, 21), QPointF(x_now + 5, 21), QPointF(x_now, self.TOP - 3)]))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(bx, 0, bw, 22), Qt.AlignCenter, t)


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


class CategoryStack(QWidget):
    """Thanh xếp chồng theo nhóm (Học tập / Trò chơi / ...) + chú thích có số phút bên dưới."""
    BAR = 20

    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, int]] = []
        self.setMinimumHeight(self.BAR + 40)

    def set(self, cats: dict):
        self.items = [(c, int(v)) for c, v in list(cats.items())[:6] if int(v) > 0]
        self.setMinimumHeight(self.BAR + 14 + 28 * max(1, math.ceil(len(self.items) / 3)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        bar = QRectF(0, 0, w, self.BAR)
        path = K.rounded(bar, self.BAR / 2)
        p.fillPath(path, QColor("#EEF0FB"))
        total = sum(v for _, v in self.items)
        f = K.font(13, QFont.ExtraBold)
        p.setFont(f)
        if not total:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, self.BAR + 8, w, 22), Qt.AlignLeft, "Chưa có hoạt động nào hôm nay")
            return
        p.save()
        p.setClipPath(path)
        x = 0.0
        for c, v in self.items:
            sw = w * v / total
            a, b = CAT_COLOR.get(c, ("#A5B4FC", "#6366F1"))
            g = QLinearGradient(0, 0, 0, self.BAR)
            g.setColorAt(0, QColor(a))
            g.setColorAt(1, QColor(b))
            p.fillRect(QRectF(x, 0, sw, self.BAR), g)
            if x > 0:
                p.fillRect(QRectF(x - 1, 0, 2, self.BAR), QColor("#FFFFFF"))
            x += sw
        p.restore()
        col_w = w / 3
        for i, (c, v) in enumerate(self.items):
            cx, cy = (i % 3) * col_w, self.BAR + 12 + (i // 3) * 28
            a, b = CAT_COLOR.get(c, ("#A5B4FC", "#6366F1"))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(b))
            p.drawRoundedRect(QRectF(cx, cy + 5, 12, 12), 4, 4)
            p.setPen(QColor(INK))
            p.drawText(QRectF(cx + 20, cy, col_w - 24, 22), Qt.AlignVCenter | Qt.AlignLeft, f"{CAT_VI.get(c, c)} · {v} phút")


class ExploreRow(QWidget):
    """Một dòng "Đã khám phá gì": biểu tượng chữ cái lớn + tên thân thiện + thanh độ dài + số phút / lượt."""

    def __init__(self, item: dict):
        super().__init__()
        self.item = item
        self.setFixedHeight(58)
        self.setAccessibleName(f"{item['title']}: {item['value']}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        it, w = self.item, self.width()
        bg, fg = it["colors"]
        av = QRectF(0, 7, 44, 44)
        g = QLinearGradient(av.topLeft(), av.bottomRight())
        g.setColorAt(0, QColor(bg).lighter(103))
        g.setColorAt(1, QColor(bg).darker(106))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        p.setBrush(g)
        p.drawRoundedRect(av, 14, 14)
        p.setPen(QColor(fg))
        p.setFont(K.font(19, QFont.Black))
        p.drawText(av, Qt.AlignCenter, it["initial"])
        val_w = 92
        tx, tw = 58, max(40.0, w - 58 - val_w)
        f = K.font(15, QFont.ExtraBold)
        p.setFont(f)
        p.setPen(QColor(INK))
        p.drawText(QRectF(tx, 6, tw, 24), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(f).elidedText(it["title"], Qt.ElideRight, tw))
        bar = QRectF(tx, 35, tw, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRoundedRect(bar, 5, 5)
        fwid = max(10.0, bar.width() * it["ratio"])
        gb = QLinearGradient(tx, 0, tx + fwid, 0)
        gb.setColorAt(0, QColor(fg).lighter(150))
        gb.setColorAt(1, QColor(fg))
        p.setBrush(gb)
        p.drawRoundedRect(QRectF(tx, 35, fwid, 10), 5, 5)
        p.setFont(K.font(13, QFont.Black))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(w - val_w, 0, val_w, 58), Qt.AlignVCenter | Qt.AlignRight, it["value"])


WHO_STYLE = {"guardian": ("#FFE4E6", "#E11D48", "#FFF5F7"), "child": ("#D1FAE5", "#059669", "#F0FDF8"),
             "system": ("#E0E7FF", "#4F46E5", "#F5F7FF")}
KIND_STICKER = {"gift": "gift", "rest": "moon", "time": "clock", "shield": "shield", "edit": "pencil", "ask": "hand"}


class ChatList(QWidget):
    """Nhật ký dạng hội thoại: ảnh đại diện tròn nối với nhau bằng đường chấm (dòng thời gian)."""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 4, 0, 4)
        self.lay.setSpacing(14)

    def set(self, entries: list[dict]):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        if not entries:
            self.lay.addWidget(label("Chưa có thay đổi nào — khi ba mẹ đổi cài đặt, Khiên Xanh sẽ ghi lại ở đây.", "Muted", True))
        for e in entries:
            bg, fg, bubble = WHO_STYLE.get(e["who"], WHO_STYLE["system"])
            row = QHBoxLayout()
            row.setSpacing(12)
            col0 = QVBoxLayout()
            col0.addSpacing(20)
            col0.addWidget(K.Avatar(e["initial"], bg, fg, 42, badge=KIND_STICKER.get(e["kind"]), round_=True))
            col0.addStretch(1)
            row.addLayout(col0)
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(label(e["stamp"], "Stamp"))
            col.addWidget(K.Bubble(e["text"], bubble))
            row.addLayout(col, 1)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.lay.addWidget(holder)
        self.update()

    def paintEvent(self, _):
        avs = [a for a in self.findChildren(K.Avatar) if a.isVisible()]
        if len(avs) < 2:
            return
        pts = sorted((a.mapTo(self, a.rect().center()) for a in avs), key=lambda q: q.y())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#C7D2FE"), 2, Qt.DashLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(pts[0].x(), pts[0].y()), QPointF(pts[-1].x(), pts[-1].y()))


# ======================================================================== viên HUD nổi (kính mờ)
class Pill(QWidget):
    """Viên thời gian nổi ở góc trên màn hình: kính mờ (DWM blur-behind nếu Windows cho phép), viền sáng mảnh;
    rê chuột => viên mở rộng nhẹ, hiện nút "Mở SafeAnchor" và "Xin thêm giờ"; kéo để đổi chỗ; bấm để mở."""
    clicked = Signal()
    request = Signal()
    W, H, PX, TOP = 344, 160, 16, 10
    SMALL, BIG = 76, 128

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self.setWindowTitle("SafeAnchor — thời gian còn lại")
        self.glass, self._glass_tried, self.t = False, False, 0.0
        bw = self.W - 2 * self.PX
        self.icon = Mascot("tictac", "happy", 56)
        self.icon.setParent(self)
        self.icon.move(self.PX + 10, self.TOP + 10)
        info = QWidget(self)
        info.setGeometry(self.PX + 76, self.TOP + 13, bw - 90, 50)
        col = QVBoxLayout(info)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        top = QHBoxLayout()
        self.label = label("Đang kết nối…")
        self.label.setStyleSheet("font-size:20px;font-weight:900")
        self.sub = label("", "Muted")
        self.sub.setStyleSheet("font-size:12px;font-weight:800")
        top.addWidget(self.label)
        top.addStretch(1)
        top.addWidget(self.sub)
        col.addLayout(top)
        self.bar = TimeBar(10)
        col.addWidget(self.bar)
        self.actions = QWidget(self)
        self.actions.setGeometry(self.PX + 14, self.TOP + self.SMALL + 4, bw - 28, 40)
        row = QHBoxLayout(self.actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.open_btn = button("Mở SafeAnchor", "HudGhost", lambda: self.clicked.emit())
        self.req_btn = button("Xin thêm giờ", "HudPrimary", lambda: self.request.emit(), "hand")
        row.addWidget(self.open_btn, 1)
        row.addWidget(self.req_btn, 1)
        self.fade = QGraphicsOpacityEffect(self.actions)
        self.fade.setOpacity(0.0)
        self.actions.setGraphicsEffect(self.fade)
        self.actions.hide()
        self.anim = QVariantAnimation(self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set_t)
        self.collapse_timer = QTimer(self)
        self.collapse_timer.setSingleShot(True)
        self.collapse_timer.timeout.connect(lambda: self._animate(0.0))
        self._drag: QPoint | None = None
        self._moved = False

    # ---- kính mờ + hình viên ----
    def body_rect(self) -> QRectF:
        return QRectF(self.PX, self.TOP, self.W - 2 * self.PX, self.SMALL + (self.BIG - self.SMALL) * self.t)

    def showEvent(self, e):
        if not self._glass_tried:
            self._glass_tried = True
            self.glass = K.enable_blur_behind(self)
        self._sync_mask()
        super().showEvent(e)

    def _sync_mask(self):
        if self.glass:  # vùng kính mờ = đúng hình viên (DWM làm mờ cả khung cửa sổ nếu không giới hạn)
            self.setMask(K.pill_region(self.body_rect(), self.SMALL / 2))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = self.body_rect()
        rad = self.SMALL / 2
        if not self.glass:
            K.draw_shadow(p, r, rad, ((10, 26, -6, (79, 70, 229, 48)), (2, 6, 0, (30, 27, 75, 20))), self.devicePixelRatioF())
        path = K.rounded(r, rad)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        a = (150, 120) if self.glass else (244, 232)
        g.setColorAt(0, QColor(255, 255, 255, a[0]))
        g.setColorAt(1, QColor(245, 243, 255, a[1]))
        p.fillPath(path, g)
        p.setPen(QPen(QColor(99, 102, 241, 34), 1))
        p.drawPath(K.rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), rad - 0.5))
        p.setPen(QPen(QColor(255, 255, 255, 235), 1.2))
        p.drawPath(K.rounded(r.adjusted(1.5, 1.5, -1.5, -1.5), rad - 1.5))

    # ---- rê chuột: mở rộng nhẹ ----
    def _animate(self, target: float):
        self.anim.stop()
        if reduced_motion():
            self._set_t(target)
            return
        self.anim.setDuration(int(240 * abs(target - self.t)) + 1)
        self.anim.setStartValue(self.t)
        self.anim.setEndValue(target)
        self.anim.start()

    def _set_t(self, v):
        self.t = float(v)
        self.actions.setVisible(self.t > 0.35)
        self.fade.setOpacity(max(0.0, min(1.0, (self.t - 0.35) / 0.65)))
        self._sync_mask()
        self.update()

    def expanded(self) -> bool:
        return self.t > 0.99

    def enterEvent(self, e):
        self.collapse_timer.stop()
        self._animate(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.collapse_timer.start(450)
        super().leaveEvent(e)

    # ---- dữ liệu ----
    def update_status(self, st: dict):
        rem = st.get("remaining_sec", 0)
        if st.get("phase") == "locked":
            self.label.setText("Tạm nghỉ")
            self.sub.setText(f"đến {st['lock_until']}" if st.get("lock_until") else "nghỉ chút nhé")
            self.icon.set("tictac", "sleepy")
        else:
            self.label.setText(V.format_remaining(rem, 'mam'))
            self.sub.setText("còn lại")   # đúng cả khi khung giờ (không phải hạn mức) giới hạn
            self.icon.set("tictac", V.time_mood(rem))   # nét mặt Tíc-Tắc báo sắp hết giờ — không chỉ dựa vào màu
        self.bar.set(rem, st.get("quota_min", 60))
        self.setToolTip(f"SafeAnchor — {V.format_remaining(rem)} hôm nay. Bấm để mở.")

    # ---- kéo / bấm ----
    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
            self._moved = True

    def mouseReleaseEvent(self, e):
        if not self._moved and self.body_rect().contains(e.position()):
            self.clicked.emit()
        self._drag = None


# ======================================================================== hộp thoại xin thêm giờ
class RequestDialog(K.ShellMixin, QDialog):
    def __init__(self, bridge: Bridge, profile: dict, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        body = self.setup_shell("Xin thêm giờ", minimize=False, resizable=False, on_close=self.reject)
        self.setMinimumWidth(660)
        self.bridge, self.profile = bridge, profile
        call = profile.get("guardian_call", "Ba Mẹ")
        card = K.Card(pad=(24, 20, 24, 20), spacing=14)
        body.addWidget(card)
        lay = card.lay
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
        lay.addWidget(label("CHỌN NHANH LÝ DO", "Eyebrow"))
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
        self.send = button(f"Gửi {call}", "Big", self._send, "hand")
        btns.addWidget(self.send)
        body.addLayout(btns)

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

    def __init__(self, bridge: Bridge, open_request, open_main=None):
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
        self.ack = button("Nghỉ thôi, lưu bài nào", "Mint", self._ack, "moon")
        self.req = button("Xin thêm giờ", None, lambda: self.open_request(), "hand")
        self.close_btn = button("Mình hiểu rồi", "Ghost", self.hide)
        # Thẻ này chỉ để BÁO (khóa thật là khóa phiên Windows) => trẻ luôn mở được app để xem vì sao, xin giờ.
        self.open_btn = button("Mở SafeAnchor", "Ghost", open_main or (lambda: None))
        self.open_btn.setVisible(open_main is not None)
        btns.addWidget(self.ack)
        btns.addWidget(self.open_btn)
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
        self.req.setText(" Xin giờ" if mam else f" Xin {call} thêm giờ")
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
NAV = (("Hôm nay", "clock", "#F97316"), ("Đã khám phá gì", "explore", "#059669"),
       ("Ai đã đổi gì", "notebook", "#4F46E5"), ("Về SafeAnchor", "shield", "#7C3AED"))


class MainWindow(K.ShellMixin, QWidget):
    def __init__(self, bridge: Bridge, open_request):
        super().__init__(None, Qt.Window)
        body = self.setup_shell("SafeAnchor", brand=True, minimize=True, resizable=True, on_close=self.hide)
        self.setWindowIcon(QIcon(str(ASSETS / "tictac_happy.svg")))
        self.titlebar.lead.insertWidget(0, Mascot("khien", "happy", 34))
        self.titlebar.title.setMinimumWidth(170)
        self.setMinimumSize(720, 560)
        self._nav_compact: bool | None = None
        self._fit_w: int | None = None
        self._flex_rows: list[QBoxLayout] = []   # hàng 2 thẻ cạnh nhau => xếp chồng khi hẹp
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1060, scr.width() - 40), min(800, scr.height() - 30))
        self.bridge, self.open_request = bridge, open_request
        self._profile: dict = {}
        self._today: dict = {}
        self._today_at = 0.0
        root = QHBoxLayout()
        root.setSpacing(14)
        body.addLayout(root, 1)
        nav = QVBoxLayout()
        nav.setSpacing(4)
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        for i, (text, sticker, accent) in enumerate(NAV):
            b = K.NavItem(text, sticker, accent)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            self.nav_group.addButton(b, i)
            nav.addWidget(b)
        nav.addStretch(1)
        promise = K.Card(fill=("#FFFFFF", "#F5F3FF"), radius=20, pad=(12, 12, 14, 12), spacing=8, shadow=K.SMALL_SHADOW)
        pr = QHBoxLayout()
        pr.setSpacing(8)
        pr.addWidget(Mascot("khien", "encourage", 42), 0, Qt.AlignTop)
        pr.addWidget(label("Mọi quy tắc đều công khai. Tớ luôn ở góc màn hình, không có gì bí mật.", "Promise", True), 1)
        promise.lay.addLayout(pr)
        self.conn = label("● Đã kết nối", "Conn")
        promise.lay.addWidget(self.conn, 0, Qt.AlignLeft)
        nav.addWidget(promise)
        nav.addSpacing(4)
        self.promise = promise
        side = QWidget()
        side.setLayout(nav)
        self.side = side
        nav.setContentsMargins(0, 2, 6, 0)
        root.addWidget(side)
        root.addWidget(self.stack, 1)
        self._build_today()
        self._build_explore()
        self._build_audit()
        self._build_about()
        self._set_nav_compact(False)
        self.go(0)

    # ---- co giãn theo cỡ cửa sổ ----
    def _set_nav_compact(self, on: bool):
        if on == self._nav_compact:
            return
        self._nav_compact = on
        for b in self.nav_group.buttons():
            b.set_compact(on)
        self.promise.setVisible(not on)
        self.side.setFixedWidth(84 if on else 224)

    def resizeEvent(self, e):
        self._set_nav_compact(self.width() < 980)
        super().resizeEvent(e)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Resize and isinstance(obj.parent(), QScrollArea):
            self._fit(obj.width())
        return super().eventFilter(obj, e)

    def _fit(self, w: int):
        """Bố cục theo bề rộng THẬT của vùng nội dung (viewport): hẹp => chữ lớn nhỏ lại và xuống dòng,
        nút xin giờ chuyển xuống dưới, các cặp thẻ xếp chồng. Không bao giờ cắt mất nội dung bên phải."""
        if w == self._fit_w or w <= 0:
            return
        self._fit_w = w
        hero_narrow = w < 720
        self.t_big.setStyleSheet("" if w >= 860 else ("font-size:38px" if w >= 720 else "font-size:34px"))
        self.t_icon.setVisible(w >= 470)
        if hero_narrow:
            self.t_grid.addWidget(self.t_right, 1, 1, Qt.AlignLeft)
        else:
            self.t_grid.addWidget(self.t_right, 0, 2)
        if w < 640:
            self.t_head_grid.addWidget(self.t_legends, 1, 0, 1, 2, Qt.AlignLeft)
        else:
            self.t_head_grid.addWidget(self.t_legends, 0, 1, Qt.AlignRight)
        for row in self._flex_rows:  # xếp chồng khi hai thẻ đặt cạnh nhau không còn đủ bề rộng tối thiểu (+ chút thở)
            cards = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]
            need = sum(c.minimumSizeHint().width() for c in cards) + row.spacing() * (len(cards) - 1) + 28 + 8
            row.setDirection(QBoxLayout.TopToBottom if w < max(640, need) else QBoxLayout.LeftToRight)

    def go(self, i: int):
        self.nav_group.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.load_explore()
        elif i == 2:
            self.load_audit()

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = K.ShadowPage()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 4, 18, 20)       # chừa chỗ cho bóng mềm của thẻ
        lay.setSpacing(16)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(page)
        sc.viewport().installEventFilter(self)
        self.stack.addWidget(sc)
        return page, lay

    @staticmethod
    def _head(sticker: str, title: str, name: str = "CardTitle") -> tuple[QHBoxLayout, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(K.Sticker(sticker, 42))
        lb = label(title, name)
        row.addWidget(lb)
        row.addStretch(1)
        return row, lb

    # ---- Hôm nay: 3 tầng ----
    def _build_today(self):
        _, lay = self._page()
        # Tầng 1 — thẻ thời gian: MỘT thông điệp + thanh đã dùng + nút xin giờ
        hero = K.Card(fill=("#FFFFFF", "#F6F4FF", "#EEEBFF"), radius=30, blob="#E0E7FF", pad=(16, 8, 26, 12))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.t_grid = grid
        self.t_icon = live_mascot("tictac", "happy", 138, hint=True)
        grid.addWidget(self.t_icon, 0, 0, 2, 1, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addStretch(1)
        self.t_eyebrow = label("CÒN LẠI HÔM NAY", "Eyebrow")
        self.t_eyebrow.setStyleSheet("color:#6366F1")
        self.t_big = label("—", "Hero", True)   # xuống dòng được khi hẹp (vd "Nghỉ ngơi chút nha")
        col.addWidget(self.t_eyebrow)
        col.addWidget(self.t_big)
        col.addSpacing(6)
        self.t_bar = UsageBar(24)
        col.addWidget(self.t_bar)
        self.t_ratio = label("", "Ratio")
        col.addWidget(self.t_ratio)
        col.addStretch(1)
        colw = QWidget()
        colw.setLayout(col)
        grid.addWidget(colw, 0, 1)
        grid.setColumnStretch(1, 1)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)
        self.t_btn = button("Xin thêm giờ", "Big", lambda: self.open_request(), "hand")
        self.t_btn.setMinimumWidth(212)
        right.addWidget(self.t_btn, 0, Qt.AlignHCenter)
        self.t_req = label("", "StatusChip")
        self.t_req.setAlignment(Qt.AlignCenter)
        self.t_req.hide()
        right.addWidget(self.t_req, 0, Qt.AlignHCenter)
        right.addStretch(1)
        self.t_right = QWidget()
        self.t_right.setLayout(right)
        grid.addWidget(self.t_right, 0, 2)
        hero.lay.addLayout(grid)
        lay.addWidget(hero)

        # Tầng 2 — hai thẻ Bento cân nhau
        row2 = QHBoxLayout()
        row2.setSpacing(18)
        study = K.Card(fill=("#F3FDF8", "#DDF7EB"), blob="#C9F2DF", pad=(22, 14, 22, 14), spacing=6)
        h, _ = self._head("book", "Góc Học Tập")
        study.lay.addLayout(h)
        self.t_study = label("0 phút", "Num")
        study.lay.addWidget(self.t_study)
        self.t_study_note = label("", "NotePill")
        study.lay.addWidget(self.t_study_note, 0, Qt.AlignLeft)
        study.lay.addStretch(1)
        fun = K.Card(fill=("#FFFAEB", "#FFE9D3"), blob="#FFE0BD", pad=(22, 14, 22, 14), spacing=6)
        h, _ = self._head("game", "Góc Giải Trí")
        fun.lay.addLayout(h)
        self.t_fun = label("0 phút", "Num")
        fun.lay.addWidget(self.t_fun)
        self.t_fun_bar = RoundBar(("#FDE68A", "#FF9F5A"), 14)
        fun.lay.addWidget(self.t_fun_bar)
        self.t_fun_note = label("", "Ratio", True)
        self.t_fun_note.setStyleSheet("color:#B45309")
        fun.lay.addWidget(self.t_fun_note)
        fun.lay.addStretch(1)
        row2.addWidget(study, 1)
        row2.addWidget(fun, 1)
        lay.addLayout(row2)
        self._flex_rows.append(row2)

        # Tầng 3 — lịch cả ngày, bên dưới là huy hiệu
        tl = K.Card(pad=(22, 14, 22, 8), spacing=4)
        h, _ = self._head("calendar", "Lịch của mình hôm nay")
        self.t_legends = QWidget()
        lg = QHBoxLayout(self.t_legends)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.setSpacing(12)
        lg.addWidget(K.Legend("sun", "Giờ được dùng"))
        lg.addWidget(K.Legend("moon", "Giờ nghỉ ngơi"))
        self.t_head_grid = QGridLayout()   # chú thích nằm bên phải tiêu đề; hẹp => xuống dòng dưới
        self.t_head_grid.setContentsMargins(0, 0, 0, 0)
        self.t_head_grid.setVerticalSpacing(4)
        self.t_head_grid.addLayout(h, 0, 0)
        self.t_head_grid.addWidget(self.t_legends, 0, 1, Qt.AlignRight)
        self.t_head_grid.setColumnStretch(0, 1)
        tl.lay.addLayout(self.t_head_grid)
        self.t_line = DayTimeline()
        tl.lay.addWidget(self.t_line)
        lay.addWidget(tl)

        ach = K.Card(fill=("#F8F6FF", "#EDE8FF"), blob="#E2DAFF", pad=(12, 4, 24, 4))
        row3 = QHBoxLayout()
        row3.setSpacing(14)
        self.t_badge_icon = live_mascot("sao", "celebrate", 104)
        self.t_badge_icon.sparkle = True
        row3.addWidget(self.t_badge_icon, 0, Qt.AlignVCenter)
        bcol = QVBoxLayout()
        bcol.setSpacing(4)
        bcol.addStretch(1)
        self.t_badge_eyebrow = label("HUY HIỆU HÔM NAY", "Eyebrow")
        self.t_badge_eyebrow.setStyleSheet("color:#7C3AED")
        self.t_badge = label("Ngôi Sao Đúng Giờ", "Title")
        self.t_badge_sub = label("", "Muted", True)
        bcol.addWidget(self.t_badge_eyebrow)
        bcol.addWidget(self.t_badge)
        bcol.addWidget(self.t_badge_sub)
        bcol.addStretch(1)
        row3.addLayout(bcol, 1)
        self.t_medal = K.Medal(72)
        row3.addWidget(self.t_medal, 0, Qt.AlignVCenter)
        ach.lay.addLayout(row3)
        lay.addWidget(ach)
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
        xung = prof.get("self_pronoun", "con")
        self.titlebar.note.setText(V.greeting(prof))
        online = st.get("online", True)
        self.conn.setText("● Đã kết nối" if online else "Mất mạng · vẫn chạy bình thường")
        set_kind(self.conn, "on" if online else "off")
        h = V.hero_time(st)
        rem = st.get("remaining_sec", 0)
        phase = st.get("phase")
        self.t_eyebrow.setText(h["eyebrow"])
        self.t_big.setText(h["big"])
        self.t_icon.set("tictac", "sleepy" if h["locked"] else ("remind" if h["low"] else "happy"))
        self.t_bar.set(h["ratio"], h["low"])
        self.t_ratio.setText(h["ratio_text"])
        rs = V.request_status(st, prof)
        self.t_req.setVisible(rs is not None)
        if rs:
            set_kind(self.t_req, rs[0])
            self.t_req.setText(rs[1])
        tiles = V.today_tiles(st, self._today_data())
        self.t_study.setText(f"{tiles['study']} phút")
        self.t_study_note.setText(V.study_note(tiles["study"]))
        f = V.fun_card(st, self._today)
        self.t_fun.setText(f["big"])
        self.t_fun_bar.setVisible(f["ratio"] is not None)
        self.t_fun_bar.set(f["ratio"] or 0)
        self.t_fun_note.setText(f["note"])
        self.t_line.set(st.get("segments"), V.now_minute(st))
        # lời thoại khi trẻ chạm vào mascot: dùng đúng số liệu đang hiện trên màn hình
        self.t_icon.set_context(profile=prof, remaining_sec=rem, phase=phase, study_min=tiles["study"])
        self.t_badge_icon.set_context(profile=prof, study_min=tiles["study"])
        self.about_khien.set_context(profile=prof)
        self.t_medal.set(tiles["on_time"])
        if tiles["on_time"]:
            self.t_badge_icon.set("sao", "celebrate")
            self.t_badge_sub.setText(f"{V._cap(xung)} đang dùng máy trong giờ cho phép. Sao Nhỏ tự hào lắm!")
        else:
            self.t_badge_icon.set("sao", "encourage")
            self.t_badge_sub.setText(f"Nghỉ ngơi một chút, ngày mai {xung} lấy huy hiệu nhé!")

    # ---- Đã khám phá gì ----
    def _build_explore(self):
        _, lay = self._page()
        head = K.Card(pad=(22, 18, 22, 18), spacing=12)
        h, self.e_title = self._head("explore", "Hôm nay mình đã khám phá gì")
        self.e_total = label("", "Ratio")
        h.addWidget(self.e_total)
        head.lay.addLayout(h)
        self.e_bars = CategoryStack()
        head.lay.addWidget(self.e_bars)
        lay.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(18)
        apps = K.Card(fill=("#F3FDF8", "#E3F8EE"), spacing=4)
        h, _ = self._head("puzzle", "Ứng dụng hay dùng")
        h.addWidget(label("7 ngày qua", "Stamp"))
        apps.lay.addLayout(h)
        self.e_apps = QVBoxLayout()
        self.e_apps.setSpacing(2)
        apps.lay.addLayout(self.e_apps)
        apps.lay.addStretch(1)
        doms = K.Card(fill=("#FFFBF0", "#FFF0DC"), spacing=4)
        h, _ = self._head("globe", "Trang web hay ghé")
        h.addWidget(label("7 ngày qua", "Stamp"))
        doms.lay.addLayout(h)
        self.e_doms = QVBoxLayout()
        self.e_doms.setSpacing(2)
        doms.lay.addLayout(self.e_doms)
        doms.lay.addStretch(1)
        row.addWidget(apps, 1)
        row.addWidget(doms, 1)
        lay.addLayout(row)
        self._flex_rows.append(row)
        promise = K.Card(fill=("#F5F7FF", "#EEF2FF"), pad=(16, 12, 22, 12))
        pr = QHBoxLayout()
        pr.addWidget(Mascot("khien", "happy", 54))
        self.e_promise = label("", None, True)
        self.e_promise.setStyleSheet("font-size:15px;font-weight:800")
        pr.addWidget(self.e_promise, 1)
        promise.lay.addLayout(pr)
        lay.addWidget(promise)
        lay.addStretch(1)

    @staticmethod
    def _fill(box: QVBoxLayout, items: list[dict], empty: str):
        while box.count():
            it = box.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        for item in items:
            box.addWidget(ExploreRow(item))
        if not items:
            box.addWidget(label(empty, "Muted", True))

    def load_explore(self):
        r = self.bridge.call("get_today")
        d = r.get("today", {}) if r.get("ok") else {}
        prof = self._profile
        xung = prof.get("self_pronoun", "con")
        self.e_title.setText(f"Hôm nay {xung} đã khám phá gì")
        self.e_total.setText(f"Hôm nay: {d.get('today_minutes', 0)} phút")
        self.e_bars.set(d.get("cats_today") or {})
        rows = V.explore_rows(d)
        self._fill(self.e_apps, rows["apps"], "Chưa có ứng dụng nào.")
        self._fill(self.e_doms, rows["domains"], "Chưa ghé trang web nào.")
        self.e_promise.setText(f"{prof.get('guardian_call', 'Ba Mẹ')} cũng thấy đúng những thông tin này, không hơn. "
                               "Khiên Xanh không đọc tin nhắn, không chụp màn hình.")

    # ---- Ai đã đổi gì ----
    def _build_audit(self):
        _, lay = self._page()
        head = K.Card(fill=("#F5F7FF", "#ECEFFF"), blob="#DFE4FF", pad=(16, 12, 22, 12))
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Mascot("khien", "happy", 76))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch(1)
        col.addWidget(label("Ai đã đổi gì", "Title"))
        self.a_sub = label("Mỗi khi ba mẹ đổi cài đặt, Khiên Xanh ghi lại ở đây để bạn biết.", "Muted", True)
        col.addWidget(self.a_sub)
        col.addStretch(1)
        row.addLayout(col, 1)
        head.lay.addLayout(row)
        lay.addWidget(head)
        chat = K.Card(pad=(22, 18, 22, 18))
        self.a_list = ChatList()
        chat.lay.addWidget(self.a_list)
        lay.addWidget(chat)
        lay.addStretch(1)

    def load_audit(self):
        r = self.bridge.call("get_audit")
        items = (r.get("audit") or {}).get("items", []) if r.get("ok") else []
        prof = self._profile
        self.a_sub.setText(f"Mỗi khi {prof.get('guardian_call', 'ba mẹ')} đổi cài đặt, Khiên Xanh ghi lại ở đây "
                           f"để {prof.get('self_pronoun', 'bạn')} biết.")
        self.a_list.set(V.audit_chat(items, prof))

    # ---- Về SafeAnchor ----
    def _build_about(self):
        _, lay = self._page()
        head = K.Card(fill=("#FFFFFF", "#F1EEFF"), blob="#E0E7FF", pad=(16, 12, 24, 12))
        row = QHBoxLayout()
        self.about_khien = live_mascot("khien", "happy", 130)
        row.addWidget(self.about_khien)
        row.addWidget(label("Tớ là Khiên Xanh — bạn đồng hành của SafeAnchor. Biểu tượng của tớ luôn ở góc màn hình.",
                            "Title", True), 1)
        head.lay.addLayout(row)
        lay.addWidget(head)
        row2 = QHBoxLayout()
        row2.setSpacing(18)
        for title, sticker, fill, items in (
                ("Tớ biết", "check", ("#F3FDF8", "#DDF7EB"),
                 ("Tên ứng dụng bạn mở", "Tên trang web (không có nội dung)", "Thời gian dùng máy")),
                ("Tớ không", "cross", ("#FFF6F2", "#FFE6DC"),
                 ("Đọc tin nhắn", "Chụp màn hình", "Nghe micro, bật camera"))):
            c = K.Card(fill=fill, spacing=10)
            h, _ = self._head(sticker, title)
            c.lay.addLayout(h)
            for it in items:
                r = QHBoxLayout()
                r.setSpacing(10)
                r.addWidget(K.Sticker(sticker, 28))
                r.addWidget(label(it, None, True), 1)
                c.lay.addLayout(r)
            c.lay.addStretch(1)
            row2.addWidget(c, 1)
        lay.addLayout(row2)
        self._flex_rows.append(row2)
        foot = K.Card(fill=("#F5F7FF", "#EEF2FF"), pad=(22, 14, 22, 14))
        foot.lay.addWidget(label("Ba mẹ và bạn cùng thấy một bảng thông tin. Dữ liệu tự xóa sau 90 ngày.", None, True))
        lay.addWidget(foot)
        lay.addStretch(1)


# ======================================================================== onboarding 4 bước
class Onboarding(K.ShellMixin, QDialog):
    def __init__(self, profile: dict):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        body = self.setup_shell("Làm quen với SafeAnchor", minimize=False, resizable=False, on_close=self.accept)
        self.resize(700, 470)
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
        card = K.Card(fill=("#FFFFFF", "#F6F4FF"), radius=28, blob="#E0E7FF", pad=(20, 18, 26, 18))
        row = QHBoxLayout()
        self.icon = live_mascot("tictac", "happy", 176)
        self.icon.set_context(profile=profile)
        self.text = label("", "Speech", True)
        self.text.setStyleSheet("font-size:19px")
        row.addWidget(self.icon)
        row.addWidget(self.text, 1, Qt.AlignVCenter)   # bong bóng thoại ôm vừa chữ, không kéo hết chiều cao
        card.lay.addLayout(row)
        body.addWidget(card, 1)
        btns = QHBoxLayout()
        btns.addWidget(button("Bỏ qua", "Ghost", self.accept))
        btns.addStretch(1)
        self.dots = label("", "Muted")
        self.dots.setStyleSheet("font-size:18px;color:#6366F1")
        btns.addWidget(self.dots)
        btns.addStretch(1)
        self.next = button("Tiếp →", None, self._next)
        self.next.setDefault(True)        # Enter = "Tiếp" (mascot chỉ nhận Space/Enter khi được Tab tới)
        btns.addWidget(self.next)
        body.addLayout(btns)
        self._show()
        self.next.setFocus()

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
        self.pill.request.connect(self.open_request)
        self.block = BlockWindow(bridge, self.open_request, lambda: self.open_main())
        self.toast = Toast()
        self.tray = QSystemTrayIcon(QIcon(str(ASSETS / "tictac_happy.svg")))
        menu = QMenu()
        for text, fn in (("Mở SafeAnchor", self.open_main), ("Xin thêm giờ", self.open_request),
                         ("Hôm nay mình đã dùng gì", lambda: self.open_main(1)),
                         ("Ai đã đổi gì", lambda: self.open_main(2))):
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
            self.pill.move(scr.right() - self.pill.width() + 4, scr.top() + 2)
            self.pill.show()
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)
        self.idle_timer = QTimer()
        self.idle_timer.timeout.connect(self.report_idle)
        self.idle_timer.start(15000)
        self.onboarded = False
        self.poll()

    def _main_up(self) -> bool:
        return self.main.isVisible() and not self.main.isMinimized()

    def open_main(self, tab: int = 0):
        # Thẻ "Máy đang tạm nghỉ" luôn-ở-trên => nhường chỗ khi trẻ mở app (app cũng báo đúng trạng thái + nút
        # xin giờ). Đóng / thu nhỏ app => lần cập nhật kế tiếp thẻ hiện lại nếu máy vẫn đang nghỉ.
        if self.block.isVisible() and not (self.block.current_key or "").startswith("app:"):
            self.block.hide()
        self.main._profile = self.status.get("profile", {})
        self.main.go(tab if isinstance(tab, int) else 0)
        self.main.showNormal() if self.main.isMinimized() else self.main.show()
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
            self.pill.label.setText("Đang kết nối…")
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
        if screen is not None and self._main_up():
            if self.block.isVisible() and not (self.block.current_key or "").startswith("app:"):
                self.block.hide()
        elif screen is not None:
            self.block.show_screen(screen, prof, key=f"{st.get('phase')}:{st.get('lock_reason')}")
        elif app_note is not None:
            self.block.show_screen(V.block_screen(st, app_note), prof, key=f"app:{app_note.get('app')}")
        elif self.block.isVisible() and not (self.block.current_key or "").startswith("app:"):
            self.block.hide()
            self.block.ack.setEnabled(True)


# ======================================================================== dữ liệu giả (demo/ảnh chụp)
DEMO_PROFILE = {"nickname": "Bin", "self_pronoun": "con", "guardian_call": "Mẹ", "age_mode": "mam"}


def demo_status(t0: float, phase: str = "active", remaining: int = 100 * 60, request: str = "approved") -> dict:
    """Số liệu giả NHẤT QUÁN: hạn mức 120 phút, đã dùng 20 (16 học + 4 giải trí) => còn 100 phút."""
    from agent import schedule as sch
    from datetime import datetime
    now = datetime.now()
    s = sch.make_schedule({d: [("06:00", "07:00"), ("16:00", "21:00")] for d in range(7)})
    return {"phase": phase, "lock_reason": "quota" if phase != "active" else None, "remaining_sec": remaining,
            "used_sec": 20 * 60, "quota_min": 120, "grace_left": 42, "now_slot": now.hour * 2 + now.minute // 30,
            "now_min": now.hour * 60 + now.minute,
            "segments": sch.day_segments(s, now), "next_allowed": "16:00", "profile": DEMO_PROFILE,
            "budgets": {"games": {"used_min": 0, "limit_min": 45}}, "online": True, "notifications": [],
            "requests": [{"id": 1, "status": request}] if request else [], "lock_until": None}


def demo_call(op: str, **kw) -> dict:
    if op == "get_today":
        return {"ok": True, "today": {
            "today_minutes": 20, "cats_today": {"education": 16, "entertainment": 4},
            "top_apps": [{"name": "scratch 3.exe", "display": "Scratch 3", "minutes": 95},
                         {"name": "minecraft.windows.exe", "display": "Minecraft Education", "minutes": 64},
                         {"name": "winword.exe", "display": "Microsoft Word", "minutes": 38},
                         {"name": "geogebra.exe", "display": "GeoGebra", "minutes": 22},
                         {"name": "mspaint.exe", "display": "Paint", "minutes": 9}],
            "top_domains": [{"name": "khanacademy.org", "count": 14}, {"name": "olm.vn", "count": 11},
                            {"name": "vi.wikipedia.org", "count": 7}, {"name": "thieunien.vn", "count": 5},
                            {"name": "example.edu", "count": 2}]}}
    if op == "get_audit":
        return {"ok": True, "audit": {"items": [
            {"when": "hôm nay, 19:50", "lines": ["Mẹ đã đồng ý cho thêm 15 phút"]},
            {"when": "hôm nay, 19:46", "lines": ["Con đã xin thêm 15 phút"]},
            {"when": "hôm qua, 20:15", "lines": ["Mẹ đã đổi giờ dùng cuối tuần từ 150 phút thành 120 phút"]},
            {"when": "17/11, 08:02", "lines": ["Mẹ đã tạo mã ghép máy tính (ba mẹ đồng ý sử dụng SafeAnchor)"]}]}}
    if op == "request_more_time":
        return {"ok": True, "sent": True, "request_id": 1}
    return {"ok": True}


def load_fonts() -> None:
    """Nunito đóng gói cục bộ (OFL) — hỗ trợ đủ tiếng Việt, không phụ thuộc mạng. Qt cần TTF (không đọc WOFF2).
    (Fredoka không có bộ dấu tiếng Việt => chữ có dấu sẽ lẫn phông khác, nên toàn bộ dùng Nunito.)"""
    QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / "Nunito.ttf"))


def _settle(ms: int = 120) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def screenshots(out: Path) -> None:
    """Xuất ảnh từng màn hình (dùng cho báo cáo / UX_TEST). Cửa sổ được hiện NGOÀI vùng nhìn thấy (-4000, -4000)
    để bố cục và phông chữ thật được áp dụng mà không che màn hình người đang dùng máy."""
    out.mkdir(parents=True, exist_ok=True)
    off = QPoint(-4000, -4000)
    bridge = Bridge(None, 0, demo=True)
    main = MainWindow(bridge, lambda: None)
    main.resize(1060, 800)
    main.move(off)
    main.show()
    main._profile = DEMO_PROFILE
    main.update_today(demo_status(0))
    for i, name in enumerate(["today", "explore", "audit", "about"]):
        main.go(i)
        _settle(250)
        main.grab().save(str(out / f"kids_{name}.png"))
    main.hide()
    pill = Pill()
    pill.move(off)
    pill.show()
    for name, rem, t in (("pill", 100 * 60, 0.0), ("pill_low", 8 * 60, 0.0), ("pill_out", 60, 0.0), ("pill_hover", 100 * 60, 1.0)):
        pill.update_status(demo_status(0, remaining=rem))
        pill._set_t(t)
        _settle(60)
        pill.grab().save(str(out / f"kids_{name}.png"))
    pill.hide()
    block = BlockWindow(bridge, lambda: None, lambda: None)
    block.move(off)
    for name, st, note in (("grace", demo_status(0, "grace", 0), None),
                           ("locked", {**demo_status(0, "locked", 0), "lock_reason": "schedule"}, None),
                           ("break", {**demo_status(0, "locked", 0), "lock_reason": "parent", "lock_until": "16:30"}, None),
                           ("blocked_app", demo_status(0), {"kind": "blocked_app", "app": "game.exe"})):
        block.show_screen(V.block_screen(st, note), DEMO_PROFILE, key=f"app:{name}" if note else name)
        block.move(off)
        _settle(60)
        block.grab().save(str(out / f"kids_block_{name}.png"))
    block.hide()
    toast = Toast()
    toast.pop(V.toast_text({"kind": "blocked_domain", "domain": "adult-sim-01.test-block.example"}, DEMO_PROFILE), "blocked_domain")
    toast.move(off)
    _settle(60)
    toast.grab().save(str(out / "kids_toast.png"))
    toast.hide()
    dlg = RequestDialog(bridge, DEMO_PROFILE)
    dlg.adjustSize()
    dlg.move(off)
    dlg.show()
    _settle(120)
    dlg.grab().save(str(out / "kids_request.png"))
    dlg.hide()
    ob = Onboarding(DEMO_PROFILE)
    ob.move(off)
    ob.show()
    _settle(250)
    ob.grab().save(str(out / "kids_onboarding.png"))
    ob.hide()
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
