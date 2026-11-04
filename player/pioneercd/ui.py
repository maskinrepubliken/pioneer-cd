"""Draws the screens, 160×80, in the paper theme of Pioneer TV.

render() takes a view, a plain dict the app builds, and returns a PIL image.
There is no status row: the screen is small, and all of it goes to what
matters. The views:

    {"kind": "list", "rows": [(num, label, value), ...], "selected": 0, "legend": [("●", "välj"), ...]}
    {"kind": "message", "title": "...", "text": "...", "error": False, "legend": [...]}
    {"kind": "playing", "title": "...", "subtitle": "...", "progress": 0.25 or None,
     "times": ("1:23", "5:29") or None, "position": "3 av 11", "line": "...",
     "paused": False, "legend": [...]}
    {"kind": "start"} and {"kind": "off"}

and "volume": {"level": 60, "muted": False} on any view draws the volume panel over it.
"""
import os

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 160, 80

# Maskinrepubliken's themes, as in Pioneer TV: paper (light) and ink (dark).
# The ochre row is the same in both, with ink on it.
THEMES = {
    "paper": {"PAPER": "#f4efe4", "PAPER_RAISED": "#fbf8f1", "PAPER_SUNKEN": "#eae3d4", "INK": "#1c1613",
              "INK_MUTED": "#4c4641", "INK_FAINT": "#5d5752", "LINE": "#cdc8be", "LINE_STRONG": "#7b756f",
              "ALARM": "#8e2f24", "FRAME": "#1c1613"},
    "ink": {"PAPER": "#1c1613", "PAPER_RAISED": "#291f1a", "PAPER_SUNKEN": "#3f3934", "INK": "#f4efe4",
            "INK_MUTED": "#c9c4ba", "INK_FAINT": "#a29d95", "LINE": "#3f3934", "LINE_STRONG": "#77716b",
            "ALARM": "#e08076", "FRAME": "#1c1613"},
}
OCHRE, ON_OCHRE = "#f5cf5a", "#1c1613"


def theme(name):
    """Sets the colours below to a theme's."""
    globals().update(THEMES[name])


theme("paper")

FONT_DIR = os.environ.get("PIONEERCD_FONTS", "/usr/share/fonts/truetype/ibm-plex")
_fonts = {}


def font(name, size):
    key = (name, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, f"IBMPlex{name}.ttf"), size)
    return _fonts[key]


SANS = lambda: font("Sans-Regular", 10)
SANS_BOLD = lambda: font("Sans-SemiBold", 10)
TITLE = lambda: font("Sans-SemiBold", 13)
BIG = lambda: font("Sans-SemiBold", 16)
SUB = lambda: font("Sans-Regular", 10)
MONO = lambda: font("Mono-Regular", 8)
MONO_BOLD = lambda: font("Mono-SemiBold", 8)

LEGEND_H, ROW_H, VISIBLE = 13, 16, 4
BOTTOM = HEIGHT - 1 - LEGEND_H        # where the legend starts


def fit(d, text, f, width):
    """text, cut with an ellipsis so it fits in width pixels."""
    if d.textlength(text, font=f) <= width:
        return text
    while text and d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def glyph(d, ch, x, y):
    """A joystick sign drawn as a shape (Plex has none of them): ● ▲ ▼ ◀ ▶,
    in a 6×6 box at x, y. Returns its width."""
    if ch == "●":
        d.ellipse([x, y, x + 5, y + 5], fill=INK)
    elif ch == "▲":
        d.polygon([(x, y + 5), (x + 5, y + 5), (x + 2.5, y)], fill=INK)
    elif ch == "▼":
        d.polygon([(x, y), (x + 5, y), (x + 2.5, y + 5)], fill=INK)
    elif ch == "◀":
        d.polygon([(x + 5, y), (x + 5, y + 5), (x, y + 2.5)], fill=INK)
    elif ch == "▶":
        d.polygon([(x, y), (x, y + 5), (x + 5, y + 2.5)], fill=INK)
    return 6


def legend(d, items):
    top = HEIGHT - 1 - LEGEND_H
    d.line([(1, top), (WIDTH - 2, top)], fill=LINE)
    x = 5
    for key, label in items:
        if all(c in "●▲▼◀▶" for c in key):
            for c in key:
                x += glyph(d, c, x, top + 5) + 1
            x += 2
        else:
            d.text((x, top + 3), key, font=MONO_BOLD(), fill=INK)
            x += d.textlength(key, font=MONO_BOLD()) + 3
        d.text((x, top + 3), label, font=MONO(), fill=INK_FAINT)
        x += d.textlength(label, font=MONO()) + 8


def draw_list(d, v):
    rows, sel = v["rows"], v.get("selected", 0)
    first = min(max(0, sel - 1), max(0, len(rows) - VISIBLE))
    y = (BOTTOM - VISIBLE * ROW_H) // 2 + 1
    right = WIDTH - 9 if len(rows) > VISIBLE else WIDTH - 5
    for i in range(first, min(len(rows), first + VISIBLE)):
        num, label, value = rows[i]
        on = i == sel
        if on:
            d.rounded_rectangle([4, y, right, y + ROW_H - 1], radius=ROW_H // 2, fill=OCHRE)
        x = 10
        fg = ON_OCHRE if on else INK
        if num is not None:
            d.text((x, y + 4), str(num), font=MONO(), fill=fg if on else INK_FAINT)
            x += 13
        value = fit(d, value or "", MONO(), 80)
        vw = d.textlength(value, font=MONO())
        d.text((right - 6 - vw, y + 4), value, font=MONO(), fill=fg if on else INK_FAINT)
        f = SANS_BOLD() if on else SANS()
        d.text((x, y + 2), fit(d, label, f, right - 12 - x - vw), font=f, fill=fg)
        y += ROW_H
    if len(rows) > VISIBLE:
        # Where in the list: a thin bar in the right edge, its thumb as long as what shows.
        top, bottom = 4, BOTTOM - 4
        d.rounded_rectangle([WIDTH - 5, top, WIDTH - 4, bottom], radius=1, fill=PAPER_SUNKEN)
        h = max(4, round((bottom - top) * VISIBLE / len(rows)))
        t = top + round((bottom - top - h) * first / (len(rows) - VISIBLE))
        d.rounded_rectangle([WIDTH - 5, t, WIDTH - 4, t + h], radius=1, fill=INK_FAINT)
    if not rows:
        d.text((10, 8), v.get("empty", "Tomt"), font=SANS(), fill=INK_MUTED)


def draw_message(d, v):
    mid = BOTTOM // 2
    title, text = v.get("title", ""), v.get("text", "")
    color = ALARM if v.get("error") else INK
    f = BIG() if d.textlength(title, font=BIG()) <= WIDTH - 16 else TITLE()   # a long title steps down
    if text:
        d.text((8, mid - 17), fit(d, title, f, WIDTH - 16), font=f, fill=color)
        d.text((8, mid + 3), fit(d, text, SUB(), WIDTH - 16), font=SUB(), fill=INK_MUTED)
    else:
        d.text((8, mid - 10), fit(d, title, f, WIDTH - 16), font=f, fill=color)


def draw_playing(d, v):
    x = 7
    d.text((x, 3), fit(d, v.get("title", ""), BIG(), WIDTH - 2 * x), font=BIG(), fill=INK)
    d.text((x, 23), fit(d, v.get("subtitle", ""), SUB(), WIDTH - 2 * x), font=SUB(), fill=INK_MUTED)
    y = 42
    if v.get("progress") is not None:
        d.rounded_rectangle([x, y, WIDTH - x, y + 2], radius=1, fill=PAPER_SUNKEN)
        end = x + round((WIDTH - 2 * x) * max(0.0, min(1.0, v["progress"])))
        if end > x:
            d.rounded_rectangle([x, y, end, y + 2], radius=1, fill=INK)
    y += 6
    if v.get("times"):
        left, right = v["times"]
        d.text((x, y), left, font=MONO(), fill=INK_FAINT)
        d.text((WIDTH - x - d.textlength(right, font=MONO()), y), right, font=MONO(), fill=INK_FAINT)
    elif v.get("line"):
        d.text((x, y - 6), fit(d, v["line"], MONO(), WIDTH - 2 * x), font=MONO(), fill=INK_FAINT)
    if v.get("paused"):
        w = 10 + d.textlength("Pausad", font=MONO_BOLD())
        px = (WIDTH - w) // 2
        d.rectangle([px, y + 2, px + 1, y + 7], fill=INK)
        d.rectangle([px + 4, y + 2, px + 5, y + 7], fill=INK)
        d.text((px + 10, y), "Pausad", font=MONO_BOLD(), fill=INK)
    elif v.get("position") and v.get("times"):
        pos = v["position"]
        d.text(((WIDTH - d.textlength(pos, font=MONO())) / 2, y), pos, font=MONO(), fill=INK_FAINT)


def draw_volume(d, vol):
    """The volume as a number, as on a TV; muted, the word Tyst."""
    x0, y0, x1, y1 = 30, 17, WIDTH - 31, 61
    d.rounded_rectangle([x0, y0, x1, y1], radius=9, fill=PAPER_RAISED, outline=LINE_STRONG)
    label = "VOLYM"
    d.text(((WIDTH - d.textlength(label, font=MONO())) / 2, y0 + 5), label, font=MONO(), fill=INK_FAINT)
    value, f = ("Tyst", TITLE()) if vol["muted"] else (str(vol["level"]), font("Mono-SemiBold", 22))
    box = d.textbbox((0, 0), value, font=f)
    d.text(((WIDTH - (box[2] - box[0])) / 2 - box[0], y0 + 27 - (box[3] - box[1]) / 2 - box[1]),
           value, font=f, fill=INK)


def draw_start(d):
    f = font("Sans-Bold", 18)
    text = "PIONEER CD"
    d.text(((WIDTH - d.textlength(text, font=f)) / 2, 22), text, font=f, fill=INK)
    d.text(((WIDTH - d.textlength("STARTAR", font=MONO())) / 2, 48), "STARTAR", font=MONO(), fill=INK_FAINT)


def render(v):
    if v["kind"] == "off":
        return Image.new("RGB", (WIDTH, HEIGHT), "#000000")
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(img)
    kind = v["kind"]
    if kind == "start":
        draw_start(d)
    else:
        {"list": draw_list, "message": draw_message, "playing": draw_playing}[kind](d, v)
        if v.get("volume"):
            legend(d, [("A", "upp"), ("B", "ner"), ("A+B", "tyst")])
            draw_volume(d, v["volume"])
        elif v.get("legend"):
            legend(d, v["legend"])
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=FRAME)   # dark edge, as the panel's own
    return img
