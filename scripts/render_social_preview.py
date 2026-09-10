"""Generate docs/assets/social-preview.png for axiom.

Produces a 1280x640 PNG matching GitHub's social preview
dimensions. Renders the wordmark 'axiom' on a soft accent
background.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    out = Path("docs/assets/social-preview.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1280, 640
    img = Image.new("RGB", (width, height), (55, 118, 171))  # Python blue
    draw = ImageDraw.Draw(img)

    # Diagonal accent strip
    strip = Image.new("RGB", (width, 96), (47, 100, 150))
    img.paste(strip, (0, height - 96))

    # Pick a font; fall back to the system default if a heavy weight
    # is not available.
    candidates = [
        "/System/Library/Fonts/HelveticaNeue-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    font_title = None
    font_sub = None
    for c in candidates:
        if Path(c).exists():
            font_title = ImageFont.truetype(c, 220)
            font_sub = ImageFont.truetype(c, 44)
            break
    if font_title is None:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    title = "axiom"
    sub = "Fully Dynamic Maximal Matching  |  pure-Python reproduction"

    tb = draw.textbbox((0, 0), title, font=font_title)
    sb = draw.textbbox((0, 0), sub, font=font_sub)
    tx = (width - (tb[2] - tb[0])) // 2
    ty = (height - (tb[3] - tb[1])) // 2 - 40
    sx = (width - (sb[2] - sb[0])) // 2
    sy = ty + (tb[3] - tb[1]) + 40

    draw.text((tx, ty), title, fill=(255, 255, 255), font=font_title)
    draw.text((sx, sy), sub, fill=(220, 230, 245), font=font_sub)

    img.save(out, format="PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
