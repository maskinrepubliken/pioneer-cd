"""Jellyfin's music: albums, artists, playlists and their tracks.

Reads with an API key (Jellyfin: Dashboard → API Keys) as one user: the one
named in the config, or the first administrator. mpv fetches the audio
itself, with the same key in its Authorization header.
"""
import json
import urllib.parse
import urllib.request

DEVICE_ID = "pioneer-cd"


class Jellyfin:
    def __init__(self, url, api_key, user=""):
        self.url = url.rstrip("/")
        self.key = api_key
        self.wanted = user
        self._uid = None

    @property
    def auth(self):
        return (f'MediaBrowser Client="Pioneer CD", Device="Pioneer CD", DeviceId="{DEVICE_ID}", '
                f'Version="1", Token="{self.key}"')

    def get(self, path, **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(f"{self.url}{path}?{query}", headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)

    def uid(self):
        if not self._uid:
            users = [u for u in self.get("/Users") if not (u.get("Policy") or {}).get("IsDisabled")]
            if self.wanted:
                user = next((u for u in users if u["Name"].lower() == self.wanted.lower()), None)
            else:
                user = next((u for u in users if (u.get("Policy") or {}).get("IsAdministrator")), None)
            user = user or (users or [None])[0]
            if not user:
                raise RuntimeError("Jellyfin har ingen användare")
            self._uid = user["Id"]
        return self._uid

    def _items(self, **params):
        return self.get("/Items", userId=self.uid(), Recursive="true", **params)["Items"]

    def albums(self, artist=None):
        return self._items(IncludeItemTypes="MusicAlbum", AlbumArtistIds=artist,
                           SortBy="ProductionYear,SortName" if artist else "SortName", Fields="ProductionYear")

    def artists(self):
        return self.get("/Artists/AlbumArtists", userId=self.uid(), SortBy="SortName")["Items"]

    def playlists(self):
        return self._items(IncludeItemTypes="Playlist", SortBy="SortName")

    def tracks(self, item):
        if item.get("Type") == "Playlist":
            return self.get(f"/Playlists/{item['Id']}/Items", userId=self.uid())["Items"]
        return self._items(ParentId=item["Id"], IncludeItemTypes="Audio",
                           SortBy="ParentIndexNumber,IndexNumber,SortName")

    def stream_url(self, track):
        return f"{self.url}/Audio/{track['Id']}/stream?static=true"


def seconds(item):
    return (item.get("RunTimeTicks") or 0) / 10_000_000


def artist(item):
    return item.get("AlbumArtist") or ", ".join(item.get("Artists") or [])
