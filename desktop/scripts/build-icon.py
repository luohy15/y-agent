"""Generate desktop/icon.png (and .icns) using the macOS icon template: an
824×824 rounded-square ("squircle") inside a 1024×1024 transparent canvas,
filled with the favicon's light-gray + blue 'Y'. The 100px transparent
margin and ~22% corner radius match Apple's HIG so the icon doesn't look
crooked against the Tahoe Dock's rounded-rectangle framing. Run once after
favicon design changes."""

import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
PNG_PATH = os.path.join(OUT_DIR, "icon.png")
ICONSET_DIR = os.path.join(OUT_DIR, "icon.iconset")
ICNS_PATH = os.path.join(OUT_DIR, "icon.icns")

BG = (243, 244, 246, 255)       # tailwind gray-100, same as favicon canvas
FG = (66, 133, 244, 255)        # blue, same hex as favicon canvas (#4285f4)
SIZE = 1024
# Apple's macOS icon template: the visible shape is 824×824 inside the 1024
# canvas (100px margin), with a 185-unit corner radius. Ratios stay constant
# so we can scale to any output size cleanly.
INNER_RATIO = 824 / 1024
CORNER_RATIO = 185 / 1024
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inner = round(size * INNER_RATIO)
    radius = round(size * CORNER_RATIO)
    margin = (size - inner) // 2
    d.rounded_rectangle(
        (margin, margin, margin + inner, margin + inner),
        radius=radius,
        fill=BG,
    )
    # Glyph fills ~75% of the inner shape — matches the web favicon's 24/32 ratio.
    font = ImageFont.truetype(FONT_PATH, int(inner * 0.75))
    bbox = d.textbbox((0, 0), "Y", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    d.text((x, y), "Y", fill=FG, font=font)
    return img


def main():
    icon = draw_icon(SIZE)
    icon.save(PNG_PATH)
    print(f"wrote {PNG_PATH}")

    # Build .icns via macOS iconutil (no external deps; ships with Xcode CLT).
    os.makedirs(ICONSET_DIR, exist_ok=True)
    # iconutil requires the standard set of sizes & @2x variants.
    for size, name in [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]:
        draw_icon(size).save(os.path.join(ICONSET_DIR, name))
    subprocess.check_call(["iconutil", "-c", "icns", ICONSET_DIR, "-o", ICNS_PATH])
    print(f"wrote {ICNS_PATH}")


if __name__ == "__main__":
    main()
