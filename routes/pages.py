"""
Blueprint: Seiten-Routen (HTML-Templates).

Enthält: /, /flow, /monitoring, /echtzeit, /verbraucher, /erzeuger, /analyse
"""
from flask import Blueprint, render_template, request, redirect
import config
from routes.helpers import get_db_connection, get_strompreis_fuer_monat

bp = Blueprint('pages', __name__)


@bp.route('/')
def index():
    """Startseite: Redirect zu Flow-Chart"""
    return redirect('/flow')


@bp.route('/flow')
def flow():
    """Energieflow Echtzeit-Visualisierung"""
    return render_template('flow_view.html')


@bp.route('/monitoring')
def monitoring():
    """Tag-View Dashboard (bisherige Startseite)"""
    return render_template('tag_view.html')


@bp.route('/echtzeit')
def echtzeit():
    """Echtzeit-Analyse (detaillierte Diagramme)"""
    return render_template('echtzeit_view.html')


@bp.route('/verbraucher')
@bp.route('/wattpilot')  # Redirect-Kompatibilität
def verbraucher_page():
    """Verbraucher-Übersicht mit Wattpilot-Status"""
    return render_template('verbraucher_view.html')


@bp.route('/erzeuger')
def erzeuger_page():
    """Erzeuger-Übersicht: F1/F2/F3 Inverter-Aufteilung"""
    return render_template('erzeuger_view.html')


@bp.route('/analyse')
@bp.route('/amortisation')  # Redirect-Kompatibilität
def analyse_redirect():
    """Redirect zur Erzeuger-Tagesansicht (Standard-Analyseseite)"""
    return redirect('/erzeuger')


@bp.route('/analyse/pv')
@bp.route('/analyse/haushalt')
@bp.route('/analyse/amortisation')
def analyse():
    """Analyse der PV-Anlage - Daten aus monthly_statistics DB"""

    # Investitionen & Finanzdaten aus config.py
    invest_pv_2022 = config.INVEST_PV_2022
    invest_pv_2024 = config.INVEST_PV_2024
    invest_wp_2022 = config.INVEST_WP_2022

    gesamt_invest_pv = config.GESAMT_INVEST_PV
    gesamt_invest_haushalt = config.GESAMT_INVEST_HAUSHALT

    # Haushalt-Basis: normaler Strombedarf ohne WP und E-Auto
    haushalt_basis_kwh = config.HAUSHALT_BASIS_KWH

    # WP-elektrisch Basis (ohne Heizpatrone-Anteil)
    wp_basis = config.WP_BASIS

    # Grundpreis (tagesgenau gewichtet pro Monat, inkl. Zählermiete)
    get_grundpreis = config.get_grundpreis

    # Heizkosten-Ersparnis
    heizkosten_ersparnis = config.HEIZKOSTEN_ERSPARNIS
    heizperiode_monate = config.HEIZPERIODE_MONATE

    # Nulleinspeiser - keine Einspeisevergütung

    # Daten aus DB statt CSV lesen
    conn = get_db_connection()
    if not conn:
        return "Datenbankfehler", 500

    # ========================================
    # MONATLICHE DATEN VERARBEITEN
    # ========================================
    cursor = conn.cursor()
    cursor.execute("""
        SELECT year, month,
               COALESCE(solar_erzeugung_kwh, 0),
               COALESCE(direktverbrauch_kwh, 0),
               COALESCE(wattpilot_kwh, 0),
               COALESCE(heizpatrone_kwh, 0),
               COALESCE(batt_entladung_kwh, 0),
               COALESCE(batt_ladung_kwh, 0),
               COALESCE(netz_bezug_kwh, 0),
               COALESCE(netz_einspeisung_kwh, 0),
               COALESCE(gesamt_verbrauch_kwh, 0),
               sonnenstunden
        FROM monthly_statistics
        WHERE year >= 2021
        ORDER BY year, month
    """)
    monthly_rows = cursor.fetchall()

    # Gruppierung nach Jahren
    years_data = {}

    for row in monthly_rows:
        year, month = row[0], row[1]
        solar, direkt, wattpilot, heizpatrone = row[2], row[3], row[4], row[5]
        batt_entl, batt_lad, netz_bezug, netz_einsp, gesamt_verbr = row[6], row[7], row[8], row[9], row[10]
        sonnenstd = row[11]

        # Strompreis für diesen Monat
        strompreis = get_strompreis_fuer_monat(year, month)

        # Kosten Netzbezug + Grundpreis (inkl. Zählermiete)
        grundpreis = get_grundpreis(year, month)
        kosten_monat = netz_bezug * strompreis + grundpreis

        # Jahresaggregation initialisieren bei Bedarf
        if year not in years_data:
            years_data[year] = {
                'year': year,
                'solar': 0,
                'direkt': 0,
                'wattpilot': 0,
                'heizpatrone': 0,
                'batt_entl': 0,
                'batt_lad': 0,
                'netz_bezug': 0,
                'netz_einsp': 0,
                'gesamt_verbr': 0,
                'kosten_strom': 0,  # Netzbezug-Kosten + Grundpreis
                'kosten_fixkosten': 0,  # Grundpreis (für avg_strompreis Berechnung)
                'monate': 0,
                'heizmonate': 0,  # Anzahl Heizperiode-Monate (Okt–Mär) mit DB-Daten
                'sonnenstunden': 0
            }

        # Akkumulieren
        years_data[year]['solar'] += solar
        years_data[year]['direkt'] += direkt
        years_data[year]['wattpilot'] += wattpilot
        years_data[year]['heizpatrone'] += heizpatrone
        years_data[year]['batt_entl'] += batt_entl
        years_data[year]['batt_lad'] += batt_lad
        years_data[year]['netz_bezug'] += netz_bezug
        years_data[year]['netz_einsp'] += netz_einsp
        years_data[year]['gesamt_verbr'] += gesamt_verbr
        years_data[year]['kosten_strom'] += kosten_monat
        years_data[year]['kosten_fixkosten'] += grundpreis
        years_data[year]['monate'] += 1
        if month in heizperiode_monate:
            years_data[year]['heizmonate'] += 1
        if sonnenstd:
            years_data[year]['sonnenstunden'] += sonnenstd

    # ========================================
    # JAHRESAUSWERTUNG
    # ========================================
    for year in years_data:
        data = years_data[year]

        # Durchschnittlicher Strompreis für dieses Jahr (für Anzeige)
        if data['netz_bezug'] > 0:
            avg_strompreis = (data['kosten_strom'] - data['kosten_fixkosten']) / data['netz_bezug']
        else:
            avg_strompreis = get_strompreis_fuer_monat(year, 6)  # Jahresmitte als Fallback

        # Autarkie: Anteil des selbst erzeugten Stroms am Gesamtverbrauch
        autarkie = (data['solar'] / data['gesamt_verbr'] * 100) if data['gesamt_verbr'] > 0 else 0

        # Batterie-Wirkungsgrad
        batt_wirkungsgrad = (data['batt_entl'] / data['batt_lad'] * 100) if data['batt_lad'] > 0 else 0

        # Ersparnis durch Solarstrom (Nulleinspeiser: gesamte Erzeugung als Ersparnis)
        # Verwende durchschnittlichen Strompreis des Jahres
        ersparnis_solar = data['solar'] * avg_strompreis

        # Netto-Ersparnis Strom = Ersparnis Solar - tatsächliche Kosten (inkl. Grundpreis)
        netto_ersparnis_strom = ersparnis_solar - data['kosten_strom']

        # WP-elektrisch: Basis + 25% der Heizpatrone
        wpel_kwh = wp_basis.get(year, 0) + 0.25 * data['heizpatrone']

        # Anteilige Netzkosten für WP und E-Auto berechnen
        # Annahme: Haushalt-Basis (3000 kWh) wird vorrangig aus Netz gedeckt
        # Der Rest des Netzbezugs geht anteilig in WP und E-Auto
        netz_ueberschuss = max(0, data['netz_bezug'] - haushalt_basis_kwh)
        wp_und_auto_bedarf = wpel_kwh + data['wattpilot']

        if wp_und_auto_bedarf > 0:
            anteil_wp_aus_netz = netz_ueberschuss * (wpel_kwh / wp_und_auto_bedarf)
            anteil_auto_aus_netz = netz_ueberschuss * (data['wattpilot'] / wp_und_auto_bedarf)
        else:
            anteil_wp_aus_netz = 0
            anteil_auto_aus_netz = 0

        # Kosten für Netz-Anteil WP und E-Auto (mit durchschnittlichem Strompreis)
        netz_kosten_wp = anteil_wp_aus_netz * avg_strompreis
        netz_kosten_auto = anteil_auto_aus_netz * avg_strompreis

        # Heizkosten-Ersparnis (eingesparte Brennstoffkosten) MINUS Netz-Anteil WP
        # Jahresbudget wird nur auf Heizperiode-Monate (Okt–Mär) verteilt
        heiz_budget = heizkosten_ersparnis.get(year, 0)
        heizmonate = data.get('heizmonate', 0)
        heiz_ersparnis_brutto = (heiz_budget / 6.0) * heizmonate if heizmonate > 0 else 0
        heiz_ersparnis = heiz_ersparnis_brutto - netz_kosten_wp

        # Benzin-Ersparnis durch E-Auto (Wattpilot) MINUS Netz-Anteil Auto
        # 15 kWh/100km, gespart 10 EUR/100km beim Verbrenner
        km_gefahren = (data['wattpilot'] / 15) * 100 if data['wattpilot'] > 0 else 0
        benzin_ersparnis_brutto = (km_gefahren / 100) * 10
        benzin_ersparnis = benzin_ersparnis_brutto - netz_kosten_auto

        # GESAMT-Ersparnis (Strom-Netto + Heizung + Benzin)
        netto_ersparnis = netto_ersparnis_strom + heiz_ersparnis + benzin_ersparnis

        # Erweiterte Daten speichern
        data['autarkie'] = autarkie
        data['batt_wirkungsgrad'] = batt_wirkungsgrad
        data['strompreis'] = avg_strompreis
        data['ersparnis_solar'] = ersparnis_solar
        data['netto_ersparnis_strom'] = netto_ersparnis_strom
        data['heiz_ersparnis'] = heiz_ersparnis
        data['benzin_ersparnis'] = benzin_ersparnis
        data['km_gefahren'] = km_gefahren
        data['netto_ersparnis'] = netto_ersparnis

    # ========================================
    # PV-AMORTISATION (nur PV-Anlage, Brutto)
    # ========================================
    amort_pv_data = []
    kum_invest_pv = 0
    kum_solar = 0

    for year in sorted(years_data.keys()):
        invest_jahr_pv = invest_pv_2022 if year == 2022 else (invest_pv_2024 if year == 2024 else 0)
        kum_invest_pv += invest_jahr_pv
        kum_solar += years_data[year]['solar']

        # Brutto-Ersparnis (wie Solarweb)
        brutto_ersparnis = years_data[year]['ersparnis_solar']

        # Netz-Kosten (was tatsächlich bezahlt wird, inkl. Grundpreis)
        netz_kosten = years_data[year]['kosten_strom']

        # Relative Amortisation (Brutto)
        rel_amort_pv = (brutto_ersparnis / gesamt_invest_pv * 100) if gesamt_invest_pv > 0 else 0
        jahre_amort_pv = (100.0 / rel_amort_pv) if rel_amort_pv > 0 else 0

        # EUR/kWh PV-Anlage (real): Was hat jede kWh gekostet?
        eur_kwh_real = kum_invest_pv / kum_solar if kum_solar > 0 else 0

        # EUR/kWh PV-Anlage (25J): Prognose mit 18.000 kWh/Jahr ab 2026
        jahre_seit_start = year - 2022 + 1
        jahre_verbleibend = 25 - jahre_seit_start
        solar_prognose_25j = kum_solar + (jahre_verbleibend * 18000)
        eur_kwh_25j = kum_invest_pv / solar_prognose_25j if solar_prognose_25j > 0 else 0

        # Prognose 25J
        wartung_pv = gesamt_invest_pv * 0.01
        prognose_pv_25j = (brutto_ersparnis - wartung_pv) * 25

        amort_pv_data.append({
            'year': year,
            'solar': years_data[year]['solar'],
            'brutto_ersparnis': brutto_ersparnis,
            'netz_kosten': netz_kosten,
            'rel_amort': rel_amort_pv,
            'jahre_amort': jahre_amort_pv,
            'kum_ersparnis': kum_solar * years_data[year]['strompreis'],  # Approximation
            'eur_kwh_real': eur_kwh_real,
            'eur_kwh_25j': eur_kwh_25j,
            'prognose_25j': prognose_pv_25j
        })

    # ========================================
    # HAUSHALTS-AMORTISATION (inkl. Wärmepumpe, alle Ersparnisse)
    # ========================================
    amort_haushalt_data = []
    kum_invest_haushalt = 0
    kum_ersparnis_haushalt = 0

    for year in sorted(years_data.keys()):
        # Investitionen in diesem Jahr
        invest_jahr_haushalt = 0
        if year == 2022:
            invest_jahr_haushalt = invest_pv_2022 + invest_wp_2022
        elif year == 2024:
            invest_jahr_haushalt = invest_pv_2024

        kum_invest_haushalt += invest_jahr_haushalt

        # Gesamt-Ersparnis (Strom-Netto + Heizung + Benzin)
        gesamt_ersparnis = years_data[year]['netto_ersparnis']
        kum_ersparnis_haushalt += gesamt_ersparnis

        # Netz-Kosten (was tatsächlich bezahlt wird, inkl. Grundpreis)
        netz_kosten = years_data[year]['kosten_strom']

        # Relative Amortisation
        rel_amort_haushalt = (gesamt_ersparnis / gesamt_invest_haushalt * 100) if gesamt_invest_haushalt > 0 else 0
        jahre_amort_haushalt = (100.0 / rel_amort_haushalt) if rel_amort_haushalt > 0 else 0

        # Prognose 25J
        wartung_haushalt = gesamt_invest_haushalt * 0.01
        prognose_haushalt_25j = (gesamt_ersparnis - wartung_haushalt) * 25

        # Effektiver Strompreis (Netzkosten inkl. Grundpreis / Gesamtverbrauch)
        if years_data[year]['gesamt_verbr'] > 0:
            eff_strompreis = netz_kosten / years_data[year]['gesamt_verbr']
        else:
            eff_strompreis = years_data[year]['strompreis']

        amort_haushalt_data.append({
            'year': year,
            'invest_jahr': invest_jahr_haushalt,
            'strom_ersparnis': years_data[year]['netto_ersparnis_strom'],
            'netz_kosten': netz_kosten,
            'heiz_ersparnis': years_data[year]['heiz_ersparnis'],
            'benzin_ersparnis': years_data[year]['benzin_ersparnis'],
            'gesamt_ersparnis': gesamt_ersparnis,
            'rel_amort': rel_amort_haushalt,
            'jahre_amort': jahre_amort_haushalt,
            'kum_ersparnis': kum_ersparnis_haushalt,
            'prognose_25j': prognose_haushalt_25j,
            'eff_strompreis': eff_strompreis
        })

    # Aktuelle Werte für Info-Cards
    current_year = max(years_data.keys())

    # Frequenz-Extremwerte (Gesamtzeitraum) aus data_1min
    freq_extremes = None
    try:
        from datetime import datetime as dt
        cursor.execute("SELECT MIN(ts), MAX(ts) FROM data_1min WHERE f_Netz_min IS NOT NULL")
        range_row = cursor.fetchone()
        if range_row and range_row[0]:
            cursor.execute("""
                SELECT ts, f_Netz_min FROM data_1min
                WHERE ts >= ? AND ts <= ? AND f_Netz_min IS NOT NULL
                ORDER BY f_Netz_min ASC LIMIT 1
            """, (range_row[0], range_row[1]))
            min_row = cursor.fetchone()
            cursor.execute("""
                SELECT ts, f_Netz_max FROM data_1min
                WHERE ts >= ? AND ts <= ? AND f_Netz_max IS NOT NULL
                ORDER BY f_Netz_max DESC LIMIT 1
            """, (range_row[0], range_row[1]))
            max_row = cursor.fetchone()
            if min_row or max_row:
                freq_extremes = {}
                if min_row:
                    dt_min = dt.fromtimestamp(min_row[0])
                    freq_extremes['f_min'] = round(min_row[1], 3)
                    freq_extremes['f_min_label'] = dt_min.strftime('%d.%m.%y, %H:%M')
                if max_row:
                    dt_max = dt.fromtimestamp(max_row[0])
                    freq_extremes['f_max'] = round(max_row[1], 3)
                    freq_extremes['f_max_label'] = dt_max.strftime('%d.%m.%y, %H:%M')
    except Exception:
        pass

    # Template je nach Route wählen
    template_map = {
        '/analyse/pv': 'analyse_pv_view.html',
        '/analyse/haushalt': 'analyse_haushalt_view.html',
        '/analyse/amortisation': 'analyse_amortisation_view.html',
    }
    template = template_map.get(request.path, 'analyse_pv_view.html')

    try:
        return render_template(template,
                             invest_pv_2022=invest_pv_2022,
                             invest_pv_2024=invest_pv_2024,
                             invest_wp_2022=invest_wp_2022,
                             gesamt_invest_pv=gesamt_invest_pv,
                             gesamt_invest_haushalt=gesamt_invest_haushalt,
                             yearly_data=list(years_data.values()),
                             amort_pv_data=amort_pv_data,
                             amort_haushalt_data=amort_haushalt_data,
                             current_year=current_year,
                             freq_extremes=freq_extremes)
    finally:
        conn.close()