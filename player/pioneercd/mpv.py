"""mpv, run in the background and steered over its JSON IPC socket.

One mpv plays everything: Jellyfin's tracks as a playlist, a radio channel
as one endless stream. The properties the screen shows are observed and
kept in self.props.
"""
import itertools
import json
import os
import socket
import subprocess
import threading
import time

OBSERVED = ("pause", "time-pos", "duration", "playlist-pos", "playlist-count", "idle-active", "paused-for-cache",
            "media-title")


class Mpv:
    def __init__(self, sock_path):
        self.path = sock_path
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        self.proc = subprocess.Popen(
            ["mpv", "--idle=yes", "--no-video", "--no-terminal", "--audio-display=no",
             "--cache=yes", "--demuxer-max-bytes=8MiB", f"--input-ipc-server={sock_path}"],
            stdin=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(sock_path)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("mpv did not open its socket")
        self.props = {"idle-active": True}
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()
        for i, name in enumerate(OBSERVED, 1):
            self.command("observe_property", i, name)

    def _read(self):
        buf = b""
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("event") == "property-change":
                    self.props[msg["name"]] = msg.get("data")

    def command(self, *args):
        with self.lock:
            self.sock.sendall(json.dumps({"command": list(args), "request_id": next(self.ids)}).encode() + b"\n")

    def set(self, name, value):
        self.command("set_property", name, value)

    def play(self, urls, start=0, headers=()):
        """Replaces what plays with urls and starts at urls[start]."""
        self.set("http-header-fields", list(headers))
        self.command("loadfile", urls[0], "replace")
        for url in urls[1:]:
            self.command("loadfile", url, "append")
        if start:
            self.command("playlist-play-index", start)
        self.set("pause", False)

    def load(self, url, start=0.0):
        """Plays one url from start seconds (the CD: the whole disc, a chapter a track)."""
        self.set("http-header-fields", [])
        self.command("loadfile", url, "replace", -1, f"start={start:.2f}")
        self.set("pause", False)

    def toggle(self):
        self.command("cycle", "pause")

    def step(self, delta):
        self.command("playlist-next" if delta > 0 else "playlist-prev")

    def stop(self):
        self.command("stop")

    def close(self):
        self.proc.terminate()
