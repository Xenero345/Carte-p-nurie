#!/usr/bin/env python3
"""
Rattrapage de l'historique à partir des archives officielles.

Le ministère publie chaque année un fichier XML (donnees.roulez-eco.fr/opendata/annee/AAAA)
contenant, pour chaque station, tous les changements de prix et toutes les ruptures
(début, fin, type temporaire/définitive). Ce script reconstitue, pour chacun des
N derniers jours (à 9 h, heure de Paris) :
  - le nombre de stations en rupture partielle et totale (France + chaque département),
  - le prix moyen de chaque carburant,
  - les « nouvelles ruptures » du jour (stations entrées en rupture / passées à sec, y compris
    celles réapprovisionnées depuis),
et l'ajoute à historique.json sans écraser les relevés quotidiens déjà présents.

Usage :
  python scripts/backfill.py                  # 365 jours, télécharge les archives nécessaires
  python scripts/backfill.py --days 60
  python scripts/backfill.py --file PrixCarburants_annuel_2026.zip   # archive locale (xml ou zip)

À lancer une fois, au démarrage du projet. Bibliothèque standard uniquement.
"""
import argparse, bisect, io, json, re, sys, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from snapshot import fuel_key, trim, station_event, PARIS, MAX_AGE_DAYS, PRICE_MAX_AGE_DAYS, KEEP_3H_DAYS  # mêmes règles que le site

ARCHIVE = "https://donnees.roulez-eco.fr/opendata/annee/{year}"
SOLD_LOOKBACK_DAYS = 60   # carburant "vendu" = prix mis à jour dans les 60 jours précédents


def parse_dt(v):
    if not v: return None
    v = v.strip().replace(" ", "T")
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=PARIS)


def dep_from_cp(cp):
    cp = re.sub(r"\D", "", cp or "").zfill(5)
    if cp.startswith("97") or cp.startswith("98"): return cp[:3]
    if cp.startswith("20"): return "2A" if int(cp) < 20200 else "2B"
    return cp[:2]


def open_source(path, year):
    if path:
        data = Path(path).read_bytes()
    else:
        url = ARCHIVE.format(year=year)
        print(f"Téléchargement de {url} …", file=sys.stderr)
        req = urllib.request.Request(url, headers={"User-Agent": "carte-penuries/1.0"})
        with urllib.request.urlopen(req, timeout=900) as r:
            data = r.read()
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        return z.open(name)
    return io.BytesIO(data)


def process(src, instants, res, ev_days=(), ev=None):
    """Parcourt une archive station par station (mémoire constante) et cumule les résultats
    pour les instants de l'année couverte par ce fichier."""
    for _, el in ET.iterparse(src, events=("end",)):
        if el.tag != "pdv":
            continue
        dep = dep_from_cp(el.get("cp"))
        prix, rup = {}, []
        for c in el:
            if c.tag == "prix":
                k, d = fuel_key(c.get("nom")), parse_dt(c.get("maj"))
                try: v = float(c.get("valeur"))
                except (TypeError, ValueError): continue
                if v > 100: v /= 1000          # anciens fichiers : prix en millièmes
                if k and d and 0.2 < v < 5:
                    prix.setdefault(k, []).append((d, v))
            elif c.tag == "rupture":
                k = fuel_key(c.get("nom"))
                deb, fin = parse_dt(c.get("debut")), parse_dt(c.get("fin"))
                if k and deb:
                    rup.append((k, deb, fin, (c.get("type") or "").lower().startswith("d")))
        el.clear()
        if not prix and not rup:
            continue
        temps = [(k, deb, fin) for k, deb, fin, definitive in rup if not definitive]
        for key, d0, d1 in ev_days:                    # nouvelles ruptures déclarées ce jour-là
            if not any(d0 <= deb < d1 for _, deb, _ in temps):
                continue
            lo = d0 - timedelta(days=SOLD_LOOKBACK_DAYS)
            sold = {k for k, v in prix.items() if any(lo <= d < d1 for d, _ in v)}
            e = station_event(sold, temps, d0, d1)
            if e:
                x = ev.setdefault(key, {"p": 0, "t": 0, "deps": {}, "source": "archive"})
                x[e] += 1
                dd = x["deps"].setdefault(dep, [0, 0]); dd[0 if e == "p" else 1] += 1
        first_year = min((d.year for v in prix.values() for d, _ in v), default=None)
        for k in prix:
            prix[k].sort()
        dates = {k: [d for d, _ in v] for k, v in prix.items()}
        for i, D in instants:
            if first_year and D.year < first_year:
                continue                       # instant couvert par une autre archive
            active = set()
            for k, deb, fin, definitive in rup:
                if definitive or deb > D or (fin and fin <= D): continue
                if (D - deb).days > MAX_AGE_DAYS: continue
                active.add(k)
            sold = set(active)
            early = D.timetuple().tm_yday <= SOLD_LOOKBACK_DAYS   # début d'année : historique incomplet
            for k, ds in dates.items():
                j = bisect.bisect_right(ds, D) - 1          # dernier prix connu avant D
                if j < 0:
                    if early: sold.add(k)
                    continue
                age = (D - ds[j]).days
                if age <= SOLD_LOOKBACK_DAYS: sold.add(k)
                if age <= PRICE_MAX_AGE_DAYS and k not in active:
                    px = res[i]["_px"].setdefault(k, [0.0, 0]); px[0] += prix[k][j][1]; px[1] += 1
            if not sold:
                continue
            r = res[i]; d = r["deps"].setdefault(dep, [0, 0, 0])
            r["all"] += 1; d[0] += 1
            if active:
                if active >= sold: r["t"] += 1; d[2] += 1
                else: r["p"] += 1; d[1] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--file", action="append", help="archive locale (.xml ou .zip), répétable")
    ap.add_argument("--out", default="historique.json")
    ap.add_argument("--overwrite", action="store_true", help="remplace aussi les jours déjà relevés")
    ap.add_argument("--out3h", default="releves-3h.json", help="relevés toutes les 3 h reconstitués (jours récents)")
    a = ap.parse_args()

    today = datetime.now(PARIS).replace(hour=9, minute=0, second=0, microsecond=0)
    daily = [today - timedelta(days=n) for n in range(a.days, 0, -1)]
    # points toutes les 3 h sur les derniers jours, jusqu'au début d'hier (l'archive a environ un jour de retard)
    midnight = today.replace(hour=0)
    h3 = [midnight - timedelta(days=1) - timedelta(hours=3 * k) for k in range((KEEP_3H_DAYS - 2) * 8, -1, -1)]
    instants = daily + h3
    res = [{"all": 0, "p": 0, "t": 0, "deps": {}, "_px": {}} for _ in instants]
    ev_days = [(D.strftime("%Y-%m-%d"), D.replace(hour=0), D.replace(hour=0) + timedelta(days=1)) for D in daily]
    ev = {}
    if a.file:
        for f in a.file:
            process(open_source(f, None), list(enumerate(instants)), res, ev_days, ev)
    else:
        for y in sorted({d.year for d in instants}):
            process(open_source(None, y), [(i, D) for i, D in enumerate(instants) if D.year == y], res,
                    [e for e in ev_days if e[1].year == y], ev)
    for r in res:
        r["prix"] = {k: round(v[0] / v[1], 4) for k, v in r.pop("_px").items() if v[1] >= 20}

    res_h3 = res[len(daily):]; res = res[:len(daily)]
    instants = daily
    p3 = Path(a.out3h)
    d3 = json.loads(p3.read_text(encoding="utf-8")) if p3.exists() else {"points": []}
    if a.overwrite:                      # on remplace les points reconstitués, pas les relevés réels
        d3["points"] = [x for x in d3.get("points", []) if x.get("source") != "archive"]
    have = {x["ts"][:13] for x in d3.get("points", [])}
    n3 = 0
    for D, v in zip(h3, res_h3):
        ts = D.isoformat()
        if v["all"] < 1000 or ts[:13] in have: continue
        d3.setdefault("points", []).append({"ts": ts, "all": v["all"], "p": v["p"], "t": v["t"], "deps": v["deps"], "source": "archive"}); n3 += 1
    d3["points"].sort(key=lambda x: x["ts"])
    p3.write_text(json.dumps(d3, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{n3} relevé(s) toutes les 3 h ajoutés à {a.out3h}")

    path = Path(a.out)
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"days": []}
    existing = {d["date"]: d for d in hist.get("days", [])}
    added = 0
    for D, v in zip(instants, res):
        date = D.strftime("%Y-%m-%d")
        if v["all"] < 1000:
            print(f"{date} ignoré ({v['all']} stations seulement)", file=sys.stderr); continue
        new = ev.get(date, {"p": 0, "t": 0, "deps": {}, "source": "archive"})
        if date in existing and not a.overwrite:
            existing[date].setdefault("prix", v["prix"])   # complète au moins les prix
            if existing[date].get("new", {}).get("source") != "jour":
                existing[date]["new"] = new
            continue
        old_new = existing.get(date, {}).get("new")
        existing[date] = {"date": date, "time": "09:00", "source": "archive", **v,
                          "new": old_new if old_new and old_new.get("source") == "jour" else new}
        added += 1
    days = trim(sorted(existing.values(), key=lambda d: d["date"]))
    hist = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": days[-400:]}
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{added} jour(s) ajoutés à {a.out}")
    for d in days[-10:]:
        px = " · ".join(f"{k} {v:.3f}" for k, v in d.get("prix", {}).items())
        print(f"  {d['date']} : {d['all']} stations · {d['p']} partielles · {d['t']} totales · {px}")


if __name__ == "__main__":
    main()
