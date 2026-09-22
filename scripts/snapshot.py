#!/usr/bin/env python3
"""
Relevé quotidien des stations en rupture.

Lit le flux instantané officiel (prix-carburants, ministère de l'Économie),
relève le prix moyen de chaque carburant,
classe chaque station exactement comme le site (partielle / totale / OK)
et ajoute (ou remplace) la ligne du jour dans historique.json.

Lancé toutes les 3 heures :
  - chaque passage ajoute un point dans releves-3h.json (32 derniers jours conservés) ;
  - le premier passage après 8 h (heure de Paris) écrit aussi la ligne du jour dans historique.json ;
  - chaque passage complète les « nouvelles ruptures » des jours précédents à partir du fichier
    quotidien officiel (toutes les ruptures déclarées, y compris celles déjà terminées).

Usage : python scripts/snapshot.py [--file flux.json] [--out historique.json] [--out3h releves-3h.json]
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import argparse, gzip, io, json, re, sys, unicodedata, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

API = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
       "prix-des-carburants-en-france-flux-instantane-v2/exports/json")
MAX_AGE_DAYS = 60          # identique au site : au-delà, une "rupture temporaire" jamais clôturée est ignorée
KEEP_DAYS = 400            # taille maximale de l'historique
KEEP_3H_DAYS = 32          # durée conservée pour les relevés toutes les 3 h (courbe 7 / 14 / 30 j)
DAILY_HOUR = 8             # heure (Paris) à partir de laquelle on écrit le relevé du jour
PRICE_MAX_AGE_DAYS = 7     # prix moyen : seuls les prix mis à jour depuis moins de 7 jours comptent
FUELS = ["gazole", "e10", "sp95", "sp98", "e85", "gplc"]
try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:
    PARIS = timezone(timedelta(hours=2))


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def fuel_key(s):
    n = re.sub(r"[^a-z0-9]", "", norm(s))
    if n.startswith("gazole") or n == "diesel": return "gazole"
    if "e10" in n: return "e10"
    if n in ("sp95", "sp98", "e85"): return n
    if n.startswith("gpl"): return "gplc"
    return None


def to_list(v):
    if isinstance(v, list): return v
    if isinstance(v, str) and v.strip(): return re.split(r"[;,|]", v)
    return []


def fuel_set(v):
    return {k for k in map(fuel_key, to_list(v)) if k}


def parse_date(v):
    if not v: return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=PARIS)
    except ValueError:
        return None


def norm_dep(c):
    c = str(c or "").strip().upper()
    return "0" + c if re.fullmatch(r"\d", c) else c


def classify(r, has_rupture_fields, now):
    dispo = fuel_set(r.get("carburants_disponibles"))
    defin = fuel_set(r.get("carburants_rupture_definitive"))
    temp = {}
    if has_rupture_fields:
        for k in fuel_set(r.get("carburants_rupture_temporaire")):
            temp[k] = None
        for f in FUELS:
            typ = r.get(f + "_rupture_type")
            debut = parse_date(r.get(f + "_rupture_debut"))
            if typ and re.search(r"temp", str(typ), re.I): temp[f] = debut
            elif typ and re.search(r"d[ée]f", str(typ), re.I): defin.add(f)
            elif f in temp and debut: temp[f] = debut
    else:
        for k in fuel_set(r.get("carburants_indisponibles")):
            temp[k] = None
    for k in list(temp):
        d = temp[k]
        if k in dispo or k in defin or (d and (now - d).total_seconds() / 86400 > MAX_AGE_DAYS):
            del temp[k]
    if not temp: return "o"
    return "t" if not dispo else "p"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "carte-penuries/1.0", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
        # le serveur peut renvoyer du gzip même sans le demander (ou l'inverse) : on détecte la signature
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return json.loads(data.decode("utf-8"))


def build_day(rows, now):
    has_rupture = any("rupture" in k for r in rows for k in r)
    day = {"date": now.astimezone(PARIS).strftime("%Y-%m-%d"),
           "time": now.astimezone(PARIS).strftime("%H:%M"),
           "all": 0, "p": 0, "t": 0, "deps": {}}
    sums = {}
    for r in rows:
        for f in FUELS:
            p, m = r.get(f + "_prix"), parse_date(r.get(f + "_maj"))
            if p and m and (now - m).total_seconds() <= PRICE_MAX_AGE_DAYS * 86400:
                s = sums.setdefault(f, [0.0, 0]); s[0] += float(p); s[1] += 1
        st = classify(r, has_rupture, now)
        dep = norm_dep(r.get("code_departement")) or "??"
        d = day["deps"].setdefault(dep, [0, 0, 0])
        day["all"] += 1; d[0] += 1
        if st == "p": day["p"] += 1; d[1] += 1
        elif st == "t": day["t"] += 1; d[2] += 1
    day["prix"] = {f: round(s[0] / s[1], 4) for f, s in sums.items() if s[1] >= 20}
    return day


def trim(days):
    """Garde le détail par département seulement sur les 45 derniers jours (fichier plus léger)."""
    days = days[-KEEP_DAYS:]
    for d in days[:-45]:
        d.pop("deps", None)
        if isinstance(d.get("new"), dict):
            d["new"].pop("deps", None)
    return days


# ---------- Nouvelles ruptures déclarées (événements) ----------
DAILY_FILE = "https://donnees.roulez-eco.fr/opendata/jour/{ymd}"


def station_event(sold_recent, rups, day0, day1):
    """Pour une station et une journée [day0, day1[ :
    "t" si elle est passée à sec ce jour-là, "p" si elle est entrée en rupture partielle, sinon None.
    rups = [(carburant, début, fin)] (ruptures temporaires uniquement)."""
    starts = sorted(deb for _, deb, _ in rups if day0 <= deb < day1)
    if not starts:
        return None

    def active(t):
        return {k for k, deb, fin in rups
                if deb <= t and (fin is None or fin > t) and (t - deb).total_seconds() <= MAX_AGE_DAYS * 86400}

    entered = total = False
    for t in starts:
        before, after = active(t - timedelta(seconds=1)), active(t)
        if after and not before:
            entered = True
        if after and sold_recent <= after and not (before and sold_recent <= before):
            total = True
    return "t" if total else ("p" if entered else None)


def events_from_daily_file(ymd, dep_of_cp):
    """Compte les stations entrées en rupture / passées à sec le jour ymd (AAAAMMJJ),
    d'après le fichier quotidien officiel (qui contient aussi les ruptures déjà terminées)."""
    req = urllib.request.Request(DAILY_FILE.format(ymd=ymd), headers={"User-Agent": "carte-penuries/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    if data[:2] != b"PK":
        return None                                  # fichier pas encore publié
    z = zipfile.ZipFile(io.BytesIO(data))
    src = z.open(next(n for n in z.namelist() if n.lower().endswith(".xml")))
    day0 = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=PARIS)
    day1 = day0 + timedelta(days=1)
    out = {"p": 0, "t": 0, "deps": {}, "source": "jour"}
    for _, el in ET.iterparse(src, events=("end",)):
        if el.tag != "pdv":
            continue
        sold, rups = set(), []
        for c in el:
            k = fuel_key(c.get("nom"))
            if not k:
                continue
            if c.tag == "prix":
                sold.add(k)
            elif c.tag == "rupture" and (c.get("type") or "").lower().startswith("t"):
                deb, fin = parse_date(c.get("debut")), parse_date(c.get("fin"))
                if deb:
                    rups.append((k, deb, fin))
        dep = dep_of_cp(el.get("cp"))
        el.clear()
        ev = station_event(sold, rups, day0, day1)
        if ev:
            out[ev] += 1
            d = out["deps"].setdefault(dep, [0, 0])
            d[0 if ev == "p" else 1] += 1
    return out


def dep_from_cp(cp):
    cp = re.sub(r"\D", "", cp or "").zfill(5)
    if cp.startswith("97") or cp.startswith("98"): return cp[:3]
    if cp.startswith("20"): return "2A" if int(cp) < 20200 else "2B"
    return cp[:2]


def update_events(out, now, days_back=3):
    """Ajoute les nouvelles ruptures des jours récents (hier, avant-hier…) si elles manquent."""
    path = Path(out)
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"days": []}
    days = {d["date"]: d for d in hist.get("days", [])}
    changed = False
    for n in range(1, days_back + 1):
        day = (now.astimezone(PARIS) - timedelta(days=n)).strftime("%Y-%m-%d")
        entry = days.get(day)
        if entry and isinstance(entry.get("new"), dict) and entry["new"].get("source") == "jour":
            continue
        try:
            ev = events_from_daily_file(day.replace("-", ""), dep_from_cp)
        except Exception as e:  # réseau, fichier absent…
            print(f"Nouvelles ruptures du {day} : fichier quotidien indisponible ({e})")
            continue
        if not ev:
            continue
        days.setdefault(day, {"date": day})["new"] = ev
        changed = True
        print(f"Nouvelles ruptures du {day} : {ev['p']} partielles, {ev['t']} à sec")
    if changed:
        hist = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "days": trim(sorted(days.values(), key=lambda d: d["date"]))}
        path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def save(day, out):
    path = Path(out)
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"days": []}
    old = next((d for d in hist.get("days", []) if d.get("date") == day["date"]), None)
    if old and "new" in old and "new" not in day:
        day = {**day, "new": old["new"]}          # garde les nouvelles ruptures déjà calculées
    days = [d for d in hist.get("days", []) if d.get("date") != day["date"]]
    days.append(day)
    days.sort(key=lambda d: d["date"])
    hist = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": trim(days)}
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def save_3h(day, now, out):
    path = Path(out)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"points": []}
    ts = now.astimezone(PARIS).replace(second=0, microsecond=0)
    point = {"ts": ts.isoformat(), "all": day["all"], "p": day["p"], "t": day["t"], "deps": day["deps"]}
    limit = now - timedelta(days=KEEP_3H_DAYS)
    pts = [x for x in data.get("points", [])
           if datetime.fromisoformat(x["ts"]) >= limit and abs((datetime.fromisoformat(x["ts"]) - ts).total_seconds()) > 1800]
    pts.append(point)
    pts.sort(key=lambda x: x["ts"])
    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "points": pts}
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def daily_due(out, now):
    """Vrai si la ligne du jour n'existe pas encore (ou date d'avant 8 h) et qu'il est au moins 8 h."""
    local = now.astimezone(PARIS)
    if local.hour < DAILY_HOUR:
        return False
    path = Path(out)
    if not path.exists():
        return True
    days = json.loads(path.read_text(encoding="utf-8")).get("days", [])
    today = next((d for d in days if d.get("date") == local.strftime("%Y-%m-%d")), None)
    return today is None or today.get("time", "00:00") < f"{DAILY_HOUR:02d}:00" or today.get("source") == "archive"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="flux JSON local (pour tester sans réseau)")
    ap.add_argument("--out", default="historique.json")
    ap.add_argument("--out3h", default="releves-3h.json")
    ap.add_argument("--force-daily", action="store_true", help="écrit la ligne du jour quelle que soit l'heure")
    a = ap.parse_args()
    raw = json.loads(Path(a.file).read_text(encoding="utf-8")) if a.file else fetch(API)
    rows = raw if isinstance(raw, list) else raw.get("results", [])
    if len(rows) < 1000:
        sys.exit(f"Flux anormalement court ({len(rows)} stations) : relevé ignoré.")
    now = datetime.now(timezone.utc)
    day = build_day(rows, now)
    save_3h(day, now, a.out3h)
    msg = "relevé 3 h enregistré"
    if a.force_daily or daily_due(a.out, now):
        save(day, a.out)
        msg += " + ligne du jour dans l'historique"
    print(f"{day['date']} {day['time']} : {day['all']} stations, {day['p']} partielles, {day['t']} totales ({msg})")
    if not a.file:
        update_events(a.out, now)


if __name__ == "__main__":
    main()
