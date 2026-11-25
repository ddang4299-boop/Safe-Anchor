"""
agent/tray/mascot3d.py — Mascot "3D" tương tác cho Tray (PySide6).

PySide6 không có WebGL / Qt Quick 3D / trình duyệt nhúng, nên Tray KHÔNG dựng hình 3D lúc chạy. Thay vào đó
tools/render_mascot_sprites.py chụp sẵn ĐÚNG mô hình three.js của trang web thành ảnh "atlas": 24 góc xoay
(15°/khung) + 5 nét mặt nhìn thẳng. Widget này phát lại atlas và tự thêm phần "sống":
  - kéo ngang để xoay 360° (có quán tính, thả tay thì tự quay về), rê chuột thì mascot quay nhẹ theo;
  - chạm: nhún co giãn rồi nhảy (lò xo giống bản web), cười tít, bắn sao; Tíc-Tắc rung "reng reng",
    Khiên Xanh xoay một vòng, Sao Nhỏ nhảy hai nhịp; kéo qua lại = cù => đỏ mặt + tim bay;
    chạm 5 lần liền => nhảy múa + pháo giấy;
  - bong bóng thoại dùng số liệu thật của trẻ (view_logic.mascot_lines), thở, chớp mắt, buồn ngủ thì "z z".
Bàn phím: Tab tới mascot, Space/Enter = chạm. Tôn trọng cài đặt Windows "Hiện hiệu ứng động": tắt thì không
nhảy/xoay/lắc, chỉ đổi nét mặt + bong bóng thoại. Thiếu ảnh atlas => app.py tự dùng lại mascot SVG.
Đồng hồ chỉ chạy khi widget đang hiện (ẩn cửa sổ/đổi trang => dừng, không tốn CPU).
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import view_logic as V

ATLAS_DIR = Path(__file__).resolve().parent / "assets" / "3d"
KINDS = ("tictac", "khien", "sao")
TAU = math.pi * 2
INK = QColor("#1E1B4B")
CONFETTI = ("#6366F1", "#10B981", "#FBBF24", "#FF8E53", "#C9B8FF", "#3B7FF2", "#FF7FA6")


def animations_enabled() -> bool:
    """Cài đặt Windows "Hiện hiệu ứng động" (Settings > Accessibility > Visual effects) — SPI_GETCLIENTAREAANIMATION."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        v = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(v), 0):
            return bool(v.value)
    except Exception:
        pass
    return True


class Atlas:
    """Các khung ảnh của một nhân vật (đọc một lần, dùng chung cho mọi widget; thu nhỏ sẵn theo cỡ hiển thị)."""
    _cache: dict[str, "Atlas | None"] = {}

    def __init__(self, kind: str):
        meta = json.loads((ATLAS_DIR / f"{kind}.json").read_text(encoding="utf-8"))
        img = QImage(str(ATLAS_DIR / f"{kind}.webp"))
        cell, cols, yaws = int(meta["cell"]), int(meta["cols"]), int(meta["yaw_frames"])
        n = yaws + len(meta["exprs"])
        if img.isNull() or img.width() < cell * cols or img.height() < cell * math.ceil(n / cols):
            raise ValueError(f"atlas {kind} hỏng hoặc thiếu")
        self.frames = [img.copy((i % cols) * cell, (i // cols) * cell, cell, cell) for i in range(n)]
        self.yaws = yaws
        self.exprs = {k: int(v) for k, v in meta["exprs"].items()}
        self.feet, self.head = float(meta["feet"]), float(meta["head"])
        self._scaled: dict[int, list[QPixmap]] = {}

    @classmethod
    def get(cls, kind: str) -> "Atlas | None":
        if kind not in cls._cache:
            try:
                cls._cache[kind] = Atlas(kind)
            except Exception:
                cls._cache[kind] = None
        return cls._cache[kind]

    def pixmaps(self, px: int) -> list[QPixmap]:
        if px not in self._scaled:
            if len(self._scaled) >= 4:
                self._scaled.clear()
            self._scaled[px] = [QPixmap.fromImage(f.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)) for f in self.frames]
        return self._scaled[px]

    def frame_index(self, yaw: float, expr: str) -> int:
        i = round((yaw % TAU) / (TAU / self.yaws)) % self.yaws
        return self.exprs.get(expr, 0) if i == 0 and expr != "happy" else i


# ------------------------------------------------------------------ bong bóng thoại
class SpeechBubble(QWidget):
    """Bong bóng thoại vẽ đè lên cửa sổ chứa mascot (con của cửa sổ đó => không cần cửa sổ nổi riêng,
    không cướp focus). Chữ vẽ bằng QPainter (không phải rich text) => tên trẻ không thể chèn HTML."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text, self.tail, self.tail_at = "", "down", 0.0
        self.font = QFont("Nunito")
        self.font.setPixelSize(14)
        self.font.setWeight(QFont.ExtraBold)
        self.hide()

    def show_text(self, text: str, anchor: QPointF, host: QRectF):
        """anchor: đỉnh đầu mascot; host: khung mascot — cả hai theo tọa độ cửa sổ."""
        self.text = text
        self.setAccessibleName(text)
        fm = QFontMetricsF(self.font, self)
        br = fm.boundingRect(QRectF(0, 0, 220, 1000), Qt.TextWordWrap, text)
        # +6px dư: làm tròn kích thước không được làm câu một dòng bị xuống dòng rồi bị cắt chữ
        w, h, tail = math.ceil(br.width()) + 36, math.ceil(br.height()) + 20, 10
        win = self.parentWidget().rect()
        top = anchor.y() - h - tail
        if top >= 4:          # đủ chỗ phía trên đầu => đuôi chỉ xuống
            x = max(6.0, min(win.width() - w - 6.0, anchor.x() - w / 2))
            self.tail, self.tail_at = "down", anchor.x() - x
            self.setGeometry(round(x), round(top), round(w), round(h + tail))
        else:                 # sát mép trên => đặt bên phải mascot, đuôi chỉ sang trái
            x = min(host.right() - 8, win.width() - w - tail - 6)
            y = max(4.0, min(win.height() - h - 4.0, anchor.y()))
            self.tail, self.tail_at = "left", min(h - 14, max(14.0, anchor.y() + 18 - y))
            self.setGeometry(round(x), round(y), round(w + tail), round(h))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        if self.tail == "down":
            body = r.adjusted(0, 0, 0, -10)
            path.addRoundedRect(body, 16, 16)
            tx = max(18.0, min(body.width() - 18, self.tail_at))
            path.moveTo(tx - 8, body.bottom() - 1)
            path.lineTo(tx, r.bottom())
            path.lineTo(tx + 8, body.bottom() - 1)
        else:
            body = r.adjusted(10, 0, 0, 0)
            path.addRoundedRect(body, 16, 16)
            path.moveTo(body.left() + 1, self.tail_at - 7)
            path.lineTo(r.left(), self.tail_at)
            path.lineTo(body.left() + 1, self.tail_at + 7)
        path = path.simplified()
        p.setPen(QPen(QColor("#C7D2FE"), 1.5))
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(path)
        p.setPen(INK)
        p.setFont(self.font)
        p.drawText(body.adjusted(14, 8, -14, -8), Qt.TextWordWrap | Qt.AlignCenter, self.text)


# ------------------------------------------------------------------ mascot
class Mascot3D(QWidget):
    """Thay thế tại chỗ cho Mascot SVG: cùng hàm set(kind, mood), thêm set_context(...) cho lời thoại."""

    reacted = Signal(str)   # "poke" / "tickle" / "party" — cho kiểm thử tự động (không mang dữ liệu)

    def __init__(self, kind: str, mood: str = "happy", size: int = 112, hint: bool = False, reduced: bool | None = None):
        super().__init__()
        self.atlas = Atlas.get(kind)
        if self.atlas is None:
            raise ValueError(f"thiếu atlas {kind}")
        self.setFixedSize(size, size)
        self.kind, self.mood = kind, mood
        self.reduced = (not animations_enabled()) if reduced is None else reduced
        self.ctx: dict = {"profile": {}, "remaining_sec": None, "phase": None, "study_min": 0}
        self.hint, self.hinted, self.interacted = hint, False, False
        self.clock, self.last, self.phase = 0.0, None, random.random() * 6
        self.yaw = self.yawV = 0.0
        self.look = self.tlook = 0.0
        self.sq = self.sqV = 0.0
        self.jumpT, self.jumpH, self.jump_px = -1.0, 0.0, 0.0
        self.spinT = self.ringT = self.wiggleT = -1.0
        self.expr_tmp, self.exprUntil = None, -1.0
        self.blinkT, self.nextBlink = -1.0, 2 + random.random() * 3
        self.nextZ = 2.0
        self.timers: list[tuple[float, object]] = []
        self.parts: list[dict] = []
        self.taps: list[float] = []
        self.drag: dict | None = None
        self.releasedAt = -10.0
        self.bubble: SpeechBubble | None = None
        self.bubbleUntil = 0.0
        self.last_line: dict[str, str] = {}
        self.sparkle = False   # lấp lánh quanh mũ tốt nghiệp (thẻ huy hiệu "Ngôi Sao Đúng Giờ")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._name()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ---- API giống Mascot SVG ----
    @staticmethod
    def available() -> bool:
        return all(Atlas.get(k) is not None for k in KINDS)

    def set(self, kind: str, mood: str) -> None:
        if kind != self.kind:
            atlas = Atlas.get(kind)
            if atlas is None:
                return
            self.kind, self.atlas, self.yaw, self.yawV = kind, atlas, 0.0, 0.0
            self._name()
        self.mood = mood
        self.update()

    def set_context(self, profile: dict | None = None, remaining_sec: int | None = None, phase: str | None = None,
                    study_min: int = 0) -> None:
        self.ctx = {"profile": profile or {}, "remaining_sec": remaining_sec, "phase": phase, "study_min": study_min}

    def _name(self):
        self.setAccessibleName(f"{V.MASCOT_NAMES.get(self.kind, 'Mascot')} — nhấn Space để chơi cùng")

    # ---- vòng lặp ----
    def showEvent(self, e):
        self.last = None
        self.timer.start(33)
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        if self.bubble:
            self.bubble.hide()
        super().hideEvent(e)

    def _busy(self) -> bool:
        return bool(self.drag or self.parts or self.jumpT >= 0 or self.spinT >= 0 or self.ringT >= 0 or self.wiggleT >= 0
                    or self.timers or abs(self.sqV) > 0.02 or abs(self.yawV) > 0.02 or abs(self.look - self.tlook) > 0.01)

    def _tick(self):
        if not self.isVisible():
            self.timer.stop()
            return
        now = time.monotonic()
        dt = 0.033 if self.last is None else min(0.1, now - self.last)
        self.last = now
        steps = max(1, math.ceil(dt * 60))
        for _ in range(steps):
            self._step(dt / steps)
        self._particles(dt)
        if self.hint and not self.hinted and not self.interacted and self.clock > 6:
            self.hinted = True
            self.jump(0.3)
            self._say("hint")
        if self.bubble and self.bubble.isVisible() and self.clock > self.bubbleUntil:
            self.bubble.hide()
        self.timer.setInterval(33 if self._busy() else 66)   # đứng yên chỉ còn thở/chớp mắt => 15 khung/giây
        self.update()

    def _step(self, h: float):
        self.clock += h
        c = self.clock
        due = [fn for at, fn in self.timers if at <= c]
        self.timers = [(at, fn) for at, fn in self.timers if at > c]
        for fn in due:
            fn()
        # nhảy + lò xo co giãn (cùng hằng số với bản web)
        y = 0.0
        if self.jumpT >= 0:
            self.jumpT += h
            u = self.jumpT / 0.55
            if u >= 1:
                self.jumpT = -1
                if self.jumpH > 0:
                    self.sqV -= 3.0
            else:
                y = 4 * self.jumpH * u * (1 - u)
        self.jump_px = y * 0.2 * self.height()
        self.sqV += (-170 * self.sq - 11 * self.sqV) * h
        self.sq += self.sqV * h
        # xoay một vòng (Khiên Xanh)
        if self.spinT >= 0:
            self.spinT += h
            if self.spinT >= 0.75:
                self.spinT = -1
        # quay theo chuột / quán tính sau khi thả tay / lò xo về hướng nhìn thẳng
        self.look += (self.tlook - self.look) * min(1.0, h * 6)
        if not self.drag:
            target = self.look * 0.3
            if abs(self.yaw - target) > math.pi:            # về hướng gần nhất, không "tua ngược" cả vòng
                self.yaw -= math.copysign(TAU, self.yaw - target)
            k = 4 if c - self.releasedAt < 1.0 else 30
            self.yawV += ((target - self.yaw) * k - self.yawV * (1.2 if k < 10 else 9)) * h
            self.yaw += self.yawV * h
        for name, dur in (("ringT", 1.0), ("wiggleT", 0.9)):
            t = getattr(self, name)
            if t >= 0:
                setattr(self, name, -1 if t + h > dur else t + h)
        # chớp mắt
        if self.blinkT >= 0:
            self.blinkT += h
            if self.blinkT > 0.13:
                self.blinkT = -1
        elif c > self.nextBlink and c > self.exprUntil and V.MOOD_TO_EXPR.get(self.mood, "happy") in ("happy", "wow"):
            self.blinkT, self.nextBlink = 0.0, c + 2.5 + random.random() * 3.5
        # buồn ngủ => "z" bay lên
        if self.mood == "sleepy" and not self.reduced and c > self.nextZ:
            self.nextZ = c + 2.2
            hx, hy = self._head()
            self.parts.append({"k": "z", "x": hx + self.width() * 0.16, "y": hy + self.height() * 0.05, "vx": 6, "vy": -14,
                               "g": 0, "life": 2.0, "t": 0, "rot": 0, "vr": 0, "s": self.width() * 0.09, "col": "#6366F1"})

    def _expr(self) -> str:
        if self.clock <= self.exprUntil and self.expr_tmp:
            return self.expr_tmp
        if self.blinkT >= 0:
            return "blink"
        return V.MOOD_TO_EXPR.get(self.mood, "happy")

    def _spin_extra(self) -> float:
        if self.spinT < 0:
            return 0.0
        u = min(1.0, self.spinT / 0.75)
        return (2 * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 2 / 2) * TAU

    # ---- hình học ----
    def _draw_size(self) -> float:
        return self.width() * 0.96

    def _feet_y(self) -> float:
        return self.height() * 0.965

    def _head(self) -> tuple[float, float]:
        d = self._draw_size()
        return self.width() / 2, self._feet_y() - self.jump_px - (self.atlas.feet - self.atlas.head) * d

    # ---- phản ứng ----
    def after(self, sec: float, fn) -> None:
        self.timers.append((self.clock + sec, fn))

    def express(self, e: str, sec: float) -> None:
        self.expr_tmp, self.exprUntil, self.blinkT = e, self.clock + sec, -1

    def jump(self, height: float = 0.55) -> None:
        if self.reduced:
            height = 0.0
        self.sqV = -2.4

        def go():
            self.jumpT, self.jumpH, self.sqV = 0.0, height, 2.6
        self.after(0.07, go)

    def poke(self) -> None:
        self.interacted = True
        self.taps = [t for t in self.taps if self.clock - t < 2.6] + [self.clock]
        if len(self.taps) >= 5:
            self.taps = []
            self.party()
            return
        self.reacted.emit("poke")
        self.jump()
        self.express("joy", 1.5)
        n = 3 if self.reduced else (10 if self.kind == "sao" else 7)
        self._burst("star", n)
        if self.kind == "tictac" and not self.reduced:
            self.ringT = 0.0
        elif self.kind == "khien" and not self.reduced:
            self.spinT = 0.0
        elif self.kind == "sao":
            self.after(0.66, lambda: self.jump(0.25))
        self._say("poke")

    def tickle(self) -> None:
        self.interacted = True
        self.reacted.emit("tickle")
        if not self.reduced:
            self.wiggleT = 0.0
        self.express("love", 1.8)
        self._burst("heart", 3 if self.reduced else 8)
        self._say("tickle")

    def party(self) -> None:
        self.reacted.emit("party")
        self.jump(0.7)
        self.express("joy", 2.2)
        if not self.reduced:
            self.spinT = 0.0
            self.ringT = 0.0 if self.kind == "tictac" else -1
            self.after(0.75, lambda: self.jump(0.45))
        self._burst("bit", 8 if self.reduced else 30)
        self._say("party")

    def _burst(self, kind: str, n: int) -> None:
        hx, hy = self._head()
        s = self.width() / 128
        for _ in range(n):
            if kind == "bit":
                p = {"x": self.width() * random.uniform(0.1, 0.9), "y": self.height() * random.uniform(0.0, 0.2),
                     "vx": random.uniform(-40, 40) * s, "vy": random.uniform(-60, 20) * s, "g": 260 * s, "life": 1.6,
                     "s": random.uniform(4, 7) * s, "col": random.choice(CONFETTI)}
            elif kind == "heart":
                p = {"x": hx + random.uniform(-0.2, 0.2) * self.width(), "y": hy + self.height() * 0.12,
                     "vx": random.uniform(-30, 30) * s, "vy": random.uniform(-90, -50) * s, "g": -10 * s, "life": 1.3,
                     "s": random.uniform(7, 11) * s, "col": random.choice(("#FF7FA6", "#FF9DBB", "#F43F5E"))}
            else:
                a = random.uniform(-math.pi * 0.95, -math.pi * 0.05)
                v = random.uniform(70, 130) * s
                p = {"x": hx, "y": hy + self.height() * 0.08, "vx": math.cos(a) * v, "vy": math.sin(a) * v, "g": 160 * s,
                     "life": 0.95, "s": random.uniform(6, 10) * s, "col": random.choice(("#FFC93C", "#FFD45C", "#FFB020"))}
            p.update({"k": kind, "t": 0.0, "rot": random.uniform(0, 360), "vr": random.uniform(-260, 260)})
            if self.reduced:
                p.update({"vx": p["vx"] * 0.3, "vy": p["vy"] * 0.3, "g": 0})
            self.parts.append(p)

    def _particles(self, dt: float) -> None:
        for p in self.parts:
            p["t"] += dt
            p["vy"] += p["g"] * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["rot"] += p["vr"] * dt
        self.parts = [p for p in self.parts if p["t"] < p["life"]]

    def _say(self, key: str) -> None:
        ctx = self.ctx
        pool = V.mascot_lines(self.kind, ctx["profile"], ctx["remaining_sec"], ctx["phase"], ctx["study_min"]).get(key) or []
        if not pool:
            return
        text = random.choice(pool)
        if len(pool) > 1:
            while text == self.last_line.get(key):
                text = random.choice(pool)
        self.last_line[key] = text
        self.setAccessibleDescription(text)
        win = self.window()
        if win is self:
            return
        if self.bubble is None or self.bubble.parentWidget() is not win:
            self.bubble = SpeechBubble(win)
        hx, hy = self._head()
        anchor = self.mapTo(win, QPointF(hx, hy + self.jump_px - 2).toPoint())
        tl = self.mapTo(win, self.rect().topLeft())
        self.bubble.show_text(text, QPointF(anchor), QRectF(tl.x(), tl.y(), self.width(), self.height()))
        self.bubbleUntil = self.clock + 3.4

    # ---- chuột / bàn phím ----
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        x = e.position().x()
        self.drag = {"x0": x, "x": x, "t0": self.clock, "moved": 0.0, "dir": 0, "flips": 0, "tickled": False, "v": 0.0}
        self.yawV = 0.0
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if not self.drag:
            self.tlook = max(-1.0, min(1.0, (x - self.width() / 2) / (self.width() / 2)))
            return
        d = self.drag
        dx = x - d["x"]
        d["x"] = x
        d["moved"] = max(d["moved"], abs(x - d["x0"]))
        if d["moved"] > 6:
            self.yaw += dx * 0.03
            d["v"] = d["v"] * 0.6 + dx * 0.03 * 30 * 0.4      # ~rad/giây (ước lượng theo nhịp 30 khung)
        if abs(dx) > 1.5:
            sgn = 1 if dx > 0 else -1
            if d["dir"] and sgn != d["dir"]:
                d["flips"] += 1
            d["dir"] = sgn
        if d["flips"] >= 4 and not d["tickled"]:
            d["tickled"] = True
            self.tickle()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.drag:
            return super().mouseReleaseEvent(e)
        d, self.drag = self.drag, None
        self.setCursor(Qt.PointingHandCursor)
        if d["moved"] < 6 and self.clock - d["t0"] < 0.5:
            self.poke()
        elif not d["tickled"]:
            self.yawV = max(-18.0, min(18.0, d["v"]))
            self.releasedAt = self.clock
        self.interacted = True

    def leaveEvent(self, e):
        self.tlook = 0.0
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.poke()
            e.accept()
            return
        super().keyPressEvent(e)

    # ---- vẽ ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        d = self._draw_size()
        feet = self._feet_y()
        t = self.clock + self.phase
        # bóng đổ: nhỏ và nhạt đi khi nhảy lên
        k = 1 - min(0.45, self.jump_px / max(1.0, 0.25 * H))
        g = QRadialGradient(QPointF(W / 2, feet - H * 0.012), W * 0.27 * k)
        g.setColorAt(0, QColor(67, 56, 202, int(70 * k)))
        g.setColorAt(1, QColor(67, 56, 202, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.save()
        p.translate(W / 2, feet - H * 0.012)
        p.scale(1, 0.22)
        p.drawEllipse(QPointF(0, 0), W * 0.27 * k, W * 0.27 * k)
        p.restore()
        # thân
        slow = self.mood == "sleepy"
        breath = 0.0 if self.reduced else math.sin(t * (1.4 if slow else 2.3)) * (0.012 if slow else 0.018)
        sy = 1 + self.sq * 0.22 + breath
        sx = 1 - self.sq * 0.12 - breath * 0.5
        rot = 0.0 if self.reduced else math.sin(t * 1.25) * 0.035
        if self.wiggleT >= 0:
            rot += math.sin(self.wiggleT * 28) * 0.12 * max(0.0, 1 - self.wiggleT / 0.9)
        if self.ringT >= 0:
            rot += math.sin(self.ringT * 46) * 0.06 * max(0.0, 1 - self.ringT)
        dpr = self.devicePixelRatioF()
        frames = self.atlas.pixmaps(max(16, round(d * dpr)))
        pix = frames[self.atlas.frame_index(self.yaw + self._spin_extra(), self._expr())]
        p.save()
        p.translate(W / 2, feet - self.jump_px)
        p.rotate(math.degrees(rot))
        p.scale(sx, sy)
        p.drawPixmap(QRectF(-d / 2, -self.atlas.feet * d, d, d), pix, QRectF(pix.rect()))
        p.restore()
        if self.sparkle:
            self._paint_sparkles(p, t)
        # hạt: sao / tim / pháo giấy / z
        for q in self.parts:
            a = max(0.0, 1 - q["t"] / q["life"])
            col = QColor(q["col"])
            col.setAlphaF(min(1.0, a * 1.6))
            p.save()
            p.translate(q["x"], q["y"])
            p.rotate(q["rot"] if q["k"] in ("star", "bit") else 0)
            sz = q["s"] * (0.6 + 0.4 * min(1.0, q["t"] * 6))
            if q["k"] == "z":
                f = QFont("Nunito")
                f.setPixelSize(max(8, round(sz * (1 + q["t"] * 0.3))))
                f.setWeight(QFont.Black)
                p.setFont(f)
                p.setPen(col)
                p.drawText(QPointF(0, 0), "z")
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                if q["k"] == "star":
                    p.drawPolygon(_star(sz))
                elif q["k"] == "heart":
                    p.drawPath(_heart(sz))
                else:
                    p.drawRoundedRect(QRectF(-sz / 2, -sz / 4, sz, sz / 2), 1.5, 1.5)
            p.restore()
        if self.hasFocus():
            pen = QPen(QColor("#6366F1"), 2.5)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2, 2, W - 4, H - 4), 18, 18)

    def _paint_sparkles(self, p: QPainter, t: float) -> None:
        """Bốn tia lấp lánh 4 cánh quanh mũ, nhấp nháy lệch nhịp (giảm chuyển động => đứng yên)."""
        hx, hy = self._head()
        W = self.width()
        for i, (dx, dy, s) in enumerate(((-0.33, 0.13, 0.075), (0.34, 0.06, 0.06), (0.22, -0.02, 0.042), (-0.2, 0.0, 0.036))):
            k = 0.85 if self.reduced else 0.3 + 0.7 * (0.5 + 0.5 * math.sin(t * 3.0 + i * 1.9))
            col = QColor("#FFC93C" if i % 2 == 0 else "#FFFFFF")
            col.setAlphaF(0.5 + 0.5 * k)
            p.save()
            p.translate(hx + dx * W, hy + dy * W)
            p.setPen(QPen(QColor(245, 158, 11, int(150 * k)), 1) if i % 2 else Qt.NoPen)
            p.setBrush(col)
            p.drawPath(_twinkle(W * s * k))
            p.restore()


def _twinkle(r: float) -> QPainterPath:
    q = r * 0.16
    path = QPainterPath(QPointF(0, -r))
    for a, b in (((q, -q), (r, 0)), ((q, q), (0, r)), ((-q, q), (-r, 0)), ((-q, -q), (0, -r))):
        path.quadTo(QPointF(*a), QPointF(*b))
    return path


def _star(r: float) -> QPolygonF:
    pts = []
    for i in range(10):
        rr = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(math.cos(a) * rr, math.sin(a) * rr))
    return QPolygonF(pts)


def _heart(s: float) -> QPainterPath:
    path = QPainterPath(QPointF(0, s * 0.35))
    path.cubicTo(QPointF(-s * 1.1, -s * 0.35), QPointF(-s * 0.45, -s * 0.95), QPointF(0, -s * 0.4))
    path.cubicTo(QPointF(s * 0.45, -s * 0.95), QPointF(s * 1.1, -s * 0.35), QPointF(0, s * 0.35))
    return path
