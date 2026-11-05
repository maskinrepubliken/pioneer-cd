"""Saving a CD: FLAC files on the Pi, then into Jellyfin's music on the server.

The drive reads one place at a time, so playing and saving cannot share it
without the playing stuttering: the disc is saved only while it does not
play. cdparanoia reads a track at a time (its fast mode, -Z, about 7×: the
paranoid modes read slower than the music plays on this drive), and is
stopped (SIGSTOP) the moment the disc plays again and goes on (SIGCONT)
when it stops or pauses. flac encodes each track, tagged, beside it.

When all tracks are saved the album goes to the server as a tar stream over
ssh, with a key the server only lets unpack into its Pioneer CD folder, and
Jellyfin is told the folder is new. What is saved stays on the Pi:
<state>/cd-rips/<disc id>/<artist>/<album>/NN title.flac, and a done file
once it is on the server. A disc taken out stops the saving; put back, it
goes on from the tracks already saved.
"""
import json
import os
import signal
import subprocess
import threading
import time

from . import cd

READ = ["cdparanoia", "-q", "-Z", "-d", cd.DEVICE]


def safe(name):
    """A name fit for a folder or a file, on the Pi and on the server."""
    name = "".join("-" if c in '/\\:*?"<>|' else c for c in name).strip().lstrip(".")
    return name[:120] or "Okänd"


def folders(album):
    """(artist, album) folder names: a disc with no album title gets its barcode or id."""
    artist = album["artist"] or "Okänd artist"
    title = album["title"]
    if title in ("CD", "Okänd skiva"):
        title = f"Skiva {album.get('barcode') or album['discid'][:8]}"
    return safe(artist), safe(title)


class Ripper:
    def __init__(self, state, upload, jellyfin, playing, disc_id):
        """upload: the config's [upload] table (host, key, folder); playing(): whether the
        disc plays now; disc_id(): the id of the disc in the drive, or None."""
        self.root = os.path.join(state, "cd-rips")
        self.upload, self.jf, self.playing, self.disc_id = upload or {}, jellyfin, playing, disc_id
        self.status = {}            # discid -> what the saving of that disc is at, for the screen
        self.thread = None

    def done(self, discid):
        return os.path.exists(os.path.join(self.root, discid, "done.json"))

    def state_of(self, discid):
        """For the screen: "sparad", "väntar", "3 av 7", "skickar", "fel", or ""."""
        if self.done(discid):
            return "sparad"
        return self.status.get(discid, "")

    def start(self, album):
        """Saves album's disc in the background. False if it is saved, or saving, already."""
        if self.done(album["discid"]) or (self.thread and self.thread.is_alive()):
            return False
        self.status[album["discid"]] = "väntar"
        self.thread = threading.Thread(target=self._run, args=(album,), daemon=True)
        self.thread.start()
        return True

    # ------------------------------------------------------------ the work
    def _run(self, album):
        discid = album["discid"]
        try:
            artist, title = folders(album)
            where = os.path.join(self.root, discid, artist, title)
            os.makedirs(where, exist_ok=True)
            tracks = album["tracks"]
            for k, track in enumerate(tracks, 1):
                name = f"{track['number']:02d} {safe(track['title'])}.flac"
                if os.path.exists(os.path.join(where, name)):
                    continue
                self.status[discid] = f"{k} av {len(tracks)}"
                wav = os.path.join(self.root, discid, f"{track['number']:02d}.wav")
                if not self._read(discid, track["number"], wav):
                    self.status[discid] = "avbruten"
                    return
                self._encode(wav, os.path.join(where, name), album, track, len(tracks))
            self.status[discid] = "skickar"
            self._send(discid, artist, title)
            with open(os.path.join(self.root, discid, "done.json"), "w") as f:
                json.dump({"artist": artist, "album": title, "saved": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f)
                f.flush()
                os.fsync(f.fileno())
            self.status[discid] = "sparad"
        except Exception as e:
            print("rip:", repr(e), flush=True)
            self.status[discid] = "fel"

    def _read(self, discid, number, wav):
        """One track to a wav, only while the disc does not play: stopped while it does."""
        while self.playing():
            if self.disc_id() != discid:
                return False
            time.sleep(1)
        proc = subprocess.Popen(READ + [str(number), wav + ".part"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        stopped = False
        while proc.poll() is None:
            if self.disc_id() != discid:            # taken out, or another disc
                if stopped:
                    proc.send_signal(signal.SIGCONT)
                proc.kill()
                proc.wait()
                return False
            busy = self.playing()
            if busy and not stopped:
                proc.send_signal(signal.SIGSTOP)
                stopped = True
            elif not busy and stopped:
                proc.send_signal(signal.SIGCONT)
                stopped = False
            time.sleep(0.2)
        if proc.returncode != 0:
            raise RuntimeError(f"cdparanoia: track {number}: exit {proc.returncode}")
        os.replace(wav + ".part", wav)
        return True

    def _encode(self, wav, flac, album, track, total):
        tags = {"TITLE": track["title"], "ARTIST": track["artist"] or album["artist"],
                "ALBUM": album["title"], "ALBUMARTIST": album["artist"], "TRACKNUMBER": str(track["number"]),
                "TRACKTOTAL": str(total), "DATE": album.get("year") or "",
                "MUSICBRAINZ_ALBUMID": album.get("musicbrainz_release") or "", "MUSICBRAINZ_DISCID": album["discid"],
                "BARCODE": album.get("barcode") or ""}
        args = ["nice", "-n", "15", "flac", "-s", "-f", "-5", "-o", flac + ".part"]
        args += [f"--tag={k}={v}" for k, v in tags.items() if v]
        subprocess.run(args + [wav], check=True)
        os.replace(flac + ".part", flac)
        os.remove(wav)

    def _send(self, discid, artist, title):
        """The album folder to the server, and word to Jellyfin that it is there."""
        host, key = self.upload.get("host"), self.upload.get("key")
        if not host or not key:
            return                                  # saved on the Pi only
        ssh = ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
               "-o", f"UserKnownHostsFile={os.path.join(os.path.dirname(key), 'known_hosts')}",
               "-o", "StrictHostKeyChecking=accept-new", host]
        tar = subprocess.Popen(["tar", "-C", os.path.join(self.root, discid), "-cf", "-",
                                os.path.join(artist, title)], stdout=subprocess.PIPE)
        sent = subprocess.run(ssh, stdin=tar.stdout, capture_output=True)
        tar.stdout.close()
        if tar.wait() or sent.returncode:
            raise RuntimeError(f"upload: {sent.stderr.decode(errors='replace').strip()[-200:]}")
        folder = self.upload.get("folder")
        if self.jf and folder:
            self.jf.media_updated(os.path.join(folder, artist, title))
