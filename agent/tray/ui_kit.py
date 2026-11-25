"""
agent/tray/ui_kit.py — Khối giao diện VẼ TAY cho Tray (PySide6): bóng mềm nhiều lớp, thẻ bo góc, cửa sổ không
viền hệ điều hành (thanh tiêu đề tích hợp), mục điều hướng có biểu tượng màu, kính mờ cho viên HUD.

Vì sao vẽ tay thay vì QGraphicsDropShadowEffect: hiệu ứng đó lọc lại TOÀN BỘ widget (kể cả mascot 3D đang chạy
bên trong) ở MỖI khung hình. Ở đây bóng được làm mờ MỘT LẦN thành một ảnh nhỏ rồi "cắt 9 mảnh" (nine-slice, như
border-image của CSS) kéo giãn theo cỡ thẻ; trang chứa thẻ vẽ bóng PHÍA SAU thẻ nên bóng loang được ra khe giữa
các thẻ mà thẻ không phải chừa lề.

Kính mờ (HUD): làm mờ phần nền phía sau bằng DWM của Windows (SetWindowCompositionAttribute) — KHÔNG chụp màn
hình, KHÔNG ẩn cửa sổ khỏi ảnh chụp. Tắt "Transparency effects" trong Windows hoặc chạy offscreen => dùng nền trắng
mờ đục (vẫn đẹp, chỉ không nhòe nền).
"""
from __future__ import annotations

import math
import os
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QRegion)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene,
                               QHBoxLayout, QLabel, QVBoxLayout, QWidget)

INK, MUTED = QColor("#1E1B4B"), QColor("#64748B")

# (dịch xuống, độ mờ, độ loang, màu RGBA) — lớp chính đúng theo đặc tả: 0 12px 28px -6px rgba(99,102,241,.10)
CARD_SHADOW = ((12, 28, -6, (99, 102, 241, 26)), (2, 6, 0, (99, 102, 241, 14)))
WINDOW_SHADOW = ((14, 30, -8, (79, 70, 229, 46)), (2, 8, 0, (30, 27, 75, 18)))
SMALL_SHADOW = ((4, 12, -2, (99, 102, 241, 30)), (1, 3, 0, (99, 102, 241, 16)))


def font(px: int, weight=QFont.Bold) -> QFont:
    f = QFont("Nunito")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def rounded(r: QRectF, rad: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, rad, rad)
    return path


# ============================================================================ bóng mềm (nine-slice)
_TILES: dict[tuple, tuple[QPixmap, float]] = {}


def _blur(img: QImage, radius: float) -> QImage:
    """Làm mờ Gauss bằng chính Qt (QGraphicsBlurEffect render ra ảnh) — chạy một lần cho mỗi kiểu bóng."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    box = QRectF(0, 0, img.width(), img.height())
    scene.render(p, box, box)
    p.end()
    return out


def _tile(radius: float, blur: float, rgba: tuple, dpr: float) -> tuple[QPixmap, float]:
    """Ảnh bóng của hình bo góc NHỎ NHẤT còn cắt 9 mảnh được. Trả (ảnh, c) với c = cỡ một góc (đơn vị logic)."""
    rad = max(0, math.ceil(radius))
    key = (rad, round(blur), rgba, round(dpr * 100))
    if key not in _TILES:
        m = math.ceil(blur) + 2                      # phần bóng loang ra ngoài hình
        c = m + rad + 2                              # góc = phần loang + bán kính bo + 2px thân
        size = 2 * c + 2                             # chừa 2px ở giữa để kéo giãn cạnh
        img = QImage(round(size * dpr), round(size * dpr), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(dpr, dpr)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*rgba))
        p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), rad, rad)
        p.end()
        _TILES[key] = (QPixmap.fromImage(_blur(img, blur * dpr)), float(c))
    return _TILES[key]


def _nine(p: QPainter, t: QRectF, pix: QPixmap, c: float, dpr: float) -> None:
    sc = c * dpr                                     # góc trong ảnh nguồn (điểm ảnh thật)
    sw, sh = pix.width(), pix.height()
    c = min(c, t.width() / 2, t.height() / 2)
    xs = (t.left(), t.left() + c, t.right() - c, t.right())
    ys = (t.top(), t.top() + c, t.bottom() - c, t.bottom())
    sx = (0, sc, sw - sc, sw)
    sy = (0, sc, sh - sc, sh)
    for i in range(3):
        for j in range(3):
            tr = QRectF(xs[i], ys[j], xs[i + 1] - xs[i], ys[j + 1] - ys[j])
            if tr.width() > 0 and tr.height() > 0:
                p.drawPixmap(tr, pix, QRectF(sx[i], sy[j], sx[i + 1] - sx[i], sy[j + 1] - sy[j]))


def draw_shadow(p: QPainter, rect: QRectF, radius: float, layers=CARD_SHADOW, dpr: float = 1.0) -> None:
    """Vẽ bóng nhiều lớp cho hình bo góc `rect` (giống box-shadow: dịch, mờ, loang, màu)."""
    for dy, blur, spread, rgba in layers:
        r = QRectF(rect).adjusted(-spread, -spread, spread, spread).translated(0, dy)
        pix, c = _tile(max(0.0, radius + spread), blur, rgba, dpr)
        m = c - math.ceil(max(0.0, radius + spread)) - 2
        _nine(p, r.adjusted(-m, -m, m, m), pix, c, dpr)


def shadow_extent(layers=CARD_SHADOW) -> float:
    return max(dy + blur + spread + 4 for dy, blur, spread, _ in layers)


def paint_card_shadows(host: QWidget, p: QPainter, clip: QRectF | None = None) -> None:
    """Vẽ bóng cho mọi Card hậu duệ GẦN NHẤT của host (thẻ thuộc host con khác do host đó tự vẽ)."""
    dpr = host.devicePixelRatioF()
    for card in host.findChildren(Card):
        if not card.shadow or not card.isVisibleTo(host) or _host_of(card) is not host:
            continue
        r = QRectF(card.rect()).translated(QPointF(card.mapTo(host, card.rect().topLeft())))
        ext = shadow_extent(card.shadow)
        if clip is not None and not r.adjusted(-ext, -ext, ext, ext).intersects(clip):
            continue
        draw_shadow(p, r, card.radius, card.shadow, dpr)


def _host_of(w: QWidget):
    q = w.parentWidget()
    while q is not None and not getattr(q, "is_shadow_host", False):
        q = q.parentWidget()
    return q


class ShadowPage(QWidget):
    """Trang chứa thẻ (đặt trong QScrollArea): vẽ bóng cho các thẻ phía sau chúng."""
    is_shadow_host = True

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        paint_card_shadows(self, p, QRectF(e.rect()))


# ============================================================================ thẻ
class Card(QFrame):
    """Thẻ bo góc: nền trơn hoặc gradient chéo, vầng sáng trang trí (blob) ở góc, viền trắng mảnh 1px."""

    def __init__(self, fill=("#FFFFFF",), radius: float = 24, blob: str | None = None,
                 pad=(22, 18, 22, 18), spacing: int = 10, shadow=CARD_SHADOW):
        super().__init__()
        self.fill, self.radius, self.blob, self.shadow = fill, radius, blob, shadow
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*pad)
        self.lay.setSpacing(spacing)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = rounded(r, self.radius)
        if len(self.fill) == 1:
            p.fillPath(path, QColor(self.fill[0]))
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            for i, c in enumerate(self.fill):
                g.setColorAt(i / (len(self.fill) - 1), QColor(c))
            p.fillPath(path, g)
        if self.blob:
            p.save()
            p.setClipPath(path)
            rr = max(r.height() * 0.9, 120.0)
            for cx, cy, k in ((r.right() - rr * 0.25, r.top() + rr * 0.05, 1.0), (r.left() + rr * 0.1, r.bottom(), 0.6)):
                g = QRadialGradient(QPointF(cx, cy), rr * k)
                col = QColor(self.blob)
                g.setColorAt(0, col)
                col.setAlpha(0)
                g.setColorAt(1, col)
                p.fillRect(r, g)
            p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.drawPath(path)


# ============================================================================ nhãn dán vẽ tay
STICKERS = Path(__file__).resolve().parent / "assets" / "stickers"   # sinh bởi tools/gen_stickers.py


@lru_cache(maxsize=None)
def _sticker(name: str) -> QSvgRenderer:
    return QSvgRenderer(str(STICKERS / f"{name}.svg"))


def paint_sticker(p: QPainter, name: str, r: QRectF, opacity: float = 1.0) -> None:
    """Vẽ nhãn dán (SVG vẽ tay, có viền trắng cắt rời) vừa khít ô vuông lớn nhất nằm giữa r."""
    s = min(r.width(), r.height())
    p.save()
    p.setOpacity(p.opacity() * opacity)
    _sticker(name).render(p, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s))
    p.restore()


def sticker_icon(name: str) -> QIcon:
    """Nhãn dán làm biểu tượng cho nút bấm (QPushButton.setIcon)."""
    return QIcon(str(STICKERS / f"{name}.svg"))


# ---- nét vector tối giản — CHỈ cho nút cửa sổ (thu nhỏ / đóng), không dùng làm hình minh họa
def paint_glyph(p: QPainter, name: str, r: QRectF, color: QColor | str) -> None:
    w = min(r.width(), r.height())
    cx, cy = r.center().x(), r.center().y()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), max(1.6, w * 0.11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if name == "cross":
        p.drawLine(QPointF(cx - w * 0.22, cy - w * 0.22), QPointF(cx + w * 0.22, cy + w * 0.22))
        p.drawLine(QPointF(cx + w * 0.22, cy - w * 0.22), QPointF(cx - w * 0.22, cy + w * 0.22))
    elif name == "min":
        p.drawLine(QPointF(cx - w * 0.26, cy), QPointF(cx + w * 0.26, cy))
    p.restore()


class Sticker(QWidget):
    """Nhãn dán vẽ tay đứng riêng (đầu thẻ, danh sách). Không có ô nền: viền trắng của nhãn đã tách nó khỏi thẻ."""

    def __init__(self, name: str, size: int = 40):
        super().__init__()
        self.name = name
        self.setFixedSize(size, size)

    def set(self, name: str):
        self.name = name
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        paint_sticker(p, self.name, QRectF(self.rect()))


# ============================================================================ điều hướng bên trái
class NavItem(QAbstractButton):
    """Mục điều hướng: nhãn dán vẽ tay + chữ. Đang chọn = viên trắng nổi có bóng mềm + chấm màu."""

    def __init__(self, text: str, sticker: str, accent: str):
        super().__init__()
        self.setText(text)
        self.sticker, self.fg = sticker, accent
        self.compact = False   # cửa sổ hẹp => chỉ còn nhãn dán (chữ chuyển thành tooltip)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedHeight(58)
        self.setAccessibleName(text)
        self._hover = False

    def set_compact(self, on: bool):
        self.compact = on
        self.setToolTip(self.text() if on else "")
        self.setMinimumWidth(64 if on else 214)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(64 if self.compact else 214, 58)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(4, 4, -6, -9)
        on = self.isChecked()
        if on:
            draw_shadow(p, r, 20, SMALL_SHADOW, self.devicePixelRatioF())
            p.fillPath(rounded(r, 20), QColor("#FFFFFF"))
        elif self._hover:
            p.fillPath(rounded(r, 20), QColor(255, 255, 255, 140))
        if self.compact:
            tile = QRectF(r.center().x() - 20, r.center().y() - 20, 40, 40)
            paint_sticker(p, self.sticker, tile, 1.0 if on or self._hover else 0.82)
            if self.hasFocus():
                pen = QPen(QColor("#6366F1"), 2)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(rounded(r.adjusted(-2, -2, 2, 2), 22))
            return
        tile = QRectF(r.left() + 6, r.center().y() - 19, 38, 38)
        paint_sticker(p, self.sticker, tile, 1.0 if on or self._hover else 0.82)
        p.setPen(Qt.NoPen)
        p.setFont(font(15, QFont.Black if on else QFont.ExtraBold))
        p.setPen(INK if on else MUTED)
        p.drawText(QRectF(tile.right() + 12, r.top(), r.right() - tile.right() - 14, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if on:
            p.setBrush(QColor(self.fg))
            p.drawRoundedRect(QRectF(r.right() - 14, r.center().y() - 4, 8, 8), 4, 4)
        if self.hasFocus():
            pen = QPen(QColor("#6366F1"), 2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(rounded(r.adjusted(-2, -2, 2, 2), 22))


# ============================================================================ khung cửa sổ không viền
class WinButton(QAbstractButton):
    """Nút thu nhỏ / đóng tròn mềm trên thanh tiêu đề tích hợp."""

    def __init__(self, glyph: str, tip: str):
        super().__init__()
        self.glyph = glyph
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        close = self.glyph == "cross"
        if self._hover or self.isDown():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFE4E6") if close else QColor("#E0E7FF"))
            p.drawEllipse(r)
        paint_glyph(p, self.glyph, r.adjusted(9, 9, -9, -9),
                    "#E11D48" if close and self._hover else ("#4338CA" if self._hover else "#64748B"))


class TitleBar(QWidget):
    """Thanh tiêu đề tích hợp thay cho thanh đen của Windows: kéo để di chuyển, nháy đúp để phóng to."""

    def __init__(self, shell: QWidget, title: str = "", brand: bool = False, minimize: bool = True, on_close=None):
        super().__init__()
        self.shell = shell
        self.setFixedHeight(54)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 2, 0)
        lay.setSpacing(10)
        self.lead = QHBoxLayout()
        self.lead.setSpacing(10)
        lay.addLayout(self.lead)
        self.title = QLabel(title)
        self.title.setObjectName("Brand" if brand else "WinTitle")
        self.lead.addWidget(self.title)
        self.note = QLabel("")
        self.note.setObjectName("TitleNote")
        lay.addWidget(self.note, 1)
        if minimize:
            self.min_btn = WinButton("min", "Thu nhỏ")
            self.min_btn.clicked.connect(shell.showMinimized)
            lay.addWidget(self.min_btn)
        self.close_btn = WinButton("cross", "Đóng")
        self.close_btn.clicked.connect(on_close or shell.close)
        lay.addWidget(self.close_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if getattr(self.shell, "_resizable", False):
            self.shell.showNormal() if self.shell.isMaximized() else self.shell.showMaximized()


class ShellMixin:
    """Cửa sổ bo góc không viền (đặt TRƯỚC QWidget/QDialog khi kế thừa): nền gradient #F8FAFC -> #F3F0FF,
    viền trắng 1px, bóng tím mềm vẽ trong phần lề trong suốt; kéo mép để đổi cỡ (startSystemResize)."""
    is_shadow_host = True
    MARGIN, RADIUS, GRIP = 18, 28, 7

    def setup_shell(self, title: str = "", brand: bool = False, minimize: bool = True, resizable: bool = True,
                    on_close=None) -> QVBoxLayout:
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setWindowTitle(title or "SafeAnchor")
        self._resizable = resizable
        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(4)
        self.titlebar = TitleBar(self, title, brand, minimize, on_close)
        self._outer.addWidget(self.titlebar)
        body = QVBoxLayout()
        body.setSpacing(12)
        self._outer.addLayout(body, 1)
        self._apply_margins()
        return body

    def _maxed(self) -> bool:
        return bool(self.windowState() & (Qt.WindowMaximized | Qt.WindowFullScreen))

    def _apply_margins(self):
        m = 0 if self._maxed() else self.MARGIN
        self._outer.setContentsMargins(m + 14, m + 4, m + 14, m + 16)

    def frame_rect(self) -> QRectF:
        m = 0 if self._maxed() else self.MARGIN
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        fr = self.frame_rect()
        rad = 0 if self._maxed() else self.RADIUS
        if rad:
            draw_shadow(p, fr, rad, WINDOW_SHADOW, self.devicePixelRatioF())
        path = rounded(fr, rad)
        g = QLinearGradient(fr.topLeft(), fr.bottomRight())
        g.setColorAt(0, QColor("#F8FAFC"))
        g.setColorAt(0.55, QColor("#F4F3FE"))
        g.setColorAt(1, QColor("#F3F0FF"))
        p.fillPath(path, g)
        p.save()
        p.setClipPath(path)
        for cx, cy, rr, col in ((fr.right() - 60, fr.top() + 30, 360, QColor(221, 214, 254, 120)),
                                (fr.left() + 80, fr.bottom() - 20, 300, QColor(209, 250, 229, 90))):
            rg = QRadialGradient(QPointF(cx, cy), rr)
            rg.setColorAt(0, col)
            col.setAlpha(0)
            rg.setColorAt(1, col)
            p.fillRect(fr, rg)
        p.restore()
        if rad:
            p.setPen(QPen(QColor(99, 102, 241, 30), 1))
            p.drawPath(rounded(fr.adjusted(-0.5, -0.5, 0.5, 0.5), rad + 0.5))
            p.setPen(QPen(QColor(255, 255, 255, 235), 1))
            p.drawPath(rounded(fr.adjusted(0.5, 0.5, -0.5, -0.5), rad - 0.5))
        paint_card_shadows(self, p, QRectF(e.rect()))

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self._apply_margins()
            self.update()
        super().changeEvent(e)

    # ---- đổi cỡ bằng mép cửa sổ ----
    def _edges_at(self, pos: QPointF):
        if not self._resizable or self._maxed():
            return None
        fr, g = self.frame_rect(), self.GRIP
        x, y = pos.x(), pos.y()
        edges = None
        for hit, edge in ((abs(x - fr.left()) <= g, Qt.LeftEdge), (abs(x - fr.right()) <= g, Qt.RightEdge),
                          (abs(y - fr.top()) <= g, Qt.TopEdge), (abs(y - fr.bottom()) <= g, Qt.BottomEdge)):
            if hit:
                edges = edge if edges is None else edges | edge
        return edges

    def mouseMoveEvent(self, e):
        edges = self._edges_at(e.position())
        if edges is None:
            self.unsetCursor()
        else:
            L, R, T, B = (bool(edges & k) for k in (Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge))
            self.setCursor(Qt.SizeFDiagCursor if (L and T) or (R and B) else Qt.SizeBDiagCursor if (R and T) or (L and B)
                           else Qt.SizeHorCursor if (L or R) else Qt.SizeVerCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        edges = self._edges_at(e.position()) if e.button() == Qt.LeftButton else None
        if edges is not None and self.windowHandle():
            self.windowHandle().startSystemResize(edges)
            e.accept()
            return
        super().mousePressEvent(e)

    def leaveEvent(self, e):
        self.unsetCursor()
        super().leaveEvent(e)


# ============================================================================ kính mờ (HUD)
def transparency_enabled() -> bool:
    """Windows Settings > Personalization > Colors > Transparency effects (HKCU ...\\Personalize\\EnableTransparency)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


def enable_blur_behind(w: QWidget) -> bool:
    """Bật làm mờ nền phía sau cửa sổ bằng DWM (ACCENT_ENABLE_BLURBEHIND). Chỉ là hiệu ứng hiển thị của chính
    cửa sổ này: không đọc/chụp nội dung màn hình. Trả False nếu không hỗ trợ / bị tắt => nền trắng mờ đục."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return False
    if os.environ.get("OGK_HUD_BLUR", "1") == "0" or not transparency_enabled():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class AccentPolicy(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

        class WinCompAttrData(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

        accent = AccentPolicy(3, 0, 0, 0)                                  # 3 = ACCENT_ENABLE_BLURBEHIND
        data = WinCompAttrData(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))  # 19 = WCA_ACCENT_POLICY
        fn = ctypes.windll.user32.SetWindowCompositionAttribute
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(WinCompAttrData)]
        fn.restype = wintypes.BOOL
        return bool(fn(int(w.winId()), ctypes.byref(data)))
    except Exception:
        return False


def pill_region(r: QRectF, rad: float) -> QRegion:
    """Vùng hình viên thuốc / bo góc cho setMask (giới hạn vùng kính mờ đúng theo hình viên)."""
    x, y, w, h = round(r.left()), round(r.top()), round(r.width()), round(r.height())
    d = min(round(rad * 2), w, h)
    reg = QRegion(x + d // 2, y, w - d, h).united(QRegion(x, y + d // 2, w, h - d))
    for cx, cy in ((x, y), (x + w - d, y), (x, y + h - d), (x + w - d, y + h - d)):
        reg = reg.united(QRegion(cx, cy, d, d, QRegion.Ellipse))
    return reg


class Legend(QWidget):
    """Chú thích nhỏ: nhãn dán (mặt trời / mặt trăng — giống trên thanh lịch) + chữ."""

    def __init__(self, sticker: str, text: str):
        super().__init__()
        self.sticker, self.text = sticker, text
        self.f = font(13, QFont.ExtraBold)
        self.setFixedSize(round(30 + QFontMetricsF(self.f).horizontalAdvance(text) + 4), 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        paint_sticker(p, self.sticker, QRectF(0, 0, 26, 26))
        p.setFont(self.f)
        p.setPen(MUTED)
        p.drawText(QRectF(30, 0, self.width() - 30, 26), Qt.AlignVCenter | Qt.AlignLeft, self.text)


class Medal(QWidget):
    """Huy chương vẽ tay "Ngôi Sao Đúng Giờ": rõ nét khi đạt, mờ nhạt khi đang chờ."""

    def __init__(self, size: int = 66):
        super().__init__()
        self.earned = False
        self.setFixedSize(size, size)

    def set(self, earned: bool):
        self.earned = earned
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        paint_sticker(p, "medal", QRectF(self.rect()), 1.0 if self.earned else 0.35)


class Avatar(QWidget):
    """Ảnh đại diện chữ cái (ứng dụng / trang web / người trong nhật ký) + huy hiệu biểu tượng nhỏ (tùy chọn)."""

    def __init__(self, initial: str, bg: str, fg: str, size: int = 42, badge: str | None = None,
                 round_: bool = False):
        super().__init__()
        self.initial, self.bg, self.fg, self.badge, self.round_ = initial, bg, fg, badge, round_
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        r = QRectF(0, 0, w, w).adjusted(1, 1, -1, -1)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(self.bg).lighter(104))
        g.setColorAt(1, QColor(self.bg).darker(104))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.setBrush(g)
        if self.round_:
            p.drawEllipse(r)
        else:
            p.drawRoundedRect(r, w * 0.3, w * 0.3)
        p.setPen(QColor(self.fg))
        p.setFont(font(round(w * 0.42), QFont.Black))
        p.drawText(r, Qt.AlignCenter, self.initial)
        if self.badge:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            paint_sticker(p, self.badge, QRectF(w * 0.5, w * 0.5, w * 0.56, w * 0.56))


class Bubble(QFrame):
    """Bong bóng hội thoại có đuôi bên trái (nhật ký "Ai đã đổi gì"). Chữ là QLabel PlainText => an toàn."""

    def __init__(self, text: str, fill: str):
        super().__init__()
        self.fill = fill
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 10, 16, 11)
        self.label = QLabel(text)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setWordWrap(True)
        self.label.setObjectName("BubbleText")
        lay.addWidget(self.label)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(7.5, 0.5, -0.5, -0.5)
        path = rounded(r, 18)
        tail = QPainterPath(QPointF(r.left() + 1, 14))
        tail.lineTo(0.5, 20)
        tail.lineTo(r.left() + 1, 26)
        path = path.united(tail)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.setBrush(QColor(self.fill))
        p.drawPath(path)
