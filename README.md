# Carte des pénuries de carburant

Site qui affiche en temps réel les stations-service en rupture partielle ou totale,
d'après le flux officiel du ministère de l'Économie (prix-carburants.gouv.fr, Licence Ouverte).

## Contenu

| Fichier | Rôle |
|---|---|
| `index.html` | Le site (carte, bandeau défilant, onglets Territoires / 30 jours / Nouvelles ruptures / Prix moyen). Lit le flux officiel en direct depuis le navigateur. |
| `departements.js` | Contours des 96 départements de métropole (mode « Départements » de la carte). |
| `releves-3h.json` | Un relevé toutes les 3 h sur les 32 derniers jours (courbe 7 / 14 / 30 j de l'onglet Évolution). |
| `historique.json` | Un relevé par jour : ruptures (France + chaque département), prix moyen de chaque carburant et nouvelles ruptures déclarées dans la journée. Sert aux variations et aux courbes. |
| `scripts/snapshot.py` | Fait un relevé (toutes les 3 h) et met à jour `releves-3h.json` et `historique.json`. |
| `enseignes.json` | Nom / enseigne de chaque station (Total, Leclerc…), affiché dans le popup d'une station. Tiré d'OpenStreetMap (© contributeurs OpenStreetMap, ODbL). |
| `scripts/enseignes.py` | Fabrique `enseignes.json` à partir d'OpenStreetMap (étiquette `ref:FR:prix-carburants`, l'identifiant officiel de la station). |
| `scripts/backfill.py` | Reconstitue les 12 derniers mois (ruptures + prix moyens) à partir des archives annuelles du ministère (donnees.roulez-eco.fr). |
| `.github/workflows/releve-quotidien.yml` | Lance `snapshot.py` automatiquement toutes les 3 h (le relevé de 8 h-11 h sert aussi de relevé du jour). |
| `.github/workflows/enseignes.yml` | Lance `enseignes.py` chaque lundi (et à la demande). |
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
- `MAX_AGE_DAYS` : les « ruptures temporaires » déclarées depuis plus de 60 jours et jamais clôturées sont ignorées
  (sans cette limite, près de 700 déclarations vieilles de plus d'un an gonfleraient les chiffres).
  Si tu le changes, change aussi la même valeur dans `scripts/snapshot.py`.

## Fond de carte

Fond gris Esri (sans clé d'API). Les serveurs OpenStreetMap refusent les pages ouvertes
directement depuis l'ordinateur (sans adresse web), ce qui affichait un message d'erreur sur la carte.

## Départements colorés

Sous les points, chaque département est coloré (case « Colorer les départements ») selon le % de ses stations en difficulté (rupture partielle ou totale) :
gris sous 20 %, jaune de 20 à 25 %, orange de 25 à 33 %, rouge de 33 à 50 %, noir à partir de 50 %.
Seuils modifiables dans `index.html` (`LEVELS = [20, 25, 33, 50]`).

## Définitions

- **Rupture partielle** : au moins un carburant manque, mais il en reste.
- **Rupture totale** : plus aucun des carburants vendus par la station n'est disponible.
- **Variation J-7 / J-30** : évolution en % du nombre de stations en rupture (partielle + totale)
  par rapport au relevé de ce jour-là.
- **Prix moyen** : moyenne des prix affichés par les stations, mis à jour depuis moins de 7 jours.
- **Nouvelles ruptures** : stations entrées en rupture (partielle) ou passées à sec dans la journée, d'après
  toutes les déclarations du jour (fichier quotidien / archive annuelle du ministère), y compris celles
  réapprovisionnées depuis. Le jour en cours est provisoire (ruptures encore en cours uniquement).
