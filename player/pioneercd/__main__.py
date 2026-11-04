"""Pioneer CD: python3 -m pioneercd

Reads /etc/pioneer-cd/config.toml (see config.example.toml), keeps its own
settings in $STATE_DIRECTORY (systemd's StateDirectory) and mpv's socket in
$RUNTIME_DIRECTORY.
"""
import os
import time
import tomllib

from . import cd, ui
from .app import App, Settings, Volume
from .hw import Board
from .keys import Keys
from .mpv import Mpv

CONFIG = os.environ.get("PIONEERCD_CONFIG", "/etc/pioneer-cd/config.toml")


def main():
    try:
        with open(CONFIG, "rb") as f:
            config = tomllib.load(f)
    except FileNotFoundError:
        config = {}
    state = os.environ.get("STATE_DIRECTORY", os.path.expanduser("~/.local/state/pioneer-cd"))
    run = os.environ.get("RUNTIME_DIRECTORY", "/tmp")

    ui.theme(config.get("player", {}).get("theme", "ink"))
    board = Board()
    board.show(ui.render({"kind": "start"}))
    settings = Settings(os.path.join(state, "settings.json"), config.get("player"))
    board.backlight(settings["brightness"])
    volume = Volume(min(settings["volume"], settings["volume_cap"]))
    try:
        from .bluetooth import Bluetooth
        bt = Bluetooth()
        bt.visible(False)
    except Exception as e:          # no adapter, or BlueZ not running: Blåtand says so
        print("bluetooth:", repr(e), flush=True)
        bt = None
    app = App(config, Mpv(os.path.join(run, "mpv.sock")), volume, settings, bt)
    app.draw = lambda view: board.show(ui.render(view))
    cd.watch(lambda disc: setattr(app, "disc", disc))
    keys = Keys()
    shown, backlight = None, settings["brightness"]
    while True:
        now = time.monotonic()
        for ev in keys.feed(board.pressed(), now):
            app.handle(ev, now)
        app.tick(now)
        if app.backlight != backlight:
            backlight = app.backlight
            board.backlight(backlight)
        img = ui.render(app.view(now))
        data = img.tobytes()
        if data != shown:
            board.show(img)
            shown = data
        time.sleep(0.03)


if __name__ == "__main__":
    main()
