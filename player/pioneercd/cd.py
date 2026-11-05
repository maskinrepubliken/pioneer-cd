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
import ctypes
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
CDS_NO_DISC, CDS_TRAY_OPEN, CDS_DISC_OK = 1, 2, 4
CDS_AUDIO, CDS_MIXED = 100, 105


def disc(device=DEVICE):
    """"audio" for a disc with music on it, "data" for another disc, "empty" for the tray
    shut with no disc in, "open" for the tray open, None while the drive is not ready (or none)."""
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0)
        if status != CDS_DISC_OK:
            return {CDS_NO_DISC: "empty", CDS_TRAY_OPEN: "open"}.get(status)
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


class _SgIoHdr(ctypes.Structure):
    """Linux's sg_io_hdr: a SCSI command straight to the drive (SG_IO)."""
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int),
                ("cmd_len", ctypes.c_ubyte), ("mx_sb_len", ctypes.c_ubyte), ("iovec_count", ctypes.c_ushort),
                ("dxfer_len", ctypes.c_uint), ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p),
                ("sbp", ctypes.c_void_p), ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("pack_id", ctypes.c_int), ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte),
                ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte), ("sb_len_wr", ctypes.c_ubyte),
                ("host_status", ctypes.c_ushort), ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int),
                ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


def cd_text(device=DEVICE):
    """The disc's own CD-Text: {"title", "artist", "tracks": [{"title", "artist"}]}, or {}.

    Asked of the drive with READ TOC format 5 (a fifth of a second; cd-info
    takes half a minute). The answer is 18-byte packs: a kind (0x80 titles,
    0x81 performers), the track the pack's text starts in, and 12 bytes of
    text, the strings of track after track one after another, NUL between.
    "Audio CD" is no title, and an empty performer no artist."""
    n = 8192
    buf, sense = ctypes.create_string_buffer(n), ctypes.create_string_buffer(32)
    cdb = (ctypes.c_ubyte * 10)(0x43, 0, 5, 0, 0, 0, 0, n >> 8, n & 0xFF, 0)
    h = _SgIoHdr(interface_id=ord("S"), dxfer_direction=-3, cmd_len=10, mx_sb_len=32, dxfer_len=n,
                 dxferp=ctypes.cast(buf, ctypes.c_void_p), cmdp=ctypes.cast(cdb, ctypes.c_void_p),
                 sbp=ctypes.cast(sense, ctypes.c_void_p), timeout=10000)
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, 0x2285, h)                  # SG_IO
        finally:
            os.close(fd)
    except OSError:
        return {}
    if h.status or h.host_status or h.driver_status:
        return {}
    raw = buf.raw[4:min(int.from_bytes(buf.raw[:2], "big") + 2, n)]
    texts = {}
    for i in range(0, len(raw) - 17, 18):
        kind, track, block = raw[i], raw[i + 1] & 0x7F, (raw[i + 3] >> 4) & 7
        if block == 0 and kind in (0x80, 0x81):         # the first language's titles and performers
            texts.setdefault(kind, [track, b""])[1] += raw[i + 4:i + 16]
    found = {}
    for kind, (first, data) in texts.items():
        for k, part in enumerate(data.split(b"\0")):
            text = part.decode("latin-1").strip()
            if text:
                found.setdefault(first + k, {})["title" if kind == 0x80 else "artist"] = text
    tracks = sorted(k for k in found if k)
    if not tracks:
        return {}
    disc = found.get(0, {})
    title = disc.get("title", "")
    return {"title": "" if title.lower() == "audio cd" else title, "artist": disc.get("artist", ""),
            "source": "cd-text", "tracks": [found.get(n, {}) for n in range(1, tracks[-1] + 1)]}


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


def _look_up(toc, path):
    """MusicBrainz (kept in path), or else the disc's own CD-Text."""
    names = {}
    try:
        names = _from_musicbrainz(toc)
    except (OSError, ValueError) as e:
        print("musicbrainz:", repr(e), flush=True)
    if not names:
        return cd_text()                # the disc's own: not kept, it is on the disc
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(path + ".tmp", path)
    return names


def album(toc, state, look_up=True):
    """The disc's names, merged onto its tracks: from our file, MusicBrainz, CD-Text or none.
    Without look_up only our file and the CD-Text are read, which is quick: enough to start playing."""
    path = os.path.join(state, "cd", toc["discid"] + ".json")
    names = {}
    try:
        with open(path) as f:
            names = json.load(f)
    except (OSError, ValueError):
        names = _look_up(toc, path) if look_up else cd_text()
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
