"""Placeholder app icons: "gr8" over "base" (8 and b bold), white on the site's blue (#0172ad).

Run inside the dev container:  python static/icons/make_icons.py
Replace the PNGs with real artwork any time; keep the file names and sizes.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLUE = (1, 114, 173, 255)
WHITE = (255, 255, 255, 255)
HERE = Path(__file__).parent


def icon(size, *, rounded, text_share):
    """Two lines, "gr8" over "base" (gr8 base), with "8" and "b" bold.

    rounded: transparent rounded corners; text_share: letter height / size.
    The image has no bold font, so the bold letters get a thicker stroke.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if rounded:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=BLUE)
    else:
        draw.rectangle((0, 0, size, size), fill=BLUE)
    font = ImageFont.load_default(size=int(size * text_share))
    bold = max(1, round(size * text_share * 0.06))

    def width(text, stroke=0):
        box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        return box[2] - box[0]

    def line(parts, y):
        """parts: [(text, is_bold)], drawn centred as one line."""
        total = sum(width(text, bold if is_bold else 0) for text, is_bold in parts)
        x = (size - total) / 2
        for text, is_bold in parts:
            stroke = bold if is_bold else 0
            draw.text((x + stroke, y), text, font=font, fill=WHITE,
                      stroke_width=stroke, stroke_fill=WHITE)
            x += width(text, stroke)

    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    gap = -int(line_height * 0.18)  # pull the lines together a bit
    top = (size - (2 * line_height + gap)) / 2
    line([("gr", False), ("8", True)], top)
    line([("b", True), ("ase", False)], top + line_height + gap)
    return img


def favicon(size):
    """Browser tab: two lines are unreadable at 32 px, so only a bold "8b"."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=BLUE)
    font = ImageFont.load_default(size=int(size * 0.62))
    bold = max(1, round(size * 0.04))
    box = draw.textbbox((0, 0), "8b", font=font, stroke_width=bold)
    x = (size - (box[2] - box[0])) / 2 - box[0]
    y = (size - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), "8b", font=font, fill=WHITE, stroke_width=bold, stroke_fill=WHITE)
    return img


icon(192, rounded=True, text_share=0.34).save(HERE / "icon-192.png")
icon(512, rounded=True, text_share=0.34).save(HERE / "icon-512.png")
# maskable: full bleed, letters inside the central safe zone (Android crops to shapes)
icon(512, rounded=False, text_share=0.26).save(HERE / "icon-maskable-512.png")
# iPhone home screen: no transparency, iOS rounds the corners itself
icon(180, rounded=False, text_share=0.34).convert("RGB").save(HERE / "apple-touch-icon.png")
favicon(32).save(HERE / "favicon-32.png")
print("icons written to", HERE)
