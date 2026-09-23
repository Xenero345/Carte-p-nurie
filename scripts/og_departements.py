#!/usr/bin/env python3
"""
Génère une image de partage (Open Graph / Twitter Card, 1200×630) pour chaque page département :
silhouette du département colorée selon son niveau, gros chiffre du moment, nom du département.

Écrit departement/<slug>/og.png (référencée par pages.py dans og:image / twitter:image).

Usage : python scripts/og_departements.py
Nécessite Playwright (déjà utilisé pour les tests locaux du site).
"""
import math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages import RACINE, charger_departements, dernier_releve, stats, fmt_pct  # noqa: E402

W, H = 1200, 630
SIL_BOX = 520          # zone carrée (en px) réservée à la silhouette, à droite de l'image

# Mêmes seuils/couleurs (thème sombre) que le bandeau d'état de la page d'accueil.
PALIERS = [(10, "#51cf66"), (15, "#e5b800"), (25, "#ffa94d"), (35, "#ff7a1a"), (999, "#ff6b6b")]


def couleur(pct):
    if pct is None:
        return "#3a414e"
    for seuil, c in PALIERS:
        if pct <= seuil:
            return c
    return PALIERS[-1][1]


def rings_de(feature):
    g = feature["geometry"]
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    return [p[0] for p in polys]


def silhouette_svg(feature, couleur_remplissage):
    k = math.cos(math.radians(46.5))
    rings = rings_de(feature)
    pts = [(x * k, y) for r in rings for x, y in r]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    pad = 0.09 * max(maxx - minx, maxy - miny, 1e-6)
    minx, maxx, miny, maxy = minx - pad, maxx + pad, miny - pad, maxy + pad
    dim = max(maxx - minx, maxy - miny)
    # Centre le département dans une boîte carrée, en conservant ses proportions.
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    minx, maxx, miny, maxy = cx - dim / 2, cx + dim / 2, cy - dim / 2, cy + dim / 2

    def P(x, y):
        return ((x * k - minx) / (maxx - minx) * SIL_BOX, (maxy - y) / (maxy - miny) * SIL_BOX)

    d = "".join("M" + "L".join(f"{P(x, y)[0]:.1f},{P(x, y)[1]:.1f}" for x, y in r) + "Z" for r in rings)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIL_BOX}" height="{SIL_BOX}" '
            f'viewBox="0 0 {SIL_BOX} {SIL_BOX}"><path d="{d}" fill="{couleur_remplissage}" '
            f'stroke="#0f1115" stroke-width="3" stroke-linejoin="round"/></svg>')


def page_html(nom, code, pct, all_, p, t, svg):
    if pct is not None:
        gros = f"{fmt_pct(pct)} %"
        sous = f"des {all_} stations-service en rupture<br>({p} partielle{'s' if p > 1 else ''} · {t} à sec)"
    else:
        gros = "—"
        sous = "Pas encore de données pour ce relevé"
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;box-sizing:border-box}}
body{{width:{W}px;height:{H}px;background:#0f1115;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#e8eaef;display:flex;overflow:hidden}}
.l{{flex:none;width:{W - SIL_BOX}px;padding:50px 0 46px 62px;display:flex;flex-direction:column}}
.live{{display:inline-flex;align-items:center;gap:8px;background:#e03131;color:#fff;font-weight:800;font-size:17px;letter-spacing:.08em;padding:7px 13px;border-radius:6px;align-self:flex-start}}
.live i{{width:9px;height:9px;border-radius:50%;background:#fff}}
h1{{font-size:30px;line-height:1.15;margin:24px 0 4px;font-weight:800;letter-spacing:-.01em;color:#aab2c0}}
.dept{{font-size:38px;font-weight:800;margin:0 0 18px;white-space:nowrap}}
.big{{font-size:104px;font-weight:800;line-height:1;letter-spacing:-.02em}}
.sous{{font-size:22px;line-height:1.4;color:#aab2c0;margin-top:10px}}
.url{{margin-top:auto;font-size:26px;font-weight:700;color:#fff}}
.r{{flex:none;width:{SIL_BOX}px;display:flex;align-items:center;justify-content:center}}
</style></head><body>
<div class="l">
<div class="live"><i></i>EN DIRECT</div>
<h1>Pénurie d'essence</h1>
<div class="dept">{nom} ({code})</div>
<div class="big">{gros}</div>
<div class="sous">{sous}</div>
<div class="url">carte-penurie-essence.fr</div>
</div>
<div class="r">{svg}</div>
</body></html>'''


def main():
    deps = charger_departements()
    brut = (RACINE / "departements.js").read_text(encoding="utf-8")
    import json
    gj = json.loads(brut[brut.index("{"):].rstrip().rstrip(";"))
    features = {f["properties"]["code"]: f for f in gj["features"]}

    deps_releve, _ = dernier_releve()
    deps_releve = deps_releve or {}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        n = 0
        for code, dep in deps.items():
            s = stats(code, deps_releve)
            pct = s["pct"] if s else None
            svg = silhouette_svg(features[code], couleur(pct))
            html = page_html(dep["nom"], code, pct, s["all"] if s else 0, s["p"] if s else 0, s["t"] if s else 0, svg)
            page.set_content(html, wait_until="load")
            dossier = RACINE / "departement" / dep["slug"]
            dossier.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(dossier / "og.png"))
            n += 1
        browser.close()
    print(f"{n} images og.png générées dans departement/<slug>/", file=sys.stderr)


if __name__ == "__main__":
    main()
