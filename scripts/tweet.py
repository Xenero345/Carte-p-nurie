#!/usr/bin/env python3
"""
Publie chaque jour un point de situation sur X (Twitter), à partir du dernier relevé (releves-3h.json).

Exemple de tweet :
  ⛽ Pénurie de carburant – point du samedi 26/09, 8h
  16,8 % des stations en difficulté en France (+1,2 pt sur 24 h).
  Les plus touchés : Bas-Rhin (28 %), Paris (27 %), Haut-Rhin (26 %).
  Carte en direct 👉 https://carte-penurie-essence.fr
  #pénurie #essence #carburant

Clés d'API lues dans les variables d'environnement (secrets GitHub) :
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
Sans ces clés, ou avec --dry-run, le tweet est seulement affiché (rien n'est publié).

Usage : python scripts/tweet.py [--dry-run]
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import argparse, base64, datetime, hashlib, hmac, json, os, re, secrets, sys, time, urllib.parse, urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SITE = "https://carte-penurie-essence.fr"
API = "https://api.x.com/2/tweets"
POP_MIN = 400        # comme l'analyse du site : on ne cite que les départements d'au moins 400 000 habitants
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def pf(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def populations():
    """Même table que l'analyse du site : lue directement dans index.html (une seule source)."""
    m = re.search(r"const DEP_POP = (\{.*?\});", (RACINE / "index.html").read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1)) if m else {}


def noms():
    brut = (RACINE / "departements.js").read_text(encoding="utf-8")
    gj = json.loads(brut[brut.index("{"):].rstrip().rstrip(";"))
    return {f["properties"]["code"]: f["properties"]["nom"] for f in gj["features"]}


def pct(pt):
    return (pt["p"] + pt["t"]) / pt["all"] * 100 if pt.get("all") else None


def composer():
    pts = json.loads((RACINE / "releves-3h.json").read_text(encoding="utf-8")).get("points", [])
    if not pts:
        raise SystemExit("Aucun relevé disponible.")
    pts.sort(key=lambda x: x["ts"])
    cur = pts[-1]
    d = datetime.datetime.fromisoformat(cur["ts"])
    # Point le plus proche de 24 h avant (à 3 h près) pour la tendance
    cible = d - datetime.timedelta(hours=24)
    ref = min(pts, key=lambda x: abs(datetime.datetime.fromisoformat(x["ts"]) - cible))
    if abs(datetime.datetime.fromisoformat(ref["ts"]) - cible) > datetime.timedelta(hours=3):
        ref = None

    nat = pct(cur)
    lignes = [f"⛽ Pénurie de carburant – point du {JOURS[d.weekday()]} {d:%d/%m}, {d.hour}h"]
    tendance = ""
    if ref and pct(ref) is not None:
        delta = nat - pct(ref)
        if abs(delta) < 0.3:
            tendance = " (stable sur 24 h)"
        else:
            tendance = f" ({'+' if delta > 0 else '−'}{pf(abs(delta))} pt{'s' if abs(delta) >= 2 else ''} sur 24 h)"
    lignes.append(f"{pf(nat)} % des stations en difficulté en France{tendance}.")

    pop, nm = populations(), noms()
    top = []
    for code, (all_, p, t) in cur.get("deps", {}).items():
        if code == "??" or all_ < 15 or pop.get(code, 0) < POP_MIN:
            continue
        top.append(((p + t) / all_ * 100, nm.get(code, code)))
    top.sort(reverse=True)
    top = [x for x in top if x[0] >= 10][:3]
    fin = [f"Carte en direct 👉 {SITE}", "#pénurie #essence #carburant"]
    # Retire un département tant que le tweet dépasse 280 (comptage X : lien = 23, emoji = 2)
    while True:
        dep = ["Les plus touchés : " + ", ".join(f"{n} ({round(v)} %)" for v, n in top) + "."] if top else []
        texte = "\n".join(lignes + dep + fin)
        if longueur_x(texte) <= 280 or not top:
            return texte
        top = top[:-1]


def longueur_x(texte):
    t = texte.replace(SITE, "x" * 23)
    return sum(2 if ord(c) > 0x2FFF else 1 for c in t)


# ---------- Signature OAuth 1.0a (compte utilisateur) ----------
def q(s):
    return urllib.parse.quote(str(s), safe="~")


def entete_oauth(methode, url, cle, secret, jeton, jeton_secret):
    params = {
        "oauth_consumer_key": cle,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": jeton,
        "oauth_version": "1.0",
    }
    base = "&".join([methode, q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(params.items())))])
    cle_sig = f"{q(secret)}&{q(jeton_secret)}"
    params["oauth_signature"] = base64.b64encode(hmac.new(cle_sig.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(params.items()))


def publier(texte):
    env = [os.environ.get(k, "") for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    if not all(env):
        print("Clés X absentes : tweet non publié (affiché seulement).", file=sys.stderr)
        return
    req = urllib.request.Request(API, data=json.dumps({"text": texte}).encode(), method="POST", headers={
        "Authorization": entete_oauth("POST", API, *env),
        "Content-Type": "application/json",
        "User-Agent": "carte-penuries/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rep = json.loads(r.read().decode())
        print(f"Publié : https://x.com/i/status/{rep['data']['id']}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")
        if e.code == 403 and "duplicate" in corps.lower():
            # Aucun nouveau relevé depuis le dernier tweet : X refuse un texte identique, on ne publie rien.
            print("Même relevé que le tweet précédent : rien de nouveau à publier.", file=sys.stderr)
            return
        raise SystemExit(f"Échec de publication ({e.code}) : {corps}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche le tweet sans le publier")
    a = ap.parse_args()
    texte = composer()
    print(texte)
    print(f"\n({len(texte)} caractères)", file=sys.stderr)
    if not a.dry_run:
        publier(texte)


if __name__ == "__main__":
    main()
