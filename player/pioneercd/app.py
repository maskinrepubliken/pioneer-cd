"""The screens and what the buttons do on them.

The app is a stack of screens; the top one gets the joystick. Some buttons
work the same everywhere: A and B set the volume, A and B together mute,
holding the middle goes Home, and left goes back. After a while without a
press the screen goes dark, and the first press only lights it again.
"""
import json
import math
import os
import random
import subprocess
import threading
import time

from . import jellyfin, radio

OVERLAY_SECONDS = 2
TIMER_MINUTES = [0, 10, 20, 30, 50, 60]   # Sovtimer's steps; 0 is off
FADE_SECONDS = 30                         # the timer's last half minute fades out
FADE_DB = 40


def clock(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------- settings


class Settings:
    """What the config's [player] table sets (see config.example.toml), and the
    volume, which is the player's own and kept between boots in a state file."""
    DEFAULTS = {"volume": 28, "volume_cap": 60, "brightness": 100, "sleep_minutes": 10, "bluetooth_boost": 8}

    def __init__(self, path, config=None):
        self.path = path
        self.values = {**self.DEFAULTS, **(config or {})}
        try:
            with open(path) as f:
                self.values["volume"] = int(json.load(f)["volume"])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def __getitem__(self, name):
        return self.values[name]

    def set(self, name, value):
        self.values[name] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # Written beside and renamed over, and synced: a power cut leaves the old file, not an empty one.
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"volume": self.values["volume"]}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


class Volume:
    """The volume as on a TV: a number from 0 to 100, one step a press.

    It sets "Pioneer", the softvol control in system/asound.conf, to
    27·log10(n/100) dB: 28 is -15 dB, the level that sounded right through
    the Lepai with its knob where it is, 50 is -8 dB and 100 is full. The
    card's own control stays at full.
    """
    CARD, CONTROL = "Device", "Pioneer"

    def __init__(self, level):
        self.level = level
        self.muted = False
        self.boost = 0          # dB on top, for a source that comes in quieter (Bluetooth)
        self.fade = 0           # dB off, while the sleep timer fades out
        run = lambda *a: subprocess.run(["amixer", "-q", "-c", self.CARD, *a], capture_output=True)
        run("sset", "Speaker", "100%", "unmute")
        if run("sget", self.CONTROL).returncode:
            # softvol makes its control the first time something plays: a second of silence.
            subprocess.run(["aplay", "-q", "-d", "1", "-f", "cd", "/dev/zero"], capture_output=True)
        self.apply()

    @staticmethod
    def db(level):
        return max(-60.0, 27 * math.log10(level / 100)) if level > 0 else -60.0

    def apply(self):
        db = -60.0 if self.muted else max(-60.0, min(0.0, self.db(self.level) + self.boost) - self.fade)
        subprocess.run(["amixer", "-q", "-c", self.CARD, "sset", self.CONTROL, "--", f"{db:.1f}dB"],
                       capture_output=True)

    def set(self, level, cap):
        self.level = max(0, min(cap, level))
        self.muted = False
        self.apply()

    def toggle_mute(self):
        self.muted = not self.muted
        self.apply()


# ---------------------------------------------------------------- screens


class ListScreen:
    """A list to move through with up and down; the middle (or right) picks."""

    def __init__(self, title, rows, pick=None, verb="välj", root=False):
        self.title, self.rows, self.pick, self.verb, self.root = title, rows, pick, verb, root
        self.sel = 0

    def view(self, app):
        legend = [("●", self.verb), ("▲▼", "bläddra")] if self.root else [("●", self.verb), ("◀", "tillbaka")]
        n = len(self.rows)
        return {"kind": "list", "status": (self.title.upper(), f"{self.sel + 1} AV {n}" if n else ""),
                "rows": [(r.get("num"), r["label"], r.get("value", "")) for r in self.rows],
                "selected": self.sel, "legend": legend}

    def key(self, app, ev):
        if ev in ("up", "down") and self.rows:     # round: up from the top is the last row
            self.sel = (self.sel + (1 if ev == "down" else -1)) % len(self.rows)
        elif ev in ("up_fast", "down_fast") and self.rows:
            self.sel = self.jump(1 if ev == "down_fast" else -1)
        elif ev in ("center", "right") and self.rows and self.pick:
            self.pick(app, self.rows[self.sel])
        elif ev == "left" and not self.root:
            app.back()


    def jump(self, step):
        """The first row of the next (or this, or the previous) letter: held long, up and down go by letters."""
        letter = lambda i: self.rows[i]["label"][:1].upper()
        i, here = self.sel, letter(self.sel)
        if step > 0:
            while i < len(self.rows) - 1 and letter(i) == here:
                i += 1
            return i
        if i > 0 and letter(i - 1) != here:     # at the top of a letter: go to the one before
            i -= 1
            here = letter(i)
        while i > 0 and letter(i - 1) == here:
            i -= 1
        return i


class MessageScreen:
    def __init__(self, status, title, text="", error=False, retry=None):
        self.status, self.title, self.text, self.error, self.retry = status, title, text, error, retry

    def view(self, app):
        legend = ([("●", "försök igen")] if self.retry else []) + [("◀", "tillbaka")]
        return {"kind": "message", "status": (self.status, ""), "title": self.title, "text": self.text,
                "error": self.error, "legend": legend}

    def key(self, app, ev):
        if ev == "left":
            app.back()
        elif ev == "center" and self.retry:
            app.back()
            self.retry(app)


class PlayingScreen:
    """Spelas nu: the queue from Jellyfin (Bibliotek on the screen) in mpv. Up and down change track."""

    def view(self, app):
        p = app.mpv.props
        q = app.queue
        i = p.get("playlist-pos")
        if not q or i is None or i < 0 or p.get("idle-active"):
            return {"kind": "message", "status": ("BIBLIOTEK", ""), "title": "Inget spelas",
                    "legend": [("◀", "tillbaka")]}
        t = q[min(i, len(q) - 1)]
        pos, dur = p.get("time-pos") or 0, p.get("duration") or jellyfin.seconds(t)
        paused = bool(p.get("pause"))
        return {"kind": "playing", "position": f"{i + 1} av {len(q)}",
                "title": t.get("Name", ""), "subtitle": jellyfin.artist(t),
                "progress": pos / dur if dur else None, "times": (clock(pos), clock(dur)), "paused": paused,
                "legend": [("●", "spela" if paused else "paus"), ("▲▼", "spår"), ("◀", "lista"), ("▶", "val")]}

    def key(self, app, ev):
        if ev == "center":
            app.notify("UPPSPELNING", "Spelar" if app.mpv.props.get("pause") else "Pausad")
            app.mpv.toggle()
        elif ev in ("up", "down"):
            app.mpv.step(1 if ev == "down" else -1)
        elif ev == "right":
            app.push(OptionsScreen("jellyfin"))
        elif ev == "left":
            app.back()


class RadioScreen:
    """Radio, spelar: a live channel. Up and down change channel; pausing
    stops the stream, and playing again picks it up live."""

    def view(self, app):
        cid, name = app.channels[app.channel]
        info = app.radio_info.get(cid, {})
        title, when = info.get("now", (name, ""))
        nxt = info.get("next")
        stopped = app.mpv.props.get("idle-active")
        return {"kind": "playing", "title": title, "subtitle": f"{name} · {when}" if when else name,
                "line": f"Nästa {nxt[1]} {nxt[0]}" if nxt else "", "paused": stopped,
                "legend": [("●", "spela" if stopped else "paus"), ("▲▼", "kanal"), ("◀", "lista"), ("▶", "val")]}

    def key(self, app, ev):
        if ev == "center":
            if app.mpv.props.get("idle-active"):
                app.notify("UPPSPELNING", "Spelar")
                app.play_radio(app.channel)
            else:
                app.notify("UPPSPELNING", "Pausad")
                app.mpv.stop()
        elif ev == "right":
            app.push(OptionsScreen("radio"))
        elif ev in ("up", "down"):
            app.play_radio((app.channel + (1 if ev == "down" else -1)) % len(app.channels))
        elif ev == "left":
            app.back()


class BluetoothScreen:
    """Blåtand: while it is on the screen, phones can find and pair with Pioneer CD
    (App.poll_bt sees to it, however the screen is left). Opened by itself
    when a phone starts to play, it is only Spelas nu, and not visible. With
    a phone connected it shows what plays there; up and down change track."""

    def __init__(self, pairing=True):
        self.pairing = pairing

    def view(self, app):
        st = app.bt.state if app.bt else {}
        if not st:
            return {"kind": "message", "status": ("BLÅTAND", "SYNLIG"), "title": "Väntar på telefon",
                    "text": "Anslut till Pioneer CD.", "legend": [("◀", "stäng av")]}
        if not st.get("title"):
            playing = st.get("streaming")
            return {"kind": "message",
                    "title": f"Spelar från {st['device']}" if playing else f"{st['device']} är ansluten",
                    "text": "Telefonen visar inte vad." if playing else "Spela något på telefonen.",
                    "legend": [("◀", "tillbaka")]}
        paused = not (st.get("status") == "playing" or st.get("streaming"))
        dur, pos = st.get("duration") or 0, st.get("position") or 0
        artist = st.get("artist", "")
        return {"kind": "playing",
                "title": st["title"], "subtitle": f"{artist} · {st['device']}" if artist else st["device"],
                "progress": pos / dur if dur else None, "times": (clock(pos), clock(dur)) if dur else None,
                "paused": paused,
                "legend": [("●", "spela" if paused else "paus"), ("▲▼", "spår"), ("◀", "tillbaka"), ("▶", "val")]}

    def key(self, app, ev):
        st = app.bt.state if app.bt else {}
        if ev == "center" and st:
            playing = st.get("status") == "playing" or st.get("streaming")
            app.notify("UPPSPELNING", "Pausad" if playing else "Spelar")
            app.bt_control("Pause" if playing else "Play")
        elif ev == "right" and st:
            app.push(OptionsScreen("bluetooth"))
        elif ev in ("up", "down") and st:
            app.bt_control("Next" if ev == "down" else "Previous")
        elif ev == "left":
            app.back()


class OptionsScreen:
    """Val, right from Spelas nu: Blanda and Upprepa for the library's queue,
    and for every source Sovtimer and Vila. The middle changes a row."""
    REPEAT = {"no": "av", "track": "låten", "list": "listan"}

    def __init__(self, source):
        self.source = source
        self.sel = 0

    def rows(self, app):
        rows = []
        if self.source == "jellyfin":
            rows += [("shuffle", "Blanda", "på" if app.shuffled else "av"),
                     ("repeat", "Upprepa", self.REPEAT[app.repeat])]
        return rows + [("timer", "Sovtimer", app.timer_text()), ("sleep", "Vila", "")]

    def view(self, app):
        rows = self.rows(app)
        return {"kind": "list", "rows": [(None, label, value) for _, label, value in rows],
                "selected": self.sel, "legend": [("●", "ändra"), ("◀", "tillbaka")]}

    def key(self, app, ev):
        rows = self.rows(app)
        if ev in ("up", "down"):
            self.sel = (self.sel + (1 if ev == "down" else -1)) % len(rows)
        elif ev in ("center", "right"):
            what = rows[self.sel][0]
            if what == "shuffle":
                app.toggle_shuffle()
            elif what == "repeat":
                app.cycle_repeat()
            elif what == "timer":
                app.cycle_timer()
            elif what == "sleep":
                app.back()                  # waking up comes back to Spelas nu
                app.go_to_sleep()
        elif ev == "left":
            app.back()


# ---------------------------------------------------------------- the app


class App:
    def __init__(self, config, mpv, volume, settings, bt=None):
        self.mpv, self.volume, self.settings, self.bt = mpv, volume, settings, bt
        self.bt_polled = 0
        self.bt_shown = False       # whether the adapter is visible and pairable
        self.bt_was_playing = False
        self.disc = None            # "audio" or "data" while a disc is in, from cd.watch()
        jf = config.get("jellyfin", {})
        self.jf = jellyfin.Jellyfin(jf["url"], jf["api_key"], jf.get("user", "")) if jf.get("api_key") else None
        chans = config.get("radio", {}).get("channels")
        self.channels = [(c["id"], c["name"]) for c in chans] if chans else radio.CHANNELS
        self.playing = None         # "radio", "jellyfin" or None
        self.queue = []
        self.counted = set()        # queue positions already counted as played in Jellyfin
        self.channel = 0
        self.radio_info = {}
        self.radio_fetched = None
        self.notice, self.notice_until = None, 0
        self.now = time.monotonic()
        self.shuffled, self.unshuffled, self.repeat = False, [], "no"
        self.timer_end = None
        self.last_press = time.monotonic()
        self.asleep = False
        self.backlight = settings["brightness"]
        self.draw = lambda view: None   # set by main: shows a view at once (for "Laddar")
        self.stack = [ListScreen("Källa", [], self.pick_source, root=True)]
        self.refresh_home()

    # navigation
    def refresh_home(self):
        rows = [{"label": "Radio", "id": "radio"}, {"label": "Bibliotek", "id": "jellyfin"},
                {"label": "Blåtand", "id": "bluetooth"}]
        if self.disc == "audio":
            rows.insert(0, {"label": "CD", "id": "cd"})
        if self.bt_playing():
            rows.insert(0, {"label": "Spelas nu", "id": "playing", "value": "Blåtand"})
        elif self.playing and not self.mpv.props.get("idle-active"):
            rows.insert(0, {"label": "Spelas nu", "id": "playing",
                            "value": self.channels[self.channel][1] if self.playing == "radio" else "Bibliotek"})
        home = self.stack[0]
        if [r["id"] for r in home.rows] != [r["id"] for r in rows]:
            home.sel = 0
        home.rows = rows

    def push(self, screen):
        self.stack.append(screen)

    def back(self):
        if len(self.stack) > 1:
            self.stack.pop()

    def pick_source(self, app, row):
        kind = row["id"]
        if kind == "playing":
            if self.bt_playing():
                self.push(BluetoothScreen(pairing=False))
            else:
                self.push(RadioScreen() if self.playing == "radio" else PlayingScreen())
        elif kind == "radio":
            rows = [{"label": name, "index": i, "value": self.radio_info.get(cid, {}).get("now", ("", ""))[0]}
                    for i, (cid, name) in enumerate(self.channels)]
            self.push(ListScreen("Radio", rows, lambda app, r: (app.play_radio(r["index"]), app.push(RadioScreen())),
                                 verb="spela"))
        elif kind == "jellyfin":
            self.open_jellyfin()
        elif kind == "cd":
            self.push(MessageScreen("CD", "Kommer snart", "Att spela skivan byggs härnäst."))
        elif kind == "bluetooth":
            if self.bt:
                self.push(BluetoothScreen())
            else:
                self.push(MessageScreen("BLÅTAND", "Fel: Bluetooth saknas", error=True))

    # jellyfin
    def load(self, status, fetch, then):
        """Shows Laddar, fetches, and passes the answer on; an error gets its own screen."""
        self.draw({"kind": "message", "status": (status, ""), "title": "Laddar"})
        try:
            result = fetch()
        except Exception as e:  # network, HTTP or JSON: all mean the same to the listener
            print("jellyfin:", repr(e), flush=True)
            self.push(MessageScreen(status, "Fel: servern svarar inte", "Jellyfin gick inte att nå.", error=True,
                                    retry=lambda app: app.load(status, fetch, then)))
            return
        then(result)

    def open_jellyfin(self):
        if not self.jf:
            self.push(MessageScreen("BIBLIOTEK", "Inte inställd", "Jellyfins API-nyckel saknas."))
            return
        rows = [{"label": "Spellistor", "id": "playlists"}, {"label": "Förslag", "id": "suggestions"},
                {"label": "Album", "id": "albums"}, {"label": "Artister", "id": "artists"}]
        self.push(ListScreen("Bibliotek", rows, lambda app, r: app.open_library(r["id"])))

    def open_library(self, kind):
        if kind == "albums":
            self.load("ALBUM", self.jf.albums, lambda items: self.push(self.album_list("Album", items)))
        elif kind == "artists":
            self.load("ARTISTER", self.jf.artists, lambda items: self.push(ListScreen(
                "Artister", [{"label": a["Name"], "item": a} for a in items],
                lambda app, r: app.load("ARTIST", lambda: app.jf.albums(r["item"]["Id"]),
                                        lambda albums: app.push(app.album_list(r["label"], albums))))))
        elif kind == "playlists":
            self.load("SPELLISTOR", self.jf.playlists, lambda items: self.push(ListScreen(
                "Spellistor", [{"label": p["Name"], "item": p} for p in items], self.open_tracks)))
        elif kind == "suggestions":
            rows = [{"label": "Ofta spelade", "fetch": self.jf.most_played},
                    {"label": "Nyligen spelade", "fetch": self.jf.recently_played},
                    {"label": "Nyinkommet", "fetch": self.jf.recently_added, "albums": True}]
            self.push(ListScreen("Förslag", rows, lambda app, r: app.load(
                r["label"].upper(), r["fetch"],
                lambda items: app.push(app.album_list(r["label"], items) if r.get("albums")
                                       else app.track_list(r["label"], items, False)))))

    def album_list(self, title, albums):
        rows = [{"label": a["Name"], "value": str(a.get("ProductionYear") or ""), "item": a} for a in albums]
        return ListScreen(title, rows, self.open_tracks, verb="öppna")

    def track_list(self, title, tracks, album=True):
        """An album's tracks by number and length; other lists (playlists, suggestions) by artist."""
        if album and all(t.get("IndexNumber") for t in tracks):
            rows = [{"num": t["IndexNumber"], "label": t.get("Name", ""), "value": clock(jellyfin.seconds(t))}
                    for t in tracks]
        else:
            rows = [{"label": t.get("Name", ""), "value": jellyfin.artist(t)} for t in tracks]
        for i, row in enumerate(rows):
            row["index"] = i
        return ListScreen(title, rows, lambda app, r: app.play_tracks(tracks, r["index"]), verb="spela")

    def open_tracks(self, app, row):
        item = row["item"]
        album = item.get("Type") != "Playlist"
        self.load(item["Name"].upper(), lambda: self.jf.tracks(item),
                  lambda tracks: self.push(self.track_list(item["Name"], tracks, album)))

    def play_tracks(self, tracks, start):
        self.pause_phone()
        self.shuffled, self.unshuffled = False, []
        self.queue = tracks
        self.counted = set()
        self.playing = "jellyfin"
        self.mpv.play([self.jf.stream_url(t) for t in tracks], start,
                      headers=[f"Authorization: {self.jf.auth}"])
        self.push(PlayingScreen())

    # Val: shuffle, repeat, the sleep timer
    def reorder(self, tracks):
        """Puts tracks in mpv's playlist around the track that plays, which plays on."""
        i = self.mpv.props.get("playlist-pos")
        if i is None or not 0 <= i < len(self.queue):
            return
        current = self.queue[i]
        self.mpv.command("playlist-clear")              # all but the one that plays
        for t in tracks:
            if t is not current:
                self.mpv.command("loadfile", self.jf.stream_url(t), "append")
        k = tracks.index(current)
        if k:
            self.mpv.command("playlist-move", 0, k + 1)
        self.queue = tracks
        self.counted = set()

    def toggle_shuffle(self):
        if self.playing != "jellyfin" or not self.queue:
            return
        if self.shuffled:
            self.reorder(self.unshuffled)
        else:
            self.unshuffled = list(self.queue)
            i = self.mpv.props.get("playlist-pos") or 0
            rest = [t for j, t in enumerate(self.queue) if j != i]
            random.shuffle(rest)
            self.reorder([self.queue[i]] + rest)
        self.shuffled = not self.shuffled

    def cycle_repeat(self):
        self.repeat = {"no": "track", "track": "list", "list": "no"}[self.repeat]
        self.mpv.set("loop-file", "inf" if self.repeat == "track" else "no")
        self.mpv.set("loop-playlist", "inf" if self.repeat == "list" else "no")

    def cycle_timer(self):
        minutes = round((self.timer_end - self.now) / 60) if self.timer_end else 0
        nxt = next((m for m in TIMER_MINUTES if m > minutes), 0)
        self.timer_end = self.now + nxt * 60 if nxt else None
        if self.volume.fade:
            self.volume.fade = 0
            self.volume.apply()

    def timer_text(self):
        if not self.timer_end:
            return "av"
        return f"{max(1, math.ceil((self.timer_end - self.now) / 60))} min"

    def run_timer(self, now):
        """The last half minute fades out; at the end everything stops and the screen sleeps."""
        if not self.timer_end:
            return
        left = self.timer_end - now
        fade = round(FADE_DB * (1 - max(0.0, left) / FADE_SECONDS)) if left < FADE_SECONDS else 0
        if fade != self.volume.fade:
            self.volume.fade = fade
            self.volume.apply()
        if left <= 0:
            self.timer_end = None
            self.mpv.stop()
            self.pause_phone()
            self.volume.fade = 0
            self.volume.apply()
            self.go_to_sleep()

    def count_play(self):
        """Half a track, or four minutes of it, counts as a play in Jellyfin, as in its own apps."""
        p = self.mpv.props
        i, pos, dur = p.get("playlist-pos"), p.get("time-pos") or 0, p.get("duration") or 0
        if self.playing != "jellyfin" or i is None or not 0 <= i < len(self.queue) or i in self.counted:
            return
        if dur and pos >= min(240, dur / 2):
            self.counted.add(i)
            track = self.queue[i]

            def run():
                try:
                    self.jf.mark_played(track)
                except Exception as e:
                    print("jellyfin played:", repr(e), flush=True)
            threading.Thread(target=run, daemon=True).start()

    # radio
    def play_radio(self, index):
        self.pause_phone()
        self.channel = index
        self.playing = "radio"
        self.queue = []
        self.mpv.play([radio.stream_url(self.channels[index][0])])
        self.radio_fetched = None       # fetch what is on now

    def fetch_radio(self):
        def run():
            for cid, _ in self.channels:
                try:
                    self.radio_info[cid] = radio.now_next(cid)
                except Exception as e:
                    print("radio:", cid, repr(e), flush=True)
        threading.Thread(target=run, daemon=True).start()

    # bluetooth: one source at a time, so a phone that starts playing stops
    # mpv, and mpv starting pauses the phone.

    def bt_control(self, method):
        try:
            self.bt.control(method)
        except Exception as e:
            print("bluetooth:", repr(e), flush=True)

    def bt_playing(self):
        st = self.bt.state if self.bt else {}
        return st.get("status") == "playing" or bool(st.get("streaming"))

    def pause_phone(self):
        if self.bt_playing():
            self.bt_control("Pause")

    def poll_bt(self, now):
        if not self.bt:
            return
        # Visible only while Blåtand is on the screen: left, Home, or the screen asleep all end it.
        top = self.stack[-1]
        show = isinstance(top, BluetoothScreen) and top.pairing and not self.asleep
        if show != self.bt_shown:
            try:
                self.bt.visible(show)
                self.bt_shown = show
            except Exception as e:
                print("bluetooth:", repr(e), flush=True)
        if now - self.bt_polled < 1:
            return
        self.bt_polled = now
        try:
            st = self.bt.poll()
        except Exception as e:
            print("bluetooth:", repr(e), flush=True)
            return
        was, playing = self.bt_was_playing, self.bt_playing()
        self.bt_was_playing = playing
        if playing and not self.mpv.props.get("idle-active"):
            self.mpv.stop()
        if playing and not was and not isinstance(self.stack[-1], BluetoothScreen):
            # The phone started: show it, Spelas nu for Blåtand, and light the screen if it slept.
            del self.stack[1:]
            self.push(BluetoothScreen(pairing=False))
            self.wake(now)
        boost = self.settings["bluetooth_boost"] if playing else 0
        if boost != self.volume.boost:
            self.volume.boost = boost
            self.volume.apply()

    # buttons, settings, the clock
    def notify(self, label, value, mono=False, legend=None):
        self.notice = {"label": label, "value": value, "mono": mono, "legend": legend}
        self.notice_until = self.now + OVERLAY_SECONDS

    def go_to_sleep(self):
        self.asleep = True
        self.backlight = 0

    def wake(self, now):
        self.last_press = now
        self.asleep = False
        self.backlight = self.settings["brightness"]

    def handle(self, ev, now):
        self.now = now
        if self.asleep:
            self.wake(now)
            return
        self.last_press = now
        if ev in ("vol_up", "vol_down"):
            self.volume.set(self.volume.level + (1 if ev == "vol_up" else -1), self.settings["volume_cap"])
            self.settings.set("volume", self.volume.level)
            self.notify_volume()
        elif ev == "mute":
            self.volume.toggle_mute()
            self.notify_volume()
        elif ev == "home":
            del self.stack[1:]
        else:
            self.stack[-1].key(self, ev)

    def notify_volume(self):
        muted = self.volume.muted
        self.notify("VOLYM", "Tyst" if muted else str(self.volume.level), mono=not muted,
                    legend=[("A", "upp"), ("B", "ner"), ("A+B", "tyst")])

    def tick(self, now):
        self.now = now
        self.run_timer(now)
        minutes = self.settings["sleep_minutes"]
        if minutes and not self.asleep and now - self.last_press > minutes * 60:
            self.asleep = True
            self.backlight = 0
        if self.radio_fetched is None or now - self.radio_fetched > 60:
            self.radio_fetched = now
            self.fetch_radio()
        self.count_play()
        self.poll_bt(now)
        self.refresh_home()

    def view(self, now):
        if self.asleep:
            return {"kind": "off"}
        v = self.stack[-1].view(self)
        if now < self.notice_until:
            v["notice"] = self.notice
        if self.timer_end and v["kind"] == "playing" and v.get("times") and not v.get("paused"):
            v["position"] = f"sover {self.timer_text()}"
        return v
