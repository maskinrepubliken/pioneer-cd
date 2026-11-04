"""Sveriges Radio: the live MP3 of a channel, and what is on now and next
from SR's open API. The same streams as the radio in Pioneer TV."""
import datetime
import json
import re
import urllib.request

# Channel ids are SR's. P4 is regional: 206 is P4 Sjuhärad, as in Pioneer TV
# (701 is P4 Stockholm). Other channels go in the config.
CHANNELS = [(132, "P1"), (163, "P2"), (164, "P3"), (206, "P4")]


def stream_url(channel):
    return f"https://sverigesradio.se/topsy/direkt/srapi/{channel}.mp3"


def _time(value):
    """'/Date(1793782800000)/' -> '10:20', local time."""
    m = re.search(r"\d+", value or "")
    if not m:
        return ""
    return datetime.datetime.fromtimestamp(int(m.group()) / 1000).strftime("%H:%M")


def parse(data):
    """SR's rightnow answer -> {"now": (title, "10:03–10:38"), "next": (title, "10:40")}."""
    ch = data.get("channel") or {}
    out = {}
    cur = ch.get("currentscheduledepisode")
    if cur:
        out["now"] = (cur.get("title", ""), f"{_time(cur.get('starttimeutc'))}–{_time(cur.get('endtimeutc'))}")
    nxt = ch.get("nextscheduledepisode")
    if nxt:
        out["next"] = (nxt.get("title", ""), _time(nxt.get("starttimeutc")))
    return out


def now_next(channel, timeout=5):
    url = f"https://api.sr.se/api/v2/scheduledepisodes/rightnow?channelid={channel}&format=json"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return parse(json.load(r))
