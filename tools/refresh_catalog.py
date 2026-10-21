#!/usr/bin/env python3
"""Met à jour les videoId du catalogue avec l'API YouTube Data v3 (lancé chaque heure par GitHub Actions).

Un direct YouTube change d'identifiant à chaque redémarrage. Pour chaque caméra :
  1. on vérifie que son videoId est toujours en direct (videos.list, 1 unité pour 50 vidéos) ;
  2. sinon, on cherche parmi les dernières vidéos de sa chaîne (playlist « uploads », 1 unité)
     un direct dont le titre contient une des expressions `match` : un direct redémarré est
     forcément récent, donc en tête de cette liste.
Le fichier n'est modifié que si un identifiant a changé, avec des remplacements ciblés pour
garder sa mise en forme. Avec --discover (une fois par jour), deux recherches (100 unités chacune)
listent dans tools/candidates.md, par destination, les directs absents du catalogue.

Quota gratuit : 10 000 unités par jour ; une exécution normale en consomme moins de 10.
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://www.googleapis.com/youtube/v3/"
# Par destination : requêtes de recherche, puis mots dont l'un doit figurer dans le titre d'un candidat.
DISCOVERY = {
    "nyc": (["NYC live cam"], ["nyc", "new york city", "manhattan", "brooklyn", "queens", "bronx", "times square"]),
    "dc": (["Washington DC live cam"], ["washington", " dc", "d.c.", "potomac", "national mall"]),
    "nevada": (["Las Vegas live cam"], ["las vegas", "nevada", "fremont", "reno", "tahoe"]),
    "england": (["UK live webcam"], ["london", "england", "uk", "beach", "harbour", "cornwall", "devon", "dorset"]),
    "france": (["webcam en direct France"], ["paris", "france", "corse", "bretagne", "port", "plage", "webcam"]),
    "poland": (["kamera na żywo"], ["kamera", "na żywo", "polska", "poland", "kraków", "gdańsk", "warszawa"]),
}
# Les balades filmées, émissions et loteries ne sont pas des webcams.
EXCLUDED_WORDS = ["walk", "driving", "draw", "news", "bird", "podcast", "nfl", "music", "radio", "msza", "msfs",
                  "protest", "breaking", "updates", "derby", "kontra", "spooktober", "kocia", "parafia", "gniazdo"]
# Chaînes écartées après vérification : « Harbor View » rediffuse des images de 2023.
IGNORED_CHANNELS = ["New York Live Camera"]


class YouTube:
    def __init__(self, key):
        self.key = key
        self.units = 0

    def get(self, endpoint, cost=1, **params):
        params["key"] = self.key
        url = API + endpoint + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as response:
            self.units += cost
            return json.load(response)

    def videos(self, ids):
        """videoId -> ressource vidéo (snippet), par paquets de 50."""
        found = {}
        ids = list(dict.fromkeys(ids))
        for start in range(0, len(ids), 50):
            data = self.get("videos", part="snippet", id=",".join(ids[start:start + 50]), maxResults=50)
            for item in data.get("items", []):
                found[item["id"]] = item
        return found

    def uploads_playlist(self, channel_url):
        path = urllib.parse.urlparse(channel_url).path.strip("/")
        if path.startswith("@"):
            data = self.get("channels", part="contentDetails", forHandle=path)
        elif path.startswith("channel/"):
            data = self.get("channels", part="contentDetails", id=path.split("/", 1)[1])
        else:
            raise ValueError(f"adresse de chaîne non gérée : {channel_url}")
        items = data.get("items", [])
        if not items:
            raise ValueError(f"chaîne introuvable : {channel_url}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def recent_uploads(self, playlist_id):
        data = self.get("playlistItems", part="contentDetails", playlistId=playlist_id, maxResults=50)
        return [item["contentDetails"]["videoId"] for item in data.get("items", [])]

    def search_live(self, query):
        data = self.get("search", cost=100, part="snippet", q=query, type="video",
                        eventType="live", maxResults=50)
        return data.get("items", [])


def is_live(video):
    return video is not None and video["snippet"].get("liveBroadcastContent") == "live"


def matches(camera, title):
    title = title.lower()
    return any(phrase.lower() in title for phrase in camera.get("match", []))


def youtube_cameras(catalog):
    """Caméras YouTube de toutes les destinations (les autres sources n'ont pas d'identifiant qui change)."""
    return [c for place in catalog["places"] for c in place["cameras"] if c.get("source", "youtube") == "youtube"]


def refresh(yt, catalog):
    """Retourne {ancien videoId: nouveau videoId} pour les caméras dont le direct a redémarré."""
    cameras = youtube_cameras(catalog)
    known = yt.videos([c["videoId"] for c in cameras if c.get("videoId")])
    stale = [c for c in cameras if not is_live(known.get(c.get("videoId")))]
    for camera in cameras:
        state = "en direct" if camera not in stale else "hors ligne"
        print(f"  {camera['id']}: {camera.get('videoId')} {state}")

    replacements = {}
    by_channel = {}
    for camera in stale:
        by_channel.setdefault(camera["channel"]["url"], []).append(camera)
    taken = {c.get("videoId") for c in cameras}
    for channel_url, channel_cameras in by_channel.items():
        try:
            uploads = yt.recent_uploads(yt.uploads_playlist(channel_url))
        except Exception as error:  # une chaîne en erreur ne bloque pas les autres
            print(f"  ! {channel_url}: {error}")
            continue
        lives = [v for v in yt.videos(uploads).values() if is_live(v)]
        for camera in channel_cameras:
            found = next((v for v in lives if v["id"] not in taken and matches(camera, v["snippet"]["title"])), None)
            if found is None:
                continue
            print(f"  -> {camera['id']}: {camera.get('videoId')} remplacé par {found['id']} ({found['snippet']['title']})")
            taken.add(found["id"])
            if camera.get("videoId"):
                replacements[camera["videoId"]] = found["id"]
    return replacements


def discover(yt, catalog):
    cameras = youtube_cameras(catalog)
    known_ids = {c.get("videoId") for c in cameras}
    lines = [
        "# Directs candidats",
        "",
        "Directs trouvés par la recherche YouTube quotidienne et absents du catalogue, par destination.",
        "À vérifier à la main (certains « 24/7 » rediffusent de vieilles images) avant de les ajouter à `catalog.json`.",
    ]
    for place_id, (queries, words) in DISCOVERY.items():
        candidates = {}
        for query in queries:
            for item in yt.search_live(query):
                video_id = item["id"]["videoId"]
                # La recherche renvoie des titres échappés en HTML (&amp;…).
                title = html.unescape(item["snippet"]["title"])
                channel = html.unescape(item["snippet"]["channelTitle"])
                lowered = title.lower()
                if video_id in known_ids or channel in IGNORED_CHANNELS:
                    continue
                if not any(word in lowered for word in words) or any(word in lowered for word in EXCLUDED_WORDS):
                    continue
                if any(matches(c, title) for c in cameras if c["channel"]["name"] == channel):
                    continue
                candidates[video_id] = (channel, title)
        lines += ["", f"## {place_id}", ""]
        for video_id, (channel, title) in sorted(candidates.items(), key=lambda kv: kv[1]):
            title = title.replace("|", "/").replace("[", "(").replace("]", ")")
            lines.append(f"- **{channel}** : [{title}](https://www.youtube.com/watch?v={video_id})")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("--discover", metavar="FICHIER", help="écrit les directs candidats dans ce fichier")
    args = parser.parse_args()
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("YOUTUBE_API_KEY manquant (secret GitHub Actions)")

    with open(args.catalog, encoding="utf-8") as f:
        text = f.read()
    catalog = json.loads(text)
    yt = YouTube(key)

    print("Vérification des directs :")
    replacements = refresh(yt, catalog)
    if replacements:
        for old, new in replacements.items():
            text = text.replace(f'"videoId": "{old}"', f'"videoId": "{new}"')
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        text = re.sub(r'"updatedAt": "[^"]*"', f'"updatedAt": "{now}"', text, count=1)
        json.loads(text)  # garde-fou : le fichier doit rester du JSON valide
        with open(args.catalog, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{len(replacements)} caméra(s) mise(s) à jour.")
    else:
        print("Aucun changement.")

    if args.discover:
        report = discover(yt, catalog)
        with open(args.discover, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
        print(f"Candidats écrits dans {args.discover}.")

    print(f"Quota consommé : {yt.units} unités.")


if __name__ == "__main__":
    main()
