"""
notify/report_format.py — Reine Textformatierung des täglichen Energieberichts.

Nimmt das fertige read-only Energie-Dict (Tag/Monat/Jahr/Gesamt) und baut die
E-Mail-Textzeilen. **Kein** DB-/Hardware-Zugriff, keine Seiteneffekte — dadurch
aus ``event_notifier.py`` ausgelagert und einzeln testbar.

Der Bericht ist ein reiner Energie-Auszug (Zählerstände/Bilanz). Systemzustand,
Datenintegrität, Netzqualität und Warnungen laufen über die separaten
Sofort-Alarm-Mails, nicht über diesen Tagesbericht.

Struktur:
  Tag    — abgelaufener Kalendertag (00:00→00:00): Energiebilanz + Autarkie +
           Batterie-Belastung (außerhalb Komfort / davon Stress) + Verbraucher
  Monat  — laufender Monat bis zum Stand des abgelaufenen Tages: Bilanz + Autarkie
  Jahr   — laufendes Jahr bis zum Stand des abgelaufenen Tages: Bilanz + Autarkie
  Gesamt — seit Inbetriebnahme bis zum Stand des abgelaufenen Tages: Bilanz + Autarkie
"""

from __future__ import annotations


def _fmt(val, dez=1) -> str:
    return '—' if val is None else f'{val:.{dez}f} kWh'


def _zeile(label: str, wert: str, einzug: str = '  ') -> str:
    return f'{einzug}{label:<13}{wert}'


def _quote(zaehler: float, nenner: float):
    """Prozentquote (0…100 %) oder None, wenn der Nenner ≤ 0 ist."""
    if not nenner or nenner <= 0:
        return None
    return max(0.0, min(100.0, zaehler / nenner * 100.0))


def _fmt_pct(val) -> str:
    return '—' if val is None else f'{val:.0f} %'


def _pct_de(val) -> str:
    """Prozent mit deutschem Dezimalkomma, eine Nachkommastelle."""
    return '—' if val is None else f'{val:.1f}'.replace('.', ',') + ' %'


def _fmt_dauer(minuten) -> str:
    """Minuten → „3 h 12 min" / „25 min" / „0 min"."""
    if minuten is None:
        return '—'
    m = int(round(minuten))
    h, mm = divmod(m, 60)
    if h and mm:
        return f'{h} h {mm} min'
    if h:
        return f'{h} h'
    return f'{mm} min'


def _bilanz_zeilen(sec: dict) -> list:
    """Energie-Kernwerte einer Sektion — kompakt, teils nebeneinander.

    Erzeugung/Verbrauch und Netzbezug/Einspeisung stehen je paarweise
    nebeneinander (Schrägstrich-getrennt); dazu Batterie (Ladung/Entladung)
    und die Kennzahl Autarkie:

      Autarkie       = (Verbrauch − Netzbezug) / Verbrauch  (Eigendeckungsgrad)
    """
    verb = sec.get('verbrauch') or 0.0
    netz = sec.get('netzbezug') or 0.0
    autarkie = _quote(verb - netz, verb)
    return [
        f'  Erzeugung {_fmt(sec.get("erzeugung"))}   /   '
        f'Verbrauch {_fmt(sec.get("verbrauch"))}',
        f'  Netzbezug {_fmt(sec.get("netzbezug"))}   /   '
        f'Einspeisung {_fmt(sec.get("einspeisung"))}',
        f'  Batterie  Ladung {_fmt(sec.get("batt_ladung"))} / '
        f'Entladung {_fmt(sec.get("batt_entladung"))}',
        f'  Autarkie {_fmt_pct(autarkie)}',
    ]


def tagesbericht(d: dict) -> str:
    """Baue den vollständigen Tagesbericht-Text aus dem Energie-Dict."""
    tag = d['tag']
    monat = d['monat']
    jahr = d['jahr']
    gesamt = d['gesamt']

    kopf = f'Tag ({tag["datum"]}, 00:00–00:00 Uhr'
    if tag.get('fallback'):
        kopf += ', vorläufig aus hourly_data'
    kopf += ')'

    zeilen = [
        f'PV-System Tagesbericht — {tag["datum"]}',
        '',
        kopf,
    ]
    zeilen += _bilanz_zeilen(tag)

    # Batterie-Belastung — ausschließlich im Tag: Zeit außerhalb Komfort
    # (schließt Stress ein) und davon die Stresszeit, je Dauer + Anteil.
    bel = tag.get('belastung')
    bd = tag.get('baender') or {}
    if bel:
        km, kx = bd.get('komfort_min'), bd.get('komfort_max')
        sl, sh = bd.get('stress_low'), bd.get('stress_high')
        zeilen.append(_zeile(
            'Belastung:',
            f'{_fmt_dauer(bel["komfort_minuten"])} außerhalb Komfort '
            f'({km}–{kx} %), davon {_fmt_dauer(bel["stress_minuten"])} '
            f'Stress (<{sl} / >{sh} %)'))
        zeilen.append(_zeile(
            '',
            f'{_pct_de(bel["komfort_pct"])} außerhalb Komfort · '
            f'{_pct_de(bel["stress_pct"])} Stress'))
    else:
        zeilen.append(_zeile('Belastung:', '—'))

    # Verbraucher — ausschließlich im Tag
    zeilen.append(_zeile(
        'Verbraucher:',
        f'WP {_fmt(tag.get("wp_kwh"))} · HP {_fmt(tag.get("hp_kwh"))} · '
        f'Wattpilot {_fmt(tag.get("wattpilot_kwh"))} · '
        f'Haushalt {_fmt(tag.get("haushalt_kwh"))}'))

    zeilen += ['', f'Monat ({monat["label"]}, Stand {monat["bis"]})']
    zeilen += _bilanz_zeilen(monat)

    zeilen += ['', f'Jahr ({jahr["label"]}, Stand {jahr["bis"]})']
    zeilen += _bilanz_zeilen(jahr)

    zeilen += ['', f'Gesamt ({gesamt["label"]}, Stand {gesamt["bis"]})']
    zeilen += _bilanz_zeilen(gesamt)

    zeilen += [
        '',
        'Reiner Energiebericht (Zählerstände). Systemfehler werden separat als',
        'Sofort-Alarm gemeldet.',
        'Konfiguration: pv-config.py → Benachrichtigungen',
    ]
    return '\n'.join(zeilen)
