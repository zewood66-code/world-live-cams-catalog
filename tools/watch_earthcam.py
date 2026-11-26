#!/usr/bin/env python3
"""Ajoute et retire les caméras EarthCam éphémères (fêtes, parades, Nouvel An…) : lancé par GitHub Actions.

EarthCam allume pour quelques jours des caméras d'événement, soit sur une page existante (Times Square),
soit sur une nouvelle page (/events/thanksgiving/2026/). Le script lit :
  - le répertoire EarthCam des États et pays couverts par le catalogue ;
  - le `json_base` de chaque page EarthCam du catalogue (il décrit toutes les caméras de la page,
    allumées ou non) et des pages de WATCHED_PAGES.
Une caméra allumée, absente du catalogue et de tools/earthcam_ignored.txt :
  - est ajoutée à la rangée `events` de sa destination si elle a l'air d'une caméra d'événement
    (page déjà lue, adresse en /events/ ou mot de EVENT_WORDS dans son titre) et qu'elle a un flux ;
  - sinon, elle est seulement signalée dans tools/earthcam.md.
Une caméra EarthCam de la rangée `events` coupée ou retirée de sa page est signalée, puis retirée
du catalogue si elle l'est encore au passage suivant (une panne passagère ne la fait pas disparaître).

tools/earthcam.md ne porte pas d'heure : il ne change que quand ses listes changent. C'est aussi la
mémoire du script (caméras déjà signalées, caméras déjà vues coupées). Une source en erreur garde les
lignes qu'elle avait données, pour ne pas renotifier à son retour.
Avec --notify, les ajouts, retraits et nouvelles lignes sont écrits dans un fichier, que le workflow
poste en commentaire sur l'issue « Caméras EarthCam ».
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from add_camera import insert_camera

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
# Une caméra du répertoire est une caméra d'événement si son adresse contient /events/ ou son titre un de ces mots.
EVENT_WORDS = ["parade", "christmas", "xmas", "holiday", "tree lighting", "thanksgiving", "halloween", "new year",
               "nye", "countdown", "ball drop", "fireworks", "festival", "celebration", "mardi gras", "carnival",
               "marathon", "st. patrick", "fourth of july", "4th of july", "independence day", "eclipse", "launch"]
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


def is_online(details):
    return str(details.get("cam_state")) == "1"


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
    """Retourne (caméras vues, json_base des pages lues, sources en erreur)."""
    # page -> (adresse lue, destination). L'adresse garde le ?cam= d'une caméra du catalogue : sans lui,
    # certaines pages (Statue of Liberty) chargent leurs caméras plus tard et leur json_base reste vide.
    pages = {}
    for place in catalog["places"]:
        for camera in place["cameras"]:
            if camera.get("source") == "earthcam":
                pages.setdefault(page_of(camera["page"]), (camera["page"], place["id"]))
    for page, place_id in WATCHED_PAGES.items():
        pages.setdefault(page, (page, place_id))

    seen = {}  # clé -> {title, city, url, place, online, source, page, cam, details}
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
                "online": is_online(cam),
                "source": source,
                "page": page,
                "cam": key,
                "details": cam,
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
                "page": page_of(url),
                "cam": cam,
                "details": None,
            })
    return seen, page_cams, failed


def looks_like_event(cam):
    """Caméra lue sur une page suivie (allumée après coup), ou caméra du répertoire au titre d'événement."""
    if cam["details"] is not None:
        return True
    title = cam["title"].lower()
    return "/events/" in cam["url"] or any(word in title for word in EVENT_WORDS)


def event_camera(cam, catalog):
    """Ligne de catalogue pour la caméra, ou (None, raison) si elle ne peut pas être ajoutée."""
    if not cam["url"].startswith("https://www.earthcam.com/"):
        return None, "lecteur hors earthcam.com"
    details, key = cam["details"], cam["cam"]
    if details is None:  # caméra du répertoire : on lit sa page
        text = fetch(cam["url"], "https://www.earthcam.com/")
        cams = json_base(text) if text else None
        if not cams:
            return None, "page illisible"
        if key is None:
            default = re.search(r"js_defaultCam\s*=\s*'([^']+)'", text)
            key = default.group(1) if default and default.group(1) in cams else next(iter(cams)) if len(cams) == 1 else None
        details = cams.get(key)
        if details is None:
            return None, "caméra absente de sa page"
    if not is_online(details) or ".m3u8" not in (details.get("html5_streampath") or ""):
        return None, "pas de flux"
    try:
        lat, lon = round(float(details["map_lat"]), 5), round(float(details["map_long"]), 5)
    except (KeyError, TypeError, ValueError):
        return None, "pas de coordonnées"
    camera_id = "ec-" + key
    if any(c["id"] == camera_id for p in catalog["places"] for c in p["cameras"]):
        return None, f"identifiant {camera_id} déjà pris"
    page = f"{cam['page']}?cam={key}"
    camera = {"id": camera_id, "name": {"en": clean(details.get("title") or cam["title"])},
              "area": details.get("city") or cam["city"] or "", "category": EVENTS_ROW, "type": "city",
              "lat": lat, "lon": lon, "source": "earthcam", "page": page, "cam": key,
              "channel": {"name": "EarthCam", "url": page},
              "thumbnail": (details.get("thumbimage") or "").replace("/256x144/", "/512x288/")}
    return camera, None


def remove_camera(text, camera_id):
    """Retire la ligne de la caméra, en gardant les virgules du tableau justes."""
    lines = text.split("\n")
    index = next(i for i, line in enumerate(lines) if line.startswith(f'        {{"id": "{camera_id}",'))
    if not lines[index].endswith(","):  # dernière caméra de sa destination
        lines[index - 1] = lines[index - 1].removesuffix(",")
    del lines[index]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return re.sub(r'"updatedAt": "[^"]*"', f'"updatedAt": "{now}"', "\n".join(lines), count=1)


def run(catalog, text, ignored, previous):
    """Retourne (catalogue modifié, rapport, notification)."""
    seen, page_cams, failed = scan(catalog)
    place_order = [p["id"] for p in catalog["places"]]
    place_rank = lambda place_id: place_order.index(place_id) if place_id in place_order else len(place_order)
    # Identifiants EarthCam et pages (share.earthcam.net…) du catalogue.
    cameras = [c for place in catalog["places"] for c in place["cameras"]]
    in_catalog = {c["cam"] for c in cameras if c.get("cam")} | {page_of(c["page"]) for c in cameras if c.get("page")}

    added, new_lines = [], {}
    for key, cam in sorted(seen.items(), key=lambda kv: (place_rank(kv[1]["place"]), kv[1]["title"].lower())):
        if not cam["online"] or key in in_catalog or key in ignored:
            continue
        reason = None
        if looks_like_event(cam):
            camera, reason = event_camera(cam, catalog)
            if camera is not None:
                text = insert_camera(text, cam["place"], camera)
                catalog["places"][place_order.index(cam["place"])]["cameras"].append(camera)
                added.append(f"- **{cam['place']}** : [{camera['name']['en']}]({camera['page']}) "
                             f"(`{camera['id']}`, {camera['area']})")
                continue
        line = (f"- **{cam['place']}** : [{clean(cam['title'])}]({cam['url']})"
                + (f" ({clean(cam['city'])})" if cam["city"] else "")
                + (f", non ajoutée : {reason}" if reason else "") + f" <!-- {key} | {cam['source']} -->")
        new_lines[key] = (place_rank(cam["place"]), clean(cam["title"]).lower(), line)

    # Caméras d'événement coupées : retirées si elles l'étaient déjà au passage précédent.
    removed, ended_lines = [], {}
    for place in catalog["places"]:
        for camera in list(place["cameras"]):
            if camera.get("category") != EVENTS_ROW or camera.get("source") != "earthcam":
                continue
            page = page_of(camera["page"])
            if page not in page_cams:
                continue  # page en erreur : la ligne précédente est reprise plus bas
            details = page_cams[page].get(camera.get("cam"))
            if details is not None and is_online(details):
                continue
            reason = "absente de sa page" if details is None else "hors ligne"
            if (ENDED_HEADING, camera["id"]) in previous:
                text = remove_camera(text, camera["id"])
                place["cameras"].remove(camera)
                removed.append(f"- **{place['id']}** : `{camera['id']}` {camera['name']['en']} ({reason})")
                continue
            ended_lines[camera["id"]] = (
                place_rank(place["id"]), camera["id"],
                f"- **{place['id']}** : `{camera['id']}` {clean(camera['name']['en'])} ({reason}, retirée au "
                f"prochain passage si elle l'est encore) <!-- {camera['id']} | {page.replace('https://www.earthcam.com', '')} -->")

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

    report = "\n".join([
        "# Caméras EarthCam à vérifier",
        "",
        "Écrit par `tools/watch_earthcam.py` (workflow horaire) à partir du répertoire EarthCam et des pages",
        "EarthCam du catalogue. Les caméras d'événement sont ajoutées à la rangée `events` et retirées toutes",
        "seules ; ajouts, retraits et nouvelles lignes sont signalés sur l'issue « Caméras EarthCam ».",
        *section(NEW_HEADING,
                 "Caméras allumées, absentes du catalogue et de `tools/earthcam_ignored.txt`, que le script n'a pas "
                 "ajoutées (pas l'air d'un événement, ou pas de flux ni de coordonnées). À ajouter à la main avec le "
                 "formulaire « Ajouter une caméra », ou à écarter en mettant leur identifiant (le texte entre `<!--` "
                 "et `|`) dans `tools/earthcam_ignored.txt`.",
                 new_lines),
        *section(ENDED_HEADING,
                 "Caméras EarthCam de la rangée `events` hors ligne ou retirées de leur page.",
                 ended_lines),
    ]) + "\n"
    if failed:
        print("Sources en erreur (lignes précédentes reprises) : " + ", ".join(sorted(failed)))

    old_lines = {line for _, line in previous.values()}
    fresh = [line for *_, line in sorted(new_lines.values()) if line not in old_lines]
    notify = []
    if added:
        notify += ["Caméras d'événement ajoutées à la rangée « Fêtes et événements » :", "", *added, "",
                   "Pour en écarter une : retire-la du catalogue et mets son identifiant EarthCam (sans `ec-`) "
                   "dans `tools/earthcam_ignored.txt`, sinon elle sera rajoutée.", ""]
    if removed:
        notify += ["Caméras d'événement coupées, retirées du catalogue :", "", *removed, ""]
    if fresh:
        notify += ["Nouvelles caméras EarthCam, non ajoutées :", "", *fresh, ""]
    print(f"{len(added)} ajoutée(s), {len(removed)} retirée(s), {len(fresh)} nouvelle(s) signalée(s).")
    return text, report, "\n".join(notify)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("--out", default="tools/earthcam.md")
    parser.add_argument("--ignored", default="tools/earthcam_ignored.txt")
    parser.add_argument("--notify", metavar="FICHIER", help="écrit ici les ajouts, retraits et nouvelles lignes")
    args = parser.parse_args()

    with open(args.catalog, encoding="utf-8") as f:
        original = f.read()
    text, report, notify = run(json.loads(original), original, load_ignored(args.ignored), load_previous(args.out))
    if text != original:
        json.loads(text)  # garde-fou : le fichier doit rester du JSON valide
        with open(args.catalog, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    if args.notify and notify:
        with open(args.notify, "w", encoding="utf-8", newline="\n") as f:
            f.write(notify + "\n")


if __name__ == "__main__":
    sys.exit(main())
