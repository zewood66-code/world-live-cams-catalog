# Caméras EarthCam à vérifier

Écrit chaque heure par `tools/watch_earthcam.py` à partir du répertoire EarthCam et des pages EarthCam
du catalogue. Chaque nouvelle ligne est signalée en commentaire sur l'issue « Caméras EarthCam ».

## Nouvelles caméras en ligne

Caméras allumées, absentes du catalogue et de `tools/earthcam_ignored.txt` : souvent des caméras d'événement (fêtes, parades…). À ajouter dans la rangée `events` de leur destination avec le formulaire « Ajouter une caméra », ou à écarter en ajoutant leur identifiant (le texte entre `<!--` et `|`) à `tools/earthcam_ignored.txt`.

- **nyc** : [Lincoln Harbor Cam](https://www.earthcam.com/usa/newjersey/weehawken/) (Weehawken, NJ) <!-- https://www.earthcam.com/usa/newjersey/weehawken/ | répertoire US-NJ -->
- **nyc** : [Thanksgiving Parade](https://www.earthcam.com/events/thanksgiving/2026/?cam=parade_thanksgiving2026) (New York City, NY) <!-- parade_thanksgiving2026 | répertoire US-NY -->

## Caméras d'événement coupées

Caméras de la rangée `events` hors ligne ou retirées de leur page EarthCam : à enlever du catalogue une fois l'événement passé.

Aucune.
