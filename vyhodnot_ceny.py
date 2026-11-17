#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vyhodnotenie zaznamov zo sleduj_ceny.py (ceny_wizz.txt).

Vytvori report_ceny.html s grafmi a otvori ho v prehliadaci:
  1. vyvoj ceny tvojho planu (tam + spat) v case
  2. v ktory DEN V TYZDNI boli ceny v priemere najnizsie
  3. v ktoru HODINU dna boli ceny v priemere najnizsie
  4. tabulka vsetkych letov: aktualna / najnizsia / najvyssia cena a kedy
  5. najlacnejsie kombinacie tam + spat podla posledneho zberu

Ako sa porovnava den a hodina (aby to neskreslil rast cien k odletu):
  - den v tyzdni: cena letu oproti priemeru TOHO ISTEHO letu v TOM ISTOM tyzdni
  - hodina:       cena letu oproti priemeru TOHO ISTEHO letu v TEN ISTY den
  Zaporne % = v ten den/hodinu bolo lacnejsie nez priemer.

Spustenie:
    python vyhodnot_ceny.py               # vytvori report a otvori ho
    python vyhodnot_ceny.py --neotvarat   # len vytvori report
Nepotrebuje ziadne kniznice navyse (len standardny Python 3.8+).
"""

import argparse
import csv
import html
import math
import re
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

# --------------------------------------------------------------------------
# KONFIGURACIA
# --------------------------------------------------------------------------
PRIECINOK = Path(__file__).resolve().parent
VSTUP = PRIECINOK / "ceny_wizz.txt"
REPORT = PRIECINOK / "report_ceny.html"
TAM, SPAT = "BUD-FNC", "FNC-BUD"
MIN_NOCI, MAX_NOCI = 3, 9          # pre tabulku kombinacii
ZALOZNY_KURZ_HUF = 363.0           # ak v starych riadkoch chyba prepocet do EUR

DNI = ["Po", "Ut", "St", "Št", "Pi", "So", "Ne"]
DNI_DLHE = ["pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa"]
NAZOV_TRASY = {TAM: "Tam (Budapešť → Funchal)", SPAT: "Späť (Funchal → Budapešť)"}


# --------------------------------------------------------------------------
# FORMATOVANIE (slovensky: desatinna ciarka, medzera v tisickach)
# --------------------------------------------------------------------------
def _cislo(v, des):
    s = f"{abs(v):,.{des}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 else "") + s


def f_eur(v, des=2):
    return f"{_cislo(v, des)} €"


def f_cena(v, mena):
    return f"{_cislo(v, 0)} Ft" if mena == "HUF" else f_eur(v)


def f_pct(v):
    return ("+" if v > 0 else "") + _cislo(v, 1) + " %"


def f_cas(c):
    return f"{DNI[c.weekday()]} {c.day}.{c.month}. {c:%H:%M}"


def f_den(d):
    return f"{DNI[d.weekday()]} {d.day}.{d.month}."


def e(s):
    return html.escape(str(s))


def f_noci(n):
    return f"{n} noc" if n == 1 else f"{n} noci" if 2 <= n <= 4 else f"{n} nocí"


# --------------------------------------------------------------------------
# NACITANIE
# --------------------------------------------------------------------------
def nacitaj():
    zaz = []
    with VSTUP.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if not r.get("cena") or not r.get("datum_letu"):
                continue                      # riadky s chybou
            try:
                cas = datetime.strptime(r["cas_zberu"], "%Y-%m-%d %H:%M")
                cena = float(r["cena"])
                datum = date.fromisoformat(r["datum_letu"])
            except (ValueError, KeyError):
                continue
            mena = r.get("mena", "")
            eur = r.get("cena_eur_orientacne") or ""
            if eur:
                eur = float(eur)
            elif mena == "EUR":
                eur = cena
            elif mena == "HUF":
                m = re.search(r"kurz ([\d.]+)", r.get("poznamka") or "")
                eur = cena / (float(m.group(1)) if m else ZALOZNY_KURZ_HUF)
            else:
                eur = None
            zaz.append({"cas": cas, "trasa": r["trasa"], "datum": datum,
                        "odlet": r.get("odlet", ""), "cena": cena, "mena": mena,
                        "eur": eur, "plan": r.get("moj_plan") == "ano"})
    return zaz


# --------------------------------------------------------------------------
# ANALYZA
# --------------------------------------------------------------------------
def efekt(zaz, kluc_skupiny, kluc_kategorie):
    """Odchylka ceny (v %) od priemeru toho isteho letu v ramci skupiny
    (tyzden / den). Pouziju sa len skupiny, kde su aspon 2 rozne kategorie."""
    skup = defaultdict(list)
    for z in zaz:
        skup[(z["trasa"], z["datum"], kluc_skupiny(z["cas"]))].append(z)
    odch, pouzite = defaultdict(list), set()
    for (_, _, g), zs in skup.items():
        if len({kluc_kategorie(z["cas"]) for z in zs}) < 2:
            continue
        m = mean(z["cena"] for z in zs)
        pouzite.add(g)
        for z in zs:
            odch[kluc_kategorie(z["cas"])].append((z["cena"] / m - 1) * 100)
    return {k: (mean(v), len(v)) for k, v in odch.items()}, len(pouzite)


def analyza(zaz):
    zbery = sorted({z["cas"] for z in zaz})
    posledny = zbery[-1]
    akt = [z for z in zaz if z["cas"] == posledny]

    # plan = lety oznacene v poslednom zbere
    plan = {(z["trasa"], z["datum"]) for z in akt if z["plan"]}
    plan_hist = defaultdict(dict)                 # cas -> trasa -> zaznam
    for z in zaz:
        if (z["trasa"], z["datum"]) in plan:
            plan_hist[z["cas"]][z["trasa"]] = z
    plan_spolu = [(c, sum(v["eur"] for v in d.values()))
                  for c, d in sorted(plan_hist.items())
                  if len(d) == len(plan) and all(v["eur"] is not None for v in d.values())]

    # historia po letoch
    lety = defaultdict(list)
    for z in sorted(zaz, key=lambda x: x["cas"]):
        lety[(z["trasa"], z["datum"])].append(z)

    den, den_skup = efekt(zaz, lambda c: c.isocalendar()[:2], lambda c: c.weekday())
    hod, hod_skup = efekt(zaz, lambda c: c.date(), lambda c: c.hour)

    # kombinacie z posledneho zberu
    tam = [z for z in akt if z["trasa"] == TAM and z["eur"] is not None]
    spat = [z for z in akt if z["trasa"] == SPAT and z["eur"] is not None]
    komb = sorted(((t, s, (s["datum"] - t["datum"]).days, t["eur"] + s["eur"])
                   for t in tam for s in spat
                   if MIN_NOCI <= (s["datum"] - t["datum"]).days <= MAX_NOCI),
                  key=lambda k: k[3])

    return {"zbery": zbery, "posledny": posledny, "plan": plan, "plan_hist": plan_hist,
            "plan_spolu": plan_spolu, "lety": lety, "den": den, "den_skup": den_skup,
            "hod": hod, "hod_skup": hod_skup, "komb": komb,
            "hodiny_zberu": sorted({c.hour for c in zbery}),
            "dni_zberu": len({c.date() for c in zbery})}


# --------------------------------------------------------------------------
# SVG GRAFY
# --------------------------------------------------------------------------
def pekne_hodnoty(lo, hi, n=5):
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    surovy = (hi - lo) / n
    rad = 10 ** math.floor(math.log10(surovy))
    krok = next(m * rad for m in (1, 2, 2.5, 5, 10) if m * rad >= surovy)
    v, out = math.floor(lo / krok) * krok, []
    while v <= math.ceil(hi / krok) * krok + krok * 1e-9:
        out.append(round(v, 10))
        v += krok
    return out


def graf_ciary(serie, sirka=760, vyska=280):
    """serie: [{nazov, farba (CSS premenna), body: [(datetime, hodnota_eur, popis)]}]"""
    L, R, T, B = 64, 120, 14, 30
    body = [b for s in serie for b in s["body"]]
    if not body:
        return '<p class="malo">Zatiaľ žiadne dáta.</p>'
    xs = [b[0].timestamp() for b in body]
    x0, x1 = min(xs), max(xs)
    if x1 == x0:
        x0, x1 = x0 - 43200, x1 + 43200
    tick = pekne_hodnoty(min(b[1] for b in body), max(b[1] for b in body))
    y0, y1 = tick[0], tick[-1]
    W, H = sirka - L - R, vyska - T - B

    def X(c):
        return L + (c.timestamp() - x0) / (x1 - x0) * W

    def Y(v):
        return T + H - (v - y0) / (y1 - y0) * H

    o = [f'<svg viewBox="0 0 {sirka} {vyska}" role="img" class="graf">']
    for v in tick:                                        # mriezka + os Y
        o.append(f'<line x1="{L}" x2="{L + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="mriezka"/>')
        o.append(f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" class="os" text-anchor="end">{e(f_eur(v, 0))}</text>')
    d_od = datetime.fromtimestamp(x0).date()
    d_do = datetime.fromtimestamp(x1).date()
    pocet = (d_do - d_od).days + 1
    krok = max(1, math.ceil(pocet / 7))                    # os X: max ~7 popisov
    d = d_od
    while d <= d_do:
        c = datetime.combine(d, datetime.min.time()) + timedelta(hours=12)
        if x0 <= c.timestamp() <= x1:
            o.append(f'<text x="{X(c):.1f}" y="{T + H + 20}" class="os" text-anchor="middle">{d.day}.{d.month}.</text>')
        d += timedelta(days=krok)
    o.append(f'<line x1="{L}" x2="{L + W}" y1="{T + H}" y2="{T + H}" class="zaklad"/>')

    konce = []
    for s in serie:
        if not s["body"]:
            continue
        p = " ".join(f"{X(c):.1f},{Y(v):.1f}" for c, v, _ in s["body"])
        o.append(f'<polyline points="{p}" fill="none" stroke="var({s["farba"]})" '
                 f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        husto = len(s["body"]) > 40          # vela zberov: bodky len na hover
        for i, (c, v, popis) in enumerate(s["body"]):
            viditelny = not husto or i == len(s["body"]) - 1
            o.append(f'<g class="bod{" skryty" if not viditelny else ""}">'
                     f'<title>{e(s["nazov"])} · zber {e(f_cas(c))} · {e(popis)}</title>'
                     f'<circle cx="{X(c):.1f}" cy="{Y(v):.1f}" r="10" fill="transparent"/>'
                     f'<circle cx="{X(c):.1f}" cy="{Y(v):.1f}" r="4" fill="var({s["farba"]})" '
                     f'stroke="var(--surface)" stroke-width="2"/></g>')
        c, v, _ = s["body"][-1]
        konce.append((Y(v), X(c), s["nazov"], v))
    konce.sort()                                          # koncove popisy, ak sa neprekryvaju
    if all(b[0] - a[0] >= 30 for a, b in zip(konce, konce[1:])):
        for y, x, n, v in konce:
            o.append(f'<text x="{x + 10:.1f}" y="{y - 2:.1f}" class="popis">{e(n)}</text>'
                     f'<text x="{x + 10:.1f}" y="{y + 13:.1f}" class="hodnota">{e(f_eur(v))}</text>')
    o.append("</svg>")
    leg = "".join(f'<span class="leg"><i style="background:var({s["farba"]})"></i>{e(s["nazov"])}</span>'
                  for s in serie)
    return (f'<div class="legenda">{leg}</div>' if len(serie) > 1 else "") + "".join(o)


def graf_stlpce(kategorie, sirka=760, vyska=240):
    """kategorie: [(popis, odchylka_% alebo None, pocet)] - zaporne = lacnejsie."""
    L, R, T, B = 56, 12, 26, 44
    hodn = [k[1] for k in kategorie if k[1] is not None]
    if not hodn:
        return '<p class="malo">Zatiaľ málo dát.</p>'
    m = max(1.0, max(abs(v) for v in hodn)) * 1.15
    tick = pekne_hodnoty(-m, m, 6)
    y0, y1 = tick[0], tick[-1]
    W, H = sirka - L - R, vyska - T - B

    def Y(v):
        return T + H - (v - y0) / (y1 - y0) * H

    o = [f'<svg viewBox="0 0 {sirka} {vyska}" role="img" class="graf">']
    for v in tick:
        o.append(f'<line x1="{L}" x2="{L + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="mriezka"/>')
        o.append(f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" class="os" text-anchor="end">{e(f_pct(v) if v else "0 %")}</text>')
    pas = W / len(kategorie)
    sir = min(24, pas * 0.6)
    y_nula = Y(0)
    najlep = min(hodn)
    for i, (popis, v, n) in enumerate(kategorie):
        cx = L + pas * (i + 0.5)
        x = cx - sir / 2
        o.append(f'<text x="{cx:.1f}" y="{T + H + 18}" class="os2" text-anchor="middle">{e(popis)}</text>')
        o.append(f'<text x="{cx:.1f}" y="{T + H + 33}" class="os" text-anchor="middle">'
                 f'{"n=" + str(n) if v is not None else "bez dát"}</text>')
        if v is None:
            continue
        y = Y(v)
        h = abs(y - y_nula)
        r = min(4, h)
        if v <= 0:      # dole od nuly, zaobleny dolny koniec
            d = (f"M{x:.1f},{y_nula:.1f} L{x:.1f},{y - r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                 f"L{x + sir - r:.1f},{y:.1f} Q{x + sir:.1f},{y:.1f} {x + sir:.1f},{y - r:.1f} "
                 f"L{x + sir:.1f},{y_nula:.1f} Z")
            ty = y + 15
        else:           # hore od nuly, zaobleny horny koniec
            d = (f"M{x:.1f},{y_nula:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                 f"L{x + sir - r:.1f},{y:.1f} Q{x + sir:.1f},{y:.1f} {x + sir:.1f},{y + r:.1f} "
                 f"L{x + sir:.1f},{y_nula:.1f} Z")
            ty = y - 6
        farba = "--lacnejsie" if v <= 0 else "--drahsie"
        trieda = "hodnota" if v == najlep else "popis"
        o.append(f'<g class="bod"><title>{e(popis)}: {e(f_pct(v))} oproti priemeru · {n} pozorovaní</title>'
                 f'<rect x="{cx - pas / 2:.1f}" y="{T}" width="{pas:.1f}" height="{H}" fill="transparent"/>'
                 f'<path d="{d}" fill="var({farba})"/></g>'
                 f'<text x="{cx:.1f}" y="{ty:.1f}" class="{trieda}" text-anchor="middle">{e(f_pct(v))}</text>')
    o.append(f'<line x1="{L}" x2="{L + W}" y1="{y_nula:.1f}" y2="{y_nula:.1f}" class="zaklad"/>')
    o.append("</svg>")
    leg = ('<div class="legenda"><span class="leg"><i style="background:var(--lacnejsie)"></i>lacnejšie než priemer</span>'
           '<span class="leg"><i style="background:var(--drahsie)"></i>drahšie než priemer</span></div>')
    return leg + "".join(o)


def sparkline(zs, sirka=120, vyska=28):
    v = [z["cena"] for z in zs]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    hi = hi if hi > lo else lo + 1
    n = len(v) - 1
    pts = [(2 + i / n * (sirka - 8), 4 + (hi - x) / (hi - lo) * (vyska - 8)) for i, x in enumerate(v)]
    p = " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
    a, b = pts[-1]
    return (f'<svg viewBox="0 0 {sirka} {vyska}" width="{sirka}" height="{vyska}" class="spark">'
            f'<polyline points="{p}" fill="none" stroke="var(--s1)" stroke-width="1.5" stroke-linejoin="round"/>'
            f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3" fill="var(--s1)"/></svg>')


# --------------------------------------------------------------------------
# REPORT
# --------------------------------------------------------------------------
CSS = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--lacnejsie:#2a78d6;--drahsie:#e34948}
@media (prefers-color-scheme:dark){.viz-root{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;
 --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--lacnejsie:#3987e5;--drahsie:#e66767}}
*{box-sizing:border-box}
body{margin:0}
.viz-root{background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:32px 20px 60px;min-height:100vh}
main{max-width:860px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:18px;margin:0 0 4px}
.sub{color:var(--ink2);margin:0 0 24px}
.karta{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px 22px;margin:0 0 20px}
.vysvetl{color:var(--ink2);font-size:14px;margin:0 0 12px}
.dlazdice{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 20px}
.dlazdica{flex:1 1 180px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.dlazdica .l{color:var(--ink2);font-size:13px}
.dlazdica .v{font-size:28px;font-weight:600;margin:2px 0}
.dlazdica .d{color:var(--muted);font-size:13px}
.zaver{margin:0;padding-left:20px}
.zaver li{margin:0 0 6px}
.graf{width:100%;height:auto;display:block}
.graf text{font-family:inherit}
.mriezka{stroke:var(--grid);stroke-width:1}
.zaklad{stroke:var(--axis);stroke-width:1}
.os{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.os2{fill:var(--ink2);font-size:13px}
.popis{fill:var(--ink2);font-size:12px}
.hodnota{fill:var(--ink);font-size:13px;font-weight:600}
.bod:hover circle:last-child{r:6}
.bod.skryty circle:last-child{opacity:0}
.bod.skryty:hover circle:last-child{opacity:1}
.bod:hover path{opacity:.8}
.legenda{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 8px;font-size:13px;color:var(--ink2)}
.leg i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
.malo{color:var(--muted);font-style:italic;margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:var(--ink2);font-weight:500;border-bottom:1px solid var(--axis);padding:6px 8px}
td{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:middle}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.plan td{font-weight:600}
.znacka{display:inline-block;font-size:11px;font-weight:600;border:1px solid var(--axis);border-radius:4px;padding:0 5px;margin-left:6px;color:var(--ink2)}
.spark{display:block}
"""


def vytvor_report(a):
    o = []
    posl = a["posledny"]
    o.append(f'<h1>Ceny leteniek Wizz Air Budapešť ⇄ Funchal</h1>'
             f'<p class="sub">{len(a["zbery"])} zberov od {e(f_cas(a["zbery"][0]))} do {e(f_cas(posl))} · '
             f'ceny pre 1 osobu bez batožiny · eurá pri forintoch sú orientačné podľa kurzu</p>')

    # ---- plan: dlazdice + graf
    zaver = []
    if a["plan_spolu"]:
        teraz = a["plan_spolu"][-1][1]
        prvy = a["plan_spolu"][0][1]
        cmin, vmin = min(a["plan_spolu"], key=lambda x: x[1])
        plan_lety = sorted(a["plan"], key=lambda k: k[1])
        popis_planu = " + ".join(f"{'tam' if t == TAM else 'späť'} {f_den(d)}" for t, d in plan_lety)
        o.append('<div class="dlazdice">'
                 f'<div class="dlazdica"><div class="l">Tvoj plán teraz</div><div class="v">{e(f_eur(teraz, 0))}</div>'
                 f'<div class="d">{e(popis_planu)}</div></div>'
                 f'<div class="dlazdica"><div class="l">Najlacnejšie doteraz</div><div class="v">{e(f_eur(vmin, 0))}</div>'
                 f'<div class="d">zber {e(f_cas(cmin))}</div></div>'
                 f'<div class="dlazdica"><div class="l">Zmena od prvého zberu</div><div class="v">{e(f_pct((teraz / prvy - 1) * 100))}</div>'
                 f'<div class="d">z {e(f_eur(prvy, 0))}</div></div></div>')
        if teraz <= vmin + 0.005:
            zaver.append(f"Tvoj plán je teraz na najnižšej zaznamenanej cene ({f_eur(teraz)}).")
        else:
            zaver.append(f"Tvoj plán stojí teraz {f_eur(teraz)}, najlacnejší bol {f_eur(vmin)} ({f_cas(cmin)}).")
        serie = []
        for trasa, farba in ((TAM, "--s1"), (SPAT, "--s2")):
            body = [(c, d[trasa]["eur"], f_cena(d[trasa]["cena"], d[trasa]["mena"]))
                    for c, d in sorted(a["plan_hist"].items())
                    if trasa in d and d[trasa]["eur"] is not None]
            if body:
                serie.append({"nazov": "Tam" if trasa == TAM else "Späť", "farba": farba, "body": body})
        o.append('<section class="karta"><h2>Vývoj ceny tvojho plánu</h2>'
                 '<p class="vysvetl">Každý bod je jeden zber. Forintová cena letu tam je prepočítaná na eurá, '
                 'presnú cenu v Ft ukáže bod po prejdení myšou.</p>' + graf_ciary(serie) + "</section>")
    else:
        o.append('<section class="karta"><h2>Tvoj plán</h2><p class="malo">V poslednom zbere nie je označený '
                 'žiadny let plánu (stĺpec moj_plan).</p></section>')

    # ---- den v tyzdni
    kat = [(DNI_DLHE[i], *(a["den"][i] if i in a["den"] else (None, 0))) for i in range(7)]
    if not a["den"]:
        pozn = "Zatiaľ málo dát: treba zbery aspoň v dvoch rôznych dňoch toho istého týždňa."
    elif a["den_skup"] < 3:
        pozn = (f"Orientačné: dáta zatiaľ len z {a['den_skup']} "
                f"{'týždňa' if a['den_skup'] == 1 else 'týždňov'}, spoľahlivejšie to bude po 3 až 4 týždňoch zberu.")
    else:
        pozn = ""
    o.append('<section class="karta"><h2>V ktorý deň v týždni kupovať</h2>'
             '<p class="vysvetl">Cena každého letu oproti jeho priemeru v tom istom týždni. '
             'Záporné číslo znamená, že v ten deň bolo v priemere lacnejšie.</p>'
             + (f'<p class="malo">{e(pozn)}</p>' if pozn else "")
             + (graf_stlpce(kat) if a["den"] else "") + "</section>")
    if a["den"]:
        k, (v, n) = min(a["den"].items(), key=lambda x: x[1][0])
        zaver.append(f"Deň v týždni: najlacnejšie v priemere {DNI_DLHE[k]} ({f_pct(v)}, {n} pozorovaní)"
                     + (" - zatiaľ len orientačne." if pozn else "."))

    # ---- hodina
    kat = [(f"{h:02d}:00", *a["hod"][h]) for h in sorted(a["hod"])]
    if len(a["hodiny_zberu"]) < 2:
        pozn = ("Zatiaľ málo dát: zbery bežia len o " + ", ".join(f"{h:02d}:00" for h in a["hodiny_zberu"])
                + ". Na porovnanie hodín treba spúšťať skript vo viacerých časoch dňa.")
    elif not a["hod"]:
        pozn = "Zatiaľ málo dát: treba aspoň jeden deň so zbermi vo viacerých hodinách."
    elif a["hod_skup"] < 5:
        pozn = (f"Orientačné: zatiaľ len {a['hod_skup']} "
                f"{'deň' if a['hod_skup'] == 1 else 'dni'} so zbermi vo viacerých hodinách.")
    else:
        pozn = ""
    o.append('<section class="karta"><h2>V ktorú hodinu kupovať</h2>'
             '<p class="vysvetl">Cena každého letu oproti jeho priemeru v ten istý deň. '
             'Záporné číslo znamená, že v tú hodinu bolo v priemere lacnejšie.</p>'
             + (f'<p class="malo">{e(pozn)}</p>' if pozn else "")
             + (graf_stlpce(kat) if kat else "") + "</section>")
    if a["hod"]:
        k, (v, n) = min(a["hod"].items(), key=lambda x: x[1][0])
        zaver.append(f"Hodina: najlacnejšie v priemere okolo {k:02d}:00 ({f_pct(v)}, {n} pozorovaní)"
                     + (" - zatiaľ len orientačne." if pozn else "."))

    # ---- kombinacie
    if a["komb"]:
        t, s, noci, spolu = a["komb"][0]
        zaver.append(f"Najlacnejšia kombinácia teraz: tam {f_den(t['datum'])}, späť {f_den(s['datum'])} "
                     f"({f_noci(noci)}) za ~{f_eur(spolu)}.")
        riadky = "".join(
            f'<tr class="{"plan" if (TAM, t["datum"]) in a["plan"] and (SPAT, s["datum"]) in a["plan"] else ""}">'
            f'<td>{e(f_den(t["datum"]))} {e(t["odlet"])}</td><td>{e(f_den(s["datum"]))} {e(s["odlet"])}</td>'
            f'<td class="n">{noci}</td><td class="n">{e(f_cena(t["cena"], t["mena"]))}</td>'
            f'<td class="n">{e(f_cena(s["cena"], s["mena"]))}</td><td class="n">~{e(f_eur(spolu))}'
            f'{"<span class=znacka>PLÁN</span>" if (TAM, t["datum"]) in a["plan"] and (SPAT, s["datum"]) in a["plan"] else ""}</td></tr>'
            for t, s, noci, spolu in a["komb"][:12])
        o.append(f'<section class="karta"><h2>Najlacnejšie kombinácie teraz</h2>'
                 f'<p class="vysvetl">Podľa posledného zberu ({e(f_cas(posl))}), {MIN_NOCI} až {MAX_NOCI} nocí. '
                 f'Návrat prilieta do Budapešti po polnoci.</p><table><thead><tr><th>Tam</th><th>Späť</th>'
                 f'<th class="n">Nocí</th><th class="n">Cena tam</th><th class="n">Cena späť</th>'
                 f'<th class="n">Spolu</th></tr></thead><tbody>{riadky}</tbody></table></section>')

    # ---- vsetky lety
    for trasa in (TAM, SPAT):
        riadky = []
        for (tr, d), zs in sorted(a["lety"].items()):
            if tr != trasa:
                continue
            posledna = zs[-1]
            zmin = min(zs, key=lambda z: z["cena"])
            zmax = max(zs, key=lambda z: z["cena"])
            stara = "" if posledna["cas"] == posl else " (už nie je v ponuke)"
            jeplan = (tr, d) in a["plan"]
            riadky.append(
                f'<tr class="{"plan" if jeplan else ""}"><td>{e(f_den(d))} {e(posledna["odlet"])}'
                f'{"<span class=znacka>PLÁN</span>" if jeplan else ""}{e(stara)}</td>'
                f'<td class="n">{e(f_cena(posledna["cena"], posledna["mena"]))}</td>'
                f'<td class="n">{e(f_cena(zmin["cena"], zmin["mena"]))}<br><span class="os">{e(f_cas(zmin["cas"]))}</span></td>'
                f'<td class="n">{e(f_cena(zmax["cena"], zmax["mena"]))}</td>'
                f'<td>{sparkline(zs)}</td></tr>')
        if riadky:
            o.append(f'<section class="karta"><h2>{e(NAZOV_TRASY.get(trasa, trasa))}</h2>'
                     f'<table><thead><tr><th>Let</th><th class="n">Teraz</th><th class="n">Najlacnejšie (kedy)</th>'
                     f'<th class="n">Najdrahšie</th><th>Vývoj</th></tr></thead><tbody>{"".join(riadky)}</tbody></table></section>')

    zaver_html = ('<section class="karta"><h2>Zhrnutie</h2><ul class="zaver">'
                  + "".join(f"<li>{e(z)}</li>" for z in zaver) + "</ul></section>")
    # zhrnutie ide hned pod dlazdice planu
    i = 2 if a["plan_spolu"] else 1
    o.insert(i, zaver_html)

    stranka = (f'<!DOCTYPE html><html lang="sk"><head><meta charset="utf-8">'
               f'<meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<title>Ceny leteniek Wizz Air</title><style>{CSS}</style></head>'
               f'<body><div class="viz-root"><main>{"".join(o)}</main></div></body></html>')
    REPORT.write_text(stranka, encoding="utf-8")
    return zaver


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--neotvarat", action="store_true", help="report len vytvor, neotvaraj")
    args = ap.parse_args()
    if not VSTUP.exists():
        print(f"Subor {VSTUP} neexistuje - najprv spusti sleduj_ceny.py")
        return 1
    zaz = nacitaj()
    if not zaz:
        print("V subore zatial nie su ziadne ceny.")
        return 1
    a = analyza(zaz)
    zaver = vytvor_report(a)
    dn = a["dni_zberu"]
    print(f"Zberov: {len(a['zbery'])} ({dn} {'deň' if dn == 1 else 'dni' if dn < 5 else 'dní'}), hodiny zberu: "
          + ", ".join(f"{h:02d}:00" for h in a["hodiny_zberu"]))
    for z in zaver:
        print(" - " + z)
    print(f"\nReport: {REPORT}")
    if not args.neotvarat:
        webbrowser.open(REPORT.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())