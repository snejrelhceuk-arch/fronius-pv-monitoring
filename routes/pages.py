"""
Blueprint: Seiten-Routen (HTML-Templates).

Enthält: /, /flow, /monitoring, /echtzeit, /verbraucher, /erzeuger, /analyse
"""
from flask import Blueprint, render_template, request, redirect
from datetime import datetime
from urllib.parse import urlencode
import config
from routes.helpers import get_db_connection, get_strompreis_fuer_monat

bp = Blueprint('pages', __name__)
NAV_CONTEXT_MAX_AGE_MS = 60 * 60 * 1000


def _get_installed_kwp_for_month(year, month):
    """Installierte PV-Leistung (kWp) je Monat gemäß Ausbaustufen."""
    if (year, month) <= (2025, 4):
        return 21.40
    if (year, month) <= (2025, 9):
        return 26.07
    return config.PV_KWP_TOTAL


def _get_pv_grenzwerte_yearly(cursor):
    """Jährliche PV-/Netz-Extremwerte je Jahr für die Statistik-Tabelle.

    Nutzt dieselbe Logik wie die Gesamt-Tooltips (`/api/period_extremes`,
    `_extremes_gesamt`) → konsistente Werte (Ertrag, Spannung L-L, Frequenz,
    cos φ, Peak-Leistung – jeweils mit Datum/Uhrzeit, soweit verfügbar).
    """
    try:
        from routes.visualization import _extremes_gesamt
        data = _extremes_gesamt(cursor).get('by_key', {})
    except Exception:
        return []
    result = []
    for year in sorted(data.keys(), reverse=True):
        e = dict(data[year])
        e['year'] = year
        result.append(e)
    return result


def _get_nav_context(args):
    """Normalisiere den UI-Zeitkontext für Links zwischen verwandten Ansichten."""
    now = datetime.now()
    now_ms = int(now.timestamp() * 1000)
    nav_ts = args.get('nav_ts', type=int)
    is_expired = nav_ts is not None and abs(now_ms - nav_ts) > NAV_CONTEXT_MAX_AGE_MS

    period = 'tag' if is_expired else args.get('period', 'tag')
    if period not in {'tag', 'monat', 'jahr', 'gesamt'}:
        period = 'tag'

    ctx = {'period': period}
    if period == 'tag':
        date_str = (None if is_expired else args.get('date')) or now.strftime('%Y-%m-%d')
        ctx['date'] = date_str
    elif period == 'monat':
        ctx['year'] = (None if is_expired else args.get('year', type=int)) or now.year
        ctx['month'] = (None if is_expired else args.get('month', type=int)) or now.month
    elif period == 'jahr':
        ctx['year'] = (None if is_expired else args.get('year', type=int)) or now.year

    ctx['nav_ts'] = now_ms

    return ctx


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


@bp.route('/maschinenraum')
@bp.route('/echtzeit')  # Redirect-Kompatibilität
def maschinenraum():
    """Maschinenraum (ehem. Echtzeit-Analyse) — detaillierte Diagramme"""
    return render_template('echtzeit_view.html')


@bp.route('/netzqualitaet')
def netzqualitaet():
    """Netzqualität — Leiterspannungen, Netzfrequenz, Musteranalyse"""
    return render_template('netzqualitaet_view.html')


@bp.route('/verbraucher')
@bp.route('/wattpilot')  # Redirect-Kompatibilität
def verbraucher_page():
    """Verbraucher-Übersicht mit Wattpilot-Status"""
    return render_template('verbraucher_view.html')


@bp.route('/verbraucher/wp-leistung')
@bp.route('/analyse/verbraucher/wp-leistung')
def wp_leistung_page():
    """WP-Leistungsnachweis (Netzbetreiber) — Zeitreihe aus Dauerprotokoll."""
    return render_template('wp_leistung_view.html')


@bp.route('/erzeuger')
def erzeuger_page():
    """Erzeuger-Übersicht: F1/F2/F3 Inverter-Aufteilung"""
    return render_template('erzeuger_view.html')


@bp.route('/analyse')
@bp.route('/amortisation')  # Redirect-Kompatibilität
def analyse_redirect():
    """Analyse-Einstieg führt immer auf die Erzeuger-Ansicht mit Zeitkontext."""
    nav_query = urlencode(_get_nav_context(request.args))
    return redirect(f"/erzeuger?{nav_query}" if nav_query else '/erzeuger')


@bp.route('/analyse/primaerenergie')
def analyse_primaerenergie():
    """Primärenergie-Importe Deutschland 1990–2026 — statische Übersicht"""
    nav_context = _get_nav_context(request.args)
    nav_query = urlencode(nav_context)

    # Aktualitäts-Hinweis: manuell gepflegte Seite, Verfallstimer (Quartal)
    stand = getattr(config, 'PRIMAERENERGIE_STAND', None)
    stale_months = getattr(config, 'PRIMAERENERGIE_STALE_MONTHS', 3)
    primaer_stale = False
    primaer_stand_label = None
    try:
        d = datetime.strptime(stand, '%Y-%m-%d')
        primaer_stand_label = d.strftime('%d.%m.%Y')
        age_days = (datetime.now() - d).days
        primaer_stale = age_days > stale_months * 30
    except Exception:
        pass

    return render_template('analyse_primaerenergie_view.html',
                           nav_query=('?' + nav_query) if nav_query else '',
                           primaer_stale=primaer_stale,
                           primaer_stand=primaer_stand_label)


@bp.route('/analyse/pv')
@bp.route('/analyse/haushalt')
@bp.route('/analyse/amortisation')
def analyse():
    """Analyse der PV-Anlage - Daten aus monthly_statistics DB"""
    nav_context = _get_nav_context(request.args)
    nav_query = urlencode(nav_context)

    # Investitionen & Finanzdaten aus config.py
    invest_pv_2021 = config.INVEST_PV_2021
    invest_pv_2024 = config.INVEST_PV_2024
    invest_wp_2021 = config.INVEST_WP_2021

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
               COALESCE(waermepumpe_kwh, 0),
               COALESCE(batt_entladung_kwh, 0),
               COALESCE(batt_ladung_kwh, 0),
               COALESCE(netz_bezug_kwh, 0),
               COALESCE(netz_einspeisung_kwh, 0),
               COALESCE(gesamt_verbrauch_kwh, 0),
               sonnenstunden,
               COALESCE(heizpatrone_kwh, 0)
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
        heizpatrone_el = row[12]  # gemessener Heizpatrone-Verbrauch (heizpatrone_kwh)

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
                'heizpatrone_el': 0,  # gemessene Heizpatrone (heizpatrone_kwh)
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
        years_data[year]['heizpatrone_el'] += heizpatrone_el
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

        # Autarkie: Anteil des Verbrauchs, der nicht aus dem Netz stammt
        autarkie = ((1 - (data['netz_bezug'] / data['gesamt_verbr'])) * 100) if data['gesamt_verbr'] > 0 else 0

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

        # Spezifischer Ertrag (kWh/kWp): jahresbezogen, monatsweise nach Ausbauphase gewichtet
        kwp_month_sum = sum(
            _get_installed_kwp_for_month(year, month)
            for month in range(1, 13)
        )
        avg_kwp_year = (kwp_month_sum / 12.0) if kwp_month_sum > 0 else config.PV_KWP_TOTAL
        spezifischer_ertrag = (data['solar'] / avg_kwp_year) if avg_kwp_year > 0 else 0

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
        data['spez_ertrag'] = spezifischer_ertrag

    # ========================================
    # PV-AMORTISATION (nur PV-Anlage, Brutto)
    # ========================================
    amort_pv_data = []
    kum_invest_pv = 0
    kum_solar = 0
    kum_brutto_ersparnis_pv = 0

    for year in sorted(years_data.keys()):
        # Historisch korrekt: Investition 2021 (Baujahr) + Erweiterung 2024
        invest_jahr_pv = invest_pv_2021 if year == 2021 else (invest_pv_2024 if year == 2024 else 0)
        kum_invest_pv += invest_jahr_pv
        kum_solar += years_data[year]['solar']

        # Brutto-Ersparnis (wie Solarweb)
        brutto_ersparnis = years_data[year]['ersparnis_solar']
        kum_brutto_ersparnis_pv += brutto_ersparnis

        # Netz-Kosten (was tatsächlich bezahlt wird, inkl. Grundpreis)
        netz_kosten = years_data[year]['kosten_strom']

        # Fortschritt: Wie viel % der Investition sind bisher gedeckt
        fortschritt_pv = (kum_brutto_ersparnis_pv / gesamt_invest_pv * 100) if gesamt_invest_pv > 0 else 0

        # EUR/kWh PV-Anlage (real): Was hat jede kWh gekostet?
        eur_kwh_real = kum_invest_pv / kum_solar if kum_solar > 0 else 0

        # EUR/kWh PV-Anlage (25J): Prognose mit 18.000 kWh/Jahr ab 2026
        jahre_seit_start = year - 2021 + 1
        jahre_verbleibend = 25 - jahre_seit_start
        solar_prognose_25j = kum_solar + (jahre_verbleibend * 18000)
        eur_kwh_25j = kum_invest_pv / solar_prognose_25j if solar_prognose_25j > 0 else 0

        amort_pv_data.append({
            'year': year,
            'solar': years_data[year]['solar'],
            'brutto_ersparnis': brutto_ersparnis,
            'netz_kosten': netz_kosten,
            'kum_ersparnis': kum_brutto_ersparnis_pv,
            'fortschritt': fortschritt_pv,
            'eur_kwh_real': eur_kwh_real,
            'eur_kwh_25j': eur_kwh_25j,
        })

    # PV-Amortisationsprognose: Wann wird 100% erreicht?
    if amort_pv_data and kum_brutto_ersparnis_pv > 0:
        rest_pv = gesamt_invest_pv - kum_brutto_ersparnis_pv
        letzte_jahre = amort_pv_data[-2:] if len(amort_pv_data) >= 2 else amort_pv_data[-1:]
        avg_ersparnis_pv = sum(d['brutto_ersparnis'] for d in letzte_jahre) / len(letzte_jahre)
        if rest_pv > 0 and avg_ersparnis_pv > 0:
            jahre_rest_pv = rest_pv / avg_ersparnis_pv
            amort_pv_jahr = amort_pv_data[-1]['year'] + round(jahre_rest_pv)
        else:
            amort_pv_jahr = amort_pv_data[-1]['year']  # Bereits amortisiert
    else:
        amort_pv_jahr = None

    # ========================================
    # HAUSHALTS-AMORTISATION (inkl. Wärmepumpe, alle Ersparnisse)
    # ========================================
    amort_haushalt_data = []
    kum_invest_haushalt = 0
    kum_ersparnis_haushalt = 0

    for year in sorted(years_data.keys()):
        # Investitionen in diesem Jahr (historisch: 2021 + 2024)
        invest_jahr_haushalt = 0
        if year == 2021:
            invest_jahr_haushalt = invest_pv_2021 + invest_wp_2021
        elif year == 2024:
            invest_jahr_haushalt = invest_pv_2024

        kum_invest_haushalt += invest_jahr_haushalt

        # Gesamt-Ersparnis (Strom-Netto + Heizung + Benzin)
        gesamt_ersparnis = years_data[year]['netto_ersparnis']
        kum_ersparnis_haushalt += gesamt_ersparnis

        # Netz-Kosten (was tatsächlich bezahlt wird, inkl. Grundpreis)
        netz_kosten = years_data[year]['kosten_strom']

        # Fortschritt: Wie viel % der Investition durch kumulierte Ersparnis gedeckt
        fortschritt_haushalt = (kum_ersparnis_haushalt / gesamt_invest_haushalt * 100) if gesamt_invest_haushalt > 0 else 0

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
            'kum_ersparnis': kum_ersparnis_haushalt,
            'fortschritt': fortschritt_haushalt,
            'eff_strompreis': eff_strompreis
        })

    # Haushalt-Amortisationsprognose: Wann wird 100% erreicht?
    if amort_haushalt_data and kum_ersparnis_haushalt > 0:
        rest_haushalt = gesamt_invest_haushalt - kum_ersparnis_haushalt
        letzte_jahre_h = amort_haushalt_data[-2:] if len(amort_haushalt_data) >= 2 else amort_haushalt_data[-1:]
        avg_ersparnis_h = sum(d['gesamt_ersparnis'] for d in letzte_jahre_h) / len(letzte_jahre_h)
        if rest_haushalt > 0 and avg_ersparnis_h > 0:
            jahre_rest_h = rest_haushalt / avg_ersparnis_h
            amort_haushalt_jahr = amort_haushalt_data[-1]['year'] + round(jahre_rest_h)
        else:
            amort_haushalt_jahr = amort_haushalt_data[-1]['year']
    else:
        amort_haushalt_jahr = None

    # ========================================
    # ENERGIEKOSTEN NACH TYP (Heizen, Mobilität, Haushalt)
    # ========================================
    # Kosten = verbrauchte kWh × eur_kwh_real (PV-Gestehungskosten, 1. Spalte).
    # Primärenergie wird aus den GEMESSENEN elektrischen kWh zurückgerechnet:
    #   Heizen:    thermisch = WP_el × SCOP + Heizpatrone_el;  Holz = thermisch / η_Holz
    #   Mobilität: Benzin   = (E-Auto_kWh / 15 × 100) / 100 × 6 l × 10 kWh/l
    #   Haushalt:  keine Hebelung (Strom = Endenergie, primär = elektrisch)
    # Rückwirkend: WP_el = WP_BASIS-Schätzung, wo waermepumpe_kwh (=0) fehlt.
    # Zukünftig:   WP_el = gemessenes waermepumpe_kwh.
    scop = config.SCOP_WAERMEPUMPE
    eta_holz = config.WIRKUNGSGRAD_HOLZKESSEL
    bev_100km = config.BEV_VERBRAUCH_KWH_100KM
    verbrenner_l = config.VERBRENNER_L_100KM
    kraftstoff_kwh_l = config.KRAFTSTOFF_KWH_PRO_L

    energy_costs_data = []
    kum_heiz_kosten = 0
    kum_mob_kosten = 0
    kum_haus_kosten = 0
    # Separate Amortisation für Energiekosten-Tabelle: Invest auf 2021 (Produktionsstart)
    kum_invest_ent = 0
    kum_solar_ent = 0

    for year in sorted(years_data.keys()):
        data = years_data[year]

        # eur_kwh_real EIGENSTÄNDIG berechnen: Investition auf 2021 (Produktionsstart)
        # 2021: PV (24k) + WP (12k) = 36k total
        if year == 2021:
            invest_jahr_ent = invest_pv_2021 + invest_wp_2021
        elif year == 2024:
            invest_jahr_ent = invest_pv_2024
        else:
            invest_jahr_ent = 0
        
        kum_invest_ent += invest_jahr_ent
        kum_solar_ent += data['solar']
        eur_kwh_real = kum_invest_ent / kum_solar_ent if kum_solar_ent > 0 else 0

        # HEIZEN — gemessenes waermepumpe_kwh, sonst WP_BASIS-Schätzung (rückwirkend)
        wp_measured = data['heizpatrone']  # DB-Spalte waermepumpe_kwh (ab 2026 gemessen)
        wp_electric = wp_measured if wp_measured > 0 else wp_basis.get(year, 0)
        heizpatrone_electric = data['heizpatrone_el']  # gemessen (heizpatrone_kwh)
        heating_kwh_electric = wp_electric + heizpatrone_electric
        heating_kwh_thermal = wp_electric * scop + heizpatrone_electric  # Heizpatrone COP≈1
        heating_kwh_primary = heating_kwh_thermal / eta_holz if eta_holz > 0 else 0
        heating_cost_year = heating_kwh_electric * eur_kwh_real
        kum_heiz_kosten += heating_cost_year
        heating_cost_per_kwh_primary = heating_cost_year / heating_kwh_primary if heating_kwh_primary > 0 else 0

        # MOBILITÄT — gemessenes Wattpilot-Laden
        mobility_kwh_electric = data['wattpilot']
        mobility_km = (mobility_kwh_electric / bev_100km) * 100 if mobility_kwh_electric > 0 else 0
        mobility_kwh_primary = (mobility_km / 100.0) * verbrenner_l * kraftstoff_kwh_l
        mobility_cost_year = mobility_kwh_electric * eur_kwh_real
        kum_mob_kosten += mobility_cost_year
        mobility_cost_per_kwh_primary = mobility_cost_year / mobility_kwh_primary if mobility_kwh_primary > 0 else 0

        # HAUSHALT — Spezial-Behandlung für 2021: Solar + Netzstrom mit unterschiedlichen Preisen
        if year == 2021:
            # 2021: Heizen & Mobilität noch nicht unterstützt (0 kWh)
            # Haushalt = Solar-Produktion (501 kWh zu Invest-Preis) + Netzbezug (1168 kWh zu Strompreis)
            household_kwh_solar = data['solar']  # 501 kWh zu eur_kwh_real
            household_kwh_netz = data['netz_bezug']  # 1168 kWh zu strompreis_jahr (0,30€/kWh)
            household_kwh = household_kwh_solar + household_kwh_netz
            # Kosten: Solar zu Investitions-Preis + Netz zu tatsächlichem Strompreis
            strompreis_2021 = 0.30  # tatsächlicher Strompreis 2021 (€/kWh)
            household_cost_year = (household_kwh_solar * eur_kwh_real) + (household_kwh_netz * strompreis_2021)
            household_cost_per_kwh = household_cost_year / household_kwh if household_kwh > 0 else 0
        else:
            # Normalfall (2022+): Haushalt = Rest des Gesamtverbrauchs nach Heiz & Mob
            household_kwh = max(0, data['gesamt_verbr'] - heating_kwh_electric - mobility_kwh_electric)
            household_cost_year = household_kwh * eur_kwh_real
            household_cost_per_kwh = eur_kwh_real  # Strom ist Endenergie
        
        kum_haus_kosten += household_cost_year

        # PRIMÄRENERGIE gesamt (real) — Kosten pro kWh ersetzter Primärenergie
        total_primary_energy = heating_kwh_primary + mobility_kwh_primary + household_kwh
        total_cost_year = heating_cost_year + mobility_cost_year + household_cost_year
        total_primary_cost_per_kwh = total_cost_year / total_primary_energy if total_primary_energy > 0 else 0

        energy_costs_data.append({
            'year': year,
            'eur_kwh_real': eur_kwh_real,
            # Heizen
            'heating_kwh_electric': heating_kwh_electric,
            'heating_kwh_primary': heating_kwh_primary,
            'heating_cost_year': heating_cost_year,
            'heating_cost_kum': kum_heiz_kosten,
            'heating_cost_per_kwh_primary': heating_cost_per_kwh_primary,
            # Mobilität
            'mobility_kwh_electric': mobility_kwh_electric,
            'mobility_kwh_primary': mobility_kwh_primary,
            'mobility_cost_year': mobility_cost_year,
            'mobility_cost_kum': kum_mob_kosten,
            'mobility_cost_per_kwh_primary': mobility_cost_per_kwh_primary,
            # Haushalt
            'household_kwh': household_kwh,
            'household_cost_year': household_cost_year,
            'household_cost_kum': kum_haus_kosten,
            'household_cost_per_kwh': household_cost_per_kwh,
            # Primärenergie gesamt
            'total_primary_energy': total_primary_energy,
            'total_cost_year': total_cost_year,
            'total_primary_cost_per_kwh': total_primary_cost_per_kwh,
        })

    # ========================================
    # GESAMTSUMMEN für Templates
    # ========================================
    totals = {
        'solar': sum(d['solar'] for d in years_data.values()),
        'direkt': sum(d['direkt'] for d in years_data.values()),
        'batt_lad': sum(d['batt_lad'] for d in years_data.values()),
        'batt_entl': sum(d['batt_entl'] for d in years_data.values()),
        'netz_einsp': sum(d['netz_einsp'] for d in years_data.values()),
        'netz_bezug': sum(d['netz_bezug'] for d in years_data.values()),
        'gesamt_verbr': sum(d['gesamt_verbr'] for d in years_data.values()),
        'kosten_strom': sum(d['kosten_strom'] for d in years_data.values()),
        'ersparnis_solar': sum(d['ersparnis_solar'] for d in years_data.values()),
        'netto_ersparnis_strom': sum(d['netto_ersparnis_strom'] for d in years_data.values()),
        'heiz_ersparnis': sum(d['heiz_ersparnis'] for d in years_data.values()),
        'benzin_ersparnis': sum(d['benzin_ersparnis'] for d in years_data.values()),
        'netto_ersparnis': sum(d['netto_ersparnis'] for d in years_data.values()),
        'wattpilot': sum(d['wattpilot'] for d in years_data.values()),
        'sonnenstunden': sum(d.get('sonnenstunden', 0) or 0 for d in years_data.values()),
        'monate': sum(d['monate'] for d in years_data.values()),
    }
    totals['autarkie'] = ((1 - (totals['netz_bezug'] / totals['gesamt_verbr'])) * 100) if totals['gesamt_verbr'] > 0 else 0
    totals['batt_wirkungsgrad'] = (totals['batt_entl'] / totals['batt_lad'] * 100) if totals['batt_lad'] > 0 else 0
    totals['km_gefahren'] = sum(d.get('km_gefahren', 0) or 0 for d in years_data.values())
    weighted_kwp_sum = sum(
        _get_installed_kwp_for_month(row[0], row[1])
        for row in monthly_rows
    )
    totals['spez_ertrag'] = (totals['solar'] / (weighted_kwp_sum / 12.0)) if weighted_kwp_sum > 0 else 0

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

    # PV-Anlage-Grenzwerte: jährliche Min/Max-Netzextremwerte (Spannung L-L, Frequenz)
    # Quelle: data_monthly (Spannung L-N → L-L via √3, Frequenz). Permanent (~10 Jahre).
    pv_grenzwerte = _get_pv_grenzwerte_yearly(cursor)

    try:
        return render_template(template,
                             invest_pv_2021=invest_pv_2021,
                             invest_pv_2024=invest_pv_2024,
                             invest_wp_2021=invest_wp_2021,
                             gesamt_invest_pv=gesamt_invest_pv,
                             gesamt_invest_haushalt=gesamt_invest_haushalt,
                             yearly_data=list(years_data.values()),
                             amort_pv_data=amort_pv_data,
                             amort_haushalt_data=amort_haushalt_data,
                             energy_costs_data=energy_costs_data,
                             totals=totals,
                             amort_pv_jahr=amort_pv_jahr,
                             amort_haushalt_jahr=amort_haushalt_jahr,
                             current_year=current_year,
                             freq_extremes=freq_extremes,
                             pv_grenzwerte=pv_grenzwerte,
                             nav_query=('?' + nav_query) if nav_query else '')
    finally:
        conn.close()