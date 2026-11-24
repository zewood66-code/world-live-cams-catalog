#!/usr/bin/env python3
"""Repère les caméras EarthCam éphémères (fêtes, parades, Nouvel An…) : lancé chaque heure par GitHub Actions.

EarthCam allume pour quelques jours des caméras d'événement, soit sur une page existante (Times Square),
soit sur une nouvelle page. Le script lit :
  - le répertoire EarthCam des États et pays couverts par le catalogue ;
  - le `json_base` de chaque page EarthCam du catalogue (il décrit toutes les caméras de la page,
    allumées ou non) et des pages de WATCHED_PAGES.
Il écrit dans tools/earthcam.md :
  - les caméras en ligne absentes du catalogue et de tools/earthcam_ignored.txt ;
  - les caméras de la rangée `events` du catalogue coupées ou retirées de leur page, à enlever.
Le fichier ne porte pas d'heure : il ne change (et n'est publié) que quand ces listes changent.
Avec --notify, les lignes absentes de la version précédente sont écrites dans un fichier, que le
workflow poste en commentaire sur l'issue « Caméras EarthCam ».

Une source en erreur garde les lignes qu'elle avait données, pour ne pas renotifier à son retour.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
DIRECTORY_API = "https://www.earthcam.com/api/dotcom/network_search.php?r=ecn&a=fetch&"
# Répertoire EarthCam : (pays, État, destination du catalogue).
DIRECTORY = [
    ("US", "NY", "nyc"), ("US", "NJ", "nyc"),
    ("US", "DC", "dc"), ("US", "MD", "dc"), ("US", "VA", "dc"),
    ("US", "MA", "boston"), ("US", "PA", "philadelphia"), ("US", "CA", "losangeles"),
    ("US", "NV", "nevada"), ("US", "FL", "florida"), ("US", "LA", "louisiana"),
    ("Canada", None, "canada"), ("England", None, "england"), ("Wales", None, "england"),
    ("Ireland", None, "ireland"),
]
# Pages sans caméra au catalogue où EarthCam allume des caméras d'événement (sapin du Rockefeller Center).
WATCHED_PAGES = {
    "https://www.earthcam.com/usa/newyork/rockefellercenter/": "nyc",
}
EVENTS_ROW = "events"
NEW_HEADING = "## Nouvelles caméras en ligne"
ENDED_HEADING = "## Caméras d'événement coupées"
DELAY = 1.0  # secondes entre deux requêtes, pour rester discret


def fetch(url, referer):
    """Texte de la page, ou None après deux échecs."""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    for attempt in (1, 2):
        time.sleep(DELAY if attempt == 1 else 10)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:
            print(f"  ! {url} (essai {attempt}) : {error}")
    return None


def page_of(url):
    """Adresse de la page EarthCam sans paramètres (une page décrit plusieurs caméras)."""
    return url.split("?", 1)[0].split("#", 1)[0]


def cam_of(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("cam", [None])[0]


def json_base(page_html):
    """Objet `json_base.cam` de la page : identifiant de caméra -> description.

    Certaines pages déclarent d'abord `json_base = {}` et le remplissent plus loin."""
    for match in re.finditer(r"json_base\s*=\s*(?=\{)", page_html):
        try:
            data, _ = json.JSONDecoder().raw_decode(page_html, match.end())
        except ValueError:
            continue
        cams = data.get("cam") if isinstance(data, dict) else None
        if isinstance(cams, dict):
            return {k: v for k, v in cams.items() if isinstance(v, dict)}
    return None


def load_ignored(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()}
    except FileNotFoundError:
        return set()


def load_previous(path):
    """Lignes de la version précédente : (section, clé) -> (source, ligne)."""
    previous = {}
    section = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("## "):
                    section = line
                match = re.search(r"<!-- (.+?) \| (.+?) -->$", line)
                if match and section:
                    previous[(section, match.group(1))] = (match.group(2), line)
    except FileNotFoundError:
        pass
    return previous


def clean(text):
    return " ".join(str(text or "").split()).replace("[", "(").replace("]", ")").replace("|", "/")


def scan(catalog):
    """Retourne (caméras vues, caméras d'événement coupées, sources en erreur)."""
    place_order = [p["id"] for p in catalog["places"]]
    # page -> (adresse lue, destination). L'adresse garde le ?cam= d'une caméra du catalogue : sans lui,
    # certaines pages (Statue of Liberty) chargent leurs caméras plus tard et leur json_base reste vide.
    pages = {}
    for place in catalog["places"]:
        for camera in place["cameras"]:
            if camera.get("source") == "earthcam":
                pages.setdefault(page_of(camera["page"]), (camera["page"], place["id"]))
    for page, place_id in WATCHED_PAGES.items():
        pages.setdefault(page, (page, place_id))

    seen = {}  # clé -> {title, city, url, place, online, source}
    page_cams = {}  # page lue -> {cam: description}
    failed = set()

    print(f"Pages EarthCam ({len(pages)}) :")
    for page, (url, place_id) in sorted(pages.items()):
        source = page.replace("https://www.earthcam.com", "")
        text = fetch(url, "https://www.earthcam.com/")
        cams = json_base(text) if text else None
        if cams is None:
            failed.add(source)
            continue
        page_cams[page] = cams
        for key, cam in cams.items():
            seen.setdefault(key, {
                "title": cam.get("title") or cam.get("long_title") or key,
                "city": ", ".join(x for x in (cam.get("city"), cam.get("state")) if x),
                "url": f"{page}?cam={key}",
                "place": place_id,
                "online": str(cam.get("cam_state")) == "1",
                "source": source,
            })

    print(f"Répertoire EarthCam ({len(DIRECTORY)} régions) :")
    for country, state, place_id in DIRECTORY:
        source = f"répertoire {country}" + (f"-{state}" if state else "")
        params = {"country": country} | ({"state": state} if state else {})
        text = fetch(DIRECTORY_API + urllib.parse.urlencode(params), "https://www.earthcam.com/network/")
        try:
            items = json.loads(text)["data"]["cam_items"] if text else None
        except (ValueError, KeyError, TypeError):
            items = None
        if items is None:
            failed.add(source)
            continue
        for item in items:
            url = item["url"]
            cam = cam_of(url)
            if cam is None and page_of(url) in page_cams:
                continue  # caméra par défaut d'une page déjà lue
            key = cam or page_of(url)
            seen.setdefault(key, {
                "title": item.get("title") or key,
                "city": ", ".join(x for x in (item.get("city"), item.get("state")) if x),
                "url": url,
                "place": place_id,
                "online": str(item.get("cam_state")) == "1",
                "source": source,
            })

    ended = []  # (destination, id, titre, raison, source)
    for place in catalog["places"]:
        for camera in place["cameras"]:
            if camera.get("category") != EVENTS_ROW or camera.get("source") != "earthcam":
                continue
            page = page_of(camera["page"])
            source = page.replace("https://www.earthcam.com", "")
            if page not in page_cams:
                continue  # page en erreur : les lignes précédentes sont reprises
            cam = page_cams[page].get(camera.get("cam"))
            if cam is None:
                ended.append((place["id"], camera["id"], camera["name"]["en"], "absente de sa page", source))
            elif str(cam.get("cam_state")) != "1":
                ended.append((place["id"], camera["id"], camera["name"]["en"], "hors ligne", source))
    ended.sort(key=lambda e: (place_order.index(e[0]), e[1]))
    return seen, ended, failed, place_order


def build(catalog, ignored, previous):
    """Retourne (texte du fichier, lignes nouvelles depuis la version précédente)."""
    seen, ended, failed, place_order = scan(catalog)
    # Identifiants EarthCam et pages (share.earthcam.net…) du catalogue.
    cameras = [c for place in catalog["places"] for c in place["cameras"]]
    in_catalog = {c["cam"] for c in cameras if c.get("cam")} | {page_of(c["page"]) for c in cameras if c.get("page")}

    new_lines = {}
    for key, cam in seen.items():
        if not cam["online"] or key in in_catalog or key in ignored:
            continue
        line = (f"- **{cam['place']}** : [{clean(cam['title'])}]({cam['url']})"
                + (f" ({clean(cam['city'])})" if cam["city"] else "") + f" <!-- {key} | {cam['source']} -->")
        new_lines[key] = (place_order.index(cam["place"]), clean(cam["title"]).lower(), line)
    ended_lines = {camera_id: (place_order.index(place_id), camera_id,
                               f"- **{place_id}** : `{camera_id}` {clean(title)} ({reason}) <!-- {camera_id} | {source} -->")
                   for place_id, camera_id, title, reason, source in ended}

    # Une source en erreur garde ses lignes précédentes.
    for (section, key), (source, line) in previous.items():
        if source not in failed:
            continue
        target = new_lines if section == NEW_HEADING else ended_lines if section == ENDED_HEADING else None
        if target is not None and key not in target:
            target[key] = (len(place_order), line.lower(), line)

    def section(heading, intro, lines):
        body = [line for *_, line in sorted(lines.values())] or ["Aucune."]
        return ["", heading, "", intro, "", *body]

    lines = [
        "# Caméras EarthCam à vérifier",
        "",
        "Écrit chaque heure par `tools/watch_earthcam.py` à partir du répertoire EarthCam et des pages EarthCam",
        "du catalogue. Chaque nouvelle ligne est signalée en commentaire sur l'issue « Caméras EarthCam ».",
        *section(NEW_HEADING,
                 "Caméras allumées, absentes du catalogue et de `tools/earthcam_ignored.txt` : souvent des caméras "
                 "d'événement (fêtes, parades…). À ajouter dans la rangée `events` de leur destination avec le "
                 "formulaire « Ajouter une caméra », ou à écarter en ajoutant leur identifiant (le texte entre "
                 "`<!--` et `|`) à `tools/earthcam_ignored.txt`.",
                 new_lines),
        *section(ENDED_HEADING,
                 "Caméras de la rangée `events` hors ligne ou retirées de leur page EarthCam : à enlever du catalogue "
                 "une fois l'événement passé.",
                 ended_lines),
    ]
    if failed:
        print("Sources en erreur (lignes précédentes reprises) : " + ", ".join(sorted(failed)))

    old_lines = {line for _, line in previous.values()}
    fresh = [line for *_, line in sorted(new_lines.values()) if line not in old_lines]
    fresh_ended = [line for *_, line in sorted(ended_lines.values()) if line not in old_lines]
    return "\n".join(lines) + "\n", fresh, fresh_ended


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("--out", default="tools/earthcam.md")
    parser.add_argument("--ignored", default="tools/earthcam_ignored.txt")
    parser.add_argument("--notify", metavar="FICHIER", help="écrit ici les lignes nouvelles, s'il y en a")
    args = parser.parse_args()

    with open(args.catalog, encoding="utf-8") as f:
        catalog = json.load(f)
    previous = load_previous(args.out)
    text, fresh, fresh_ended = build(catalog, load_ignored(args.ignored), previous)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{len(fresh)} nouvelle(s) caméra(s), {len(fresh_ended)} caméra(s) d'événement coupée(s) depuis la dernière fois.")

    if args.notify and (fresh or fresh_ended):
        parts = []
        if fresh:
            parts += ["Nouvelles caméras EarthCam en ligne :", "", *fresh, ""]
        if fresh_ended:
            parts += ["Caméras d'événement coupées, à retirer du catalogue :", "", *fresh_ended, ""]
        with open(args.notify, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(parts) + "\n")


if __name__ == "__main__":
    sys.exit(main())
