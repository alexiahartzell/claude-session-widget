#!/usr/bin/env python3
"""Draw docs/schemes.png: every colour scheme as sample cards, dark then light.

Usage: python3 docs/make_schemes_sheet.py   (needs Pillow)

Each scheme is one row: its ten colours in rainbow order, first on the dark
panel, then on the light panel, using the same card colours as the widget.
"""
import importlib.util, os, sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import widgetlib as w

spec = importlib.util.spec_from_file_location("tint", os.path.join(SCRIPTS, "tint.py"))
tint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tint)

# Full-rainbow schemes, then cool themes, then warm ones, then the extras.
ORDER = ["muted", "jewel", "colourblind", "dusk", "berry", "galaxy", "neon", "nordic", "ocean",
         "aurora", "green", "forest", "desert", "autumn", "ember", "tropical", "dracula", "crewtractor"]
assert set(ORDER) == set(tint.DARK), "add new schemes to ORDER"

SCALE = 2                       # draw at twice the size, then shrink, for smooth edges
LABEL_W, CARD_W, CARD_H, GAP = 114, 74, 40, 8
BAND_H, ROW_GAP, TOP = 48, 8, 4
WIDTH = LABEL_W + 10 * CARD_W + 9 * GAP + 18


def font(size, weight="Medium"):
    path = "/System/Library/Fonts/Avenir Next.ttc"
    if os.path.exists(path):
        for i in range(12):
            f = ImageFont.truetype(path, size * SCALE, index=i)
            if f.getname()[1] == weight:
                return f
    if os.path.exists("/System/Library/Fonts/Helvetica.ttc"):
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size * SCALE)
    return ImageFont.load_default()


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rainbow(pal):
    return sorted(pal, key=lambda nh: (w._hsv(w._dark_of(nh[1]) if w.is_light(nh[1]) else nh[1])[0] + 0.1) % 1)   # start at pinks and reds


def fit(draw, text, f, width):
    """Shrink a long name until it fits, then trim it as a last resort."""
    size = f.size
    while draw.textlength(text, font=f) > width and size > 7 * SCALE:
        size -= SCALE // 2 or 1
        f = f.font_variant(size=size)
    while text and draw.textlength(text, font=f) > width:
        text = text[:-1]
    return text, f


def card(draw, x, y, tint_hex, name, mode, f):
    th = w.PANEL_THEMES[mode]
    fill = w.card_fill(tint_hex, th["bg"], mode)
    edge = w.accent(tint_hex, mode)
    s = SCALE
    box = [x * s, y * s, (x + CARD_W) * s, (y + CARD_H) * s]
    draw.rounded_rectangle(box, radius=6 * s, fill=rgb(fill), outline=rgb(edge), width=2 * s)
    bar = w._mix(th["fg"], fill, 0.88)
    draw.rounded_rectangle([(x + 6) * s, (y + 24) * s, (x + CARD_W - 6) * s, (y + 33) * s],
                           radius=3 * s, fill=rgb(bar))
    text, f = fit(draw, name, f, (CARD_W - 10) * s)
    draw.text(((x + 6) * s, (y + 4) * s), text, font=f, fill=rgb(th["fg"]))


def main(out=os.path.join(HERE, "schemes.png")):
    row_h = 2 * BAND_H + ROW_GAP
    height = TOP + len(ORDER) * row_h
    dark_bg, light_bg = rgb(w.PANEL_THEMES["dark"]["bg"]), rgb(w.PANEL_THEMES["light"]["bg"])
    img = Image.new("RGB", (WIDTH * SCALE, height * SCALE), dark_bg)
    draw = ImageDraw.Draw(img)
    f_label, f_card = font(14), font(9, "Regular")
    for r, scheme in enumerate(ORDER):
        y0 = TOP + r * row_h
        draw.text((8 * SCALE, (y0 + 16) * SCALE), scheme, font=f_label, fill=rgb(w.PANEL_THEMES["dark"]["fg"]))
        for b, mode in enumerate(("dark", "light")):
            yb = y0 + b * BAND_H
            band_bg = light_bg if mode == "light" else dark_bg
            draw.rectangle([LABEL_W * SCALE, yb * SCALE, WIDTH * SCALE, (yb + BAND_H) * SCALE], fill=band_bg)
            for i, (name, h) in enumerate(rainbow(tint.palette(scheme, mode))):
                card(draw, LABEL_W + 4 + i * (CARD_W + GAP), yb + 4, h, name, mode, f_card)
    img.resize((WIDTH, height), Image.LANCZOS).save(out)
    print(f"wrote {out} ({WIDTH}x{height})")


if __name__ == "__main__":
    main()
