"""tools/make_brand_assets.py — Tạo ảnh thương hiệu SafeAnchor từ ảnh mascot do nhóm cung cấp (mascot.jpg).

Ảnh gốc là JPEG có nền "ô caro giả trong suốt" (#FFFFFF/#EFEFEF). Script:
  1. tách nền: nét vẽ tay có khe hở (vai — tay) nên giãn nét R px để "đóng khe", loang (flood fill) từ mép
     ảnh qua phần còn lại, rồi nới vùng nền trở lại R px qua các điểm sáng trung tính;
  2. khử viền trắng: điểm ảnh sát nền được "tách lớp" (un-mix) theo màu nền cục bộ => viền mịn, không quầng;
  3. cắt sát hình + lề, xuất PNG trong suốt và favicon 32/64/180 px.
Chạy: .venv\\Scripts\\python.exe tools\\make_brand_assets.py [đường_dẫn_mascot.jpg]
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "static" / "brand"


def is_light(c: QColor) -> bool:
    r, g, b = c.red(), c.green(), c.blue()
    return min(r, g, b) >= 214 and max(r, g, b) - min(r, g, b) <= 16


def main(src: Path) -> None:
    img = QImage(str(src)).convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    px = [[img.pixelColor(x, y) for x in range(w)] for y in range(h)]
    light = [[is_light(px[y][x]) for x in range(w)] for y in range(h)]

    # 1) Nét vẽ tay có KHE HỞ (vai — tay): loang thẳng thì nền tràn vào thân. => "đóng khe" bằng cách giãn
    #    nét (dilate R px), loang từ mép ảnh trên phần còn lại, rồi nới vùng nền trở lại R px (chỉ qua điểm sáng).
    R = 5
    dark = [[not light[y][x] for x in range(w)] for y in range(h)]

    def dilate(mask, r):
        tmp = [[any(mask[y][max(0, x - r):x + r + 1]) for x in range(w)] for y in range(h)]
        return [[any(tmp[yy][x] for yy in range(max(0, y - r), min(h, y + r + 1))) for x in range(w)] for y in range(h)]

    closed = dilate(dark, R)
    seed = [[False] * w for _ in range(h)]
    q = deque((x, y) for y in range(h) for x in range(w)
              if (x in (0, w - 1) or y in (0, h - 1)) and not closed[y][x])
    for x, y in q:
        seed[y][x] = True
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not closed[ny][nx] and not seed[ny][nx]:
                seed[ny][nx] = True
                q.append((nx, ny))
    grown = dilate(seed, R)
    bg = [[seed[y][x] or (grown[y][x] and light[y][x]) for x in range(w)] for y in range(h)]
    body_n = sum(1 for y in range(h) for x in range(w) if light[y][x] and not bg[y][x])

    # 2) alpha + tách lớp màu ở viền
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    for y in range(h):
        for x in range(w):
            if bg[y][x]:
                continue
            c = px[y][x]
            near = [px[ny][nx] for ny in range(max(0, y - 2), min(h, y + 3)) for nx in range(max(0, x - 2), min(w, x + 3))
                    if bg[ny][nx]]
            if not near:
                out.setPixelColor(x, y, c)
                continue
            br = sum(n.red() for n in near) / len(near)
            bgc = sum(n.green() for n in near) / len(near)
            bb = sum(n.blue() for n in near) / len(near)
            d = max(abs(c.red() - br), abs(c.green() - bgc), abs(c.blue() - bb))
            a = max(0.0, min(1.0, d / 110))
            if a <= 0.02:
                continue
            un = [max(0, min(255, round(b0 + (v - b0) / a))) for v, b0 in ((c.red(), br), (c.green(), bgc), (c.blue(), bb))]
            out.setPixelColor(x, y, QColor(un[0], un[1], un[2], round(a * 255)))

    # 3) cắt sát + lề 6 px
    xs = [x for y in range(h) for x in range(w) if out.pixelColor(x, y).alpha() > 8]
    ys = [y for y in range(h) for x in range(w) if out.pixelColor(x, y).alpha() > 8]
    pad = 6
    box = QRect(max(0, min(xs) - pad), max(0, min(ys) - pad), 0, 0)
    box.setRight(min(w - 1, max(xs) + pad))
    box.setBottom(min(h - 1, max(ys) + pad))
    mascot = out.copy(box)
    OUT.mkdir(parents=True, exist_ok=True)
    mascot.save(str(OUT / "mascot.png"))

    # favicon vuông: hình đặt giữa, chiếm ~92% cạnh
    for size, name in ((32, "favicon-32.png"), (64, "favicon-64.png"), (180, "apple-touch-icon.png")):
        canvas = QImage(size, size, QImage.Format.Format_ARGB32)
        canvas.fill(QColor(255, 255, 255) if size == 180 else Qt.GlobalColor.transparent)
        scale = (0.80 if size == 180 else 0.96) * size / max(mascot.width(), mascot.height())
        sw, sh = round(mascot.width() * scale), round(mascot.height() * scale)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRect((size - sw) // 2, (size - sh) // 2, sw, sh), mascot)
        p.end()
        canvas.save(str(OUT / name))
    print(f"mascot.png {mascot.width()}x{mascot.height()} | điểm sáng giữ lại (thân + mắt): {body_n} px")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "mascot.jpg")
