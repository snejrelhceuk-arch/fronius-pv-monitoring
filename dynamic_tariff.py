"""Gesamtkosten-Modell einer kWh für den dynamischen Börsentarif (Tibber-Schiene).

Cross-Role-Hilfsmodul (wie solar_geometry.py): wird vom Collector (Rolle A,
Spot-Erfassung/Aggregation) UND der Web-/Analyse-Schicht (Rolle B) genutzt.
Enthält KEINEN Hardware- oder DB-Schreibzugriff — reine Rechenlogik auf Basis
der in config.DYN_TARIF gepflegten Komponenten.

Formel:
    Gesamt_brutto(ct/kWh) = (Börsenpreis_ct + Σ feste_netto_adder_ct) × (1 + MwSt.)

Der Börsenpreis (EPEX Day-Ahead DE-LU, 15-min) ist der einzige variable Anteil;
alle übrigen Komponenten (Netzentgelt, Umlagen, Steuern, Anbieteraufschlag) sind
feste Adder pro kWh. Fixkosten (Grundgebühren, Messstellenbetrieb) sind NICHT pro
kWh und werden separat über dyn_fixkosten_eur_monat() bereitgestellt.
"""
from __future__ import annotations

import config


def _cfg() -> dict:
    return config.DYN_TARIF


def mwst_faktor() -> float:
    return 1.0 + _cfg()['mwst_pct'] / 100.0


# --- Komponenten pro kWh (netto, ct) ---------------------------------------
# Reihenfolge = Darstellungsreihenfolge in der Analyse-Aufschlüsselung.
NETTO_ADDER_KEYS = [
    ('netzentgelt_ap_ct',    'Netzentgelt (MITNETZ, Arbeitspreis)'),
    ('konzessionsabgabe_ct', 'Konzessionsabgabe'),
    ('kwkg_umlage_ct',       'KWKG-Umlage'),
    ('offshore_umlage_ct',   'Offshore-Netzumlage'),
    ('paragraf19_umlage_ct', 'Aufschlag § 19 StromNEV'),
    ('stromsteuer_ct',       'Stromsteuer'),
    ('anbieter_aufschlag_ct','Anbieteraufschlag (Tibber)'),
]


def netto_adder_ct() -> float:
    """Summe der festen Netto-Adder pro kWh (ct/kWh), ohne Börsenpreis/MwSt."""
    c = _cfg()
    return round(sum(c[k] for k, _ in NETTO_ADDER_KEYS), 4)


def spot_eur_mwh_to_ct_kwh(eur_mwh: float) -> float:
    """EPEX-Preis (EUR/MWh) → ct/kWh (netto). 1 EUR/MWh = 0,1 ct/kWh."""
    return eur_mwh / 10.0


def total_price_ct(spot_ct: float) -> float:
    """Gesamtkosten einer kWh (brutto ct/kWh) bei gegebenem Börsenpreis (netto ct/kWh)."""
    return round((spot_ct + netto_adder_ct()) * mwst_faktor(), 4)


def total_price_from_eur_mwh(eur_mwh: float) -> float:
    """Komfort: EPEX EUR/MWh → Gesamtpreis brutto ct/kWh."""
    return total_price_ct(spot_eur_mwh_to_ct_kwh(eur_mwh))


def components_breakdown_ct(spot_ct: float) -> list[dict]:
    """Aufschlüsselung der Gesamtkosten in Komponenten (Rechnungslogik).

    Jede Zeile führt ihren Netto-Beitrag (ct/kWh); die letzte Zeile ist die MwSt
    auf die Netto-Summe. Die Summe aller 'ct' ergibt exakt total_price_ct(spot_ct).
    """
    c = _cfg()
    rows = [{'key': 'boerse', 'label': 'Börsenpreis (EPEX Day-Ahead)',
             'ct': round(spot_ct, 4)}]
    for k, label in NETTO_ADDER_KEYS:
        rows.append({'key': k, 'label': label, 'ct': round(c[k], 4)})
    netto_sum = spot_ct + netto_adder_ct()
    rows.append({'key': 'mwst', 'label': f"Mehrwertsteuer ({c['mwst_pct']:.0f} %)",
                 'ct': round(netto_sum * (mwst_faktor() - 1.0), 4)})
    return rows


# --- Fixkosten (nicht pro kWh) ---------------------------------------------
def dyn_fixkosten_eur_monat() -> float:
    """Feste Monatskosten der dynamischen Schiene (brutto EUR/Monat):
    Anbieter-Grundgebühr + Netz-Grundpreis/12 + Messstellenbetrieb/12."""
    c = _cfg()
    f = mwst_faktor()
    netz = c['netz_grundpreis_eur_jahr'] * (f if c.get('netz_grundpreis_netto') else 1.0)
    msb = c['messstellenbetrieb_eur_jahr']
    return round(c['anbieter_grundgebuehr_eur_monat'] + (netz + msb) / 12.0, 4)


def dyn_fixkosten_breakdown_eur_monat() -> list[dict]:
    c = _cfg()
    f = mwst_faktor()
    netz = c['netz_grundpreis_eur_jahr'] * (f if c.get('netz_grundpreis_netto') else 1.0)
    return [
        {'key': 'anbieter', 'label': 'Anbieter-Grundgebühr (Tibber)',
         'eur_monat': round(c['anbieter_grundgebuehr_eur_monat'], 4)},
        {'key': 'netz', 'label': 'Netz-Grundpreis (MITNETZ)',
         'eur_monat': round(netz / 12.0, 4)},
        {'key': 'msb', 'label': 'Messstellenbetrieb (iMSys)',
         'eur_monat': round(c['messstellenbetrieb_eur_jahr'] / 12.0, 4)},
    ]


# --- Fixtarif-Referenz (bestehender Vertrag) -------------------------------
def fixtarif_ct(year: int, month: int, day: int) -> float:
    """Tagesgenauer Fixtarif-Preis (brutto ct/kWh) aus config.STROMTARIFE."""
    date_tuple = (year, month, day)
    price = config.STROMTARIFE[0][1]
    for valid_from, p in config.STROMTARIFE:
        if date_tuple >= valid_from:
            price = p
        else:
            break
    return round(price * 100.0, 4)


def fix_grundpreis_eur_monat(year: int, month: int, day: int = 15) -> float:
    """Fixtarif-Grundpreis (EUR/Monat) aus config.STROM_GRUNDPREISE."""
    date_tuple = (year, month, day)
    price = config.STROM_GRUNDPREISE[0][1]
    for valid_from, p in config.STROM_GRUNDPREISE:
        if date_tuple >= valid_from:
            price = p
        else:
            break
    return round(price, 2)
