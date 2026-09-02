"""
notify/report_format.py — Reine Textformatierung des täglichen Energieberichts.

Nimmt das fertige read-only Energie-Dict (Tag/Monat/Jahr/Gesamt) und baut die
E-Mail-Textzeilen. **Kein** DB-/Hardware-Zugriff, keine Seiteneffekte — dadurch
aus ``event_notifier.py`` ausgelagert und einzeln testbar.

Der Bericht ist ein reiner Energie-Auszug (Zählerstände/Bilanz). Systemzustand,
Datenintegrität, Netzqualität und Warnungen laufen über die separaten
Sofort-Alarm-Mails, nicht über diesen Tagesbericht.

Struktur:
  Tag    — abgelaufener Kalendertag (00:00→00:00): 5 Kernwerte + Stresszeit + Verbraucher
  Monat  — laufender Monat bis zum Stand des abgelaufenen Tages: 5 Kernwerte
  Jahr   — laufendes Jahr bis zum Stand des abgelaufenen Tages: 5 Kernwerte
  Gesamt — seit Inbetriebnahme bis zum Stand des abgelaufenen Tages: 5 Kernwerte
"""

from __future__ import annotations


def _fmt(val, dez=1) -> str:
    return '—' if val is None else f'{val:.{dez}f} kWh'


def _zeile(label: str, wert: str, einzug: str = '  ') -> str:
    return f'{einzug}{label:<13}{wert}'


def _bilanz_zeilen(sec: dict) -> list:
    """Die 5 Energie-Kernwerte einer Sektion.

    Erzeugung / Verbrauch / Netzbezug / Einspeisung / Batterie (Ladung+Entladung).
    """
    return [
        _zeile('Erzeugung:', _fmt(sec.get('erzeugung'))),
        _zeile('Verbrauch:', _fmt(sec.get('verbrauch'))),
        _zeile('Netzbezug:', _fmt(sec.get('netzbezug'))),
        _zeile('Einspeisung:', _fmt(sec.get('einspeisung'))),
        _zeile('Batterie:',
               f'Ladung {_fmt(sec.get("batt_ladung"))} · '
               f'Entladung {_fmt(sec.get("batt_entladung"))}'),
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

    # Stresszeit — ausschließlich im Tag
    if tag.get('stresszeit_pct') is not None:
        zeilen.append(_zeile(
            'Stresszeit:',
            f'{tag["stresszeit_pct"]:.1f} %  '
            f'(SOC außerhalb {tag["stress_low"]}–{tag["stress_high"]} %)'))
    else:
        zeilen.append(_zeile('Stresszeit:', '—'))

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
