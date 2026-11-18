"""
tools/gen_mascots.py — Sinh bộ mascot SVG GỐC của OGK (vẽ tay bằng hình học, không dùng tài sản bên ngoài).

Phong cách: khối hình học phẳng màu tươi + đôi mắt to tròn, đồng tử lệch nhìn tò mò, miệng đơn giản,
má hồng pastel. 3 nhân vật × 5 biểu cảm:
  tictac (Tíc-Tắc, đồng hồ san hô)  — quản lý thời gian
  khien  (Khiên Xanh, khiên xanh dương) — an toàn trên mạng, giải thích vì sao trang/ứng dụng chưa mở
  sao    (Sao Nhỏ, ngôi sao vàng)     — khích lệ, ăn mừng
Biểu cảm: happy (vui), encourage (khích lệ), remind (nhắc nhẹ), sleepy (buồn ngủ/giờ nghỉ), celebrate (ăn mừng).
Không bao giờ có biểu cảm giận dữ/thất vọng (nguyên tắc UX cho trẻ).

Chạy: python tools/gen_mascots.py  -> dashboard/static/mascots/*.svg và agent/tray/assets/*.svg
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [ROOT / "dashboard" / "static" / "mascots", ROOT / "agent" / "tray" / "assets"]

INK = "#1F2937"
BLUSH = "#FFB4C2"
MOODS = ("happy", "encourage", "remind", "sleepy", "celebrate")


def eyes(mood: str, lx: float, rx: float, y: float, r: float = 9.5) -> str:
    if mood == "sleepy":  # mắt nhắm: hai đường cong xuống
        return "".join(f'<path d="M{x - r} {y} Q{x} {y + r * 0.9} {x + r} {y}" fill="none" stroke="{INK}" '
                       f'stroke-width="3.2" stroke-linecap="round"/>' for x in (lx, rx))
    if mood == "celebrate":  # mắt cười: hai đường cong lên ^ ^
        return "".join(f'<path d="M{x - r} {y + 3} Q{x} {y - r} {x + r} {y + 3}" fill="none" stroke="{INK}" '
                       f'stroke-width="3.6" stroke-linecap="round"/>' for x in (lx, rx))
    dx, dy = {"happy": (2.5, 0.5), "encourage": (0, -3.5), "remind": (4, 1)}[mood]
    out = ""
    for x in (lx, rx):
        out += f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * 1.08}" fill="#FFFFFF"/>'
        out += f'<circle cx="{x + dx}" cy="{y + dy}" r="{r * 0.55}" fill="{INK}"/>'
        out += f'<circle cx="{x + dx + 1.8}" cy="{y + dy - 2}" r="{r * 0.16}" fill="#FFFFFF"/>'
        if mood == "remind":  # mí mắt hạ nhẹ: nhìn sang bên, kiểu "này, nhớ nhé"
            out += f'<path d="M{x - r - 1} {y - r * 0.35} L{x + r + 1} {y - r * 0.35} L{x + r + 1} {y - r * 1.2} L{x - r - 1} {y - r * 1.2} Z" fill="currentColor"/>'
    return out


def mouth(mood: str, cx: float, y: float, w: float = 9) -> str:
    if mood in ("encourage", "celebrate"):
        return (f'<path d="M{cx - w} {y - 2} Q{cx} {y + w * 1.4} {cx + w} {y - 2} Z" fill="{INK}"/>'
                f'<path d="M{cx - w * 0.5} {y + w * 0.62} Q{cx} {y + w * 0.2} {cx + w * 0.5} {y + w * 0.62} Q{cx} {y + w * 0.95} {cx - w * 0.5} {y + w * 0.62} Z" fill="#FF8FA3"/>')
    if mood == "sleepy":
        return f'<ellipse cx="{cx}" cy="{y + 2}" rx="3.2" ry="3.8" fill="{INK}"/>'
    if mood == "remind":
        return f'<path d="M{cx - w * 0.6} {y + 1} Q{cx} {y + 5} {cx + w * 0.6} {y + 1}" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>'
    return f'<path d="M{cx - w * 0.7} {y} Q{cx} {y + w * 0.9} {cx + w * 0.7} {y}" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>'


def blush(lx, rx, y) -> str:
    return "".join(f'<ellipse cx="{x}" cy="{y}" rx="7" ry="4.2" fill="{BLUSH}" opacity=".85"/>' for x in (lx, rx))


def extras(mood: str, color: str) -> str:
    if mood == "sleepy":
        # chữ "z" vẽ bằng path (không phụ thuộc font => hiển thị giống nhau trên web và Qt)
        return (f'<path d="M94 20 h10 l-10 11 h10" fill="none" stroke="{INK}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/>'
                f'<path d="M106 8 h7 l-7 8 h7" fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity=".4"/>')
    if mood == "celebrate":
        s = ""
        for x, y, c in ((14, 22, "#FBBF24"), (108, 26, "#10B981"), (10, 92, "#2563EB"), (110, 96, "#FF6B6B")):
            s += f'<path d="M{x} {y - 7} L{x + 2} {y - 2} L{x + 7} {y} L{x + 2} {y + 2} L{x} {y + 7} L{x - 2} {y + 2} L{x - 7} {y} L{x - 2} {y - 2} Z" fill="{c}"/>'
        return s
    return ""


def tictac(mood: str) -> str:
    c, dark, light = "#FF6B6B", "#E8505A", "#FFC2C2"
    body = (f'<rect x="56" y="10" width="8" height="12" rx="4" fill="{dark}"/>'
            f'<circle cx="34" cy="24" r="11" fill="{dark}"/><circle cx="86" cy="24" r="11" fill="{dark}"/>'
            f'<ellipse cx="44" cy="110" rx="9" ry="5" fill="{dark}"/><ellipse cx="76" cy="110" rx="9" ry="5" fill="{dark}"/>'
            f'<circle cx="60" cy="64" r="44" fill="{c}"/>')
    ticks = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2.5" fill="{light}"/>'
                    for x, y, w, h in ((57.5, 25, 5, 10), (57.5, 93, 5, 10), (21, 61.5, 10, 5), (89, 61.5, 10, 5)))
    face = eyes(mood, 46, 74, 58) + blush(36, 84, 74) + mouth(mood, 60, 78)
    return body + ticks + face


def khien(mood: str) -> str:
    c, light = "#2563EB", "#93C5FD"
    body = (f'<path d="M60 8 C76 16 92 18 104 18 L104 58 C104 86 86 104 60 114 C34 104 16 86 16 58 L16 18 C28 18 44 16 60 8 Z" fill="{c}"/>'
            f'<path d="M60 20 C72 26 84 28 93 28 L93 58 C93 80 79 94 60 102" fill="none" stroke="{light}" stroke-width="4" stroke-linecap="round" opacity=".7"/>')
    face = eyes(mood, 46, 74, 56) + blush(34, 86, 72) + mouth(mood, 60, 76)
    return body + face


def sao(mood: str) -> str:
    c = "#FBBF24"
    pts = "60,12 73,44 107,46 81,68 90,101 60,83 30,101 39,68 13,46 47,44"
    body = f'<polygon points="{pts}" fill="{c}" stroke="{c}" stroke-width="12" stroke-linejoin="round"/>'
    face = eyes(mood, 49, 71, 58, r=8) + blush(40, 80, 72) + mouth(mood, 60, 74, w=7)
    return body + face


MASCOTS = {"tictac": (tictac, "#FF6B6B"), "khien": (khien, "#2563EB"), "sao": (sao, "#FBBF24")}
TITLES = {"tictac": "Tíc-Tắc", "khien": "Khiên Xanh", "sao": "Sao Nhỏ"}


def svg(name: str, mood: str) -> str:
    fn, color = MASCOTS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120" '
            f'role="img" aria-label="{TITLES[name]}" style="color:{color}">'
            f'<title>{TITLES[name]}</title>{fn(mood)}{extras(mood, color)}</svg>\n')


def main():
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        for name in MASCOTS:
            for mood in MOODS:
                (d / f"{name}_{mood}.svg").write_text(svg(name, mood), encoding="utf-8")
    print(f"Đã sinh {len(MASCOTS) * len(MOODS)} mascot vào: " + ", ".join(str(d) for d in OUT_DIRS))


if __name__ == "__main__":
    main()
