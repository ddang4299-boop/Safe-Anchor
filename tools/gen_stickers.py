"""Sinh bộ NHÃN DÁN VẼ TAY cho giao diện của trẻ (Tray + trang /kid) — thay cho icon đóng gói sẵn.

Phong cách: nét mực run tay (đỉnh hình bị xê dịch ngẫu nhiên), nét dày mỏng không đều (lớp màu in lệch
nhẹ lên trên-trái so với nét mực, như tô sáp/in lụa), viền trắng cắt rời + bóng mờ như sticker dán.
Chỉ dùng phần tử SVG Tiny (path/circle, fill/stroke/opacity/transform) để Qt (QtSvg) và trình duyệt vẽ giống nhau.

Ngẫu nhiên có hạt giống theo tên nhãn => chạy lại ra y hệt.
    python tools/gen_stickers.py
Ghi vào: agent/tray/assets/stickers/*.svg và dashboard/static/stickers/*.svg
"""
from __future__ import annotations

import math
import random
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = (ROOT / "agent" / "tray" / "assets" / "stickers", ROOT / "dashboard" / "static" / "stickers")

INK = "#2E2850"
CUT = 10.5          # bề rộng viền trắng cắt rời (nét trắng phía sau)
INK_W = 4.8         # nét mực bao hình (một nửa bị lớp màu che => ~2.4)
SHIFT = (-0.9, -0.9)  # lớp màu in lệch => nét trên-trái mảnh, dưới-phải đậm

# bảng màu sáp (khớp tông Tray/web)
CORAL, ORANGE, SUN, MINT, SKY, GRAPE, PINK = "#FF8A73", "#FFA45B", "#FFD45C", "#6FD6A8", "#86CCF6", "#B9A4FF", "#FF9EC7"
CREAM, PAPER, BROWN, SKIN, GOLD, LEAF = "#FFF3D6", "#FFFDF7", "#D39A6A", "#FFD3AE", "#FFC83D", "#58C98F"

R = random.Random(0)


def f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def pt(p) -> str:
    return f"{f(p[0])},{f(p[1])}"


def jit(pts, j):
    return [(x + R.uniform(-j, j), y + R.uniform(-j, j)) for x, y in pts]


def smooth_closed(pts) -> str:
    """Đường cong Catmull-Rom khép kín qua các điểm."""
    n = len(pts)
    d = f"M{pt(pts[0])}"
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{pt(c1)} {pt(c2)} {pt(p2)}"
    return d + "Z"


def stroke(pts, j=0.45) -> str:
    """Nét hở, hơi run."""
    pts = jit(pts, j)
    if len(pts) == 2:  # nét thẳng => cong nhẹ như kéo tay
        (x1, y1), (x2, y2) = pts
        L = math.hypot(x2 - x1, y2 - y1) or 1
        b = R.uniform(-0.06, 0.06) * L
        c = ((x1 + x2) / 2 - (y2 - y1) / L * b, (y1 + y2) / 2 + (x2 - x1) / L * b)
        return f"M{pt(pts[0])}Q{pt(c)} {pt(pts[1])}"
    ext = [pts[0]] + pts + [pts[-1]]
    d = f"M{pt(pts[0])}"
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f"C{pt(c1)} {pt(c2)} {pt(p2)}"
    return d


def blob(cx, cy, rx, ry=None, n=9, j=0.06) -> str:
    """Hình tròn/elip vẽ tay: bán kính dao động nhẹ."""
    ry = rx if ry is None else ry
    a0 = R.uniform(0, math.tau)
    pts = []
    for i in range(n):
        a = a0 + i * math.tau / n + R.uniform(-0.12, 0.12)
        k = 1 + R.uniform(-j, j)
        pts.append((cx + math.cos(a) * rx * k, cy + math.sin(a) * ry * k))
    return smooth_closed(pts)


def rpoly(pts, r=3.2, j=0.95, bow=0.09) -> str:
    """Đa giác bo góc, cạnh hơi phồng/lõm — cho hộp, trang giấy, ngôi sao…"""
    pts = jit(pts, j)
    n = len(pts)

    def toward(p, q, dist):
        L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1
        t = min(dist, L / 2.2) / L
        return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)

    A = [toward(pts[i], pts[i - 1], r) for i in range(n)]
    B = [toward(pts[i], pts[(i + 1) % n], r) for i in range(n)]
    d = f"M{pt(B[0])}"
    for i in range(n):
        k = (i + 1) % n
        (x1, y1), (x2, y2) = B[i], A[k]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        b = R.uniform(-bow, bow) * L
        c = ((x1 + x2) / 2 - (y2 - y1) / L * b, (y1 + y2) / 2 + (x2 - x1) / L * b)
        d += f"Q{pt(c)} {pt(A[k])}Q{pt(pts[k])} {pt(B[k])}"
    return d + "Z"


def box(x1, y1, x2, y2, **kw) -> str:
    return rpoly([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], **kw)


def star_pts(cx, cy, ro, ri, rot=-90):
    return [(cx + math.cos(math.radians(rot + i * 36)) * (ro if i % 2 == 0 else ri),
             cy + math.sin(math.radians(rot + i * 36)) * (ro if i % 2 == 0 else ri)) for i in range(10)]


def heart(cx, cy, s) -> str:
    pts = []
    for i in range(14):
        t = i * math.tau / 14
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * s / 16, cy + y * s / 16))
    return smooth_closed(jit(pts, 0.3))


class S:
    """Một nhãn: các NHÓM hình tô màu (cùng nhóm => chung một đường viền mực), nét chi tiết, chấm."""

    def __init__(self):
        self.groups: list[list[tuple[str, str, float]]] = []
        self.lines: list[tuple[str, float, str]] = []
        self.dots: list[tuple[float, float, float, str]] = []
        self.shine: list[str] = []

    def g(self, *shapes):  # shapes: (d, fill) hoặc (d, fill, ink_w)
        self.groups.append([(s[0], s[1], s[2] if len(s) > 2 else INK_W) for s in shapes])
        return self

    def ln(self, d, w=2.4, color=INK):
        self.lines.append((d, w, color))
        return self

    def dot(self, x, y, r=1.6, color=INK):
        self.dots.append((x, y, r, color))
        return self

    def hi(self, d):  # vệt sáng trắng
        self.shine.append(d)
        return self

    def svg(self, rot: float) -> str:
        shapes = [s for grp in self.groups for s in grp]
        o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">',
             f'<g transform="rotate({f(rot)} 32 32)">']
        for layer, (dx, dy), color, op in (("shadow", (0.9, 1.7), INK, 0.13), ("cut", (0, 0), "#FFFFFF", 1)):
            o.append(f'<g transform="translate({f(dx)} {f(dy)})" opacity="{op}" stroke="{color}" '
                     f'stroke-linejoin="round" stroke-linecap="round">')
            for d, _, w in shapes:
                o.append(f'<path d="{d}" fill="{color}" stroke-width="{f(CUT + w / 2 - INK_W / 2)}"/>')
            for d, w, _ in self.lines:
                o.append(f'<path d="{d}" fill="none" stroke-width="{f(w + CUT - 2)}"/>')
            for x, y, r, _ in self.dots:
                o.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r + CUT / 2 - 1)}" fill="{color}" stroke="none"/>')
            o.append("</g>")
        for grp in self.groups:
            for d, _, w in grp:
                o.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{f(w)}" '
                         f'stroke-linejoin="round" stroke-linecap="round"/>')
            o.append(f'<g transform="translate({f(SHIFT[0])} {f(SHIFT[1])})">')
            for d, fill, _ in grp:
                o.append(f'<path d="{d}" fill="{fill}"/>')
            o.append("</g>")
        for d in self.shine:
            o.append(f'<path d="{d}" fill="none" stroke="#FFFFFF" stroke-opacity=".8" stroke-width="2.6" stroke-linecap="round"/>')
        for d, w, c in self.lines:
            o.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{f(w)}" stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, r, c in self.dots:
            o.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{c}"/>')
        o.append("</g></svg>")
        return "\n".join(o) + "\n"


# ============================================================================ từng nhãn
def clock():  # đồng hồ báo thức — "Hôm nay"
    s = S()
    s.g((blob(18.5, 15.5, 6.2), SUN), (blob(45.5, 15.5, 6.2), SUN))
    s.ln(stroke([(21, 51), (16.5, 57)]), 3.2).ln(stroke([(43, 51), (47.5, 57)]), 3.2)
    s.g((blob(32, 35, 19.5, 19, n=10), CORAL))
    s.g((blob(32, 35, 13.5, n=9, j=0.03), PAPER, 3.6))
    s.hi(stroke([(17.5, 30), (20, 24.5), (24.5, 20.5)], 0.2))
    s.ln(stroke([(32, 35), (31.5, 26.5)]), 2.8).ln(stroke([(32, 35), (38.5, 38)]), 2.8).dot(32, 35, 2.2)
    for a in (0, 90, 180, 270):
        x, y = 32 + math.cos(math.radians(a)) * 10.5, 35 + math.sin(math.radians(a)) * 10.5
        s.dot(x, y, 1.1)
    return s


def explore():  # kính lúp — "Đã khám phá gì"
    s = S()
    s.g((rpoly([(36.5, 41), (41, 36.5), (55.5, 50.5), (51, 55)], r=3), BROWN))
    s.g((blob(27, 27, 18, n=10, j=0.03), SUN))
    s.g((blob(27, 27, 12, n=9, j=0.04), "#D8F1FF", 3.6))
    s.hi(stroke([(19.5, 27), (20.5, 22), (24.5, 19)], 0.2))
    s.ln(stroke([(42, 46), (46, 42)]), 2)
    return s


def notebook():  # sổ ghi chép + bút — "Ai đã đổi gì"
    s = S()
    s.g((rpoly([(13, 11), (47, 9), (49, 55), (15, 57)], r=3.5), CREAM))
    for y in (17, 27, 37, 47):
        s.ln(stroke([(10, y + 1.5), (17, y - 0.5)]), 2.4)
    for y, x2 in ((21, 41), (29.5, 39.5), (38, 33)):
        s.ln(stroke([(22, y), (x2, y - 0.6)], 0.35), 2.2, "#8C86B5")
    s.g((rpoly([(35, 52), (51.5, 35.5), (57, 41), (40.5, 57.5)], r=1.6), SKY))
    s.g((rpoly([(35, 52), (40.5, 57.5), (31, 61)], r=1.2), CREAM, 3.6))
    s.dot(32.6, 59.6, 1.5)
    return s


def shield():  # khiên — "Về SafeAnchor"
    s = S()
    pts = [(32, 7), (43, 11.5), (52.5, 13.5), (51.5, 31), (45, 46), (32, 57.5), (19, 46), (12.5, 31), (11.5, 13.5), (21, 11.5)]
    s.g((smooth_closed(jit(pts, 0.6)), GRAPE))
    s.g((heart(32, 31, 10.5), PINK, 3.8))
    s.hi(stroke([(17.5, 19), (17.5, 28)], 0.2))
    return s


def book():  # sách mở — "Học tập"
    s = S()
    s.g((rpoly([(5, 16), (32, 21), (59, 16), (59, 53), (32, 58), (5, 53)], r=3), MINT))
    s.g((rpoly([(32, 19), (9.5, 13), (9.5, 49), (32, 53)], r=2.4), PAPER, 3.8),
        (rpoly([(32, 19), (54.5, 13), (54.5, 49), (32, 53)], r=2.4), PAPER, 3.8))
    s.ln(stroke([(32, 19.5), (32, 52.5)], 0.3), 2.4)
    for y in (23, 30, 37):
        s.ln(stroke([(14.5, y - 3), (27, y)], 0.3), 2, "#8C86B5")
        s.ln(stroke([(37, y), (49.5, y - 3)], 0.3), 2, "#8C86B5")
    return s


def game():  # tay cầm trò chơi — "Giải trí"
    s = S()
    pts = [(14, 22.5), (24, 21), (32, 24), (40, 21), (50, 22.5), (56.5, 33), (57.5, 45), (51.5, 49),
           (44.5, 43.5), (32, 41.5), (19.5, 43.5), (12.5, 49), (6.5, 45), (7.5, 33)]
    s.g((smooth_closed(jit(pts, 0.5)), ORANGE))
    s.ln(stroke([(14.5, 32), (24.5, 32)], 0.3), 4).ln(stroke([(19.5, 27), (19.5, 37)], 0.3), 4)
    s.g((blob(42.5, 29.5, 3.4, n=7), PINK, 3.4), (blob(48.5, 35.5, 3.4, n=7), SUN, 3.4))
    s.hi(stroke([(12, 30), (15, 25.5)], 0.2))
    return s


def sun():  # mặt trời — giờ được dùng
    s = S()
    for i in range(8):
        a = math.radians(i * 45 + R.uniform(-6, 6))
        r1, r2 = 18.5, 26 + R.uniform(-1.5, 1)
        s.ln(stroke([(32 + math.cos(a) * r1, 32 + math.sin(a) * r1), (32 + math.cos(a) * r2, 32 + math.sin(a) * r2)]), 3.4)
    s.g((blob(32, 32, 13.5, n=9), SUN))
    s.dot(27.5, 30, 1.5).dot(36.5, 30, 1.5)
    s.ln(stroke([(28, 35.5), (32, 38), (36, 35.5)], 0.2), 2.2)
    return s


def moon():  # trăng khuyết — giờ nghỉ
    s = S()
    oc, orr, ic, ir = (30, 33), 20.0, (40.5, 24.5), 16.5
    pts = []
    for i in range(40):  # cung ngoài nằm ngoài hình tròn "cắn"
        a = math.tau * i / 40
        x, y = oc[0] + math.cos(a) * orr, oc[1] + math.sin(a) * orr
        if math.hypot(x - ic[0], y - ic[1]) > ir:
            pts.append((a, x, y))
    # sắp theo góc liên tục (bắt đầu sau khe hở)
    angs = [p[0] for p in pts]
    gaps = [((angs[(k + 1) % len(angs)] - angs[k]) % math.tau, k) for k in range(len(angs))]
    start = (max(gaps)[1] + 1) % len(pts)
    outer = [(p[1], p[2]) for p in pts[start:] + pts[:start]][::3]
    # cung trong (ngược lại) nối hai đầu
    e1, e2 = outer[-1], outer[0]
    a1 = math.atan2(e1[1] - ic[1], e1[0] - ic[0])
    a2 = math.atan2(e2[1] - ic[1], e2[0] - ic[0])
    da = (a2 - a1) % math.tau
    if da > math.pi:
        da -= math.tau
    inner = [(ic[0] + math.cos(a1 + da * t / 5) * ir, ic[1] + math.sin(a1 + da * t / 5) * ir) for t in range(1, 5)]
    s.g((smooth_closed(jit(outer + inner, 0.35)), GRAPE))
    s.g((rpoly(star_pts(47.5, 44, 7, 3.2), r=1, j=0.3), SUN, 3.6))
    s.dot(50.5, 14, 1.6, INK)
    return s


def puzzle():  # mảnh ghép — "Ứng dụng hay dùng"
    s = S()
    s.g((box(12, 20, 44, 52, r=4), SKY), (blob(28, 15, 6.5, n=8), SKY), (blob(49, 36, 6.5, n=8), SKY))
    s.hi(stroke([(16.5, 31), (16.5, 25), (21, 24)], 0.2))
    return s


def globe():  # quả địa cầu — "Trang web hay ghé"
    s = S()
    s.g((blob(32, 32, 22, n=11, j=0.03), SKY))
    s.g((smooth_closed(jit([(18, 22), (26, 17), (31, 21), (28, 28), (31, 34), (24, 38), (19, 32), (15, 28)], 0.4)), LEAF, 3.6))
    s.g((smooth_closed(jit([(39, 33), (46, 31), (49, 38), (45, 47), (38, 48), (36, 41)], 0.4)), LEAF, 3.6))
    s.g((blob(42, 19.5, 3.2, n=6), LEAF, 3.6))
    s.hi(stroke([(14, 38), (16.5, 43.5)], 0.2))
    return s


def hand():  # bàn tay giơ lên — "Xin thêm giờ"
    s = S()
    pts = [(22, 56), (19.5, 46), (14, 39.5), (9.5, 33.5), (11, 29.5), (15.5, 30.5), (20.5, 36),
           (19.5, 19), (21.5, 12), (26, 12), (27.5, 18.5), (28.5, 25),
           (29, 13.5), (30.5, 7.5), (35, 7.5), (36.5, 13), (36.5, 25),
           (37.5, 14.5), (40, 10.5), (44, 12.5), (44, 20), (43.5, 28),
           (45.5, 21), (48.5, 19), (51.5, 22), (50, 33), (47.5, 44), (44, 56)]
    s.g((smooth_closed(jit(pts, 0.25)), SKIN))
    s.g((box(19.5, 50.5, 46.5, 59, r=2.5), SKY))
    s.ln(stroke([(53, 9.5), (57.5, 5.5)], 0.2), 2.6).ln(stroke([(55.5, 15.5), (60, 13.5)], 0.2), 2.6)
    return s


def star():  # ngôi sao — chuỗi ngày, huy hiệu
    s = S()
    s.g((rpoly(star_pts(32, 34, 25, 11.5), r=3.2, j=0.6, bow=0.05), SUN))
    s.dot(27.5, 33.5, 1.5).dot(36.5, 33.5, 1.5)
    s.ln(stroke([(29.5, 38.5), (32, 40.2), (34.5, 38.5)], 0.15), 2)
    return s


def check():  # dấu tích — "Tớ biết"
    s = S()
    s.g((blob(32, 32, 20, n=9, j=0.06), MINT))
    s.ln(stroke([(22, 33), (29, 40.5), (43, 23.5)], 0.4), 5)
    return s


def cross():  # dấu chéo — "Tớ không"
    s = S()
    s.g((blob(32, 32, 20, n=9, j=0.06), CORAL))
    s.ln(stroke([(24, 24), (40, 40)], 0.4), 5).ln(stroke([(40, 24), (24, 40)], 0.4), 5)
    return s


def gift():  # hộp quà — được tặng thêm giờ
    s = S()
    s.g((blob(24.5, 15.5, 7.5, 5, n=7), SUN), (blob(39.5, 15.5, 7.5, 5, n=7), SUN))
    s.g((box(14, 29, 50, 56, r=2.5), PINK))
    s.g((box(10.5, 20.5, 53.5, 30.5, r=2.5), PINK))
    s.g((box(28, 20.5, 36, 56, r=1.2, j=0.4), SUN, 3.6))
    return s


def pencil():  # bút chì — đổi cài đặt
    s = S()
    s.g((rpoly([(14, 41), (41, 14), (50, 23), (23, 50)], r=1.6), SUN))
    s.g((rpoly([(41, 14), (46, 9), (55, 18), (50, 23)], r=2.4), PINK))
    s.g((rpoly([(14, 41), (23, 50), (9, 55)], r=1.4), CREAM, 3.6))
    s.dot(10.5, 53.5, 1.7)
    s.ln(stroke([(18.5, 45.5), (45.5, 18.5)], 0.3), 1.8, "#C99A1E")
    return s


def calendar():  # tờ lịch — "Lịch của mình", "Theo từng tuần"
    s = S()
    s.g((box(10, 14, 54, 56, r=4), PAPER))
    s.g((box(10, 14, 54, 26, r=3.5), CORAL, 4))
    s.ln(stroke([(22, 9), (22, 19)], 0.2), 4).ln(stroke([(42, 9), (42, 19)], 0.2), 4)
    for i, (x, y) in enumerate([(19, 34), (28, 34), (37, 34), (46, 34), (19, 43), (28, 43), (37, 43), (46, 43)]):
        if i != 6:
            s.dot(x + R.uniform(-0.4, 0.4), y + R.uniform(-0.4, 0.4), 1.6, "#8C86B5")
    s.ln(blob(37, 43, 5.2, 4.6, n=7, j=0.12), 2.2, "#E5484D")
    return s


def chart():  # cột — "7 ngày vừa qua"
    s = S()
    s.g((box(12, 34, 22, 52, r=2.2), MINT, 4))
    s.g((box(27, 20, 37, 52, r=2.2), SUN, 4))
    s.g((box(42, 28, 52, 52, r=2.2), GRAPE, 4))
    s.ln(stroke([(7.5, 53.5), (56.5, 53)], 0.3), 3)
    return s


def lock():  # ổ khóa — "Bí mật của tớ"
    s = S()
    s.ln(stroke([(22, 31), (21.5, 20), (26, 12.5), (32, 11), (38, 12.5), (42.5, 20), (42, 31)], 0.3), 5.5)
    s.g((box(13, 29, 51, 56, r=4.5), SUN))
    s.dot(32, 39.5, 3.2)
    s.ln(stroke([(32, 41), (32, 48)], 0.2), 3.2)
    s.hi(stroke([(17.5, 35), (17.5, 46)], 0.2))
    return s


def medal():  # huy chương — "Ngôi sao đúng giờ"
    s = S()
    s.g((rpoly([(18, 30), (28, 33), (22, 59), (17.5, 53.5), (11.5, 55)], r=1.6), PINK, 4),
        (rpoly([(46, 30), (36, 33), (42, 59), (46.5, 53.5), (52.5, 55)], r=1.6), GRAPE, 4))
    s.g((blob(32, 25, 18, n=10, j=0.03), GOLD))
    s.g((rpoly(star_pts(32, 26, 10.5, 4.8), r=1.4, j=0.35), "#FFF1B8", 3.4))
    s.hi(stroke([(18.5, 23), (21, 16.5)], 0.2))
    return s


STICKERS = {
    "clock": clock, "explore": explore, "notebook": notebook, "shield": shield, "book": book, "game": game,
    "sun": sun, "moon": moon, "puzzle": puzzle, "globe": globe, "hand": hand, "star": star, "check": check,
    "cross": cross, "gift": gift, "pencil": pencil, "calendar": calendar, "chart": chart, "lock": lock, "medal": medal,
}


def main() -> None:
    global R
    for d in OUT:
        d.mkdir(parents=True, exist_ok=True)
    for name, fn in STICKERS.items():
        R = random.Random(zlib.crc32(name.encode()))
        rot = R.uniform(-5, 5)
        text = fn().svg(rot)
        for d in OUT:
            (d / f"{name}.svg").write_text(text, encoding="utf-8")
    print(f"Đã ghi {len(STICKERS)} nhãn vào:", *[str(d.relative_to(ROOT)) for d in OUT], sep="\n  ")


if __name__ == "__main__":
    main()
