#!/usr/bin/env python3
"""
Analyse: Auswirkung der WSW-90°-Beschattung auf die Leistungskurve.

Die WSW-90°-Module (F2-S6+7) werden in Realität nachmittags durch Gebäude 
und Bäume beschattet. Das Clear-Sky-Modell rechnet jedoch volle Einstrahlung.

Diese Analyse zeigt:
1. Wie stark sich die Kurve verschiebt, wenn WSW-90° nachmittags abgeschattet wird
2. Ab welcher Uhrzeit die Beschattung einsetzt (je nach Jahreszeit)
3. Wie viel Energie dadurch "fehlt" (→ Clear-Sky Überschätzung nachmittags)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import solar_geometry as sg
from datetime import date, datetime, timedelta

# String-Namen direkt aus PV_STRINGS
SSO90_NAME = None
WSW90_NAME = None
for s in sg.PV_STRINGS:
    if 'SSO-90' in s['name']:
        SSO90_NAME = s['name']
        SSO90_INV = s['inverter']
    if 'WSW-90' in s['name']:
        WSW90_NAME = s['name']
        WSW90_INV = s['inverter']

test_dates = [
    (date(2026, 1, 21), "Winter"),
    (date(2026, 3, 21), "Frühling"),
    (date(2026, 6, 21), "Sommer"),
    (date(2026, 9, 21), "Herbst"),
    (date(2026, 12, 21), "Wintersonnenwende"),
]

print("=" * 100)
print("SIMULATION: WSW-90° Beschattung ab verschiedenen Uhrzeiten")
print("Vergleich Center-of-Power und Peak-Verschiebung")
print("=" * 100)

for d, label in test_dates:
    curve = sg.get_clearsky_day_curve(d, interval_min=5)
    
    # Stündliche Leistung der WSW-90° Module
    print(f"\n{'─'*100}")
    print(f"  {d.strftime('%Y-%m-%d')} ({label}) - max Sonnenhöhe: ", end="")
    max_elev = max(p.get('sun_elevation', 0) for p in curve)
    print(f"{max_elev:.1f}°")
    
    # WSW-90° Tagesverlauf (stündlich)
    print(f"\n  Uhrzeit │ Gesamt │ WSW-90° │ SSO-90° │ Rest  │ SonnenAz │ Elev")
    print(f"  {'─'*70}")
    
    for p in curve:
        if p['total_ac'] <= 0:
            continue
        dt = datetime.fromtimestamp(p['timestamp'])
        if dt.minute != 0:
            continue
        s = p.get('strings', {})
        wsw = s.get(WSW90_NAME, 0) * sg.INVERTER_EFFICIENCY.get(WSW90_INV, 0.96)
        sso = s.get(SSO90_NAME, 0) * sg.INVERTER_EFFICIENCY.get(SSO90_INV, 0.96)
        rest = p['total_ac'] - wsw - sso
        az = p.get('sun_azimuth', 0)
        elev = p.get('sun_elevation', 0)
        bar_wsw = '█' * int(wsw / 200)
        bar_sso = '▓' * int(sso / 200)
        print(f"  {dt.strftime('%H:%M')} │ {p['total_ac']:>5.0f}W │ {wsw:>6.0f}W {bar_wsw:<15} │ "
              f"{sso:>6.0f}W {bar_sso:<15} │ {rest:>5.0f}W │ {az:>7.1f}° │ {elev:.1f}°")

    # Szenarien: WSW-90° Beschattung ab verschiedenen Uhrzeiten
    shading_scenarios = [
        ("Keine Beschattung", 24, 0),     # Referenz
        ("50% ab 14:00", 14.0, 0.5),
        ("50% ab 15:00", 15.0, 0.5),
        ("75% ab 14:00", 14.0, 0.75),
        ("75% ab 15:00", 15.0, 0.75),
        ("100% ab 15:00", 15.0, 1.0),
        ("100% ab 16:00", 16.0, 1.0),
    ]
    
    print(f"\n  Beschattungs-Szenarien:")
    print(f"  {'Szenario':<25} │ {'Energie':>8} │ {'Diff':>6} │ {'CoP':>7} │ {'CoP-Shift':>9} │ {'Peak':>5} │ {'PkShift':>7}")
    print(f"  {'─'*85}")
    
    ref_cop = None
    ref_energy = None
    
    for name, shade_start, shade_pct in shading_scenarios:
        total_e = 0
        weighted_t = 0
        peak_p = 0
        peak_t = None
        
        for p in curve:
            ac = p['total_ac']
            if ac <= 0:
                continue
            
            dt = datetime.fromtimestamp(p['timestamp'])
            hour_frac = dt.hour + dt.minute / 60.0
            
            s = p.get('strings', {})
            wsw_dc = s.get(WSW90_NAME, 0)
            wsw_ac = wsw_dc * sg.INVERTER_EFFICIENCY.get(WSW90_INV, 0.96)
            
            # Beschattung anwenden
            if hour_frac >= shade_start:
                shaded_ac = ac - wsw_ac * shade_pct
            else:
                shaded_ac = ac
            
            dt_h = 5.0 / 60.0
            total_e += shaded_ac * dt_h
            weighted_t += hour_frac * shaded_ac * dt_h
            
            if shaded_ac > peak_p:
                peak_p = shaded_ac
                peak_t = hour_frac
        
        if total_e > 0:
            cop = weighted_t / total_e
            if ref_cop is None:
                ref_cop = cop
                ref_energy = total_e
            
            shift = (cop - ref_cop) * 60
            ediff = (total_e - ref_energy) / 1000
            cop_str = f"{int(cop // 1)}:{int((cop % 1) * 60):02d}"
            pk_str = f"{int(peak_t // 1)}:{int((peak_t % 1) * 60):02d}" if peak_t else "---"
            
            print(f"  {name:<25} │ {total_e/1000:>7.1f}k │ {ediff:>+5.1f}k │ "
                  f"{cop_str:>7} │ {shift:>+8.1f}m │ {pk_str:>5} │ "
                  f"{'(Ref)' if shift == 0 else f'{shift:>+6.1f}m'}")
    
    ref_cop = None
    ref_energy = None

print(f"\n{'='*100}")
print("FAZIT:")
print("  Die WSW-90°-Beschattung nachmittags verschiebt die Kurve nach LINKS (morgens)")
print("  → In der Realität erscheint die Ertragskurve morgens-lastiger als das Clear-Sky-Modell")
print("  → string_factor für WSW-90° < 1.0 oder zeitabhängiges Schattenprofil in geometry_config.json")
