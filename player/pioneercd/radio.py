"""The radio: Sveriges Radio's live MP3s, with what is on now and next from
SR's open API (the same streams as the radio in Pioneer TV), and other
stations by their stream's address, which tell the song playing in the
stream itself (mpv's media-title)."""
import datetime
import json
import re
import urllib.request

# An SR channel by its id (api.sr.se/api/v2/channels), another station by
# its stream. P4 is regional: 206 is P4 Sjuhärad. The config can replace the list.
CHANNELS = [
    {"id": 132, "name": "P1"},
    {"id": 163, "name": "P2"},
    {"id": 164, "name": "P3"},
    {"id": 206, "name": "P4 Sjuhärad"},
    {"id": 2755, "name": "Radioapans knattekanal"},
    {"name": "Lugna Favoriter", "url": "https://fm03-ice.stream.khz.se/fm03_mp3"},
    {"name": "Bandit Rock", "url": "https://fm02-ice.stream.khz.se/fm02_mp3"},
    {"name": "Yoga Chill", "url": "http://178.32.111.41:8027/stream-128kmp3-YogaChill"},
    {"name": "Nightride FM", "url": "https://stream.nightride.fm/nightride.mp3"},
    {"name": "Sensual Lounge", "url": "https://kathy.torontocast.com:3590/;"},
    {"name": "Radio Art Tantra", "url": "https://live.radioart.com/fTantra.mp3"},
]


def stream_url(channel):
    return channel.get("url") or f"https://sverigesradio.se/topsy/direkt/srapi/{channel['id']}.mp3"


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
