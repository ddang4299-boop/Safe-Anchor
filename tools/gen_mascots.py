"""
tools/gen_mascots.py — Sinh bộ mascot SVG GỐC của OGK (vẽ bằng hình học + gradient, không dùng tài sản bên ngoài).

Phong cách: khối hình học nhân hóa, gradient mềm có điểm sáng (highlight) tạo cảm giác khối, đôi mắt to
long lanh (2 đốm sáng), má hồng, chuyển động nhẹ để nhân vật trông như đang "thở":
  tictac (Tíc-Tắc, đồng hồ cam san hô #FF6B6B -> #FF8E53) — quản lý thời gian; kim đồng hồ quay chậm
  khien  (Khiên Xanh, khiên xanh dương #2563EB -> #3B82F6) — an toàn trên mạng; vẫy tay, cầm biển nhắc
  sao    (Sao Nhỏ, ngôi sao tím pastel #8B5CF6 + điểm nhấn mint #10B981) — bạn học, khích lệ, ăn mừng
Biểu cảm: happy, encourage, remind, sleepy, celebrate (+ "blink" = khung mắt nhắm cho Tray tự chớp mắt).
Không có biểu cảm giận dữ/thất vọng (nguyên tắc UX cho trẻ: khích lệ thay vì trừng phạt).

Chuyển động viết bằng CSS @keyframes NGAY TRONG tệp SVG => chạy được cả khi chèn bằng <img> trên web
(trình duyệt chạy hoạt ảnh khai báo trong ảnh SVG, không chạy script). Qt (Tray) bỏ qua <style> nên
vẽ khung tĩnh; Tray tự tạo hiệu ứng chớp mắt bằng cách luân phiên tệp *_happy.svg và *_blink.svg.

Chạy: python tools/gen_mascots.py  -> dashboard/static/mascots/*.svg, agent/tray/assets/*.svg,
                                     dashboard/static/img/deco_*.svg (hình trang trí góc thẻ)
"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [ROOT / "dashboard" / "static" / "mascots", ROOT / "agent" / "tray" / "assets"]
DECO_DIR = ROOT / "dashboard" / "static" / "img"

INK = "#2A2140"          # mắt/miệng: tím than ấm (mềm hơn đen thuần)
BLUSH = "#FF7FA0"
MOODS = ("happy", "encourage", "remind", "sleepy", "celebrate", "blink")
NAMES = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}

STYLE = """<style>
@keyframes f{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
@keyframes s{0%,100%{transform:scaleX(1);opacity:.18}50%{transform:scaleX(.86);opacity:.1}}
@keyframes bl{0%,90%,100%{transform:scaleY(1)}94%{transform:scaleY(.08)}}
@keyframes wv{0%,100%{transform:rotate(0)}50%{transform:rotate(-26deg)}}
@keyframes sp{to{transform:rotate(360deg)}}
@keyframes ck{0%,100%{opacity:.45}50%{opacity:.8}}
@keyframes zz{0%{opacity:0;transform:translate(0,6px)}25%{opacity:1}100%{opacity:0;transform:translate(9px,-16px)}}
@keyframes pp{0%,100%{transform:scale(1) rotate(0)}50%{transform:scale(1.18) rotate(8deg)}}
.b{animation:f 3.4s ease-in-out infinite}
.sh{transform-box:fill-box;transform-origin:center;animation:s 3.4s ease-in-out infinite}
.e{transform-box:fill-box;transform-origin:center;animation:bl 5.2s infinite}
.w{transform-box:fill-box;animation:wv 1.8s ease-in-out infinite}
.hm{transform-origin:80px 90px;animation:sp 12s linear infinite}
.hh{transform-origin:80px 90px;animation:sp 144s linear infinite}
.ck{animation:ck 3.4s ease-in-out infinite}
.z{animation:zz 2.8s ease-in-out infinite}.z2{animation-delay:1.4s}
.pp{transform-box:fill-box;transform-origin:center;animation:pp 1.7s ease-in-out infinite}
.d2{animation-delay:.5s}.d3{animation-delay:1s}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>"""


# ------------------------------------------------------------------ bộ phận dùng chung
def eyes(mood: str, lx: float, rx: float, y: float, kind: str = "white", r: float = 11.0) -> str:
    """kind='white': lòng trắng + đồng tử (thân màu đậm); kind='dark': mắt tròn đậm (mặt sáng màu)."""
    if mood in ("sleepy", "blink"):  # mắt nhắm: cong xuống, có mi
        out = ""
        for x in (lx, rx):
            out += (f'<path d="M{x - r * .85} {y} Q{x} {y + r * .8} {x + r * .85} {y}" fill="none" stroke="{INK}" '
                    f'stroke-width="3.4" stroke-linecap="round"/>')
            if mood == "sleepy":
                out += (f'<path d="M{x - r * .55} {y + r * .45} l-2.5 3.2 M{x + r * .55} {y + r * .45} l2.5 3.2" '
                        f'stroke="{INK}" stroke-width="2" stroke-linecap="round"/>')
        return out
    if mood == "celebrate":  # mắt cười ^ ^
        return "".join(f'<path d="M{x - r * .85} {y + 3} Q{x} {y - r} {x + r * .85} {y + 3}" fill="none" stroke="{INK}" '
                       f'stroke-width="3.8" stroke-linecap="round"/>' for x in (lx, rx))
    dx, dy = {"happy": (1.6, 1.2), "encourage": (0, -3.2), "remind": (3.6, 0.6)}[mood]
    out = ""
    for x in (lx, rx):
        out += '<g class="e">'
        if kind == "white":
            out += f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * 1.12}" fill="#FFFFFF"/>'
            out += f'<ellipse cx="{x + dx}" cy="{y + dy}" rx="{r * .62}" ry="{r * .7}" fill="{INK}"/>'
            px, py = x + dx, y + dy
        else:
            out += f'<ellipse cx="{x}" cy="{y}" rx="{r * .82}" ry="{r}" fill="{INK}"/>'
            px, py = x + dx * .4, y + dy * .4
        # 2 đốm sáng: mắt "long lanh"
        out += f'<circle cx="{px + r * .26}" cy="{py - r * .32}" r="{r * .3}" fill="#FFFFFF"/>'
        out += f'<circle cx="{px - r * .28}" cy="{py + r * .3}" r="{r * .13}" fill="#FFFFFF" opacity=".9"/>'
        out += '</g>'
    if mood == "remind":  # lông mày nhướng nhẹ: "này, nhớ nhé"
        out += "".join(f'<path d="M{x - 7} {y - r * 1.55} Q{x} {y - r * 1.95} {x + 7} {y - r * 1.55}" fill="none" '
                       f'stroke="{INK}" stroke-width="2.6" stroke-linecap="round"/>' for x in (lx, rx))
    return out


def mouth(mood: str, x: float, y: float) -> str:
    if mood == "happy":
        return f'<path d="M{x - 9} {y} Q{x} {y + 10} {x + 9} {y}" fill="none" stroke="{INK}" stroke-width="3.6" stroke-linecap="round"/>'
    if mood == "blink":
        return f'<path d="M{x - 9} {y} Q{x} {y + 10} {x + 9} {y}" fill="none" stroke="{INK}" stroke-width="3.6" stroke-linecap="round"/>'
    if mood == "encourage":
        return (f'<path d="M{x - 11} {y - 2} Q{x} {y + 15} {x + 11} {y - 2} Z" fill="{INK}"/>'
                f'<path d="M{x - 5.5} {y + 6.5} Q{x} {y + 3.5} {x + 5.5} {y + 6.5} Q{x} {y + 11} {x - 5.5} {y + 6.5} Z" fill="#FF7A8A"/>')
    if mood == "remind":
        return f'<ellipse cx="{x}" cy="{y + 2}" rx="4.6" ry="5.2" fill="{INK}"/>'
    if mood == "sleepy":
        return f'<path d="M{x - 5} {y + 1} Q{x} {y + 4.5} {x + 5} {y + 1}" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>'
    # celebrate: miệng mở to + lưỡi
    return (f'<path d="M{x - 14} {y - 3} Q{x} {y + 21} {x + 14} {y - 3} Z" fill="{INK}"/>'
            f'<path d="M{x - 7} {y + 9} Q{x} {y + 5} {x + 7} {y + 9} Q{x} {y + 15.5} {x - 7} {y + 9} Z" fill="#FF7A8A"/>')


def cheeks(lx: float, rx: float, y: float, color: str = BLUSH) -> str:
    return (f'<g class="ck"><ellipse cx="{lx}" cy="{y}" rx="8.5" ry="5.2" fill="{color}" opacity=".6"/>'
            f'<ellipse cx="{rx}" cy="{y}" rx="8.5" ry="5.2" fill="{color}" opacity=".6"/></g>')


def sparkle(x: float, y: float, s: float, color: str, cls: str = "pp") -> str:
    """Ngôi sao 4 cánh nhỏ (lấp lánh)."""
    return (f'<path class="{cls}" d="M{x} {y - s} Q{x + s * .18} {y - s * .18} {x + s} {y} Q{x + s * .18} {y + s * .18} {x} {y + s} '
            f'Q{x - s * .18} {y + s * .18} {x - s} {y} Q{x - s * .18} {y - s * .18} {x} {y - s} Z" fill="{color}"/>')


def extras(mood: str) -> str:
    """Hiệu ứng quanh nhân vật theo biểu cảm (vẽ ngoài nhóm .b nên không nhấp nhô theo thân)."""
    if mood == "sleepy":  # chữ z bay lên (vẽ bằng path, không phụ thuộc phông chữ)
        return (f'<path class="z" d="M118 30 h11 l-11 12 h11" fill="none" stroke="#7C83DB" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<path class="z z2" d="M134 14 h8 l-8 9 h8" fill="none" stroke="#A5ACF0" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
    if mood == "celebrate":  # hoa giấy
        bits = [(22, 30, "#FFC23A", 0), (138, 26, "#26B685", 1), (16, 78, "#47AEF5", 2), (146, 70, "#FF74A0", 0),
                (34, 12, "#9A7BFF", 1), (124, 8, "#FF8A1F", 2)]
        out = ""
        for i, (x, y, c, d) in enumerate(bits):
            dcls = ["", " d2", " d3"][d]
            if i % 2:
                out += f'<rect class="pp{dcls}" x="{x - 4}" y="{y - 2.5}" width="8" height="5" rx="2" fill="{c}" transform="rotate({20 + i * 25} {x} {y})"/>'
            else:
                out += f'<circle class="pp{dcls}" cx="{x}" cy="{y}" r="4" fill="{c}"/>'
        return out
    if mood == "encourage":
        return sparkle(134, 30, 10, "#FFC23A") + sparkle(24, 44, 7, "#FFD978", "pp d2")
    return ""


def shadow() -> str:
    return '<ellipse class="sh" cx="80" cy="152" rx="40" ry="6" fill="#4338CA" opacity=".18"/>'


def svg(kind: str, mood: str, defs: str, body: str) -> str:
    title = NAMES[kind]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" width="160" height="160" role="img" '
            f'aria-label="{title}"><title>{title}</title>{STYLE}<defs>{defs}</defs>{shadow()}{extras(mood)}'
            f'<g class="b">{body}</g></svg>')


# ------------------------------------------------------------------ Tíc-Tắc: đồng hồ báo thức
def tictac(mood: str) -> str:
    p = f"tt{mood}"
    defs = (f'<linearGradient id="{p}b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FF8E53"/>'
            f'<stop offset="1" stop-color="#FF6B6B"/></linearGradient>'
            f'<linearGradient id="{p}l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FF9E6A"/>'
            f'<stop offset="1" stop-color="#F25F5C"/></linearGradient>'
            f'<radialGradient id="{p}f" cx=".45" cy=".35" r=".75"><stop offset="0" stop-color="#FFFFFF"/>'
            f'<stop offset="1" stop-color="#FFE9DD"/></radialGradient>')
    dark = "#E5545A"
    # tay: tay trái tĩnh; tay phải vẫy (happy) / giơ cao (celebrate, remind)
    arm_l = f'<rect x="10" y="88" width="26" height="12" rx="6" fill="url(#{p}l)" transform="rotate(22 23 94)"/>'
    if mood == "celebrate":
        arm_l = f'<rect x="12" y="52" width="12" height="30" rx="6" fill="url(#{p}l)" transform="rotate(-28 18 67)"/>'
    if mood in ("happy", "celebrate", "remind", "blink"):
        arm_r = (f'<g class="w" style="transform-origin:15% 92%"><rect x="134" y="66" width="12" height="30" rx="6" '
                 f'fill="url(#{p}l)" transform="rotate(30 140 81)"/><circle cx="148" cy="64" r="7.5" fill="url(#{p}l)"/></g>')
    else:
        arm_r = f'<rect x="124" y="88" width="26" height="12" rx="6" fill="url(#{p}l)" transform="rotate(-22 137 94)"/>'
    ticks = "".join(
        f'<rect x="78" y="{50 - 1}" width="4" height="9" rx="2" fill="#FFB49C" transform="rotate({a} 80 90)"/>'
        for a in (0, 90, 180, 270))
    dots = "".join(
        f'<circle cx="{80 + 37 * math.sin(math.radians(a)):.1f}" cy="{90 - 37 * math.cos(math.radians(a)):.1f}" r="1.7" fill="#FFCDBA"/>'
        for a in range(30, 360, 30) if a % 90)
    body = (
        # chuông + núm
        f'<rect x="73" y="18" width="14" height="16" rx="7" fill="{dark}"/>'
        f'<circle cx="40" cy="38" r="18" fill="url(#{p}l)"/><circle cx="120" cy="38" r="18" fill="url(#{p}l)"/>'
        f'<ellipse cx="34" cy="31" rx="6.5" ry="4" fill="#FFFFFF" opacity=".5" transform="rotate(-35 34 31)"/>'
        f'<ellipse cx="114" cy="31" rx="6.5" ry="4" fill="#FFFFFF" opacity=".5" transform="rotate(-35 114 31)"/>'
        # chân
        f'<path d="M58 132 L50 146 M102 132 L110 146" stroke="{dark}" stroke-width="7" stroke-linecap="round"/>'
        f'<ellipse cx="47" cy="148" rx="11" ry="5.5" fill="{dark}"/><ellipse cx="113" cy="148" rx="11" ry="5.5" fill="{dark}"/>'
        f'{arm_l}{arm_r}'
        # thân + vành sáng
        f'<circle cx="80" cy="88" r="56" fill="url(#{p}b)"/>'
        f'<path d="M38 62 A52 52 0 0 1 78 34" stroke="#FFFFFF" stroke-opacity=".42" stroke-width="7" stroke-linecap="round" fill="none"/>'
        # mặt đồng hồ
        f'<circle cx="80" cy="90" r="44" fill="url(#{p}f)"/>{ticks}{dots}'
        # kim đồng hồ: màu nhạt, quay chậm phía sau nét mặt
        f'<rect class="hh" x="77.5" y="72" width="5" height="20" rx="2.5" fill="#FFC9B6"/>'
        f'<rect class="hm" x="78" y="60" width="4" height="32" rx="2" fill="#FFD9CB"/>'
        f'<circle cx="80" cy="90" r="4.5" fill="#FFC1AC"/>'
        f'{cheeks(56, 104, 102)}{eyes(mood, 64, 96, 84, "dark", 10.5)}{mouth(mood, 80, 104)}'
    )
    return svg("tictac", mood, defs, body)


# ------------------------------------------------------------------ Khiên Xanh: khiên bảo vệ
SHIELD = ("M80 16 C96 25 113 29 128 29 C132 29 135 32 135 36 L135 80 C135 113 112 135 80 147 "
          "C48 135 25 113 25 80 L25 36 C25 32 28 29 32 29 C47 29 64 25 80 16 Z")
SHIELD_IN = "M80 28 C94 35 109 38 122 38 L122 80 C122 106 104 124 80 134 C56 124 38 106 38 80 L38 38 C51 38 66 35 80 28 Z"


def khien(mood: str) -> str:
    p = f"kx{mood}"
    defs = (f'<linearGradient id="{p}b" x1="0" y1="0" x2=".4" y2="1"><stop offset="0" stop-color="#3B82F6"/>'
            f'<stop offset="1" stop-color="#2563EB"/></linearGradient>'
            f'<linearGradient id="{p}a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4F8FF7"/>'
            f'<stop offset="1" stop-color="#2F6BE8"/></linearGradient>')
    arm_l = f'<rect x="8" y="84" width="26" height="12" rx="6" fill="url(#{p}a)" transform="rotate(24 21 90)"/>'
    if mood == "celebrate":
        arm_l = f'<rect x="10" y="44" width="12" height="32" rx="6" fill="url(#{p}a)" transform="rotate(-26 16 60)"/>'
    if mood == "remind":  # cầm biển nhắc nhỏ có trái tim
        arm_r = (f'<rect x="122" y="78" width="22" height="12" rx="6" fill="url(#{p}a)" transform="rotate(-35 133 84)"/>'
                 f'<rect x="131" y="34" width="4" height="50" rx="2" fill="#C2894B"/>'
                 f'<rect x="111" y="8" width="44" height="30" rx="10" fill="#FFF8E8" stroke="#FFC23A" stroke-width="3"/>'
                 f'<path d="M133 32 C124 26 121 21 124.5 17.5 C127 15 130.5 15.8 133 18.8 C135.5 15.8 139 15 141.5 17.5 '
                 f'C145 21 142 26 133 32 Z" fill="#FF6B8A"/>')
    elif mood in ("happy", "celebrate", "blink"):
        arm_r = (f'<g class="w" style="transform-origin:15% 92%"><rect x="130" y="44" width="12" height="34" rx="6" '
                 f'fill="url(#{p}a)" transform="rotate(24 136 61)"/><circle cx="143" cy="42" r="7.5" fill="url(#{p}a)"/></g>')
    elif mood == "encourage":  # giơ ngón cái
        arm_r = (f'<rect x="126" y="80" width="24" height="12" rx="6" fill="url(#{p}a)" transform="rotate(-30 138 86)"/>'
                 f'<rect x="140" y="58" width="16" height="18" rx="7" fill="url(#{p}a)"/>'
                 f'<rect x="145" y="44" width="7" height="18" rx="3.5" fill="url(#{p}a)"/>')
    else:
        arm_r = f'<rect x="126" y="84" width="26" height="12" rx="6" fill="url(#{p}a)" transform="rotate(-24 139 90)"/>'
    body = (
        f'<path d="M58 134 L54 146 M102 134 L106 146" stroke="#1D4ED8" stroke-width="7" stroke-linecap="round"/>'
        f'<ellipse cx="52" cy="148" rx="11" ry="5.5" fill="#1D4ED8"/><ellipse cx="108" cy="148" rx="11" ry="5.5" fill="#1D4ED8"/>'
        f'{arm_l}{arm_r}'
        f'<path d="{SHIELD}" fill="url(#{p}b)"/>'
        f'<path d="{SHIELD_IN}" fill="none" stroke="#BFDBFE" stroke-opacity=".55" stroke-width="3"/>'
        f'<path d="M38 46 C52 44 64 39 76 32" stroke="#FFFFFF" stroke-opacity=".5" stroke-width="6" stroke-linecap="round" fill="none"/>'
        # huy hiệu dấu tích trên trán
        f'<circle cx="80" cy="52" r="10" fill="#DBEAFE"/>'
        f'<path d="M75 52.5 L78.6 56 L85.5 48.8" stroke="#2563EB" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        f'{cheeks(52, 108, 102)}{eyes(mood, 63, 97, 84, "white", 12)}{mouth(mood, 80, 106)}'
    )
    return svg("khien", mood, defs, body)


# ------------------------------------------------------------------ Sao Nhỏ: ngôi sao bạn học
def star_path(cx: float, cy: float, ro: float, ri: float) -> str:
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        r = ro if i % 2 == 0 else ri
        pts.append(f"{cx + r * math.cos(a):.1f} {cy + r * math.sin(a):.1f}")
    return "M" + " L".join(pts) + " Z"


def sao(mood: str) -> str:
    p = f"sn{mood}"
    defs = (f'<linearGradient id="{p}b" x1="0" y1="0" x2=".3" y2="1"><stop offset="0" stop-color="#A78BFA"/>'
            f'<stop offset="1" stop-color="#8B5CF6"/></linearGradient>'
            f'<linearGradient id="{p}m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#34D399"/>'
            f'<stop offset="1" stop-color="#10B981"/></linearGradient>')
    star = star_path(80, 90, 60, 30)
    pencil = ""
    if mood == "encourage":  # cầm bút chì mint: "mình cùng học nhé"
        pencil = (f'<g transform="rotate(28 132 98)"><rect x="126" y="70" width="12" height="44" rx="4" fill="url(#{p}m)"/>'
                  f'<path d="M126 114 L132 126 L138 114 Z" fill="#FDE7C4"/><path d="M130.4 121.5 L132 126 L133.6 121.5 Z" fill="{INK}"/>'
                  f'<rect x="126" y="66" width="12" height="7" rx="3" fill="#FF9FB6"/></g>')
    body = (
        f'<path d="{star}" fill="url(#{p}b)" stroke="url(#{p}b)" stroke-width="14" stroke-linejoin="round"/>'
        f'<path d="M56 64 L68 44" stroke="#FFFFFF" stroke-opacity=".5" stroke-width="6" stroke-linecap="round"/>'
        f'{sparkle(80, 34, 7, "#6EE7B7", "pp")}'
        f'{cheeks(57, 103, 104, "#FFB3D9")}{eyes(mood, 66, 94, 88, "white", 10.5)}{mouth(mood, 80, 106)}{pencil}'
    )
    return svg("sao", mood, defs, body)


# ------------------------------------------------------------------ hình trang trí góc thẻ (Study-Buddy)
DECO = {
    "deco_ruler.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40" width="120" height="40" aria-hidden="true">'
                       '<rect x="2" y="6" width="116" height="28" rx="8" fill="#10B981"/><rect x="2" y="6" width="116" height="10" rx="5" fill="#34D399"/>'
                       + "".join(f'<rect x="{12 + i * 12}" y="{20 if i % 2 else 16}" width="2.5" height="{10 if i % 2 else 14}" rx="1.2" fill="#ECFDF5"/>'
                                 for i in range(9)) + '</svg>'),
    "deco_shapes.svg": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140" width="140" height="140" aria-hidden="true">'
                        '<path d="M98 14 L128 66 L68 66 Z" fill="#8B5CF6" opacity=".9" stroke="#8B5CF6" stroke-width="10" stroke-linejoin="round"/>'
                        '<circle cx="40" cy="98" r="22" fill="#FFC23A"/><circle cx="34" cy="92" r="6" fill="#FFFFFF" opacity=".5"/>'
                        '<rect x="84" y="88" width="34" height="34" rx="10" fill="#10B981" transform="rotate(18 101 105)"/>'
                        '<path d="M14 30 q10 -12 20 0 t20 0" fill="none" stroke="#47AEF5" stroke-width="6" stroke-linecap="round"/></svg>'),
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
