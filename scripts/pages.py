#!/usr/bin/env python3
"""
Génère une page /departement/<slug>/ par département, pour le référencement.

Chaque page reprend exactement index.html (même carte, mêmes onglets, mêmes données en direct)
mais avec : un <title>/description propres au département, un <h1> dédié, un petit texte
statique (chiffres du moment + départements voisins) visible même sans JavaScript, et un
script qui centre automatiquement la carte sur ce département au chargement.

Écrit aussi departement/index.html (annuaire de tous les départements) et met à jour sitemap.xml.

Usage : python scripts/pages.py
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import datetime, json, math, re, sys, unicodedata
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SITE = "https://carte-penurie-essence.fr"
VOISINS = 4          # nombre de départements voisins affichés


def slugifier(nom):
    s = unicodedata.normalize("NFD", nom).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def charger_departements():
    """Lit departements.js (contours + centroïdes approximatifs, pour trouver les voisins)."""
    brut = (RACINE / "departements.js").read_text(encoding="utf-8")
    gj = json.loads(brut[brut.index("{"):].rstrip().rstrip(";"))
    deps = {}
    for f in gj["features"]:
        code, nom = f["properties"]["code"], f["properties"]["nom"]
        geom = f["geometry"]
        anneaux = geom["coordinates"] if geom["type"] == "Polygon" else [a for poly in geom["coordinates"] for a in poly]
        pts = [pt for anneau in anneaux for pt in anneau]
        clat = sum(p[1] for p in pts) / len(pts)
        clon = sum(p[0] for p in pts) / len(pts)
        deps[code] = {"code": code, "nom": nom, "slug": slugifier(nom), "lat": clat, "lon": clon}
    return deps


def voisins_de(code, deps):
    k = math.cos(math.radians(46.5))   # correction grossière de la déformation est-ouest
    x0, y0 = deps[code]["lon"] * k, deps[code]["lat"]
    autres = [(d, ((d["lon"] * k - x0) ** 2 + (d["lat"] - y0) ** 2) ** 0.5) for c, d in deps.items() if c != code]
    autres.sort(key=lambda t: t[1])
    return [d for d, _ in autres[:VOISINS]]


def dernier_releve():
    p = RACINE / "releves-3h.json"
    if not p.exists():
        return None, None
    pts = json.loads(p.read_text(encoding="utf-8")).get("points", [])
    if not pts:
        return None, None
    dernier = max(pts, key=lambda x: x["ts"])
    return dernier.get("deps", {}), dernier.get("ts")


def fmt_date(ts):
    try:
        d = datetime.datetime.fromisoformat(ts)
    except Exception:
        return ""
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"{jours[d.weekday()]} {d:%d/%m/%Y} à {d:%H:%M}"


def stats(code, deps_releve):
    v = deps_releve.get(code)
    if not v or not v[0]:
        return None
    all_, p, t = v
    return {"all": all_, "p": p, "t": t, "pct": round((p + t) / all_ * 100, 1)}


def fmt_pct(x):
    return f"{x:.1f}".replace(".", ",")


# « de » + département, avec le bon article (du Var, de la Sarthe, de l'Ain, des Landes...).
# Pas de règle mécanique fiable en français pour le genre : table vérifiée département par département.
DEP_DE = {
    "01": "de l'Ain", "02": "de l'Aisne", "03": "de l'Allier",
    "04": "des Alpes-de-Haute-Provence", "05": "des Hautes-Alpes", "06": "des Alpes-Maritimes",
    "07": "de l'Ardèche", "08": "des Ardennes", "09": "de l'Ariège", "10": "de l'Aube",
    "11": "de l'Aude", "12": "de l'Aveyron", "13": "des Bouches-du-Rhône", "14": "du Calvados",
    "15": "du Cantal", "16": "de la Charente", "17": "de la Charente-Maritime", "18": "du Cher",
    "19": "de la Corrèze", "2A": "de la Corse-du-Sud", "2B": "de la Haute-Corse",
    "21": "de la Côte-d'Or", "22": "des Côtes-d'Armor", "23": "de la Creuse", "24": "de la Dordogne",
    "25": "du Doubs", "26": "de la Drôme", "27": "de l'Eure", "28": "de l'Eure-et-Loir",
    "29": "du Finistère", "30": "du Gard", "31": "de la Haute-Garonne", "32": "du Gers",
    "33": "de la Gironde", "34": "de l'Hérault", "35": "de l'Ille-et-Vilaine", "36": "de l'Indre",
    "37": "de l'Indre-et-Loire", "38": "de l'Isère", "39": "du Jura", "40": "des Landes",
    "41": "du Loir-et-Cher", "42": "de la Loire", "43": "de la Haute-Loire",
    "44": "de la Loire-Atlantique", "45": "du Loiret", "46": "du Lot", "47": "du Lot-et-Garonne",
    "48": "de la Lozère", "49": "du Maine-et-Loire", "50": "de la Manche", "51": "de la Marne",
    "52": "de la Haute-Marne", "53": "de la Mayenne", "54": "de la Meurthe-et-Moselle",
    "55": "de la Meuse", "56": "du Morbihan", "57": "de la Moselle", "58": "de la Nièvre",
    "59": "du Nord", "60": "de l'Oise", "61": "de l'Orne", "62": "du Pas-de-Calais",
    "63": "du Puy-de-Dôme", "64": "des Pyrénées-Atlantiques", "65": "des Hautes-Pyrénées",
    "66": "des Pyrénées-Orientales", "67": "du Bas-Rhin", "68": "du Haut-Rhin", "69": "du Rhône",
    "70": "de la Haute-Saône", "71": "de la Saône-et-Loire", "72": "de la Sarthe",
    "73": "de la Savoie", "74": "de la Haute-Savoie", "75": "de Paris", "76": "de la Seine-Maritime",
    "77": "de la Seine-et-Marne", "78": "des Yvelines", "79": "des Deux-Sèvres", "80": "de la Somme",
    "81": "du Tarn", "82": "du Tarn-et-Garonne", "83": "du Var", "84": "du Vaucluse",
    "85": "de la Vendée", "86": "de la Vienne", "87": "de la Haute-Vienne", "88": "des Vosges",
    "89": "de l'Yonne", "90": "du Territoire de Belfort", "91": "de l'Essonne",
    "92": "des Hauts-de-Seine", "93": "de la Seine-Saint-Denis", "94": "du Val-de-Marne",
    "95": "du Val-d'Oise",
}


def de_nom(code, nom):
    """« de » + nom de département, avec l'article correct (du Var, de la Sarthe, de l'Ain...)."""
    return DEP_DE.get(code, f"de {nom}")


def faq_qa(code, nom):
    dn = de_nom(code, nom)
    return [
        (f"Pourquoi y a-t-il des stations en rupture {dn} ?",
         f"Les ruptures observées {dn} reflètent les tensions d'approvisionnement qui touchent une partie du "
         f"réseau français de stations-service : le temps que leur livraison arrive, certaines stations se "
         f"retrouvent à court d'un ou plusieurs carburants, une situation qui peut durer de quelques heures à "
         f"plusieurs jours selon la zone."),
        (f"La situation {dn} va-t-elle s'améliorer ?",
         f"Ça évolue au jour le jour. Le chiffre en tête de page est recalculé à partir des données officielles "
         f"du ministère de l'Économie, actualisées plusieurs fois par heure : c'est le moyen le plus fiable de "
         f"suivre la tendance {dn} en temps réel."),
        (f"Comment savoir si une station précise {dn} est concernée ?",
         f"La carte et le tableau ci-dessus listent chaque station en rupture partielle ou totale {dn}, avec son "
         f"adresse et les carburants qui lui manquent. Utilisez les filtres par carburant en haut de page pour "
         f"affiner la recherche."),
    ]


# ---------- Construction d'une page département à partir du gabarit index.html ----------
def construire_page(gabarit, dep, deps_releve, voisins, maj):
    code, nom, slug = dep["code"], dep["nom"], dep["slug"]
    s = stats(code, deps_releve)

    qa = faq_qa(code, nom)
    faq_json = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa],
    }, ensure_ascii=False, indent=2)
    faq_html = ('<section class="faq">\n  <h2>Questions fréquentes</h2>\n' +
                "\n".join(f'  <details><summary>{q}</summary><p>{a}</p></details>' for q, a in qa) +
                "\n</section>\n")

    titre = f"Pénurie d'essence en {nom} ({code}) : carte des stations en temps réel"
    if s:
        desc = (f"{fmt_pct(s['pct'])} % des stations-service {de_nom(code, nom)} sont en rupture partielle ou totale "
                f"de carburant. Carte interactive en temps réel, données officielles du ministère de l'Économie.")
    else:
        desc = (f"Carte interactive en temps réel des stations-service en rupture de carburant dans le "
                f"département {nom} ({code}). Données officielles du ministère de l'Économie.")
    url = f"{SITE}/departement/{slug}/"

    entete = f'''<title>{titre}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{url}">
<link rel="icon" href="{SITE}/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{SITE}/apple-touch-icon.png">
<meta name="theme-color" content="#0f1115">

<!-- Open Graph (Facebook, LinkedIn, WhatsApp) -->
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{titre}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{nom} : part des stations-service en rupture de carburant">
<meta property="og:locale" content="fr_FR">
<meta property="og:site_name" content="Carte pénurie essence">

<!-- Twitter / X Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{titre}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{url}og.png">

<!-- Données structurées (Google) -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "Pénurie d'essence en {nom}",
  "description": "{desc}",
  "url": "{url}",
  "image": "{url}og.png",
  "applicationCategory": "UtilitiesApplication",
  "operatingSystem": "Tous (navigateur web)",
  "inLanguage": "fr",
  "isAccessibleForFree": true,
  "offers": {{"@type": "Offer", "price": "0", "priceCurrency": "EUR"}}
}}
</script>
<script type="application/ld+json">
{faq_json}
</script>'''

    deb = gabarit.index("<title>")
    fin = gabarit.index("</script>", gabarit.index("application/ld+json")) + len("</script>")
    page = gabarit[:deb] + entete + gabarit[fin:]

    page = page.replace("<body>", f'<body>\n<script>window.SCOPE_DEP="{code}";</script>', 1)
    page = page.replace("<h1>Carte des pénuries de carburant</h1>", f"<h1>Pénurie d'essence en {nom} ({code})</h1>", 1)

    if s:
        chiffres = (f"<b>{fmt_pct(s['pct'])} %</b> des {s['all']} stations-service {de_nom(code, nom)} sont actuellement en rupture "
                    f"({s['p']} en rupture partielle, {s['t']} à sec).")
    else:
        chiffres = f"Pas encore de données pour {nom} sur ce relevé."
    maj_txt = f" Relevé du {fmt_date(maj)}." if maj else ""
    liens_voisins = " · ".join(f'<a href="{SITE}/departement/{v["slug"]}/">{v["nom"]}</a>' for v in voisins)
    hero = f'''<div class="dep-hero">
  <div class="dh-in">
    {chiffres}{maj_txt}
    <div class="dh-links">Départements voisins : {liens_voisins} · <a href="{SITE}/">France entière</a> · <a href="{SITE}/departement/">Tous les départements</a></div>
  </div>
</div>
'''
    page = page.replace('<main class="wrap" id="details">', hero + '<main class="wrap" id="details">', 1)
    page = page.replace("<footer>", faq_html + "  <footer>", 1)
    return page


# ---------- Annuaire /departement/index.html ----------
def construire_annuaire(deps, deps_releve, maj):
    par_code = sorted(deps.values(), key=lambda d: d["nom"])
    lignes = []
    for d in par_code:
        s = stats(d["code"], deps_releve)
        pct = f"{fmt_pct(s['pct'])} %" if s else "n.d."
        cls = "hi" if s and s["pct"] >= 15 else ("mid" if s and s["pct"] >= 8 else "")
        lignes.append(f'<a class="dep-row {cls}" href="{SITE}/departement/{d["slug"]}/"><span>{d["nom"]} ({d["code"]})</span><b>{pct}</b></a>')
    maj_txt = fmt_date(maj) if maj else "—"
    return f'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pénurie d'essence par département : la carte de toute la France</title>
<meta name="description" content="Le taux de stations-service en rupture de carburant dans chaque département français, mis à jour toutes les 3 heures.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{SITE}/departement/">
<link rel="icon" href="{SITE}/favicon.svg" type="image/svg+xml">
<meta name="theme-color" content="#0f1115">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE}/departement/">
<meta property="og:title" content="Pénurie d'essence par département">
<meta property="og:description" content="Le taux de stations-service en rupture de carburant dans chaque département français.">
<meta property="og:image" content="{SITE}/preview.png">
<style>
:root{{--bg:#f6f7f9;--surface:#fff;--text:#16181d;--muted:#5d6470;--border:#e1e4ea;--accent:#1f6feb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--surface:#171a21;--text:#e8eaef;--muted:#9aa2b1;--border:#2a2f3a;--accent:#58a6ff}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:900px;margin:0 auto;padding:24px 16px 50px}}
a{{color:inherit;text-decoration:none}}
h1{{font-size:22px;margin:0 0 6px}} p.sub{{color:var(--muted);margin:0 0 22px}}
.home{{display:inline-block;margin-bottom:16px;color:var(--accent);font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px}}
.dep-row{{display:flex;justify-content:space-between;gap:10px;padding:10px 12px;background:var(--surface);border:1px solid var(--border);border-radius:8px}}
.dep-row:hover{{border-color:var(--accent)}}
.dep-row b{{font-variant-numeric:tabular-nums}}
.dep-row.mid b{{color:#f08c00}} .dep-row.hi b{{color:#e03131}}
footer{{color:var(--muted);font-size:12.5px;margin-top:26px}}
</style>
</head>
<body>
<div class="wrap">
<a class="home" href="{SITE}/">← Carte de France entière</a>
<h1>Pénurie d'essence : tous les départements</h1>
<p class="sub">Part des stations-service en rupture partielle ou totale, par département. Relevé du {maj_txt}.</p>
<div class="grid">
{chr(10).join(lignes)}
</div>
<footer>Données officielles du ministère de l'Économie, via <a href="{SITE}/">carte-penurie-essence.fr</a>.</footer>
</div>
</body>
</html>
'''


def maj_sitemap(slugs):
    aujourdhui = datetime.date.today().isoformat()
    urls = [(f"{SITE}/", "hourly", "1.0"), (f"{SITE}/departement/", "daily", "0.6")]
    urls += [(f"{SITE}/departement/{s}/", "hourly", "0.8") for s in sorted(slugs)]
    corps = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{aujourdhui}</lastmod><changefreq>{c}</changefreq><priority>{p}</priority></url>"
        for u, c, p in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{corps}\n</urlset>\n'
    (RACINE / "sitemap.xml").write_text(xml, encoding="utf-8")


def main():
    gabarit = (RACINE / "index.html").read_text(encoding="utf-8")
    if "window.SCOPE_DEP" not in gabarit:
        sys.exit("index.html ne gère pas encore window.SCOPE_DEP : générez les pages après avoir mis à jour index.html.")

    deps = charger_departements()
    deps_releve, maj_ts = dernier_releve()
    deps_releve = deps_releve or {}

    dossier = RACINE / "departement"
    dossier.mkdir(exist_ok=True)
    ecrites = 0
    for code, dep in deps.items():
        page = construire_page(gabarit, dep, deps_releve, voisins_de(code, deps), maj_ts)
        cible = dossier / dep["slug"]
        cible.mkdir(parents=True, exist_ok=True)
        (cible / "index.html").write_text(page, encoding="utf-8")
        ecrites += 1

    (dossier / "index.html").write_text(construire_annuaire(deps, deps_releve, maj_ts), encoding="utf-8")
    maj_sitemap([d["slug"] for d in deps.values()])
    print(f"{ecrites} pages département écrites dans {dossier}/, annuaire et sitemap.xml mis à jour.", file=sys.stderr)


if __name__ == "__main__":
    main()
