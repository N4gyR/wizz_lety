#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sledovanie cien Wizz Air Budapest <-> Funchal (Madeira), marec 2027.

Ceny sa citaju priamo z wizzair.com (rovnake API, z ktoreho web kresli cenovy
kalendar). Kazda trasa sa pyta zvlast, takze cena je vzdy v DOMACEJ mene letu:
  BUD -> FNC v HUF (forinty)   -> tak aj platit
  FNC -> BUD v EUR             -> tak aj platit
Pre porovnanie sa prida aj orientacna cena v EUR podla denneho kurzu ECB.

Kazde spustenie pripise riadky do ceny_wizz.txt (oddelovac ;, otvoris aj v Exceli).

Spustenie:
    python sleduj_ceny.py              # stiahne ceny a zapise ich
    python sleduj_ceny.py --vyhodnot   # vyhodnoti doterajsie zaznamy
Nepotrebuje ziadne kniznice navyse (len standardny Python 3.8+).
"""

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# --------------------------------------------------------------------------
# KONFIGURACIA
# --------------------------------------------------------------------------
OD = "2027-03-01"        # sledovane obdobie (vratane)
DO = "2027-03-14"
TRASY = [("BUD", "FNC"), ("FNC", "BUD")]

# Tvoj plan: tieto dva lety sa v subore oznacia a scitaju
PLAN = {("BUD", "FNC"): "2027-03-05",   # tam:  piatok
        ("FNC", "BUD"): "2027-03-10"}   # spat: streda

VYSTUP = Path(__file__).resolve().parent / "ceny_wizz.txt"
ZALOZNA_VERZIA_API = "29.25.0"   # pouzije sa, ak sa verziu nepodari zistit z webu
# Ak nie je dostupny ziadny online kurz, prepocita sa tymto (Ft za 1 EUR).
# Obcas ho uprav podla aktualneho kurzu.
ZALOZNY_KURZ_HUF = 363.0

HLAVICKA = ["cas_zberu", "trasa", "datum_letu", "den", "odlet", "cena", "mena",
            "cena_eur_orientacne", "moj_plan", "poznamka"]
DNI = ["Po", "Ut", "St", "Št", "Pi", "So", "Ne"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HLAVICKY = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-GB,en;q=0.9",
            "Origin": "https://www.wizzair.com",
            "Referer": "https://www.wizzair.com/en-gb"}


# --------------------------------------------------------------------------
# WIZZ AIR
# --------------------------------------------------------------------------
def _http(url, data=None, timeout=30):
    hdr = dict(HLAVICKY)
    if data is not None:
        hdr["Content-Type"] = "application/json"
        data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def verzia_api():
    """Wizz meni verziu API v adrese (napr. 29.25.0); je zapisana v HTML webu."""
    try:
        html = _http("https://www.wizzair.com/en-gb")
        m = re.search(r"be\.wizzair\.com/(\d+\.\d+\.\d+)/Api", html)
        if m:
            return m.group(1)
    except Exception as e:  # noqa: BLE001
        print(f"  (verziu API sa nepodarilo zistit: {e}; skusam {ZALOZNA_VERZIA_API})")
    return ZALOZNA_VERZIA_API


def timetable_http(verzia, z, do):
    body = {"flightList": [{"departureStation": z, "arrivalStation": do,
                            "from": OD, "to": DO}],
            "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
    url = f"https://be.wizzair.com/{verzia}/Api/search/timetable"
    return json.loads(_http(url, body))


def timetable_prehliadac(verzia, trasy):
    """Zaloha, ak Wizz zablokuje priame volanie: rovnaky dotaz z ozajstneho
    prehliadaca (treba: pip install playwright && playwright install chromium)."""
    from playwright.sync_api import sync_playwright
    vysl = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(user_agent=UA, locale="en-GB")
        page.goto("https://www.wizzair.com/en-gb", wait_until="domcontentloaded", timeout=60000)
        for z, do in trasy:
            body = {"flightList": [{"departureStation": z, "arrivalStation": do,
                                    "from": OD, "to": DO}],
                    "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
            vysl[(z, do)] = page.evaluate(
                """async ([url, body]) => {
                     const r = await fetch(url, {method: 'POST',
                       headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
                     if (!r.ok) throw new Error('HTTP ' + r.status);
                     return await r.json();
                   }""",
                [f"https://be.wizzair.com/{verzia}/Api/search/timetable", body])
        b.close()
    return vysl


def stiahni_ceny():
    verzia = verzia_api()
    data, chyby = {}, {}
    for z, do in TRASY:
        try:
            data[(z, do)] = timetable_http(verzia, z, do)
        except Exception as e:  # noqa: BLE001
            chyby[(z, do)] = f"{type(e).__name__}: {e}"
    if chyby:
        try:
            data.update(timetable_prehliadac(verzia, list(chyby)))
            chyby = {k: v for k, v in chyby.items() if k not in data}
        except ImportError:
            for k in chyby:
                chyby[k] += (" | zaloha cez prehliadac nie je nainstalovana: "
                             "pip install playwright && playwright install chromium")
        except Exception as e:  # noqa: BLE001
            for k in chyby:
                chyby[k] += f" | prehliadac: {type(e).__name__}: {e}"
    return data, chyby


# --------------------------------------------------------------------------
# KURZ ECB (len orientacny prepocet do EUR)
# --------------------------------------------------------------------------
def kurz_huf():
    """Vrati (Ft za 1 EUR, zdroj). Skusa ECB, potom Frankfurter (tiez data ECB,
    iny server - pomoze pri chybe SSL certifikatu), nakoniec zalozny kurz."""
    zdroje = [
        ("ECB", "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
         lambda t: float(re.search(r"currency='HUF' rate='([\d.]+)'", t).group(1))),
        ("Frankfurter/ECB", "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=HUF",
         lambda t: float(json.loads(t)["rates"]["HUF"])),
        ("Frankfurter/ECB", "https://api.frankfurter.app/latest?from=EUR&to=HUF",
         lambda t: float(json.loads(t)["rates"]["HUF"])),
    ]
    chyby = []
    for nazov, url, parse in zdroje:
        try:
            return parse(_http(url, timeout=15)), nazov
        except Exception as e:  # noqa: BLE001
            chyby.append(f"{nazov}: {type(e).__name__}")
    print(f"  (online kurz nedostupny - {', '.join(chyby)}; "
          f"pouzivam zalozny kurz {ZALOZNY_KURZ_HUF})")
    return ZALOZNY_KURZ_HUF, "zalozny kurz zo skriptu"


def kurzy_ecb():
    k, zdroj = kurz_huf()
    return {"HUF": k, "_zdroj": zdroj}


def na_eur(suma, mena, kurzy):
    if mena == "EUR":
        return suma
    if mena in kurzy:
        return suma / kurzy[mena]
    return None


# --------------------------------------------------------------------------
# ZBER
# --------------------------------------------------------------------------
def zber():
    teraz = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"=== Zber cien Wizz Air: {teraz} ===")
    data, chyby = stiahni_ceny()
    kurzy = kurzy_ecb()
    print(f"Kurz: 1 EUR = {kurzy['HUF']:.2f} Ft ({kurzy['_zdroj']})\n")
    kurz_pozn = f"kurz {kurzy['HUF']:.2f} Ft/EUR ({kurzy['_zdroj']})"
    riadky, plan_eur, plan_ok = [], 0.0, True

    for z, do in TRASY:
        trasa = f"{z}-{do}"
        if (z, do) in chyby:
            riadky.append([teraz, trasa, "", "", "", "", "", "", "", "CHYBA " + chyby[(z, do)]])
            plan_ok = False
            continue
        lety = data[(z, do)].get("outboundFlights") or []
        if not lety:
            riadky.append([teraz, trasa, "", "", "", "", "", "", "",
                           "ziadne lety v obdobi (este nie su v predaji?)"])
        for f in sorted(lety, key=lambda x: x["departureDate"]):
            d = f["departureDate"][:10]
            odlet = ",".join(t[11:16] for t in f.get("departureDates") or [])
            cena, mena = f["price"]["amount"], f["price"]["currencyCode"]
            pozn = "" if f.get("priceType") == "price" else f"typ ceny: {f.get('priceType')}"
            if not cena:
                cena, pozn = None, (pozn or "bez ceny (vypredane?)")
            eur = na_eur(cena, mena, kurzy) if cena else None
            if eur is not None and mena != "EUR":
                pozn = "; ".join(x for x in (pozn, kurz_pozn) if x)
            moj = PLAN.get((z, do)) == d
            if moj:
                if eur is None:
                    plan_ok = False
                else:
                    plan_eur += eur
            riadky.append([teraz, trasa, d, DNI[date.fromisoformat(d).weekday()], odlet,
                           f"{cena:.2f}" if cena else "", mena,
                           f"{eur:.2f}" if eur is not None else "",
                           "ano" if moj else "", pozn])
        # plan existuje, ale v ten den let nie je
        if PLAN.get((z, do)) and not any(r[1] == trasa and r[8] == "ano" for r in riadky):
            plan_ok = False
            print(f"  POZOR: na {PLAN[(z, do)]} nie je let {trasa}")

    novy = not VYSTUP.exists()
    with VYSTUP.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if novy:
            w.writerow(HLAVICKA)
        w.writerows(riadky)

    for r in riadky:
        cena = f"{float(r[5]):>10,.2f} {r[6]}".replace(",", " ") if r[5] else " " * 14
        eur = f"~{float(r[7]):7.2f} EUR" if r[7] else ""
        pozn = r[9].replace(kurz_pozn, "").strip("; ")
        print(f"{r[1]}  {r[2]} {r[3]:<2} {r[4]:<5} {cena}  {eur:<12} {'<- PLAN' if r[8] else ''} {pozn}")
    if plan_ok:
        print(f"\nTvoj plan spolu (tam + spat): ~{plan_eur:.2f} EUR na osobu")
    print(f"Zapisane do {VYSTUP}")
    return 0 if not chyby else 1


# --------------------------------------------------------------------------
# VYHODNOTENIE
# --------------------------------------------------------------------------
def vyhodnot():
    if not VYSTUP.exists():
        print("Este nie su ziadne zaznamy.")
        return 1
    hist = defaultdict(list)   # (trasa, datum) -> [(cas, cena, mena, eur, plan)]
    with VYSTUP.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["cena"]:
                hist[(r["trasa"], r["datum_letu"])].append(
                    (r["cas_zberu"], float(r["cena"]), r["mena"],
                     float(r["cena_eur_orientacne"]) if r["cena_eur_orientacne"] else None,
                     r["moj_plan"] == "ano"))
    print(f"{'trasa':<8} {'datum':<11}{'den':<4}{'teraz':>12}{'min':>12}{'max':>12}"
          f"  {'zmien':>5}  najlacnejsie dna")
    for (trasa, d), zaz in sorted(hist.items()):
        mena = zaz[-1][2]
        ceny = [c for _, c, _, _, _ in zaz]
        kedy_min = min(zaz, key=lambda x: x[1])[0]
        zmeny = sum(1 for a, b in zip(ceny, ceny[1:]) if a != b)
        oznac = "  <- PLAN" if zaz[-1][4] else ""
        fmt = ",.0f" if mena == "HUF" else ",.2f"
        print(f"{trasa:<8} {d:<11}{DNI[date.fromisoformat(d).weekday()]:<4}"
              f"{ceny[-1]:>12{fmt}}{min(ceny):>12{fmt}}{max(ceny):>12{fmt}}  {zmeny:>5}  "
              f"{kedy_min} ({mena}){oznac}".replace(",", " "))
    print(f"\nPocet zberov: {len({z[0] for v in hist.values() for z in v})}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vyhodnot", action="store_true", help="vyhodnot doterajsie zaznamy")
    sys.exit(vyhodnot() if ap.parse_args().vyhodnot else zber())
