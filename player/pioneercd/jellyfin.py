"""Jellyfin's music: albums, artists, playlists and their tracks.

Reads with an API key (Jellyfin: Dashboard → API Keys) as one user: the one
named in the config, or the first administrator. mpv fetches the audio
itself, with the same key in its Authorization header.
"""
import datetime
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

    def get(self, path, method="GET", **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(f"{self.url}{path}?{query}", headers={"Authorization": self.auth},
                                     method=method)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r) if method == "GET" else None

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

    def most_played(self, limit=50):
        return self._items(IncludeItemTypes="Audio", Filters="IsPlayed", SortBy="PlayCount,DatePlayed",
                           SortOrder="Descending", Limit=limit)

    def recently_played(self, limit=50):
        return self._items(IncludeItemTypes="Audio", Filters="IsPlayed", SortBy="DatePlayed",
                           SortOrder="Descending", Limit=limit)

    def recently_added(self, limit=50):
        return self._items(IncludeItemTypes="MusicAlbum", SortBy="DateCreated", SortOrder="Descending",
                           Limit=limit, Fields="ProductionYear")

    def mark_played(self, track):
        """Counts a play. Without datePlayed Jellyfin only sets Played, and a track
        already played keeps its count and its date: with it, the count goes up."""
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.get(f"/UserPlayedItems/{track['Id']}", method="POST", userId=self.uid(), datePlayed=now)

    def tracks(self, item):
        if item.get("Type") == "Playlist":
            return self.get(f"/Playlists/{item['Id']}/Items", userId=self.uid())["Items"]
        return self._items(ParentId=item["Id"], IncludeItemTypes="Audio",
                           SortBy="ParentIndexNumber,IndexNumber,SortName")

    def media_updated(self, path):
        """Tells Jellyfin a folder on the server is new, so it reads it in."""
        body = json.dumps({"Updates": [{"Path": path, "UpdateType": "Created"}]}).encode()
        req = urllib.request.Request(f"{self.url}/Library/Media/Updated", data=body, method="POST",
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).close()

    def stream_url(self, track):
        return f"{self.url}/Audio/{track['Id']}/stream?static=true"


def seconds(item):
    return (item.get("RunTimeTicks") or 0) / 10_000_000


def artist(item):
    return item.get("AlbumArtist") or ", ".join(item.get("Artists") or [])
