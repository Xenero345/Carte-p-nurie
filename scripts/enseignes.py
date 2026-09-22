#!/usr/bin/env python3
"""
Noms et enseignes des stations-service (Total, Leclerc, Intermarché…).

Le flux officiel prix-carburants ne donne pas le nom des stations. OpenStreetMap, lui, relie
~10 000 stations françaises à leur identifiant officiel (étiquette « ref:FR:prix-carburants »).
Ce script récupère ces stations via l'API Overpass et écrit enseignes.json :
  {"source": "...", "maj": "...", "stations": {"<id officiel>": "Nom affiché", ...}}

Données © contributeurs OpenStreetMap, licence ODbL.
Usage : python scripts/enseignes.py [--out enseignes.json] [--file reponse-overpass.json]
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import argparse, datetime, gzip, json, re, sys, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

SERVEURS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
REQUETE = '[out:json][timeout:300];nwr["ref:FR:prix-carburants"];out tags;'
MINIMUM = 3000   # en dessous, la réponse est jugée incomplète et le fichier existant est conservé


def telecharger():
    corps = urllib.parse.urlencode({"data": REQUETE}).encode()
    for url in SERVEURS:
        for essai in range(2):
            try:
                print(f"Interrogation de {url} …", file=sys.stderr)
                req = urllib.request.Request(url, data=corps, headers={"User-Agent": "carte-penuries/1.0", "Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=400) as r:
                    data = r.read()
                if data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return json.loads(data.decode("utf-8"))
            except Exception as e:
                print(f"  échec : {e}", file=sys.stderr)
                time.sleep(20)
    raise SystemExit("Aucun serveur Overpass n'a répondu. Le fichier enseignes.json n'a pas été modifié.")


def cle(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def libelle(tags):
    nom = (tags.get("name") or "").strip()
    marque = (tags.get("brand") or tags.get("operator") or "").strip()
    if nom and marque:
        m = cle(re.sub(r"^\s*e\.\s*", "", marque, flags=re.I))[:5]   # « E.Leclerc » → « lecle »
        return nom if m and m in cle(nom) else f"{nom} ({marque})"
    return nom or marque


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="enseignes.json")
    ap.add_argument("--file", help="réponse Overpass déjà téléchargée (tests)")
    a = ap.parse_args()

    brut = json.loads(Path(a.file).read_text(encoding="utf-8")) if a.file else telecharger()
    stations = {}
    for el in brut.get("elements", []):
        tags = el.get("tags") or {}
        txt = libelle(tags)
        if not txt:
            continue
        for ident in re.split(r"[;,\s]+", tags.get("ref:FR:prix-carburants", "")):
            if ident.isdigit():
                stations.setdefault(ident, txt[:80])

    if len(stations) < MINIMUM and not a.file:
        raise SystemExit(f"Seulement {len(stations)} stations nommées : réponse incomplète, fichier conservé.")
    out = {
        "source": "Noms et enseignes © contributeurs OpenStreetMap (licence ODbL)",
        "maj": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "stations": dict(sorted(stations.items())),
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(stations)} stations nommées écrites dans {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
