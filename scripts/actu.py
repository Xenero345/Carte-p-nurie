#!/usr/bin/env python3
"""
Actualités sur la pénurie de carburant, via le flux RSS de Google Actualités.

Interroge Google Actualités (aucune clé requise) pour la recherche « pénurie carburant »,
et écrit actu.json :
  {"maj": "...", "articles": [{"title": "...", "link": "...", "source": "...", "date": "JJ/MM"}, ...]}

Usage : python scripts/actu.py [--out actu.json] [--max 6]
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import argparse, datetime, json, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

RSS = "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"
REQUETE = "pénurie carburant OR rupture essence OR rupture carburant"


def telecharger():
    url = RSS.format(q=urllib.parse.quote(REQUETE))
    req = urllib.request.Request(url, headers={"User-Agent": "carte-penuries/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def nettoyer_titre(titre, source):
    # Google Actualités suffixe le titre par « - Source » : on l'enlève si on a déjà la source à part.
    if source and titre.endswith(" - " + source):
        return titre[: -(len(source) + 3)]
    return titre


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="actu.json")
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--file", help="flux RSS déjà téléchargé (tests)")
    a = ap.parse_args()

    try:
        brut = Path(a.file).read_bytes() if a.file else telecharger()
        root = ET.fromstring(brut)
    except Exception as e:
        print(f"Flux RSS indisponible ({e}), fichier conservé.", file=sys.stderr)
        return

    articles = []
    for item in root.iter("item"):
        titre = (item.findtext("title") or "").strip()
        lien = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        pub = item.findtext("pubDate")
        date = ""
        if pub:
            try:
                date = parsedate_to_datetime(pub).strftime("%d/%m")
            except Exception:
                pass
        if not titre or not lien:
            continue
        articles.append({"title": nettoyer_titre(titre, source), "link": lien, "source": source, "date": date})
        if len(articles) >= a.max:
            break

    if not articles:
        print("Aucun article trouvé, fichier conservé.", file=sys.stderr)
        return

    out = {"maj": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "articles": articles}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(articles)} article(s) écrits dans {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
