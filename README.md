# Carte des pénuries de carburant

Site qui affiche en temps réel les stations-service en rupture partielle ou totale,
d'après le flux officiel du ministère de l'Économie (prix-carburants.gouv.fr, Licence Ouverte).

## Contenu

| Fichier | Rôle |
|---|---|
| `index.html` | Le site (carte, bandeau défilant, onglets Territoires / 30 jours / Nouvelles ruptures / Prix moyen). Lit le flux officiel en direct depuis le navigateur. |
| `departements.js` | Contours des 96 départements de métropole (mode « Départements » de la carte). |
| `releves-3h.json` | Un relevé toutes les 3 h sur les 8 derniers jours (courbe 24 h / 48 h / 7 j de l'onglet Évolution). |
| `historique.json` | Un relevé par jour : ruptures (France + chaque département) et prix moyen de chaque carburant. Sert aux variations J-1 / J-7 / J-30 et aux courbes. |
| `scripts/snapshot.py` | Fait un relevé (toutes les 3 h) et met à jour `releves-3h.json` et `historique.json`. |
| `scripts/backfill.py` | Reconstitue les 12 derniers mois (ruptures + prix moyens) à partir des archives annuelles du ministère (donnees.roulez-eco.fr). |
| `.github/workflows/releve-quotidien.yml` | Lance `snapshot.py` automatiquement toutes les 3 h (le relevé de 8 h-11 h sert aussi de relevé du jour). |
| `.github/workflows/rattrapage.yml` | Lance `backfill.py` à la demande (une seule fois au départ). |

## Mise en ligne (GitHub Pages, gratuit)

1. Crée un compte sur github.com, puis un dépôt public (ex. `carte-penuries`).
2. Envoie tous les fichiers de ce dossier dans le dépôt (bouton **Add file → Upload files**,
   en gardant les dossiers `scripts` et `.github`).
3. **Settings → Pages** : Source = *Deploy from a branch*, branche `main`, dossier `/ (root)`.
   Le site sera en ligne à l'adresse `https://<ton-pseudo>.github.io/carte-penuries/`.
4. **Settings → Actions → General → Workflow permissions** : coche *Read and write permissions*.
5. Onglet **Actions** → *Rattrapage de l'historique* → **Run workflow** (365 jours par défaut, quelques minutes).
   Puis *Relevé des ruptures (toutes les 3 h)* → **Run workflow** pour le premier relevé.
   Ensuite le relevé se fait tout seul toutes les 3 heures.

## Réglages (en haut du script dans `index.html`)

- `REFRESH_MIN` : fréquence d'actualisation automatique (10 min).
- `MAX_AGE_DAYS` : les ruptures plus anciennes que ce nombre de jours sont ignorées (21).
  Si tu le changes, change aussi la même valeur dans `scripts/snapshot.py`.

## Fond de carte

Fond gris Esri (sans clé d'API). Les serveurs OpenStreetMap refusent les pages ouvertes
directement depuis l'ordinateur (sans adresse web), ce qui affichait un message d'erreur sur la carte.

## Mode « Départements »

Chaque département est coloré selon le % de ses stations en difficulté (rupture partielle ou totale) :
gris sous 20 %, jaune de 20 à 25 %, orange de 25 à 33 %, rouge de 33 à 50 %, noir à partir de 50 %.
Seuils modifiables dans `index.html` (`LEVELS = [20, 25, 33, 50]`).

## Définitions

- **Rupture partielle** : au moins un carburant manque, mais il en reste.
- **Rupture totale** : plus aucun des carburants vendus par la station n'est disponible.
- **Variation J-7 / J-30** : évolution en % du nombre de stations en rupture (partielle + totale)
  par rapport au relevé de ce jour-là.
- **Prix moyen** : moyenne des prix affichés par les stations, mis à jour depuis moins de 7 jours.
- **Nouvelles ruptures** : stations dont la rupture en cours a commencé ce jour-là. Les ruptures
  déjà terminées ne figurent plus dans le flux : les jours anciens sont donc sous-estimés.
