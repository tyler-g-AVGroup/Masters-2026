"""A fictional streaming catalog: profiles, two services, browse/search/home menus.

Every name here is invented for the demo. Items carry SignedData whose SourceData is
HMAC-signed by this server, so a client must hand it back unmodified (as on a real
device). A song's SignedData also records the folder it was listed in ("Queue"),
which becomes the play queue for NextTrack/PreviousTrack after LoadSource.
"""

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field

PAGE_LIMIT = 20
PLAYABLE = ("song", "station", "podcastepisode")
FOLDERS = ("dirmenu", "album", "artist", "playlist", "podcastseries")
SEARCH_CATEGORIES = ("song", "album", "artist", "playlist", "station")

RADIO, STREAM = "Provider1", "Provider2"
PROVIDER_NAMES = {RADIO: "Internet Radio", STREAM: "DemoStream"}
PROFILES = {
    "Profile1": {"Name": "Main House", "Providers": [RADIO, STREAM]},
    "Profile2": {"Name": "Guest", "Providers": [RADIO]},
}

ARTISTS = [
    ("Aurora Lane", ["Northern Glass", "Paper Satellites"]),
    ("The Quiet Engines", ["Low Tide Signals", "Engine Room"]),
    ("Mara Vey", ["Wildflower Static", "Late Bloom"]),
    ("Copper Atlas", ["Iron Meridian", "Open Roads"]),
    ("Nightjar Collective", ["Moth Light", "Echo Garden"]),
    ("Silas Grey Trio", ["Blue Hour Sessions", "Standards at Dusk"]),
]
ADJECTIVES = ["Silver", "Hollow", "Golden", "Restless", "Quiet", "Electric", "Velvet",
              "Distant", "Burning", "Paper", "Crystal", "Midnight", "Wandering"]
NOUNS = ["Harbor", "Signal", "Garden", "Static", "River", "Lanterns", "Skyline", "Avenue",
         "Weather", "Satellite", "Morning", "Window", "Compass", "Fever", "Shoreline", "Echo",
         "Orchard"]
CITIES = ["Harbor", "Northline", "Summit", "Lakeside", "Redwood", "Meridian", "Coastal",
          "Prairie", "Granite", "Riverbend", "Skyline", "Evergreen"]
GENRES = ["Pop", "Rock", "Indie", "Country", "Hits", "Classic Rock", "Dance", "Folk"]
JAZZ = ["Smoky Room Jazz", "Late Set Radio", "Delta Porch Blues", "Brushstroke Jazz",
        "Velvet Lounge", "Bebop Corner"]
NEWS = ["City Desk News", "Open Line Talk", "World Hour", "Morning Briefing"]


@dataclass
class Node:
    id: str
    name: str
    kind: str  # StreamingMediaType
    provider: str
    children: list = field(default_factory=list)
    artist: str = ""
    album: str = ""
    duration: int = 0  # seconds; 0 = live
    genre: str = ""
    album_id: str = ""


class Catalog:
    def __init__(self, secret=None):
        self.secret = secret or os.urandom(32)
        self.nodes = {}
        self.roots = {}
        self._build()

    # --- construction --------------------------------------------------------

    def _add(self, node):
        self.nodes[node.id] = node
        return node

    def _folder(self, node_id, name, kind, provider, children):
        return self._add(Node(node_id, name, kind, provider, [c.id for c in children]))

    def _build(self):
        # Internet Radio: three folders of live stations.
        popular = [
            self._add(Node("ir:pop:{:02d}".format(i + 1),
                           "{} {}".format(CITIES[i % 12], ("FM", "Radio")[i // 12]),
                           "station", RADIO, genre=GENRES[i % len(GENRES)]))
            for i in range(24)
        ]
        jazz = [self._add(Node("ir:jazz:{}".format(i + 1), name, "station", RADIO, genre="Jazz"))
                for i, name in enumerate(JAZZ)]
        news = [self._add(Node("ir:news:{}".format(i + 1), name, "station", RADIO, genre="News"))
                for i, name in enumerate(NEWS)]
        self.roots[RADIO] = self._folder("ir:root", "Internet Radio", "dirmenu", RADIO, [
            self._folder("ir:popular", "Popular stations", "dirmenu", RADIO, popular),
            self._folder("ir:jazz", "Jazz & Blues", "dirmenu", RADIO, jazz),
            self._folder("ir:news", "News & Talk", "dirmenu", RADIO, news),
        ])

        # DemoStream: artists -> albums -> songs, plus playlists that reuse the songs.
        albums, artists, songs = [], [], []
        for a, (artist, titles) in enumerate(ARTISTS):
            artist_albums = []
            for b, title in enumerate(titles):
                album_id = "ds:alb:{}{}".format(a + 1, "ab"[b])
                tracks = []
                for t in range(8):
                    seed = a * 16 + b * 8 + t
                    name = "{} {}".format(ADJECTIVES[(seed * 5 + b) % len(ADJECTIVES)],
                                          NOUNS[(seed * 3 + a) % len(NOUNS)])
                    tracks.append(self._add(Node(
                        "{}:{}".format(album_id, t + 1), name, "song", STREAM,
                        artist=artist, album=title, duration=150 + (seed * 37) % 150,
                        album_id=album_id)))
                songs += tracks
                album = self._folder(album_id, title, "album", STREAM, tracks)
                album.artist = artist
                artist_albums.append(album)
            albums += artist_albums
            node = self._folder("ds:art:{}".format(a + 1), artist, "artist", STREAM, artist_albums)
            node.artist = artist
            artists.append(node)
        playlists = [
            self._folder("ds:pl:focus", "Morning Focus", "playlist", STREAM, songs[::8][:12]),
            self._folder("ds:pl:road", "Road Trip", "playlist", STREAM, songs[3::6][:15]),
            self._folder("ds:pl:chill", "Chill Evenings", "playlist", STREAM, songs[80:90]),
            self._folder("ds:pl:big", "Big Mix", "playlist", STREAM, songs[:45]),
        ]
        self.roots[STREAM] = self._folder("ds:root", "DemoStream", "dirmenu", STREAM, [
            self._folder("ds:playlists", "Playlists", "dirmenu", STREAM, playlists),
            self._folder("ds:albums", "Albums", "dirmenu", STREAM, albums),
            self._folder("ds:artists", "Artists", "dirmenu", STREAM, artists),
            self._folder("ds:new", "New Releases", "dirmenu", STREAM, albums[1::3]),
        ])
        # Favorites: (node, queue context)
        self.favorites = {
            "Profile1": [
                ("ir:pop:01", None),
                ("ir:jazz:1", None),
                ("ds:alb:1a:1", "ds:alb:1a"),
                ("ds:pl:road", None),
            ],
            "Profile2": [],
        }

    # --- signing ---------------------------------------------------------------

    def _signature(self, source):
        raw = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
        return base64.b64encode(hmac.new(self.secret, raw, hashlib.sha256).digest()).decode()

    def sign(self, source):
        source = dict(source)
        source["Page"] = {"limit": PAGE_LIMIT, "PageUrl": ""}
        return {"SourceData": source, "Signature": self._signature(source)}

    def verify(self, signed):
        """The SourceData of untampered SignedData, else None."""
        if not isinstance(signed, dict) or not isinstance(signed.get("SourceData"), dict):
            return None
        expected = self._signature(signed["SourceData"])
        if not hmac.compare_digest(expected, str(signed.get("Signature", ""))):
            return None
        return signed["SourceData"]

    # --- items -------------------------------------------------------------------

    def item(self, node, queue=None):
        meta = {"ProviderKey": node.provider}
        if node.kind == "song":
            meta.update(ArtistName=node.artist, AlbumName=node.album, Duration=node.duration)
        elif node.kind in ("album", "artist"):
            meta["ArtistName"] = node.artist
        elif node.kind == "station":
            meta["Genre"] = node.genre
        source = {"Node": node.id, "ProviderKey": node.provider}
        if node.kind == "song":
            source["Queue"] = queue or node.album_id
        return {
            "BrowseKey": node.id,
            "BrowseItemName": node.name,
            "StreamingMediaType": node.kind,
            "MediaTypeMetaData": meta,
            "UrlIcon": "",
            "SignedData": self.sign(source),
        }

    def queue_for(self, source):
        """(list of song/station node ids, index) for a LoadSource."""
        node = self.nodes[source["Node"]]
        if node.kind != "song":
            return [node.id], 0
        folder = self.nodes.get(source.get("Queue") or node.album_id)
        queue = [c for c in (folder.children if folder else []) if self.nodes[c].kind == "song"]
        if node.id not in queue:
            queue = [node.id]
        return queue, queue.index(node.id)

    def programme(self, station_id, step):
        """The 'now playing on air' line for a live station: '<song> / <artist>'."""
        songs = [n for n in self.nodes.values() if n.kind == "song"]
        seed = sum(map(ord, station_id)) + step * 7
        song = songs[seed % len(songs)]
        return "{} / {}".format(song.name, song.artist)

    # --- menus -------------------------------------------------------------------

    @staticmethod
    def _category(name, items, total):
        return {"DisplayMenuName": name, "ItemCount": len(items), "TotalItemCount": total,
                "MenuDataItems": items}

    def _page(self, title, children, offset, parent_signed, context=None):
        page = children[offset:offset + PAGE_LIMIT]
        items = [self.item(self.nodes[c], context) for c in page]
        return {
            "ParentBrowseKey": {"BrowseKey": title, "SignedData": parent_signed},
            "Categories": {"Category1": self._category(title, items, len(children))},
        }

    def _search_ids(self, provider, text, category):
        wanted = text.casefold()
        hits = []
        for node in self.nodes.values():
            if node.provider != provider or node.kind != category:
                continue
            if node.id.endswith(":root") or node.kind == "dirmenu":
                continue
            haystack = " ".join((node.name, node.artist, node.album, node.genre)).casefold()
            if wanted in haystack:
                hits.append(node.id)
        return hits

    def providers(self, profile):
        return PROFILES[profile]["Providers"] if profile in PROFILES else []

    def navigate(self, profile, category, options):
        """Returns (menu, None) or (None, refusal message)."""
        if profile not in PROFILES:
            return None, "Unknown ProfileKey '{}'".format(profile)
        options = options if isinstance(options, dict) else {}
        try:
            offset = max(0, int(options.get("ItemOffset") or 0))
        except (TypeError, ValueError):
            return None, "ItemOffset must be a number"
        if category == "ProviderBrowseMenu":
            return self._browse(profile, options, offset)
        if category == "SearchMenu":
            provider = options.get("SearchProviderKey")
            if provider not in self.providers(profile):
                return None, "Provider '{}' is not assigned to {}".format(provider, profile)
            search = options.get("SearchCategory")
            if search not in SEARCH_CATEGORIES:
                return None, "Invalid Search Category provided in request"
            text = str(options.get("SearchText") or "").strip()
            if not text:
                return None, "Search text is empty"
            source = {"Node": "search", "ProviderKey": provider, "Query": text, "Category": search}
            return self._page("Search: " + text, self._search_ids(provider, text, search),
                              0, self.sign(source)), None
        if category == "HomeScreenMenu":
            categories = {}
            for index, provider in enumerate(self.providers(profile), 1):
                featured = self.nodes[self.roots[provider].children[0]]
                items = [self.item(self.nodes[c]) for c in featured.children[:6]]
                categories["Category{}".format(index)] = self._category(
                    "{}: {}".format(PROVIDER_NAMES[provider], featured.name), items, len(items))
            return {"Categories": categories}, None
        return None, "Unsupported MenuCategory '{}'".format(category)

    def _browse(self, profile, options, offset):
        provider = options.get("ProviderKey")
        if provider not in self.providers(profile):
            return None, "Provider '{}' is not assigned to {}".format(provider, profile)
        signed = options.get("SignedData")
        if not signed:
            if options.get("BrowseKey") != provider:
                return None, "BrowseKey needs SignedData unless it is the provider key"
            root = self.roots[provider]  # the root ignores paging and lists everything
            return self._page(root.name, root.children, 0, self.sign(
                {"Node": root.id, "ProviderKey": provider})), None
        source = self.verify(signed)
        if source is None:
            return None, "SignedData was modified or is not from this device"
        if source.get("ProviderKey") != provider:
            return None, "SignedData belongs to another provider"
        if source.get("Node") == "search":
            ids = self._search_ids(provider, source["Query"], source["Category"])
            return self._page("Search: " + source["Query"], ids, offset, signed), None
        node = self.nodes.get(source.get("Node"))
        if node is None or node.kind not in FOLDERS:
            return None, "That item is not a folder"
        return self._page(node.name, node.children, offset, signed,
                          node.id if node.kind in ("album", "playlist") else None), None

    def favorites_list(self, profile, with_signed=True):
        entries = {}
        for order, (node_id, queue) in enumerate(self.favorites.get(profile, []), 1):
            item = self.item(self.nodes[node_id], queue)
            if not with_signed:
                item.pop("SignedData")
            entries["Favorite{}".format(order)] = {"OrderNumber": order, "MenuDataItems": item}
        return entries
