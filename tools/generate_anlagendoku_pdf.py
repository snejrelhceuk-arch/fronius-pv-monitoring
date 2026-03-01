#!/usr/bin/env python3
"""
PV-Anlagendokumentation als PDF für das Heizhaus.

Erzeugt ein mehrseitiges A4-Dokument:
  Seite 1:   Hardware-Übersicht (Anlage, WR, Module, Batterie, Verbraucher)
  Seite 2+:  Je ein Betriebsjahr mit:
             - Energiebilanz (PV-Flüsse)
             - Verbraucher-Aufschlüsselung & Kennzahlen
             - Jahresübersicht & Finanzen

Datenstruktur orientiert sich an der API/Visualisierung:
  Energiefluss:  PV → Direkt / Batterie / Netz
  Verbraucher:   Haushalt / Heizpatrone / Wattpilot
  Kennzahlen:    Autarkie / Eigenverbrauch / Sonnenstunden / Batt-Effizienz
  Finanzen:      Ersparnis Autarkie / Eigenverbrauch

Aufruf:
  python3 tools/generate_anlagendoku_pdf.py
  → erzeugt  tools/PV_Anlagendokumentation.pdf

Benötigt: reportlab (pip install reportlab)
"""

import os
import sys
import sqlite3
from datetime import datetime

# Projekt-Root für config-Import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Konstanten ──
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "PV_Anlagendokumentation.pdf")
DB_PATH = config.DB_PATH

MONATE_KURZ = [
    "", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"
]

# kWp je Ausbaustufe (für spez. Ertrag)
KWP_PHASE = {2021: 21.40, 2022: 21.40, 2023: 21.40, 2024: 21.40,
             2025: 26.07, 2026: 37.59}  # 2025 gewichteter Schnitt

# ── Farben ──
COL_HEADER_BG = colors.HexColor('#1a5276')
COL_HEADER_FG = colors.white
COL_SECTION_BG = colors.HexColor('#d4e6f1')
COL_SUMMER_BG = colors.HexColor('#eaf7ea')
COL_SUM_BG = colors.HexColor('#d4e6f1')
COL_GRID = colors.HexColor('#bdc3c7')
COL_ACCENT = colors.HexColor('#1a5276')
COL_GREY = colors.HexColor('#666666')
COL_LIGHT_GREY = colors.HexColor('#999999')

# ── Styles ──
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    'DocTitle', parent=styles['Title'],
    fontSize=18, spaceBefore=0, spaceAfter=4 * mm, alignment=TA_CENTER
))
styles.add(ParagraphStyle(
    'SectionHead', parent=styles['Heading2'],
    fontSize=11, spaceBefore=3 * mm, spaceAfter=1.5 * mm,
    textColor=COL_ACCENT
))
styles.add(ParagraphStyle(
    'SubHead', parent=styles['Normal'],
    fontSize=9, fontName='Helvetica-Bold',
    spaceBefore=2 * mm, spaceAfter=1 * mm,
    textColor=colors.HexColor('#2c3e50')
))
styles.add(ParagraphStyle(
    'TinyNote', parent=styles['Normal'],
    fontSize=7.5, leading=10, textColor=COL_GREY
))
styles.add(ParagraphStyle(
    'YearTitle', parent=styles['Title'],
    fontSize=16, spaceBefore=0, spaceAfter=2 * mm, alignment=TA_CENTER,
    textColor=COL_ACCENT
))
styles.add(ParagraphStyle(
    'TableTitle', parent=styles['Normal'],
    fontSize=9, fontName='Helvetica-Bold',
    spaceBefore=1 * mm, spaceAfter=0.5 * mm,
    textColor=COL_ACCENT
))
styles.add(ParagraphStyle(
    'Footer', parent=styles['Normal'],
    fontSize=7, textColor=COL_LIGHT_GREY, alignment=TA_CENTER
))


# ── Hilfsfunktionen ──

def fmt(val, decimals=1):
    """Zahl formatieren, None → '–'."""
    if val is None:
        return "–"
    if decimals == 0:
        return f"{val:,.0f}".replace(",", ".")
    return f"{val:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(val):
    """Prozent formatieren."""
    if val is None:
        return "–"
    return f"{val:.1f}\u2009%".replace(".", ",")


def fmt_eur(val):
    """Euro formatieren."""
    if val is None or val == 0:
        return "–"
    return f"{val:,.0f}\u2009\u20ac".replace(",", ".")


def _table_style_base():
    """Basis-Tabellenstil für alle Monatstabellen."""
    return [
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), COL_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COL_HEADER_FG),
        ('BACKGROUND', (0, -1), (-1, -1), COL_SUM_BG),
        ('GRID', (0, 0), (-1, -1), 0.4, COL_GRID),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEADING', (0, 0), (-1, -1), 8),
    ]


def _summer_highlight(monthly_rows, style_cmds):
    """Sommermonate (Apr–Sep) farbig."""
    for idx, m_row in enumerate(monthly_rows, start=1):
        mon = m_row['month']
        if 4 <= mon <= 9:
            style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), COL_SUMMER_BG))


# ══════════════════════════════════════════════════════════════════════
#  Seite 1: Hardware-Übersicht
# ══════════════════════════════════════════════════════════════════════

def build_hardware_page():
    """Hardware-Seite."""
    elements = []

    elements.append(Paragraph("PV-Anlage \u2014 Technische Dokumentation", styles['DocTitle']))

    # ── Standort ──
    elements.append(Paragraph("Standort & Allgemeines", styles['SectionHead']))
    standort_data = [
        ["Standort", "Mittelsachsen (Erlau)"],
        ["Koordinaten", "51,01\u00b0 N  /  12,95\u00b0 E  \u2014  315 m \u00fc.NN"],
        ["Inbetriebnahme", "November 2021 (Phase 1)"],
        ["Aktueller Ausbau", "Phase 3 (seit Oktober 2025)"],
        ["Strategie", "Nulleinspeisung (Eigenverbrauch-Maximierung)"],
        ["Generator gesamt", "37,59 kWp  (98 Module)"],
        ["Inverter gesamt", "26,5 kW  (3 Wechselrichter)"],
        ["Overpaneling", "142 %"],
    ]
    t = Table(standort_data, colWidths=[55 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t)

    # ── Wechselrichter & Strings ──
    elements.append(Paragraph("Wechselrichter & String-Konfiguration", styles['SectionHead']))
    wr_data = [
        ["WR", "Modell", "AC", "kWp", "Strings"],
        ["F1", "GEN24 12 kW\n(Hybrid)", "12 kW", "19,32",
         "S1: 20\u00d7345 SSO 52\u00b0 | S2: 20\u00d7345 NNW 52\u00b0\n"
         "S3: 8\u00d7345 SSO 45\u00b0  | S4: 8\u00d7345 NNW 45\u00b0"],
        ["F2", "GEN24 10 kW", "10 kW", "12,42",
         "S5: 15\u00d7450 WSW 18\u00b0 | S6: 8\u00d7450 WSW 90\u00b0\n"
         "S7: 6\u00d7345 WSW 90\u00b0"],
        ["F3", "Symo 4,5 kW", "4,5 kW", "5,85",
         "S8: 13\u00d7450 SSO 90\u00b0"],
    ]
    t = Table(wr_data, colWidths=[10*mm, 32*mm, 14*mm, 16*mm, 105*mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), COL_SECTION_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COL_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    elements.append(t)

    # ── Batterie ──
    elements.append(Paragraph("Batteriespeicher", styles['SectionHead']))
    batt_data = [
        ["Modell", "BYD Battery-Box Premium HVS 10.2"],
        ["Kapazit\u00e4t", "10,24 kWh (nutzbar) / 10 kW Lade-/Entladeleistung"],
        ["Typ", "LiFePO\u2084 (Lithium-Eisenphosphat)"],
        ["Kopplung", "DC-gekoppelt an F1 (Gen24 Hybrid)"],
        ["BMS", "BYD Battery Management System (Modbus RTU via Gen24)"],
        ["Seit", "November 2021 (unver\u00e4ndert)"],
    ]
    t = Table(batt_data, colWidths=[35 * mm, 140 * mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t)

    # ── Verbraucher ──
    elements.append(Paragraph("Hauptverbraucher", styles['SectionHead']))
    verb_data = [
        ["Verbraucher", "Typ / Modell", "Leistung", "Bemerkung"],
        ["Haushalt", "5-Personen-HH", "variabel", "~5.400 kWh/a Grundlast"],
        ["W\u00e4rmepumpe", "Dimplex SIK 11 TES", "2,5\u20134 kW el.", "Sole-Wasser, Heizung + WW"],
        ["Wallbox", "Fronius Wattpilot go", "max. 22 kW", "3\u00d7 E-Auto, PV-\u00dcberschuss"],
        ["Heizpatrone", "Warmwasserspeicher", "2 kW", "\u00dcberschussvernichtung"],
        ["Klimager\u00e4t", "Split-Klima", "1,3 kW", "\u00dcberschussvernichtung"],
    ]
    t = Table(verb_data, colWidths=[30 * mm, 42 * mm, 28 * mm, 75 * mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), COL_SECTION_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COL_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    elements.append(t)

    # ── Messtechnik ──
    elements.append(Paragraph("Messtechnik & Monitoring", styles['SectionHead']))
    mess_data = [
        ["Protokoll", "SunSpec Modbus TCP (3s-Polling)"],
        ["SmartMeter", "4\u00d7 Fronius SM (Netz, F2, W\u00e4rmepumpe, F3)"],
        ["Monitoring-HW", "Raspberry Pi 4 (Produktion) + Pi 4 (Failover) + Pi 5 (Backup)"],
        ["Datenbank", "SQLite (RAM + SD + NVMe-Backup)"],
        ["Webinterface", "Flask + Gunicorn + ECharts (LAN-lokal)"],
    ]
    t = Table(mess_data, colWidths=[35 * mm, 140 * mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    elements.append(t)

    # ── Ausbaustufen ──
    elements.append(Paragraph("Ausbaustufen", styles['SubHead']))
    ph_data = [
        ["Phase", "Zeitraum", "Generator", "Wechselrichter"],
        ["1", "Nov 2021 \u2013 Apr 2025", "21,40 kWp", "Gen24 10 kW"],
        ["2", "Mai 2025 \u2013 Sep 2025", "26,07 kWp", "Gen24 12 kW + Gen24 10 kW"],
        ["3", "Ab Okt 2025", "37,59 kWp", "Gen24 12 kW + Gen24 10 kW + Symo 4,5 kW"],
    ]
    t = Table(ph_data, colWidths=[16 * mm, 45 * mm, 30 * mm, 84 * mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), COL_SECTION_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COL_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        f"Dokumentstand: {datetime.now().strftime('%d.%m.%Y')}  \u2014  "
        "Quelle: Fronius Modbus-Monitoring, Eigenmessung",
        styles['TinyNote']
    ))

    return elements


# ══════════════════════════════════════════════════════════════════════
#  Jahresseiten: API-orientierte Datengruppierung
# ══════════════════════════════════════════════════════════════════════

def build_year_page(year, monthly_rows, yearly_row):
    """
    Eine Seite pro Betriebsjahr, Daten gruppiert nach API-Logik:

    Tabelle 1 — Energiebilanz (woher/wohin fließt Energie)
                 PV | Direkt | Batt↑ | Batt↓ | Bezug | Einsp. | Verbrauch | ☀h

    Tabelle 2 — Verbraucher & Kennzahlen (wer verbraucht + Effizienz)
                 Haushalt | Heizpatr. | Wattpilot | Σ Verbr. | Autarkie | Eigenverbr.

    Block 3   — Jahres-Kennzahlen + Finanzen (2-spaltige Zusammenfassung)
    """
    elements = []
    elements.append(PageBreak())

    # Titel mit Phase-Info
    phase_str = _phase_label(year)
    elements.append(Paragraph(f"Betriebsjahr {year}{phase_str}", styles['YearTitle']))

    # ──────────────────────────────────────────────────────
    #  Tabelle 1: Energiebilanz
    # ──────────────────────────────────────────────────────
    elements.append(Paragraph("Energiebilanz  (kWh)", styles['TableTitle']))

    eb_header = ["Mon.", "PV", "Direkt",
                 "Batt \u2191", "Batt \u2193",
                 "Bezug", "Einsp.",
                 "Verbr.", "\u2600h"]
    eb_rows = [eb_header]

    # Summen
    eb_sums = [0.0] * 8  # pv, direkt, batt_ch, batt_dis, bezug, einsp, verbr, sun

    for m in monthly_rows:
        vals = [m['pv'], m['direkt'], m['batt_ch'], m['batt_dis'],
                m['bezug'], m['einsp'], m['verbr'], m['sun']]
        row = [MONATE_KURZ[m['month']]]
        for i, v in enumerate(vals):
            row.append(fmt(v, 0) if v and abs(v) >= 10 else fmt(v, 1))
            eb_sums[i] += (v or 0)
        eb_rows.append(row)

    # Summenzeile
    sum_row = ["\u03a3 Jahr"]
    for s in eb_sums:
        sum_row.append(fmt(s, 0) if abs(s) >= 10 else fmt(s, 1))
    eb_rows.append(sum_row)

    col_w1 = [16 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 18 * mm, 20 * mm, 18 * mm]
    t1 = Table(eb_rows, colWidths=col_w1, repeatRows=1)
    style1 = _table_style_base()
    _summer_highlight(monthly_rows, style1)
    t1.setStyle(TableStyle(style1))
    elements.append(t1)

    elements.append(Spacer(1, 2 * mm))

    # ──────────────────────────────────────────────────────
    #  Tabelle 2: Verbraucher & Kennzahlen
    # ──────────────────────────────────────────────────────
    elements.append(Paragraph("Verbraucher & Kennzahlen", styles['TableTitle']))

    vk_header = ["Mon.", "Haushalt", "Heizpatr.", "Wattpilot",
                 "\u03a3 Verbr.", "Autarkie", "Eigenv."]
    vk_rows = [vk_header]

    vk_sums = [0.0] * 4  # haushalt, hp, wtp, verbr
    aut_sum = 0.0
    aut_count = 0

    for m in monthly_rows:
        haushalt = (m['verbr'] or 0) - (m['hp'] or 0) - (m['wtp'] or 0)
        row = [
            MONATE_KURZ[m['month']],
            fmt(haushalt, 0) if haushalt >= 10 else fmt(haushalt, 1),
            fmt(m['hp'], 0) if m['hp'] and m['hp'] >= 10 else fmt(m['hp'], 1),
            fmt(m['wtp'], 0) if m['wtp'] and m['wtp'] >= 10 else fmt(m['wtp'], 1),
            fmt(m['verbr'], 0) if m['verbr'] and m['verbr'] >= 10 else fmt(m['verbr'], 0),
            fmt_pct(m['aut']),
            fmt_pct(m['ev']),
        ]
        vk_rows.append(row)
        vk_sums[0] += haushalt
        vk_sums[1] += (m['hp'] or 0)
        vk_sums[2] += (m['wtp'] or 0)
        vk_sums[3] += (m['verbr'] or 0)
        if m['aut'] is not None:
            aut_sum += m['aut']
            aut_count += 1

    # Summenzeile
    yr = yearly_row or {}
    sum_row2 = [
        "\u03a3 Jahr",
        fmt(vk_sums[0], 0),
        fmt(vk_sums[1], 0),
        fmt(vk_sums[2], 0),
        fmt(vk_sums[3], 0),
        fmt_pct(yr.get('autarkie')) if yr else fmt_pct(aut_sum / aut_count if aut_count else None),
        fmt_pct(yr.get('eigenverbrauch')) if yr else "\u2013",
    ]
    vk_rows.append(sum_row2)

    col_w2 = [16 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 22 * mm, 22 * mm]
    t2 = Table(vk_rows, colWidths=col_w2, repeatRows=1)
    style2 = _table_style_base()
    _summer_highlight(monthly_rows, style2)
    t2.setStyle(TableStyle(style2))
    elements.append(t2)

    elements.append(Spacer(1, 2 * mm))

    # ──────────────────────────────────────────────────────
    #  Block 3: Jahresübersicht & Finanzen
    # ──────────────────────────────────────────────────────
    elements.append(Paragraph("Jahres\u00fcbersicht & Finanzen", styles['TableTitle']))

    if yearly_row:
        yr = yearly_row
        kwp = KWP_PHASE.get(year, 37.59)
        spez_ertrag = yr['pv'] / kwp if yr['pv'] else 0
        batt_eff = yr['batt_dis'] / yr['batt_ch'] * 100 if yr['batt_ch'] > 0 else 0
        vollzyklen = yr['batt_ch'] / 10.24 if yr['batt_ch'] else 0
        haushalt_yr = (yr['verbr'] or 0) - (yr['hp'] or 0) - (yr['wtp'] or 0)

        # Zwei-Spalten Kennzahlen-Tabelle
        kz_data = [
            ["Erzeugung", "", "", "Netz & Speicher", ""],
            ["PV-Erzeugung", f"{fmt(yr['pv'], 0)} kWh",
             "", "Netz-Bezug", f"{fmt(yr['bezug'], 0)} kWh"],
            ["Spezif. Ertrag", f"{fmt(spez_ertrag, 0)} kWh/kWp",
             "", "Netz-Einspeisung", f"{fmt(yr['einsp'], 1)} kWh"],
            ["Direktverbrauch", f"{fmt(yr['direkt'], 0)} kWh",
             "", "Batterie-Effizienz", f"{fmt(batt_eff, 1)} %"],
            ["Sonnenstunden", f"{fmt(yr['sun'], 0)} h",
             "", "Vollzyklen (ca.)", f"{fmt(vollzyklen, 0)}"],
            ["Verbrauch", "", "", "Finanzen (Ersparnis)", ""],
            ["Gesamtverbrauch", f"{fmt(yr['verbr'], 0)} kWh",
             "", "Durch Autarkie", fmt_eur(yr.get('ersparnis_aut'))],
            ["  davon Haushalt", f"{fmt(haushalt_yr, 0)} kWh",
             "", "Durch Eigenverbr.", fmt_eur(yr.get('ersparnis_ev'))],
            ["  davon Heizpatrone", f"{fmt(yr['hp'], 0)} kWh",
             "", "Strompreis", f"{fmt(yr.get('strompreis', 0.33), 2)} \u20ac/kWh"],
            ["  davon Wattpilot", f"{fmt(yr['wtp'], 0)} kWh",
             "", "Einsp.-Verg\u00fctung", f"{fmt(yr.get('eisp_verg', 0.082), 3)} \u20ac/kWh"],
        ]

        t3 = Table(kz_data, colWidths=[34 * mm, 28 * mm, 6 * mm, 36 * mm, 30 * mm])
        t3.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            # Abschnittsköpfe fett + Hintergrund
            ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (3, 0), (4, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 5), (1, 5), 'Helvetica-Bold'),
            ('FONTNAME', (3, 5), (4, 5), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 0), (1, 0), COL_SECTION_BG),
            ('BACKGROUND', (3, 0), (4, 0), COL_SECTION_BG),
            ('BACKGROUND', (0, 5), (1, 5), COL_SECTION_BG),
            ('BACKGROUND', (3, 5), (4, 5), COL_SECTION_BG),
            # Labels fett
            ('FONTNAME', (0, 1), (0, 4), 'Helvetica-Bold'),
            ('FONTNAME', (3, 1), (3, 4), 'Helvetica-Bold'),
            ('FONTNAME', (0, 6), (0, 9), 'Helvetica-Bold'),
            ('FONTNAME', (3, 6), (3, 9), 'Helvetica-Bold'),
            # Trennlinie Abschnitte
            ('LINEBELOW', (0, 0), (1, 0), 0.5, colors.grey),
            ('LINEBELOW', (3, 0), (4, 0), 0.5, colors.grey),
            ('LINEBELOW', (0, 5), (1, 5), 0.5, colors.grey),
            ('LINEBELOW', (3, 5), (4, 5), 0.5, colors.grey),
            # Werte rechtsbündig
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        elements.append(t3)
    else:
        elements.append(Paragraph("(keine Jahresdaten verf\u00fcgbar)", styles['TinyNote']))

    # ── Fußnoten ──
    elements.append(Spacer(1, 1.5 * mm))
    elements.append(Paragraph(_phase_note(year), styles['TinyNote']))
    elements.append(Paragraph(
        f"Stand: {datetime.now().strftime('%d.%m.%Y')}  \u2014  "
        "Quelle: Fronius Solar.web (2021\u20132025) / Eigenmessung Modbus (ab 2026)",
        styles['TinyNote']
    ))

    return elements


def _phase_label(year):
    """Phase-Label f\u00fcr den Titel."""
    if year <= 2024:
        return "  (Phase 1: 21,40 kWp)"
    elif year == 2025:
        return "  (Phase 1\u21922\u21923)"
    else:
        return "  (Phase 3: 37,59 kWp)"


def _phase_note(year):
    """Fu\u00dfnote zur Hardware-Konfiguration."""
    if year == 2021:
        return "Teilbetrieb ab 05.11.2021 (Phase 1: 21,40 kWp, Gen24 10 kW, BYD HVS 10 kWh)"
    elif 2022 <= year <= 2023:
        return "Phase 1: 21,40 kWp, Gen24 10 kW, BYD HVS 10 kWh"
    elif year == 2024:
        return "Phase 1: 21,40 kWp, Gen24 10 kW, BYD HVS 10 kWh  \u2014  Wattpilot ab April 2024"
    elif year == 2025:
        return ("Phase 1 (Jan\u2013Apr): 21,40 kWp  \u2192  Phase 2 (Mai\u2013Sep): 26,07 kWp  \u2192  "
                "Phase 3 (ab Okt): 37,59 kWp")
    else:
        return "Phase 3: 37,59 kWp, 3 Wechselrichter, 98 Module  \u2014  Datenerfassung via Modbus (3s)"


# ══════════════════════════════════════════════════════════════════════
#  Daten laden & PDF zusammenbauen
# ══════════════════════════════════════════════════════════════════════

def load_data():
    """Lade Monats- und Jahresdaten aus der DB als dict-Listen."""
    con = sqlite3.connect(DB_PATH)

    # ── Monatsdaten ──
    monthly_raw = con.execute("""
        SELECT year, month,
               solar_erzeugung_kwh, direktverbrauch_kwh,
               batt_ladung_kwh, batt_entladung_kwh,
               netz_bezug_kwh, netz_einspeisung_kwh,
               gesamt_verbrauch_kwh, heizpatrone_kwh, wattpilot_kwh,
               autarkie_prozent, eigenverbrauch_prozent, sonnenstunden
        FROM monthly_statistics
        ORDER BY year, month
    """).fetchall()

    # ── Jahresdaten + Finanzen ──
    yearly_raw = con.execute("""
        SELECT year,
               solar_erzeugung_kwh, direktverbrauch_kwh,
               batt_ladung_kwh, batt_entladung_kwh,
               netz_bezug_kwh, netz_einspeisung_kwh,
               gesamt_verbrauch_kwh, heizpatrone_kwh, wattpilot_kwh,
               autarkie_prozent_avg, eigenverbrauch_prozent_avg,
               sonnenstunden,
               ersparnis_autarkie_eur, ersparnis_eigenverbrauch_eur
        FROM yearly_statistics
        ORDER BY year
    """).fetchall()

    con.close()

    # Gruppiere Monate nach Jahr als dicts
    years = {}
    for r in monthly_raw:
        y = r[0]
        if y not in years:
            years[y] = []
        years[y].append({
            'month': r[1], 'pv': r[2], 'direkt': r[3],
            'batt_ch': r[4], 'batt_dis': r[5],
            'bezug': r[6], 'einsp': r[7],
            'verbr': r[8], 'hp': r[9], 'wtp': r[10],
            'aut': r[11], 'ev': r[12], 'sun': r[13],
        })

    # Yearly als dict mit Strompreis-Lookup
    yearly = {}
    for r in yearly_raw:
        y = r[0]
        strompreis = config.get_strompreis(y, 6)  # Mitte des Jahres
        yearly[y] = {
            'pv': r[1], 'direkt': r[2],
            'batt_ch': r[3], 'batt_dis': r[4],
            'bezug': r[5], 'einsp': r[6],
            'verbr': r[7], 'hp': r[8], 'wtp': r[9],
            'autarkie': r[10], 'eigenverbrauch': r[11],
            'sun': r[12],
            'ersparnis_aut': r[13], 'ersparnis_ev': r[14],
            'strompreis': strompreis,
            'eisp_verg': config.EINSPEISEVERGUETUNG,
        }

    return years, yearly


def add_page_number(canvas, doc):
    """Fu\u00dfzeile mit Seitenzahl."""
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(COL_LIGHT_GREY)
    canvas.drawCentredString(
        A4[0] / 2, 12 * mm,
        f"PV-Anlage Erlau \u2014 Seite {doc.page}"
    )
    canvas.restoreState()


def generate_pdf():
    """Erzeuge das PDF."""
    years_data, yearly_data = load_data()

    doc = SimpleDocTemplate(
        OUTPUT_FILE,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=15 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm
    )

    elements = []

    # Seite 1: Hardware
    elements.extend(build_hardware_page())

    # Jahresseiten (ältestes zuerst)
    now = datetime.now()
    for year in sorted(years_data.keys()):
        # Laufendes Jahr nur wenn mind. 1 voller Monat
        if year == now.year and now.month <= 1 and len(years_data[year]) <= 1:
            continue
        yr_data = yearly_data.get(year)
        elements.extend(build_year_page(year, years_data[year], yr_data))

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\u2713 PDF erzeugt: {OUTPUT_FILE}")
    print(f"  {len(years_data)} Betriebsjahre, {sum(len(v) for v in years_data.values())} Monatsdatens\u00e4tze")
    print(f"  \u2192 {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_pdf()
