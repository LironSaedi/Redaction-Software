"""Draw the Obscura app icon and write the formats each platform needs (no design tools required).

    python packaging/common/make_icons.py OUT_DIR      -> OUT_DIR/obscura.png, obscura.ico, Obscura.iconset/ (+ .icns on macOS)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def draw(size: int = 1024) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # rounded tile with a vertical indigo gradient
    tile = Image.new("RGBA", (s, s))
    top, bottom = (99, 102, 241), (49, 46, 129)
    px = tile.load()
    for y in range(s):
        t = y / (s - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(s):
            px[x, y] = c
    mask = Image.new("L", (s, s), 0)
    m = int(s * 0.1)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, s - m, s - m), radius=int(s * 0.2), fill=255)
    shadow = mask.filter(ImageFilter.GaussianBlur(s * 0.02))
    img.paste((0, 0, 0, 90), (0, int(s * 0.012)), shadow)
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # a document page with text lines, one of them redacted
    pw, ph = s * 0.44, s * 0.56
    x0, y0 = (s - pw) / 2, (s - ph) / 2
    d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=s * 0.035, fill=(248, 250, 252, 255))
    lx0, lx1 = x0 + pw * 0.14, x0 + pw * 0.86
    rows = [0.18, 0.32, 0.46, 0.60, 0.74]
    for i, r in enumerate(rows):
        yy = y0 + ph * r
        if i == 2:
            d.rounded_rectangle((lx0, yy - s * 0.03, lx1, yy + s * 0.03), radius=s * 0.008, fill=(15, 23, 42, 255))
        else:
            end = lx1 if i % 2 == 0 else lx0 + (lx1 - lx0) * 0.72
            d.rounded_rectangle((lx0, yy - s * 0.011, end, yy + s * 0.011), radius=s * 0.01,
                                fill=(148, 163, 184, 255))
    return img


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    big = draw(1024)
    big.save(out / "obscura.png")
    big.save(out / "obscura.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    iconset = out / "Obscura.iconset"
    iconset.mkdir(exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        big.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
        big.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")
    if sys.platform == "darwin":
        subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "Obscura.icns")])


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/icons"))
