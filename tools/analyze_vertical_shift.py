#!/usr/bin/env python3
"""
Analyse: Einfluss der 90°-Module auf die Tages-Leistungskurve.

Hypothese: Die senkrechten SSO-90°-Module (F3-S8) verschieben die
Ertragskurve nach morgens, besonders bei niedrigem Sonnenstand (Winter).
Die WSW-90°-Module (F2-S6+7) sind durch Gebäude/Bäume nachmittags eingeschränkt.

Analysiert für repräsentative Tage jedes Monats:
- Leistungsanteil 90°-Module an Gesamtleistung
- Morgendlicher vs. nachmittäglicher Ertrag der 90°-Module
- Schwerpunktzeit (Center of Power) mit und ohne 90°-Module
- Verschiebung der Peak-Zeit durch 90°-Module
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import solar_geometry as sg
from datetime import date, datetime, timedelta

# String-Indizes in PV_STRINGS identifizieren
SSO90_IDX = None
WSW90_IDX = None
for i, s in enumerate(sg.PV_STRINGS):
    if 'SSO-90' in s['name']:
        SSO90_IDX = i
    if 'WSW-90' in s['name']:
        WSW90_IDX = i

SSO90_NAME = sg.PV_STRINGS[SSO90_IDX]['name']
WSW90_NAME = sg.PV_STRINGS[WSW90_IDX]['name']

print(f"SSO-90° String: {SSO90_NAME} (idx {SSO90_IDX}, {sg.PV_STRINGS[SSO90_IDX]['kwp']} kWp)")
print(f"WSW-90° String: {WSW90_NAME} (idx {WSW90_IDX}, {sg.PV_STRINGS[WSW90_IDX]['kwp']} kWp)")
print(f"Gesamt-Anlage: {sum(s['kwp'] for s in sg.PV_STRINGS):.2f} kWp")
print()

# Repräsentative Tage (21. jedes Monats)
test_dates = [
    date(2026, 1, 21),   # Winter - niedrigster Sonnenstand
    date(2026, 2, 21),   # Spätwinter
    date(2026, 3, 21),   # Frühlingsbeginn (Tag = Nacht)
    date(2026, 4, 21),   # Frühling
    date(2026, 6, 21),   # Sommersonnenwende - höchster Sonnenstand
    date(2026, 9, 21),   # Herbstbeginn
    date(2026, 12, 21),  # Wintersonnenwende
]

print(f"{'Datum':>12} │ {'max_elev':>8} │ {'Gesamt':>8} │ {'SSO90':>8} │ {'WSW90':>8} │ "
      f"{'90°%':>5} │ {'SSO%':>5} │ {'WSW%':>5} │ "
      f"{'CoP_all':>7} │ {'CoP_o90':>7} │ {'Shift':>6} │ "
      f"{'Peak_all':>8} │ {'Peak_o90':>8} │ {'PkShft':>6}")
print("─" * 160)

for d in test_dates:
    curve = sg.get_clearsky_day_curve(d, interval_min=5)
    
    total_energy = 0          # Wh gesamt
    sso90_energy = 0          # Wh SSO-90°
    wsw90_energy = 0          # Wh WSW-90°
    other_energy = 0          # Wh ohne 90°-Module
    
    weighted_time_all = 0     # Für Center of Power (alle)
    weighted_time_other = 0   # Für Center of Power (ohne 90°)
    
    peak_power_all = 0
    peak_time_all = None
    peak_power_other = 0
    peak_time_other = None
    max_elev = 0
    
    # Vormittag/Nachmittag Analyse (bezogen auf Sonnenhöchststand ~12:00-13:00 MEZ)
    sso90_morning = 0   # vor 12:30
    sso90_afternoon = 0 # nach 12:30
    wsw90_morning = 0
    wsw90_afternoon = 0
    
    for p in curve:
        ac = p['total_ac']
        if ac <= 0:
            continue
            
        s = p.get('strings', {})
        sso = s.get(SSO90_NAME, 0)
        wsw = s.get(WSW90_NAME, 0)
        rest = ac - (sso + wsw) * sg.INVERTER_EFFICIENCY.get(sg.PV_STRINGS[SSO90_IDX]['inverter'], 0.96)
        # Vereinfachung: AC-Anteil der 90°-Module ≈ DC * inv_eff
        sso_ac = sso * sg.INVERTER_EFFICIENCY.get(sg.PV_STRINGS[SSO90_IDX]['inverter'], 0.96)
        wsw_ac = wsw * sg.INVERTER_EFFICIENCY.get(sg.PV_STRINGS[WSW90_IDX]['inverter'], 0.96)
        other_ac = ac - sso_ac - wsw_ac
        
        elev = p.get('sun_elevation', 0)
        if elev > max_elev:
            max_elev = elev
        
        dt = datetime.fromtimestamp(p['timestamp'])
        hour_frac = dt.hour + dt.minute / 60.0
        
        # Energie (5min = 1/12 Stunde)
        dt_h = 5.0 / 60.0
        total_energy += ac * dt_h
        sso90_energy += sso_ac * dt_h
        wsw90_energy += wsw_ac * dt_h
        other_energy += other_ac * dt_h
        
        # Gewichtete Zeit für Center of Power
        weighted_time_all += hour_frac * ac * dt_h
        weighted_time_other += hour_frac * other_ac * dt_h
        
        # Peak-Tracking
        if ac > peak_power_all:
            peak_power_all = ac
            peak_time_all = hour_frac
        if other_ac > peak_power_other:
            peak_power_other = other_ac
            peak_time_other = hour_frac
        
        # Vormittag/Nachmittag (Grenze 12:30 MEZ ≈ solarer Mittag)
        if hour_frac < 12.5:
            sso90_morning += sso_ac * dt_h
            wsw90_morning += wsw_ac * dt_h
        else:
            sso90_afternoon += sso_ac * dt_h
            wsw90_afternoon += wsw_ac * dt_h
    
    if total_energy > 0:
        cop_all = weighted_time_all / total_energy
        cop_other = weighted_time_other / other_energy if other_energy > 0 else 0
        shift_min = (cop_all - cop_other) * 60  # Verschiebung in Minuten
        
        pct_90 = (sso90_energy + wsw90_energy) / total_energy * 100
        pct_sso = sso90_energy / total_energy * 100
        pct_wsw = wsw90_energy / total_energy * 100
        
        pk_all_str = f"{int(peak_time_all // 1)}:{int((peak_time_all % 1) * 60):02d}"
        pk_oth_str = f"{int(peak_time_other // 1)}:{int((peak_time_other % 1) * 60):02d}" if peak_time_other else "---"
        pk_shift = (peak_time_all - peak_time_other) * 60 if peak_time_other else 0
        
        cop_all_str = f"{int(cop_all // 1)}:{int((cop_all % 1) * 60):02d}"
        cop_oth_str = f"{int(cop_other // 1)}:{int((cop_other % 1) * 60):02d}"
        
        print(f"{d.strftime('%Y-%m-%d'):>12} │ {max_elev:>7.1f}° │ "
              f"{total_energy/1000:>7.1f}k │ {sso90_energy/1000:>7.2f}k │ {wsw90_energy/1000:>7.2f}k │ "
              f"{pct_90:>4.1f}% │ {pct_sso:>4.1f}% │ {pct_wsw:>4.1f}% │ "
              f"{cop_all_str:>7} │ {cop_oth_str:>7} │ {shift_min:>+5.1f}m │ "
              f"{pk_all_str:>8} │ {pk_oth_str:>8} │ {pk_shift:>+5.0f}m")
    
    # Detail: Vor-/Nachmittag-Asymmetrie der 90°-Module
    if sso90_energy > 0:
        sso_ratio = sso90_morning / (sso90_morning + sso90_afternoon) * 100 if (sso90_morning + sso90_afternoon) > 0 else 0
        wsw_ratio = wsw90_morning / (wsw90_morning + wsw90_afternoon) * 100 if (wsw90_morning + wsw90_afternoon) > 0 else 0
        print(f"             │ SSO-90° Vormittag/Nachmittag: {sso90_morning:.0f}/{sso90_afternoon:.0f} Wh "
              f"({sso_ratio:.0f}% morgens)  │  WSW-90° VM/NM: {wsw90_morning:.0f}/{wsw90_afternoon:.0f} Wh "
              f"({wsw_ratio:.0f}% morgens)")

print()
print("═" * 80)
print("LEGENDE:")
print("  max_elev  = Maximale Sonnenhöhe am Tag")
print("  Gesamt    = Tages-Gesamtenergie (kWh, Clear-Sky)")
print("  SSO90/WSW90 = Energiebeitrag der 90°-Module (kWh)")
print("  90°%      = Anteil 90°-Module an Gesamtenergie")
print("  CoP_all   = Center of Power (alle Module)")
print("  CoP_o90   = Center of Power (ohne 90°-Module)")
print("  Shift     = Verschiebung durch 90°-Module (Minuten, - = nach morgens)")
print("  Peak_all  = Zeitpunkt Maximalleistung (alle Module)")
print("  Peak_o90  = Zeitpunkt Maximalleistung (ohne 90°)")
print("  PkShft    = Verschiebung Peakzeit (Minuten)")
