"""
tools/gen_mascots.py — Sinh bộ mascot SVG GỐC của OGK (vẽ bằng hình học, không dùng tài sản bên ngoài).

Phong cách (bản 2 — "chibi nét vẽ tay"): nét viền nâu đậm dày, bo tròn đầu nét như vẽ bút dạ; thân tròn
mũm mĩm; mắt đen to có đốm sáng; má hồng có gạch chéo "///"; miệng chữ ω; tay chân ngắn cũn. Đây chỉ là
PHONG CÁCH vẽ phổ biến của tranh kawaii — cả ba nhân vật đều là thiết kế riêng của OGK, giữ màu nhận diện:
  tictac (Tíc-Tắc, đồng hồ báo thức san hô #FF6B6B -> #FF8E53) — quản lý thời gian; kim đồng hồ trên trán quay
  khien  (Khiên Xanh, chiếc khiên xanh dương #2563EB -> #3B82F6, mặt trắng) — an toàn trên mạng
  sao    (Sao Nhỏ, ngôi sao tím pastel #8B5CF6 đội mũ tốt nghiệp mint #10B981) — bạn học, khích lệ
Biểu cảm: happy, encourage, remind, sleepy, celebrate (+ "blink" = khung mắt nhắm cho Tray tự chớp mắt).
Không có biểu cảm giận dữ/thất vọng (nguyên tắc UX cho trẻ: khích lệ thay vì trừng phạt).

Chuyển động viết bằng CSS @keyframes NGAY TRONG tệp SVG => chạy được cả khi chèn bằng <img> trên web
(trình duyệt chạy hoạt ảnh khai báo trong ảnh SVG, không chạy script). Qt (Tray) bỏ qua <style> nên
vẽ khung tĩnh; Tray tự tạo hiệu ứng chớp mắt bằng cách luân phiên tệp *_happy.svg và *_blink.svg.
Mọi màu/nét đặt bằng THUỘC TÍNH trình bày (fill=, stroke=) để Qt SVG (SVG Tiny 1.2) vẽ đúng.

Chạy: python tools/gen_mascots.py  -> dashboard/static/mascots/*.svg, agent/tray/assets/*.svg,
                                     dashboard/static/img/deco_*.svg (hình trang trí góc thẻ)
"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [ROOT / "dashboard" / "static" / "mascots", ROOT / "agent" / "tray" / "assets"]
DECO_DIR = ROOT / "dashboard" / "static" / "img"

LINE = "#4A3530"     # nét viền: nâu đậm ấm (mềm hơn đen thuần)
EYE = "#3A2724"      # mắt, miệng
BLUSH = "#FFB3C2"    # má hồng
HATCH = "#EE7591"    # gạch chéo trên má
TONGUE = "#FF8FA3"
SW = 4.4             # độ dày nét viền chính (viewBox 160)
MOODS = ("happy", "encourage", "remind", "sleepy", "celebrate", "blink")
NAMES = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}

STYLE = """<style>
@keyframes f{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@keyframes s{0%,100%{transform:scaleX(1);opacity:.14}50%{transform:scaleX(.86);opacity:.08}}
@keyframes bl{0%,91%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}
@keyframes wv{0%,100%{transform:rotate(0)}50%{transform:rotate(-22deg)}}
@keyframes sp{to{transform:rotate(360deg)}}
@keyframes ck{0%,100%{opacity:.85}50%{opacity:1}}
@keyframes zz{0%{opacity:0;transform:translate(0,6px)}25%{opacity:1}100%{opacity:0;transform:translate(9px,-16px)}}
@keyframes pp{0%,100%{transform:scale(1) rotate(0)}50%{transform:scale(1.18) rotate(8deg)}}
@keyframes jg{0%,100%{transform:rotate(0)}25%{transform:rotate(-7deg)}75%{transform:rotate(7deg)}}
.b{animation:f 3.4s ease-in-out infinite}
.sh{transform-box:fill-box;transform-origin:center;animation:s 3.4s ease-in-out infinite}
.e{transform-box:fill-box;transform-origin:center;animation:bl 5.2s infinite}
.w{transform-box:fill-box;animation:wv 1.8s ease-in-out infinite}
.hm{transform-origin:80px 66px;animation:sp 10s linear infinite}
.hh{transform-origin:80px 66px;animation:sp 120s linear infinite}
.ck{animation:ck 3.4s ease-in-out infinite}
.z{animation:zz 2.8s ease-in-out infinite}.z2{animation-delay:1.4s}
.pp{transform-box:fill-box;transform-origin:center;animation:pp 1.7s ease-in-out infinite}
.jg{transform-box:fill-box;transform-origin:50% 90%;animation:jg 1.2s ease-in-out infinite}
.d2{animation-delay:.5s}.d3{animation-delay:1s}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>"""


def ln(w: float = SW) -> str:
    """Thuộc tính nét viền nâu, đầu nét + góc bo tròn (cảm giác bút dạ)."""
    return f'stroke="{LINE}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


# ------------------------------------------------------------------ bộ phận khuôn mặt dùng chung
def eyes(mood: str, lx: float, rx: float, y: float, s: float = 1.0) -> str:
    if mood in ("sleepy", "blink"):  # mắt nhắm: cung cong xuống ︶
        out = "".join(f'<path d="M{x - 6.5 * s} {y - 1} Q{x} {y + 5.5 * s} {x + 6.5 * s} {y - 1}" fill="none" {ln(3.2)}/>'
                      for x in (lx, rx))
        if mood == "sleepy":  # mi dưới nho nhỏ
            out += "".join(f'<path d="M{x - 6.8 * s} {y - 1} l-2.4 -1.6 M{x + 6.8 * s} {y - 1} l2.4 -1.6" fill="none" {ln(2)}/>'
                           for x in (lx, rx))
        return out
    if mood == "celebrate":  # mắt cười tít > <
        return (f'<path d="M{lx - 5 * s} {y - 6 * s} L{lx + 4.5 * s} {y} L{lx - 5 * s} {y + 6 * s}" fill="none" {ln(3.4)}/>'
                f'<path d="M{rx + 5 * s} {y - 6 * s} L{rx - 4.5 * s} {y} L{rx + 5 * s} {y + 6 * s}" fill="none" {ln(3.4)}/>')
    big = 1.12 if mood == "encourage" else 1.0
    dx = 1.4 if mood == "remind" else 0.0  # "nhớ nhé": liếc nhẹ sang bên
    out = ""
    for x in (lx, rx):
        rxe, rye = 6.4 * s * big, 7.6 * s * big
        out += (f'<g class="e"><ellipse cx="{x + dx}" cy="{y}" rx="{rxe:.2f}" ry="{rye:.2f}" fill="{EYE}"/>'
                f'<circle cx="{x + dx + 2.1 * s:.2f}" cy="{y - 2.9 * s:.2f}" r="{2.7 * s * big:.2f}" fill="#FFFFFF"/>'
                f'<circle cx="{x + dx - 2.3 * s:.2f}" cy="{y + 3.1 * s:.2f}" r="{1.25 * s:.2f}" fill="#FFFFFF"/></g>')
    return out


def mouth(mood: str, x: float, y: float) -> str:
    if mood in ("happy", "blink"):  # chữ ω
        return f'<path d="M{x - 7} {y - 1} Q{x - 3.5} {y + 5} {x} {y} Q{x + 3.5} {y + 5} {x + 7} {y - 1}" fill="none" {ln(2.8)}/>'
    if mood in ("encourage", "celebrate"):  # miệng mở cười + lưỡi hồng
        w, h = (8, 11) if mood == "encourage" else (10, 14)
        return (f'<path d="M{x - w} {y - 2} Q{x} {y + h} {x + w} {y - 2} Q{x} {y + 1} {x - w} {y - 2} Z" fill="{EYE}" {ln(2.4)}/>'
                f'<path d="M{x - w * .5} {y + h * .48} Q{x} {y + h * .2} {x + w * .5} {y + h * .48} Q{x} {y + h * .78} {x - w * .5} {y + h * .48} Z" fill="{TONGUE}"/>')
    if mood == "remind":  # miệng tròn nhỏ "ồ"
        return f'<ellipse cx="{x}" cy="{y + 1}" rx="3" ry="3.6" fill="{EYE}"/>'
    # sleepy: miệng nhỏ xíu
    return f'<path d="M{x - 3.5} {y} Q{x} {y + 3} {x + 3.5} {y}" fill="none" {ln(2.6)}/>'


def cheeks(lx: float, rx: float, y: float) -> str:
    """Má hồng + 3 gạch chéo — nét đặc trưng của tranh chibi."""
    out = '<g class="ck">'
    for cx in (lx, rx):
        out += f'<ellipse cx="{cx}" cy="{y}" rx="8.6" ry="5.4" fill="{BLUSH}"/>'
        out += "".join(f'<path d="M{cx - 5.5 + i * 4:.1f} {y + 2.6} L{cx - 2.7 + i * 4:.1f} {y - 2.6}" stroke="{HATCH}" '
                       f'stroke-width="1.5" stroke-linecap="round"/>' for i in range(3))
    return out + "</g>"


def sparkle(x: float, y: float, s: float, color: str, cls: str = "pp") -> str:
    """Ngôi sao 4 cánh nhỏ (lấp lánh), có viền nâu mảnh cho hợp nét vẽ tay."""
    return (f'<path class="{cls}" d="M{x} {y - s} Q{x + s * .2} {y - s * .2} {x + s} {y} Q{x + s * .2} {y + s * .2} {x} {y + s} '
            f'Q{x - s * .2} {y + s * .2} {x - s} {y} Q{x - s * .2} {y - s * .2} {x} {y - s} Z" fill="{color}" {ln(1.6)}/>')


def bubble_bang(x: float, y: float) -> str:
    """Bong bóng "!" nhỏ cạnh đầu (biểu cảm nhắc nhở — không phải cảnh báo đỏ)."""
    return (f'<g class="jg"><rect x="{x - 11}" y="{y - 14}" width="22" height="26" rx="9" fill="#FFFFFF" {ln(2.6)}/>'
            f'<path d="M{x} {y - 7} L{x} {y + 1}" stroke="#FF8E53" stroke-width="3.6" stroke-linecap="round"/>'
            f'<circle cx="{x}" cy="{y + 6.5}" r="2.1" fill="#FF8E53"/></g>')


def extras(mood: str) -> str:
    """Hiệu ứng quanh nhân vật theo biểu cảm (vẽ ngoài nhóm .b nên không nhấp nhô theo thân)."""
    if mood == "sleepy":  # chữ z bay lên (vẽ bằng path, không phụ thuộc phông chữ)
        return (f'<path class="z" d="M120 30 h11 l-11 12 h11" fill="none" stroke="#7C83DB" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<path class="z z2" d="M136 14 h8 l-8 9 h8" fill="none" stroke="#A5ACF0" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
    if mood == "celebrate":  # hoa giấy
        bits = [(18, 34, "#FFC23A", 0), (142, 30, "#26B685", 1), (12, 80, "#47AEF5", 2), (150, 76, "#FF74A0", 0),
                (34, 12, "#9A7BFF", 1), (126, 10, "#FF8A1F", 2)]
        out = ""
        for i, (x, y, c, d) in enumerate(bits):
            dcls = ["", " d2", " d3"][d]
            if i % 2:
                out += f'<rect class="pp{dcls}" x="{x - 4}" y="{y - 2.5}" width="8" height="5" rx="2" fill="{c}" transform="rotate({20 + i * 25} {x} {y})"/>'
            else:
                out += f'<circle class="pp{dcls}" cx="{x}" cy="{y}" r="4" fill="{c}"/>'
        return out
    if mood == "encourage":
        return sparkle(138, 28, 9, "#FFD54A") + sparkle(22, 42, 6.5, "#FFE38A", "pp d2")
    return ""


def shadow() -> str:
    return '<ellipse class="sh" cx="80" cy="153" rx="36" ry="5" fill="#4338CA" opacity=".14"/>'


def svg(kind: str, mood: str, defs: str, body: str, after: str = "") -> str:
    title = NAMES[kind]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" width="160" height="160" role="img" '
            f'aria-label="{title}"><title>{title}</title>{STYLE}<defs>{defs}</defs>{shadow()}{extras(mood)}'
            f'<g class="b">{body}</g>{after}</svg>')


def arm(x: float, y: float, angle: float, fill: str, w: float = 13, h: float = 24, cls: str = "", origin: str = "") -> str:
    """Tay ngắn cũn: viên nang bo tròn, (x, y) là vai; angle=0 => thõng xuống."""
    st = f' style="transform-origin:{origin}"' if origin else ""
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}{st}><rect x="{x - w / 2}" y="{y - 3}" width="{w}" height="{h}" rx="{w / 2}" fill="{fill}" {ln(3.6)} '
            f'transform="rotate({angle} {x} {y})"/></g>')


def grad(gid: str, a: str, b: str, x2: float = .3, y2: float = 1) -> str:
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}"><stop offset="0" stop-color="{a}"/>'
            f'<stop offset="1" stop-color="{b}"/></linearGradient>')


def face_grad(gid: str) -> str:
    return (f'<radialGradient id="{gid}" cx=".42" cy=".34" r=".8"><stop offset="0" stop-color="#FFFFFF"/>'
            f'<stop offset="1" stop-color="#FFF4EC"/></radialGradient>')


def arms_for(mood: str, lx: float, rx: float, y: float, fill: str) -> tuple[str, str]:
    """(tay trái, tay phải) theo biểu cảm. Tay giơ cao = vẫy (happy/blink) hoặc ăn mừng/cổ vũ."""
    down_l, down_r = arm(lx, y, 38, fill), arm(rx, y, -38, fill)
    up_r = arm(rx, y - 6, -150, fill, cls="w", origin="15% 90%")
    up_l = arm(lx, y - 6, 150, fill)
    if mood in ("happy", "blink"):
        return down_l, up_r
    if mood == "celebrate":
        return up_l, arm(rx, y - 6, -150, fill)
    if mood == "encourage":
        return down_l, arm(rx, y - 6, -160, fill)
    if mood == "remind":
        return down_l, arm(rx, y - 6, -168, fill, w=12, h=24)
    return arm(lx, y, 18, fill), arm(rx, y, -18, fill)  # sleepy: tay thõng


# ------------------------------------------------------------------ Tíc-Tắc: đồng hồ báo thức
def bell(cx: float, cy: float, rot: float, fill: str) -> str:
    return (f'<g transform="rotate({rot} {cx} {cy})"><path d="M{cx - 15} {cy + 7} Q{cx - 16} {cy - 15} {cx} {cy - 15} '
            f'Q{cx + 16} {cy - 15} {cx + 15} {cy + 7} Z" fill="{fill}" {ln()}/>'
            f'<path d="M{cx - 8} {cy - 6} Q{cx - 6} {cy - 10} {cx - 1} {cy - 11}" fill="none" stroke="#FFFFFF" stroke-opacity=".75" '
            f'stroke-width="3" stroke-linecap="round"/></g>')


def tictac(mood: str) -> str:
    p = f"tt{mood}"
    defs = grad(f"{p}b", "#FF9A62", "#FF6B6B", .35, 1) + face_grad(f"{p}f")
    body_fill = f"url(#{p}b)"
    arm_l, arm_r = arms_for(mood, 33, 127, 98, body_fill)
    ring = mood == "remind"  # nhắc giờ: chuông rung
    bells = (f'<g{" class=\"jg\"" if ring else ""}>{bell(45, 44, -30, body_fill)}</g>'
             f'<g{" class=\"jg d2\"" if ring else ""}>{bell(115, 44, 30, body_fill)}</g>')
    body = (
        # chân, núm chuông, chuông (nằm SAU thân)
        f'<rect x="56" y="126" width="16" height="20" rx="8" fill="{body_fill}" {ln(3.6)}/>'
        f'<rect x="88" y="126" width="16" height="20" rx="8" fill="{body_fill}" {ln(3.6)}/>'
        f'<path d="M80 41 L80 30" {ln(4)}/><circle cx="80" cy="27" r="5.5" fill="{body_fill}" {ln(3.4)}/>'
        f'{bells}{arm_l}{arm_r}'
        # thân tròn + mặt đồng hồ trắng
        f'<circle cx="80" cy="90" r="50" fill="{body_fill}" {ln()}/>'
        f'<path d="M44 70 Q50 52 66 45" fill="none" stroke="#FFFFFF" stroke-opacity=".55" stroke-width="4.5" stroke-linecap="round"/>'
        f'<circle cx="80" cy="93" r="39" fill="url(#{p}f)" {ln(3.4)}/>'
        # vạch giờ 3–6–9 (mờ) + kim trên trán (quay chậm)
        f'<path d="M45.5 93 h4.5 M110 93 h4.5 M80 126 v5" stroke="{LINE}" stroke-opacity=".45" stroke-width="2.6" stroke-linecap="round"/>'
        f'<path class="hh" d="M80 66 L80 59" {ln(3)}/>'
        f'<path class="hm" d="M80 66 L88.5 61.5" {ln(2.6)}/>'
        f'<circle cx="80" cy="66" r="2.6" fill="{LINE}"/>'
        f'{cheeks(56, 104, 104)}{eyes(mood, 65, 95, 91)}{mouth(mood, 80, 102)}'
    )
    after = bubble_bang(142, 26) if mood == "remind" else ""
    return svg("tictac", mood, defs, body, after)


# ------------------------------------------------------------------ Khiên Xanh: chiếc khiên mặt trắng
SHIELD = ("M80 20 C97 28 114 31 130 31 Q136 31 136 37 L136 82 C136 114 113 135 80 148 "
          "C47 135 24 114 24 82 L24 37 Q24 31 30 31 C46 31 63 28 80 20 Z")
PLATE = ("M80 40 C93 45.5 106 48 118 48 L118 84 C118 108 102 123 80 132 C58 123 42 108 42 84 L42 48 "
         "C54 48 67 45.5 80 40 Z")


def star_points(cx: float, cy: float, ro: float, ri: float, n: int = 5) -> list[tuple[float, float]]:
    pts = []
    for i in range(n * 2):
        a = math.radians(-90 + i * 180 / n)
        r = ro if i % 2 == 0 else ri
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def rounded_poly(pts: list[tuple[float, float]], radii: list[float]) -> str:
    """Đa giác bo góc: tại mỗi đỉnh cắt một đoạn r dọc hai cạnh rồi nối bằng đường cong bậc hai."""
    n = len(pts)
    segs = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        r = radii[i % len(radii)]

        def toward(a, b, d):
            L = math.dist(a, b)
            return (a[0] + (b[0] - a[0]) * d / L, a[1] + (b[1] - a[1]) * d / L)
        segs.append((toward(p1, p0, r), p1, toward(p1, p2, r)))
    d = f"M{segs[0][2][0]:.1f} {segs[0][2][1]:.1f}"
    for i in range(1, n + 1):
        a, c, b = segs[i % n]
        d += f" L{a[0]:.1f} {a[1]:.1f} Q{c[0]:.1f} {c[1]:.1f} {b[0]:.1f} {b[1]:.1f}"
    return d + " Z"


def khien(mood: str) -> str:
    p = f"kx{mood}"
    defs = grad(f"{p}b", "#4C8DF8", "#2563EB", .35, 1) + face_grad(f"{p}f")
    blue = f"url(#{p}b)"
    arm_l, arm_r = arms_for(mood, 25, 135, 96, blue)
    emblem = rounded_poly(star_points(80, 30.5, 7.5, 3.6), [1.6, .8])
    body = (
        f'<rect x="58" y="128" width="16" height="20" rx="8" fill="{blue}" {ln(3.6)}/>'
        f'<rect x="86" y="128" width="16" height="20" rx="8" fill="{blue}" {ln(3.6)}/>'
        f'{arm_l}{arm_r}'
        f'<path d="{SHIELD}" fill="{blue}" {ln()}/>'
        f'<path d="M34 46 Q36 38 48 37" fill="none" stroke="#FFFFFF" stroke-opacity=".6" stroke-width="4.5" stroke-linecap="round"/>'
        f'<path d="{PLATE}" fill="url(#{p}f)" {ln(3.4)}/>'
        f'<path d="{emblem}" fill="#FFD54A" {ln(2.2)}/>'
        f'{cheeks(55, 105, 100)}{eyes(mood, 65, 95, 87)}{mouth(mood, 80, 98)}'
    )
    after = bubble_bang(144, 24) if mood == "remind" else ""
    return svg("khien", mood, defs, body, after)


# ------------------------------------------------------------------ Sao Nhỏ: ngôi sao tím đội mũ tốt nghiệp
def sao(mood: str) -> str:
    p = f"sn{mood}"
    defs = (grad(f"{p}b", "#EDE6FF", "#C4B2FF", .25, 1) + grad(f"{p}m", "#3FDDA5", "#10B981", .2, 1))
    star = rounded_poly(star_points(80, 92, 66, 33), [11, 6])
    pencil = ""
    if mood == "encourage":  # cầm bút chì mint: "mình cùng học nhé"
        pencil = (f'<g transform="rotate(26 134 96)"><rect x="128" y="70" width="12" height="40" rx="3" fill="url(#{p}m)" {ln(2.8)}/>'
                  f'<path d="M128 110 L134 123 L140 110 Z" fill="#FDE7C4" {ln(2.6)}/><path d="M132.2 119 L134 123 L135.8 119 Z" fill="{LINE}"/>'
                  f'<rect x="128" y="64" width="12" height="8" rx="3" fill="#FF9FB6" {ln(2.6)}/></g>')
    cap = (  # mũ tốt nghiệp mint đội lệch trên mũi sao
        f'<g transform="rotate(-12 80 26)">'
        f'<path d="M67 24 L67 33 Q80 39 93 33 L93 24 Z" fill="url(#{p}m)" {ln(3.2)}/>'
        f'<path d="M80 11 L106 21 L80 31 L54 21 Z" fill="url(#{p}m)" {ln(3.2)}/>'
        f'<path d="M80 21 Q96 23 101 26 L101 37" fill="none" stroke="#FFC23A" stroke-width="2.6" stroke-linecap="round"/>'
        f'<circle cx="101" cy="39.5" r="3.6" fill="#FFC23A" {ln(2)}/>'
        f'<circle cx="80" cy="21" r="2.4" fill="#FFC23A" {ln(1.6)}/></g>')
    body = (
        f'<path d="{star}" fill="url(#{p}b)" {ln()}/>'
        f'<path d="M58 70 Q62 60 70 55" fill="none" stroke="#FFFFFF" stroke-opacity=".8" stroke-width="4.5" stroke-linecap="round"/>'
        f'{cap}'
        f'{cheeks(59, 101, 103)}{eyes(mood, 67, 93, 91, .95)}{mouth(mood, 80, 101)}{pencil}'
    )
    after = bubble_bang(142, 30) if mood == "remind" else ""
    return svg("sao", mood, defs, body, after)


# ------------------------------------------------------------------ hình trang trí góc thẻ (Study-Buddy)
DECO = {
    "deco_ruler.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40" width="120" height="40" aria-hidden="true">'
                       f'<rect x="3" y="7" width="114" height="26" rx="8" fill="#34D399" stroke="{LINE}" stroke-width="3"/>'
                       + "".join(f'<rect x="{13 + i * 12}" y="{7 if i % 2 else 7}" width="2.6" height="{9 if i % 2 else 13}" rx="1.2" fill="{LINE}"/>'
                                 for i in range(9)) + '</svg>'),
    "deco_shapes.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140" width="140" height="140" aria-hidden="true">'
                        f'<path d="M98 16 L126 64 L70 64 Z" fill="#C4B5FD" stroke="{LINE}" stroke-width="3.5" stroke-linejoin="round"/>'
                        f'<circle cx="40" cy="98" r="21" fill="#FFD54A" stroke="{LINE}" stroke-width="3.5"/>'
                        f'<rect x="84" y="88" width="32" height="32" rx="9" fill="#6EE7B7" stroke="{LINE}" stroke-width="3.5" transform="rotate(18 100 104)"/>'
                        f'<path d="M14 32 q10 -12 20 0 t20 0" fill="none" stroke="#47AEF5" stroke-width="6" stroke-linecap="round"/></svg>'),
}

DRAW = {"tictac": tictac, "khien": khien, "sao": sao}


def main() -> None:
    n = 0
    for out in OUT_DIRS:
        out.mkdir(parents=True, exist_ok=True)
        for kind, fn in DRAW.items():
            for mood in MOODS:
                (out / f"{kind}_{mood}.svg").write_text(fn(mood), encoding="utf-8")
                n += 1
    DECO_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in DECO.items():
        (DECO_DIR / name).write_text(text, encoding="utf-8")
    print(f"Đã sinh {n} tệp mascot + {len(DECO)} hình trang trí")


if __name__ == "__main__":
    main()
