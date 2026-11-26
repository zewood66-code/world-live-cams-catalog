# Caméras EarthCam à vérifier

Écrit par `tools/watch_earthcam.py` (workflow horaire) à partir du répertoire EarthCam et des pages
EarthCam du catalogue. Les caméras d'événement sont ajoutées à la rangée `events` et retirées toutes
seules ; ajouts, retraits et nouvelles lignes sont signalés sur l'issue « Caméras EarthCam ».

## Nouvelles caméras en ligne

Caméras allumées, absentes du catalogue et de `tools/earthcam_ignored.txt`, que le script n'a pas ajoutées (pas l'air d'un événement, ou pas de flux ni de coordonnées). À ajouter à la main avec le formulaire « Ajouter une caméra », ou à écarter en mettant leur identifiant (le texte entre `<!--` et `|`) dans `tools/earthcam_ignored.txt`.

Aucune.

## Caméras d'événement coupées

Caméras EarthCam de la rangée `events` hors ligne ou retirées de leur page.

Aucune.
