#!/usr/bin/env python3
"""Ajoute au catalogue la caméra décrite par une issue « Ajouter une caméra » (lancé par GitHub Actions).

Le formulaire (.github/ISSUE_TEMPLATE/add-camera.yml) produit un corps d'issue en sections « ### Libellé ».
On en tire la caméra, on complète ce que la source permet de deviner (chaîne et titre YouTube via l'API,
coordonnées et vignette EarthCam, vignettes Skyline et webcamera.pl), puis on insère une ligne dans
catalog.json après la dernière caméra de la même rangée, sans toucher au reste du fichier.

Le message (succès ou erreurs) est écrit dans le fichier --report, que le workflow poste en commentaire.
Code de sortie : 0 si la caméra est ajoutée, 1 si l'issue doit être corrigée.

Essai en local : python tools/add_camera.py catalog.json --body issue.md --report rapport.md
(YOUTUBE_API_KEY n'est nécessaire que pour une caméra YouTube).
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

API = "https://www.googleapis.com/youtube/v3/"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
TYPES = ["city", "landmark", "skyline", "beach", "port", "mountain", "nature", "airport", "traffic", "rail"]
# Libellés des sections du formulaire -> clés (doivent suivre add-camera.yml).
FIELDS = {
    "Lien de la caméra": "link",
    "Destination": "place",
    "Rangée": "category",
    "Type de vue": "type",
    "Nom (anglais)": "name_en",
    "Nom (français)": "name_fr",
    "Lieu affiché": "area",
    "Coordonnées": "coords",
    "Mots du titre YouTube": "match",
    "Fuseau horaire": "timezone",
    "Libellé de l'heure": "clock",
    "Identifiant": "id",
}


class FormError(Exception):
    pass


def parse_body(body):
    """Corps d'issue -> {clé: valeur}, les champs vides (« _No response_ ») valant ""."""
    values = {}
    for section in re.split(r"^### ", body.replace("\r\n", "\n"), flags=re.M)[1:]:
        label, _, value = section.partition("\n")
        key = FIELDS.get(label.strip())
        if key:
            value = value.strip()
            values[key] = "" if value == "_No response_" else value
    return values


def fetch(url, **headers):
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, **headers})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def parse_coords(text):
    """« 40.7128, -74.006 » (copié de Google Maps) -> (lat, lon) arrondis à 5 décimales."""
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(numbers) != 2:
        raise FormError("Coordonnées : il faut deux nombres, latitude puis longitude (ex. `40.7128, -74.006`).")
    lat, lon = (round(float(n), 5) for n in numbers)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise FormError(f"Coordonnées hors limites : {lat}, {lon} (latitude d'abord).")
    return lat, lon


def detect_source(link):
    """Lien -> (source, infos utiles à cette source)."""
    url = urllib.parse.urlparse(link.strip())
    host = url.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host in ("youtube.com", "youtu.be"):
        if host == "youtu.be":
            video_id = url.path.strip("/")
        else:
            video_id = urllib.parse.parse_qs(url.query).get("v", [""])[0]
            if not video_id:
                match = re.match(r"/(?:live|embed|shorts)/([^/?]+)", url.path)
                video_id = match.group(1) if match else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise FormError("Lien YouTube : il faut le lien de la vidéo en direct (`youtube.com/watch?v=…`), pas celui de la chaîne.")
        return "youtube", {"videoId": video_id}
    if host == "earthcam.com":
        cam = urllib.parse.parse_qs(url.query).get("cam", [""])[0]
        if not cam:
            raise FormError("Lien EarthCam : il manque `?cam=…` (ouvre la caméra voulue sur la page et recopie le lien).")
        page = f"https://www.earthcam.com{url.path}?cam={cam}"
        return "earthcam", {"page": page, "cam": cam}
    if host == "skylinewebcams.com":
        path = re.sub(r"^/[a-z]{2}/webcam/", "/en/webcam/", url.path)
        if not path.startswith("/en/webcam/") or not path.endswith(".html"):
            raise FormError("Lien SkylineWebcams : il faut la page d'une caméra (`…/webcam/<pays>/<région>/<ville>/<caméra>.html`).")
        return "skyline", {"page": f"https://www.skylinewebcams.com{path}"}
    if host.endswith("webcamera.pl"):
        match = re.fullmatch(r"/kamera/([a-z0-9-]+)/?", url.path)
        if host == "webcamera.pl" and match:
            slug = match.group(1)
            page = f"https://www.webcamera.pl/kamera/{slug}/"
        elif host != "webcamera.pl" and url.path in ("", "/"):
            slug = host.removesuffix(".webcamera.pl")
            page = f"https://{slug}.webcamera.pl/"
        else:
            raise FormError("Lien webcamera.pl : il faut la page d'une caméra (`https://<caméra>.webcamera.pl/` ou `…/kamera/<caméra>/`).")
        return "webcamerapl", {"page": page, "slug": slug}
    raise FormError("Lien non reconnu : YouTube, EarthCam, SkylineWebcams ou webcamera.pl uniquement.")


def youtube_video(video_id):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise FormError("YOUTUBE_API_KEY manquant : impossible de vérifier la vidéo YouTube.")
    url = API + "videos?" + urllib.parse.urlencode({"part": "snippet", "id": video_id, "key": key})
    with urllib.request.urlopen(url, timeout=30) as response:
        items = json.load(response).get("items", [])
    if not items:
        raise FormError(f"Vidéo YouTube `{video_id}` introuvable.")
    return items[0]["snippet"]


def earthcam_info(page, cam):
    """Coordonnées, ville et vignette de la caméra, lues dans le json_base de la page."""
    text = fetch(page, Referer="https://www.earthcam.com/network/")
    match = re.search(r"json_base\s*=\s*(\{.*?\});\s*\n", text)
    if not match:
        raise FormError("Page EarthCam illisible (json_base absent) : la caméra existe-t-elle encore ?")
    cameras = json.loads(match.group(1)).get("cam", {})
    if cam not in cameras:
        raise FormError(f"La page EarthCam ne décrit pas la caméra `{cam}` (caméras : {', '.join(cameras)}).")
    info = cameras[cam]
    thumbnail = info.get("thumbimage", "").replace("/256x144/", "/512x288/")
    return info, thumbnail


def skyline_thumbnail(page):
    text = fetch(page)
    if "livee.m3u8" not in text:
        raise FormError("Cette page Skyline n'a pas de flux direct (souvent une vidéo YouTube intégrée) : "
                        "ajoute plutôt la vidéo YouTube.")
    match = re.search(r'og:image" content="([^"]+)"', text)
    return match.group(1) if match else None


def build_camera(form, catalog):
    """Formulaire -> (place, caméra), ou FormError avec toutes les erreurs trouvées."""
    errors = []
    places = {p["id"]: p for p in catalog["places"]}
    place_id = form.get("place", "").split(" ")[0]
    place = places.get(place_id)
    if place is None:
        raise FormError(f"Destination inconnue : `{form.get('place')}`.")

    category = form.get("category", "").strip()
    category_ids = [c["id"] for c in place["categories"]]
    if category not in category_ids:
        errors.append(f"Rangée `{category}` inconnue pour {place_id}. Rangées possibles : "
                      + ", ".join(f"`{c}`" for c in category_ids) + ".")
    camera_type = form.get("type", "")
    if camera_type not in TYPES:
        errors.append(f"Type de vue `{camera_type}` inconnu.")
    name = {"en": form.get("name_en", "").strip()}
    if form.get("name_fr", "").strip():
        name["fr"] = form["name_fr"].strip()
    if not name["en"]:
        errors.append("Le nom anglais est obligatoire.")

    source, info = detect_source(form.get("link", ""))
    area = form.get("area", "").strip()
    coords = None
    if form.get("coords"):
        try:
            coords = parse_coords(form["coords"])
        except FormError as error:
            errors.append(str(error))

    if source == "youtube":
        snippet = youtube_video(info["videoId"])
        title = snippet["title"]
        if snippet.get("liveBroadcastContent") != "live":
            errors.append(f"« {title} » n'est pas en direct en ce moment.")
        match = [m.strip() for m in form.get("match", "").splitlines() if m.strip()]
        if not match:
            errors.append(f"Pour YouTube, indique quelques mots du titre du direct (titre actuel : « {title} »).")
        elif not any(m.lower() in title.lower() for m in match):
            errors.append(f"Aucun des « Mots du titre » ne figure dans le titre actuel « {title} » : "
                          "le direct ne serait pas retrouvé après un redémarrage.")
        default_id = slugify(name["en"])
        channel = {"name": snippet["channelTitle"], "url": f"https://www.youtube.com/channel/{snippet['channelId']}"}
        extra = {"channel": channel, "match": match, "videoId": info["videoId"]}
    elif source == "earthcam":
        details, thumbnail = earthcam_info(info["page"], info["cam"])
        if coords is None and details.get("map_lat") and details.get("map_long"):
            coords = (round(float(details["map_lat"]), 5), round(float(details["map_long"]), 5))
        area = area or details.get("city") or ""
        default_id = "ec-" + info["cam"]
        extra = {"source": source, "page": info["page"], "cam": info["cam"],
                 "channel": {"name": "EarthCam", "url": info["page"]}, "thumbnail": thumbnail}
    elif source == "skyline":
        thumbnail = skyline_thumbnail(info["page"])
        default_id = "sky-" + "-".join(info["page"].removesuffix(".html").split("/")[-2:])
        extra = {"source": source, "page": info["page"], "channel": {"name": "SkylineWebcams", "url": info["page"]}}
        if thumbnail:
            extra["thumbnail"] = thumbnail
    else:
        if "data-src" not in fetch(info["page"]):
            raise FormError("Pas de flux sur cette page webcamera.pl (caméra Premium ou disparue ?).")
        default_id = "wc-" + info["slug"]
        extra = {"source": source, "page": info["page"], "channel": {"name": "WebCamera.pl", "url": info["page"]},
                 "thumbnail": f"https://static.webcamera.pl/camsbig/{info['slug']}.jpg"}

    if coords is None and not any(e.startswith("Coordonnées") for e in errors):
        errors.append("Coordonnées manquantes (clic droit sur Google Maps, puis copier les deux nombres).")
    if not area:
        errors.append("Le lieu affiché (quartier, ville) est obligatoire.")

    timezone_name, clock = form.get("timezone", "").strip(), form.get("clock", "").strip()
    if timezone_name and available_timezones():  # base absente sous Windows : pas de vérification
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"Fuseau horaire `{timezone_name}` inconnu (ex. `America/New_York`, `Europe/Paris`).")
    if place.get("global") and not (timezone_name and clock):
        errors.append(f"{place_id} est une destination mondiale : le fuseau horaire et le libellé de l'heure sont obligatoires.")
    if bool(timezone_name) != bool(clock):
        errors.append("Le fuseau horaire et le libellé de l'heure vont ensemble.")

    # Doublons dans tout le catalogue.
    all_cameras = [c for p in catalog["places"] for c in p["cameras"]]
    for other in all_cameras:
        same = (source == "youtube" and other.get("videoId") == extra.get("videoId")) or \
               (source != "youtube" and other.get("page") == extra.get("page") and other.get("cam") == extra.get("cam"))
        if same:
            errors.append(f"Cette caméra est déjà dans le catalogue : `{other['id']}` ({other['name']['en']}).")
    ids = {c["id"] for c in all_cameras}
    camera_id = form.get("id", "").strip() or default_id
    if form.get("id", "").strip():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", camera_id):
            errors.append("Identifiant : minuscules, chiffres, - et _ uniquement.")
        elif camera_id in ids:
            errors.append(f"L'identifiant `{camera_id}` est déjà pris.")
    else:
        base, n = camera_id, 2
        while camera_id in ids:
            camera_id, n = f"{base}-{n}", n + 1

    if errors:
        raise FormError("\n".join(f"- {e}" for e in errors))

    # Ordre des clés identique aux caméras existantes.
    camera = {"id": camera_id, "name": name, "area": area, "category": category, "type": camera_type,
              "lat": coords[0], "lon": coords[1], **extra}
    if timezone_name:
        camera["timezone"], camera["clockLabel"] = timezone_name, clock
    return place, camera


def insert_camera(text, place_id, camera):
    """Insère la ligne de la caméra après la dernière de sa rangée (ou en fin de destination)."""
    lines = text.split("\n")
    current_place, in_cameras, last_in_place, last_in_category = None, False, None, None
    for i, line in enumerate(lines):
        place_match = re.match(r'      "id": "([^"]+)",$', line)
        if place_match:
            current_place = place_match.group(1)
        elif current_place == place_id:
            if line.strip() == '"cameras": [':
                in_cameras = True
            elif in_cameras and line.strip() == "]":
                break
            elif in_cameras and line.startswith('        {"id"'):
                last_in_place = i
                if json.loads(line.strip().rstrip(","))["category"] == camera["category"]:
                    last_in_category = i
    if last_in_place is None:
        raise ValueError(f"caméras de {place_id} introuvables dans le fichier")
    after = last_in_category if last_in_category is not None else last_in_place
    entry = "        " + json.dumps(camera, ensure_ascii=False)
    if lines[after].endswith(","):
        entry += ","
    else:  # on insère après la dernière caméra de la destination
        lines[after] += ","
    lines.insert(after + 1, entry)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return re.sub(r'"updatedAt": "[^"]*"', f'"updatedAt": "{now}"', "\n".join(lines), count=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("--body", required=True, help="fichier contenant le corps de l'issue")
    parser.add_argument("--report", required=True, help="fichier où écrire le message pour l'issue")
    args = parser.parse_args()

    with open(args.body, encoding="utf-8") as f:
        form = parse_body(f.read())
    with open(args.catalog, encoding="utf-8") as f:
        text = f.read()
    catalog = json.loads(text)

    try:
        place, camera = build_camera(form, catalog)
    except FormError as error:
        report = f"La caméra n'a pas été ajoutée :\n\n{error}\n\nModifie l'issue pour corriger : l'ajout sera retenté."
        status = 1
    except Exception as error:  # site ou API injoignable, page inattendue…
        report = f"La caméra n'a pas été ajoutée, erreur inattendue :\n\n```\n{error}\n```\n\nModifie l'issue pour réessayer."
        status = 1
    else:
        text = insert_camera(text, place["id"], camera)
        json.loads(text)  # garde-fou : le fichier doit rester du JSON valide
        with open(args.catalog, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        line = json.dumps(camera, ensure_ascii=False)
        report = (f"Caméra **{camera['name']['en']}** ajoutée à {place['id']} / {camera['category']} "
                  f"(`{camera['id']}`). Les applis la verront au prochain lancement (cache de 5 min).\n\n"
                  f"```json\n{line}\n```")
        status = 0
        print(f"Ajouté : {line}")

    with open(args.report, "w", encoding="utf-8", newline="\n") as f:
        f.write(report + "\n")
    print(report)
    sys.exit(status)


if __name__ == "__main__":
    main()
