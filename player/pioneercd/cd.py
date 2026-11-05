"""The CD drive: whether a disc is in, what is on it, and its names.

Whether a disc is in is asked straight from the drive with the kernel's
CD-ROM ioctls (the user is in the cdrom group), every few seconds in a
thread of its own: an answer can take a moment while the disc spins up.

The names come, in turn, from a file of our own for the disc
(<state>/cd/<disc id>.json, which can also be written by hand), from
MusicBrainz by the disc's id or else its tracks' lengths, or else are
Spår 1, 2, … What MusicBrainz says is kept in that file, so a disc is
looked up once. mpv plays the disc as one file, a chapter a track.
"""
import fcntl
import json
import os
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
    d = libdiscid.read(device)
    starts = [(o - 150) / 75 for o in d.track_offsets]
    return {"discid": d.id, "toc": d.toc, "submit": d.submission_url,
            "tracks": [{"number": d.first_track + i, "start": start, "seconds": n / 75}
                       for i, (start, n) in enumerate(zip(starts, d.track_lengths))]}


def _musicbrainz(query):
    req = urllib.request.Request(MUSICBRAINZ + query, headers={"User-Agent": USER_AGENT})
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
    """The disc's names, merged onto its tracks: from our file, MusicBrainz or none."""
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
        if names:
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
            "title": names.get("title") or "Okänd skiva", "artist": names.get("artist") or "",
            "year": names.get("year") or "", "source": names.get("source") or "",
            "musicbrainz_release": names.get("musicbrainz_release"), "tracks": tracks}
