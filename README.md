# Hold — site

Site statique (HTML, CSS, JS sans build). Carte 3D avec MapLibre GL, imagerie satellite drapée sur le relief.

## Lancer en local

```bash
cd hold-site
python3 serve.py
```

Puis ouvrir http://localhost:8765. Ouvrir `index.html` en double-clic ne suffit pas : le navigateur bloque la lecture des fichiers GPX hors serveur. `serve.py` gère aussi la lecture partielle de la vidéo, sans laquelle Safari ne la lit pas.

## Le principe

Une seule expérience : le scroll, c'est la course. La carte de nuit reste à l'écran, le coureur avance sur le tracé à mesure qu'on descend, et une phrase à la fois raconte la méthode (« Un coach. Tes données. » → « On ne te lâche pas la veille. »).
Acte 1 : Marathon de Paris (`data/paris-marathon.gpx`). Acte 2 : UTMB (`data/utmb.gpx`, chargé seulement à l'approche). Puis l'essai (ton dernier chrono → ton marathon d'après la table générique), les offres, le pied de page. Le film s'ouvre à la demande (bouton « Le film · 49 s »).

Réglages : les phrases et leurs moments (`data-from` / `data-to`, entre 0 et 1) dans `index.html` ; caméra et stratégie d'exemple dans `js/main.js` (tableaux `ACTS` et `PARIS`).

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `index.html` | Le contenu |
| `css/styles.css` | Le design |
| `js/main.js` | Scroll → course, phrases, compteur, essai, film |
| `js/nightmap.js` | Cartes de nuit : tracé allumé jusqu'au coureur, caméra |
| `js/gpx.js` | Lecture GPX, distance, D+, points de passage |
| `media/` | Le film et son image d'attente |
| `serve.py` | Serveur local (avec lecture partielle pour la vidéo) |

## Avant la mise en ligne

- Remplacer les champs entre crochets : `[LIEN STRIPE]`, `[LIEN CALENDLY]`, `[TON EMAIL]`, `[SIRET]`…
- **Imagerie satellite** : les tuiles Esri World Imagery conviennent pour le développement. Pour un site commercial, passer à un fournisseur avec clé (par exemple MapTiler Satellite, offre gratuite limitée) ou à un compte Esri. Il suffit de changer l'URL `SAT` en haut de `js/nightmap.js` (utilisée par la carte du Mont-Blanc).
- Le relief (AWS Terrain Tiles / Mapzen) est libre d'usage avec attribution, déjà affichée.
