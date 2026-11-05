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

and "notice": {"label": "VOLYM", "value": "28", "mono": True, "legend": [...]} on any view
draws a panel over it for a moment: the volume, Tyst, Pausad or Spelar.
"""
import math
import os
import time

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
ROW = lambda: font("Sans-Regular", 17)          # a menu row
ROW_BOLD = lambda: font("Sans-SemiBold", 17)
ROW_VALUE = lambda: font("Mono-Regular", 10)
TITLE = lambda: font("Sans-SemiBold", 13)
BIG = lambda: font("Sans-SemiBold", 16)
HUGE = lambda: font("Sans-SemiBold", 20)        # what plays, and a message
SUB = lambda: font("Sans-Regular", 13)
TIMES = lambda: font("Mono-Regular", 10)
MONO = lambda: font("Mono-Regular", 8)
MONO_BOLD = lambda: font("Mono-SemiBold", 8)

LEGEND_H, ROW_H, VISIBLE = 13, 21, 3     # three rows fill all above the legend
BOTTOM = HEIGHT - 1 - LEGEND_H        # where the legend starts


def fit(d, text, f, width):
    """text, cut with an ellipsis so it fits in width pixels."""
    if d.textlength(text, font=f) <= width:
        return text
    while text and d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip() + "…"


# Text too long for its place rolls by, round and round: it waits, glides one
# lap (text, a gap, the text again) with an ease in and out, and waits again.
# Each text keeps its own clock from when it first showed, so a row chosen
# anew starts from its beginning.
MARQUEE_WAIT, MARQUEE_SPEED, MARQUEE_GAP = 2.0, 18, 24   # seconds, pixels a second, pixels
_since = {}      # (slot, text) -> when it first showed
_seen = set()    # the keys drawn in this frame


def marquee(img, xy, width, text, f, fill, slot, now, anchor="la"):
    """Draws text at xy, or, when it is wider than width, rolling within width."""
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=f)
    if tw <= width:
        d.text(xy, text, font=f, fill=fill, anchor=anchor)
        return
    key = (slot, text)
    _seen.add(key)
    start = _since.setdefault(key, now)
    lap = tw + MARQUEE_GAP
    move = lap / MARQUEE_SPEED
    t = (now - start) % (MARQUEE_WAIT + move)
    p = 0.0 if t < MARQUEE_WAIT else (1 - math.cos(math.pi * (t - MARQUEE_WAIT) / move)) / 2
    offset = round(p * lap)
    asc, desc = f.getmetrics()
    h = asc + desc + 2
    layer = Image.new("RGBA", (int(width), h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((-offset, 1), text, font=f, fill=fill)
    ld.text((-offset + lap, 1), text, font=f, fill=fill)
    # Where plain text with this anchor would sit: its top at y ("la"), or its middle ("lm").
    x, y = xy
    y = round(y - h / 2) if anchor[1] == "m" else round(y) - 1
    img.paste(layer, (int(x), y), layer)


def star(d, cx, cy, r, fill, hollow=False):
    """A five-pointed star, centred at cx, cy, its points r from the centre; hollow, an outline."""
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy - rr * math.sin(a)))
    if hollow:
        d.polygon(pts, outline=fill, width=2)
    else:
        d.polygon(pts, fill=fill)


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
    right = WIDTH - 6 if len(rows) > VISIBLE else WIDTH - 2
    for i in range(first, min(len(rows), first + VISIBLE)):
        num, label, value = rows[i]
        on = i == sel
        mid = y + ROW_H // 2
        if on:
            d.rounded_rectangle([1, y, right, y + ROW_H - 1], radius=3, fill=OCHRE)
        x = 6
        fg = ON_OCHRE if on else INK
        if num == "★":
            star(d, x + 6, mid, 6.5, fg)
            x += 17
        elif num is not None:
            d.text((x, mid), str(num), font=ROW_VALUE(), fill=fg if on else INK_FAINT, anchor="lm")
            x += 17
        value = fit(d, value or "", ROW_VALUE(), 64)
        vw = d.textlength(value, font=ROW_VALUE())
        d.text((right - 5, mid), value, font=ROW_VALUE(), fill=fg if on else INK_FAINT, anchor="rm")
        f = ROW_BOLD() if on else ROW()
        if on:
            marquee(v["img"], (x, mid), right - 9 - x - vw, label, f, fg, "row", v["now"], anchor="lm")
        else:
            d.text((x, mid), fit(d, label, f, right - 9 - x - vw), font=f, fill=fg, anchor="lm")
        y += ROW_H
    if len(rows) > VISIBLE:
        # Where in the list: a thin bar in the right edge, its thumb as long as what shows.
        top, bottom = 2, BOTTOM - 2
        d.rectangle([WIDTH - 4, top, WIDTH - 3, bottom], fill=PAPER_SUNKEN)
        h = max(4, round((bottom - top) * VISIBLE / len(rows)))
        t = top + round((bottom - top - h) * first / (len(rows) - VISIBLE))
        d.rectangle([WIDTH - 4, t, WIDTH - 3, t + h], fill=INK_FAINT)
    if not rows:
        d.text((6, BOTTOM // 2), v.get("empty", "Tomt"), font=ROW(), fill=INK_MUTED, anchor="lm")


def draw_message(d, v):
    title, text = v.get("title", ""), v.get("text", "")
    color = ALARM if v.get("error") else INK
    # A long title steps down until it fits.
    f = next((f for f in (HUGE(), BIG(), TITLE()) if d.textlength(title, font=f) <= WIDTH - 10), TITLE())
    img, now = v["img"], v["now"]
    if text:
        marquee(img, (5, 4), WIDTH - 10, title, f, color, "title", now)
        marquee(img, (5, 32), WIDTH - 10, text, SUB(), INK_MUTED, "text", now)
    else:
        marquee(img, (5, BOTTOM // 2), WIDTH - 10, title, f, color, "title", now, anchor="lm")


def draw_playing(d, v):
    x, img, now = 5, v["img"], v["now"]
    marquee(img, (x, 1), WIDTH - 2 * x, v.get("title", ""), HUGE(), INK, "title", now)
    marquee(img, (x, 26), WIDTH - 2 * x, v.get("subtitle", ""), SUB(), INK_MUTED, "subtitle", now)
    y = 47
    if v.get("progress") is not None:
        d.rectangle([x, y, WIDTH - x, y + 2], fill=PAPER_SUNKEN)
        end = x + round((WIDTH - 2 * x) * max(0.0, min(1.0, v["progress"])))
        if end > x:
            d.rectangle([x, y, end, y + 2], fill=INK)
    y += 5
    if v.get("times"):
        left, right = v["times"]
        d.text((x, y), left, font=TIMES(), fill=INK_FAINT)
        d.text((WIDTH - x - d.textlength(right, font=TIMES()), y), right, font=TIMES(), fill=INK_FAINT)
    elif v.get("line"):
        marquee(img, (x, y - 7), WIDTH - 2 * x, v["line"], TIMES(), INK_FAINT, "line", now)
    if v.get("paused"):
        w = 10 + d.textlength("Pausad", font=MONO_BOLD())
        px = (WIDTH - w) // 2
        d.rectangle([px, y + 2, px + 1, y + 8], fill=INK)
        d.rectangle([px + 4, y + 2, px + 5, y + 8], fill=INK)
        d.text((px + 10, y + 1), "Pausad", font=MONO_BOLD(), fill=INK)
    elif v.get("position") and v.get("times"):
        pos = v["position"]
        d.text(((WIDTH - d.textlength(pos, font=TIMES())) / 2, y), pos, font=TIMES(), fill=INK_FAINT)


def draw_notice(d, n):
    """A small label over one big word or number, in a panel in the middle of the screen."""
    x0, y0, x1, y1 = 3, 4, WIDTH - 4, HEIGHT - 5
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], fill=PAPER)        # nothing behind it shows through
    d.rounded_rectangle([x0, y0, x1, y1], radius=4, fill=PAPER_RAISED, outline=LINE_STRONG)
    label = n["label"]
    lf = font("Mono-Regular", 10)
    d.text(((WIDTH - d.textlength(label, font=lf)) / 2, y0 + 6), label, font=lf, fill=INK_FAINT)
    value = n["value"]
    room = x1 - x0 - 10 - (26 if n.get("star") else 0)
    # As big as fits: numbers in mono, words in the interface face.
    sizes = ((font("Mono-SemiBold", s) for s in (34, 28, 22, 18)) if n.get("mono")
             else (font("Sans-SemiBold", s) for s in (28, 24, 20, 16, 13)))
    for f in sizes:
        box = d.textbbox((0, 0), value, font=f)
        if box[2] - box[0] <= room:
            break
    else:
        if " " in value and not n.get("star"):     # a long name: two lines, split near the middle
            f = font("Sans-SemiBold", 18)
            words = value.split(" ")
            cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(value) / 2))
            for k, line in enumerate((" ".join(words[:cut]), " ".join(words[cut:]))):
                line = fit(d, line, f, room)
                d.text((WIDTH / 2, y0 + 32 + k * 21), line, font=f, fill=INK, anchor="mm")
            return
    value = fit(d, value, f, room)
    box = d.textbbox((0, 0), value, font=f)
    w = box[2] - box[0] + (26 if n.get("star") else 0)
    x, mid = (WIDTH - w) / 2, y0 + 42
    if n.get("star"):
        star(d, x + 10, mid, 11, INK, hollow=n["star"] == "empty")
        x += 26
    d.text((x - box[0], mid - (box[3] - box[1]) / 2 - box[1]), value, font=f, fill=INK)
    if n.get("strike"):     # off: the word struck through
        d.line([(x - 3, mid), (x + box[2] - box[0] + 3, mid)], fill=INK, width=2)


def draw_start(d):
    f = font("Sans-Bold", 18)
    text = "PIONEER CD"
    d.text(((WIDTH - d.textlength(text, font=f)) / 2, 22), text, font=f, fill=INK)
    d.text(((WIDTH - d.textlength("STARTAR", font=MONO())) / 2, 48), "STARTAR", font=MONO(), fill=INK_FAINT)


def render(v, now=None):
    if v["kind"] == "off":
        return Image.new("RGB", (WIDTH, HEIGHT), "#000000")
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(img)
    v = {**v, "img": img, "now": time.monotonic() if now is None else now}
    _seen.clear()
    kind = v["kind"]
    if kind == "start":
        draw_start(d)
    else:
        {"list": draw_list, "message": draw_message, "playing": draw_playing}[kind](d, v)
        if v.get("notice"):
            draw_notice(d, v["notice"])         # centred on the whole screen, over the legend too
        elif v.get("legend"):
            legend(d, v["legend"])
    for key in set(_since) - _seen:     # a text no longer shown starts over when it comes back
        del _since[key]
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=FRAME)   # dark edge, as the panel's own
    return img
