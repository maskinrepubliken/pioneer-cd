"""The CD drive: whether a disc is in, what is on it, and its names.

Whether a disc is in is asked straight from the drive with the kernel's
CD-ROM ioctls (the user is in the cdrom group), every few seconds in a
thread of its own: an answer can take a moment while the disc spins up.

The names come, in turn, from a file of our own for the disc
(<state>/cd/<disc id>.json, which can also be written by hand), from
MusicBrainz by the disc's id, its tracks' lengths or its barcode, from the
CD-Text on the disc itself, or else are Spår 1, 2, … What MusicBrainz says
is kept in that file, so a disc is looked up once. mpv plays the disc as one file, a chapter a track.
"""
import fcntl
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

MUSICBRAINZ = "https://musicbrainz.org/ws/2/discid/"
USER_AGENT = "PioneerCD/1.0 ( https://github.com/maskinrepubliken/pioneer-cd )"

DEVICE = "/dev/sr0"
CDROM_DRIVE_STATUS, CDROM_DISC_STATUS = 0x5326, 0x5327
CDS_DISC_OK = 4
CDS_AUDIO, CDS_MIXED = 100, 105


def disc(device=DEVICE):
    """"audio" for a disc with music on it, "data" for another disc, None for none (or no drive)."""
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0) != CDS_DISC_OK:
            return None
        return "audio" if fcntl.ioctl(fd, CDROM_DISC_STATUS, 0) in (CDS_AUDIO, CDS_MIXED) else "data"
    except OSError:
        return None
    finally:
        os.close(fd)


def watch(changed, every=3):
    """Calls changed(disc()) now and whenever the answer changes."""
    def run():
        last = object()
        while True:
            now = disc()
            if now != last:
                last = now
                changed(now)
            time.sleep(every)
    threading.Thread(target=run, daemon=True).start()


def read_toc(device=DEVICE):
    """The disc's id for MusicBrainz and its tracks' starts and lengths, in seconds."""
    import libdiscid
    d = libdiscid.read(device, features=libdiscid.FEATURE_READ | libdiscid.FEATURE_MCN)
    starts = [(o - 150) / 75 for o in d.track_offsets]
    return {"discid": d.id, "toc": d.toc, "submit": d.submission_url, "barcode": d.mcn or "",
            "tracks": [{"number": d.first_track + i, "start": start, "seconds": n / 75}
                       for i, (start, n) in enumerate(zip(starts, d.track_lengths))]}


def cd_text(device=DEVICE):
    """The disc's own CD-Text, read by cd-info: {"title", "artist", "tracks": [{"title", "artist"}]}.
    "Audio CD" is no title, and an empty performer no artist."""
    try:
        out = subprocess.run(["cd-info", "--no-header", "--no-device-info", device],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    disc, tracks, block = {}, {}, None
    for line in out.splitlines():
        m = re.match(r"CD-TEXT for (Disc|Track\s+(\d+)):", line)
        if m:
            block = disc if m.group(1) == "Disc" else tracks.setdefault(int(m.group(2)), {})
            continue
        m = re.match(r"\s+(TITLE|PERFORMER):\s*(.*)", line)
        if m and block is not None:
            block["title" if m.group(1) == "TITLE" else "artist"] = m.group(2).strip()
        elif not line.startswith("\t"):
            block = None
    if not tracks:
        return {}
    title = disc.get("title", "")
    return {"title": "" if title.lower() == "audio cd" else title, "artist": disc.get("artist", ""),
            "source": "cd-text", "tracks": [tracks.get(n, {}) for n in range(1, max(tracks) + 1)]}


def _musicbrainz(query, base=MUSICBRAINZ):
    time.sleep(1)       # MusicBrainz takes one request a second
    req = urllib.request.Request(base + query, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _from_musicbrainz(toc):
    """The release whose disc matches, by id or else by the tracks' lengths: {} for none."""
    inc = "inc=artist-credits+recordings&fmt=json"
    data = {}
    try:
        data = _musicbrainz(f"{toc['discid']}?{inc}")
    except OSError:
        pass
    if not data.get("releases"):
        data = _musicbrainz(f"-?toc={toc['toc'].replace(' ', '+')}&{inc}")
    if not data.get("releases") and toc.get("barcode"):
        found = _musicbrainz(f"?query=barcode:{toc['barcode']}&fmt=json", MUSICBRAINZ.replace("discid/", "release/"))
        ids = [r["id"] for r in found.get("releases", [])][:1]
        if ids:
            data = {"releases": [_musicbrainz(f"{ids[0]}?{inc}", MUSICBRAINZ.replace("discid/", "release/"))]}
    n = len(toc["tracks"])
    for release in data.get("releases", []):
        for medium in release.get("media", []):
            tracks = medium.get("tracks") or []
            if len(tracks) != n:
                continue
            credit = lambda c: "".join(a["name"] + a.get("joinphrase", "") for a in c or [])
            artist = credit(release.get("artist-credit"))
            return {"title": release.get("title"), "artist": artist, "year": (release.get("date") or "")[:4],
                    "musicbrainz_release": release.get("id"), "source": "musicbrainz",
                    "tracks": [{"title": t.get("title"), "artist": credit(t.get("artist-credit")) or artist}
                               for t in tracks]}
    return {}


def album(toc, state):
    """The disc's names, merged onto its tracks: from our file, MusicBrainz, CD-Text or none."""
    path = os.path.join(state, "cd", toc["discid"] + ".json")
    names = {}
    try:
        with open(path) as f:
            names = json.load(f)
    except (OSError, ValueError):
        try:
            names = _from_musicbrainz(toc)
        except (OSError, ValueError) as e:
            print("musicbrainz:", repr(e), flush=True)
        if not names:
            names = cd_text()               # the disc's own: not kept, it is on the disc
        elif names.get("source") == "musicbrainz":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w") as f:
                json.dump(names, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(path + ".tmp", path)
    named = names.get("tracks") or []
    tracks = []
    for i, t in enumerate(toc["tracks"]):
        extra = named[i] if i < len(named) else {}
        tracks.append({**t, "title": extra.get("title") or f"Spår {t['number']}",
                       "artist": extra.get("artist") or names.get("artist") or ""})
    return {"discid": toc["discid"], "submit": toc["submit"], "file": path,
            "title": names.get("title") or ("CD" if names else "Okänd skiva"), "artist": names.get("artist") or "",
            "year": names.get("year") or "", "source": names.get("source") or "",
            "musicbrainz_release": names.get("musicbrainz_release"), "tracks": tracks}
