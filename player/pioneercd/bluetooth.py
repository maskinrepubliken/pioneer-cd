"""Bluetooth (Blåtand on the screen): Pioneer CD as a speaker for a phone.

BlueZ does the connection, BlueALSA (bluealsa and bluealsa-aplay, set up by
install.sh) plays the sound through the default ALSA device, and bt-agent
accepts a pairing without a code. This module only talks to BlueZ over
D-Bus: the adapter is visible while the Blåtand screen is open, and the
phone's media player (AVRCP) gives the track and takes play, pause, next
and previous.
"""
import dbus

BLUEZ = "org.bluez"
ADAPTER = "/org/bluez/hci0"
PROPS = "org.freedesktop.DBus.Properties"


class Bluetooth:
    def __init__(self, name="Pioneer CD"):
        self.bus = dbus.SystemBus()
        self.name = name
        self.state = {}              # the last answer of poll()

    def _adapter(self, prop, value):
        self.bus.get_object(BLUEZ, ADAPTER).Set("org.bluez.Adapter1", prop, value, dbus_interface=PROPS)

    def visible(self, on):
        """Powers the adapter and lets phones find and pair with it, or stops that."""
        self._adapter("Powered", dbus.Boolean(True))
        self._adapter("Alias", dbus.String(self.name))
        self._adapter("DiscoverableTimeout", dbus.UInt32(0))
        self._adapter("Pairable", dbus.Boolean(on))
        self._adapter("Discoverable", dbus.Boolean(on))

    def poll(self):
        """{"device": name, "status": "playing"/"paused"/..., "title", "artist",
        "duration" and "position" in seconds}, or {} with no phone connected."""
        objects = self.bus.get_object(BLUEZ, "/").GetManagedObjects(dbus_interface="org.freedesktop.DBus.ObjectManager")
        state = {}
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if not dev or not dev.get("Connected"):
                continue
            if not dev.get("Trusted"):     # so the phone may reconnect by itself later
                self.bus.get_object(BLUEZ, path).Set("org.bluez.Device1", "Trusted", dbus.Boolean(True),
                                                     dbus_interface=PROPS)
            state = {"device": str(dev.get("Alias") or dev.get("Name") or "Telefon"), "path": str(path)}
            for ppath, pifaces in objects.items():
                player = pifaces.get("org.bluez.MediaPlayer1")
                if player and str(ppath).startswith(str(path) + "/"):
                    track = player.get("Track", {})
                    state.update(player=str(ppath), status=str(player.get("Status", "")),
                                 title=str(track.get("Title", "")), artist=str(track.get("Artist", "")),
                                 duration=int(track.get("Duration", 0)) / 1000,
                                 position=int(player.get("Position", 0)) / 1000)
            break
        if state:
            state["streaming"] = self._streaming()
        self.state = state
        return state

    def _streaming(self):
        """Whether sound comes in from the phone right now. Not every phone tells
        AVRCP when it plays, so BlueALSA's own word for it is what counts."""
        objects = self.bus.get_object("org.bluealsa", "/org/bluealsa").GetManagedObjects(
            dbus_interface="org.freedesktop.DBus.ObjectManager")
        return any(bool(i["org.bluealsa.PCM1"].get("Running")) for i in objects.values() if "org.bluealsa.PCM1" in i)

    def control(self, method):
        """Play, Pause, Next or Previous on the phone."""
        if self.state.get("player"):
            self.bus.get_object(BLUEZ, self.state["player"]).get_dbus_method(method, "org.bluez.MediaPlayer1")()
