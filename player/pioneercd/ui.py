"""Draws the screens, 160×80, in the paper theme of Pioneer TV.

render() takes a view, a plain dict the app builds, and returns a PIL image.
The views:

    {"kind": "list", "status": ("KÄLLA", "1 AV 5"), "rows": [(num, label, value), ...],
     "selected": 0, "legend": [("●", "välj"), ...]}
    {"kind": "message", "status": (...), "title": "...", "text": "...", "error": False, "legend": [...]}
    {"kind": "playing", "status": (...), "title": "...", "subtitle": "...",
     "progress": 0.25 or None, "times": ("1:23", "5:29") or None, "line": "...",
     "paused": False, "legend": [...]}
    {"kind": "start"} and {"kind": "off"}

and "volume": {"level": 60, "muted": False} on any view draws the volume panel over it.
"""
import os

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 160, 80

# Maskinrepubliken, paper theme
PAPER = "#f4efe4"
PAPER_RAISED = "#fbf8f1"
PAPER_SUNKEN = "#eae3d4"
INK = "#1c1613"
INK_MUTED = "#4c4641"
INK_FAINT = "#5d5752"
LINE = "#cdc8be"
LINE_STRONG = "#7b756f"
OCHRE = "#f5cf5a"
ALARM = "#8e2f24"

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
SUB = lambda: font("Sans-Regular", 9)
MONO = lambda: font("Mono-Regular", 8)
MONO_BOLD = lambda: font("Mono-SemiBold", 8)

STATUS_H, LEGEND_H, ROW_H = 12, 13, 16


def fit(d, text, f, width):
    """text, cut with an ellipsis so it fits in width pixels."""
    if d.textlength(text, font=f) <= width:
        return text
    while text and d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def status(d, left, right):
    d.line([(1, STATUS_H), (WIDTH - 2, STATUS_H)], fill=LINE)
    f = MONO()
    right = right or ""
    rw = d.textlength(right, font=f)
    d.text((WIDTH - 6 - rw, 2), right, font=f, fill=INK_FAINT)
    d.text((5, 2), fit(d, left or "", f, WIDTH - 16 - rw), font=f, fill=INK_FAINT)


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
    visible = 3
    first = min(max(0, sel - 1), max(0, len(rows) - visible))
    y = STATUS_H + 2
    for i in range(first, min(len(rows), first + visible)):
        num, label, value = rows[i]
        on = i == sel
        if on:
            d.rounded_rectangle([4, y, WIDTH - 5, y + ROW_H - 1], radius=ROW_H // 2, fill=OCHRE)
        x = 10
        if num is not None:
            d.text((x, y + 4), str(num), font=MONO(), fill=INK if on else INK_FAINT)
            x += 13
        value = fit(d, value or "", MONO(), 80)
        vw = d.textlength(value, font=MONO())
        d.text((WIDTH - 10 - vw, y + 4), value, font=MONO(), fill=INK if on else INK_FAINT)
        f = SANS_BOLD() if on else SANS()
        d.text((x, y + 2), fit(d, label, f, WIDTH - 22 - x - vw), font=f, fill=INK)
        y += ROW_H
    if not rows:
        d.text((10, y + 2), v.get("empty", "Tomt"), font=SANS(), fill=INK_MUTED)


def draw_message(d, v):
    top, bottom = STATUS_H, HEIGHT - 1 - LEGEND_H
    mid = (top + bottom) // 2
    title, text = v.get("title", ""), v.get("text", "")
    f = TITLE()
    color = ALARM if v.get("error") else INK
    if text:
        d.text((8, mid - 14), fit(d, title, f, WIDTH - 16), font=f, fill=color)
        d.text((8, mid + 2), fit(d, text, SUB(), WIDTH - 16), font=SUB(), fill=INK_MUTED)
    else:
        d.text((8, mid - 8), fit(d, title, f, WIDTH - 16), font=f, fill=color)


def draw_playing(d, v):
    x, y = 7, STATUS_H + 2
    d.text((x, y), fit(d, v.get("title", ""), TITLE(), WIDTH - 2 * x), font=TITLE(), fill=INK)
    d.text((x, y + 16), fit(d, v.get("subtitle", ""), SUB(), WIDTH - 2 * x), font=SUB(), fill=INK_MUTED)
    y += 31
    if v.get("progress") is not None:
        d.rounded_rectangle([x, y, WIDTH - x, y + 2], radius=1, fill=PAPER_SUNKEN)
        end = x + round((WIDTH - 2 * x) * max(0.0, min(1.0, v["progress"])))
        if end > x:
            d.rounded_rectangle([x, y, end, y + 2], radius=1, fill=INK)
    y += 5
    if v.get("times"):
        left, right = v["times"]
        d.text((x, y), left, font=MONO(), fill=INK_FAINT)
        d.text((WIDTH - x - d.textlength(right, font=MONO()), y), right, font=MONO(), fill=INK_FAINT)
    elif v.get("line"):
        d.text((x, y - 2), fit(d, v["line"], MONO(), WIDTH - 2 * x), font=MONO(), fill=INK_FAINT)
    if v.get("paused"):
        w = 10 + d.textlength("Pausad", font=MONO_BOLD())
        px = (WIDTH - w) // 2
        d.rectangle([px, y + 2, px + 1, y + 7], fill=INK)
        d.rectangle([px + 4, y + 2, px + 5, y + 7], fill=INK)
        d.text((px + 10, y), "Pausad", font=MONO_BOLD(), fill=INK)


def draw_volume(d, vol):
    x0, y0, x1, y1 = 9, 15, WIDTH - 10, 63
    d.rounded_rectangle([x0, y0, x1, y1], radius=9, fill=PAPER_RAISED, outline=LINE_STRONG)
    d.text((x0 + 8, y0 + 6), "VOLYM", font=MONO(), fill=INK_FAINT)
    value = "Tyst" if vol["muted"] else f"{vol['level']} %"
    d.text((x1 - 8 - d.textlength(value, font=TITLE()), y0 + 2), value, font=TITLE(), fill=INK)
    filled = 0 if vol["muted"] else round(vol["level"] / 10)
    for i in range(10):
        cx, cy = x0 + 13 + i * 12, y1 - 13
        box = [cx - 4, cy - 4, cx + 4, cy + 4]
        if i < filled:
            d.ellipse(box, fill=INK)
        else:
            d.ellipse(box, outline=LINE_STRONG, width=1)


def draw_start(d):
    f = font("Sans-Bold", 18)
    text = "PIONEER CD"
    d.text(((WIDTH - d.textlength(text, font=f)) / 2, 22), text, font=f, fill=INK)
    d.text(((WIDTH - d.textlength("STARTAR", font=MONO())) / 2, 48), "STARTAR", font=MONO(), fill=INK_FAINT)


def render(v):
    if v["kind"] == "off":
        return Image.new("RGB", (WIDTH, HEIGHT), INK)
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(img)
    kind = v["kind"]
    if kind == "start":
        draw_start(d)
    else:
        status(d, *v.get("status", ("", "")))
        {"list": draw_list, "message": draw_message, "playing": draw_playing}[kind](d, v)
        if v.get("volume"):
            legend(d, [("A", "upp"), ("B", "ner"), ("A+B", "tyst")])
            draw_volume(d, v["volume"])
        elif v.get("legend"):
            legend(d, v["legend"])
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=INK)
    return img
