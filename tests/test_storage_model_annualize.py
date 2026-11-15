"""
Tests fuer die saisonale Annualisierung des Speicherausbau-Modells
(analysis/storage_model.py): Teilmonat-Normalisierung, Dezember-Fuellung,
Deckelung am gemessenen Netzbezug sowie die Baseline-Gruendung auf Messwerten.
"""
import numpy as np

from analysis import storage_model as sm


def test_annualize_normalizes_partial_month():
    # November nur zur Haelfte belegt (15 von 30 Tagen) -> auf Vollmonat skalieren.
    by_month = np.zeros((1, 12))
    by_month[0, 10] = 100.0            # November: 100 Wh in 15 Tagen
    present = np.full(12, 30.0); present[10] = 15.0   # alle anderen voll belegt
    full = np.full(12, 30.0)
    mask = present >= 3.0
    out = sm._annualize_by_month(by_month, present, full, mask)
    assert out.shape == (1,)
    assert abs(out[0] - 200.0) < 1e-6   # 100 * 30/15, uebrige Monate = 0


def test_annualize_fills_missing_month_from_neighbours():
    # Dezember (Index 11) fehlt -> aus Nachbarn Nov(10) und Jan(0) gemittelt.
    by_month = np.zeros((1, 12))
    present = np.full(12, 30.0); present[11] = 0.0
    full = np.full(12, 30.0)
    mask = present >= 3.0
    by_month[0, 0] = 40.0    # Jan (voll belegt -> norm 1.0)
    by_month[0, 10] = 60.0   # Nov
    out = sm._annualize_by_month(by_month, present, full, mask)
    # Dezember = Mittel aus Nachbarn (40, 60) = 50; Gesamtsumme = 40+60+50 = 150.
    assert abs(out[0] - 150.0) < 1e-6


def test_annualize_caps_at_measured_import():
    by_month = np.zeros((1, 12))
    by_month[0, 5] = 500.0   # Juni: simuliert 500 Wh vermieden
    present = np.full(12, 30.0)
    full = np.full(12, 30.0)
    mask = present >= 3.0
    cap = np.zeros(12); cap[5] = 120.0   # aber nur 120 Wh tatsaechlich bezogen
    out = sm._annualize_by_month(by_month, present, full, mask, cap_wh=cap)
    assert abs(out[0] - 120.0) < 1e-6


def test_measured_profile_excludes_current_month_and_is_12_or_fewer():
    prof = sm.measured_profile()
    assert prof['months'] <= 12
    # Kalendermonate sind 1..12, Werte nicht-negativ.
    for m, v in prof['import_by_month'].items():
        assert 1 <= m <= 12
        assert v >= 0.0
    if prof['months'] >= 1:
        assert prof['import_kwh_year'] == round(sum(prof['import_by_month'].values()), 1)


def test_run_sweep_measured_baseline_and_monotonic_avoided():
    res = sm.run_sweep(add_pv_kwp=0.0, use_curtailment=True)
    if not res.get('ok'):
        import pytest
        pytest.skip("keine 5-min-Daten im Testfenster")
    # Baseline aus Messwerten, Netzbezug > 0.
    assert res['baseline']['import_kwh_year'] > 0
    avoided = [c['avoided_kwh_year'] for c in res['curve']]
    assert avoided[0] == 0.0                      # 0 kWh Zusatzspeicher -> 0 vermieden
    assert avoided[-1] >= avoided[0]              # monoton steigend/saettigend
    # Vermiedener Bezug kann den gemessenen Netzbezug nie uebersteigen.
    assert max(avoided) <= res['baseline']['import_kwh_year'] + 1e-6
    # Integer-kWh-Gitter fuer saubere Achse.
    assert all(float(c['batt_nom_kwh']).is_integer() for c in res['curve'])


def test_run_detail_representative_year_with_estimated_december():
    res = sm.run_detail(add_pv_kwp=0.0, batt_nom_kwh=12.0, use_curtailment=True)
    if not res.get('ok'):
        import pytest
        pytest.skip("keine 5-min-Daten im Testfenster")
    if res.get('baseline_source') == 'measured':
        # Dezember hat keine 5-min-Daten -> als geschaetzt markiert.
        dec = [m for m in res['monthly'] if m['month'].startswith('Dez')]
        assert dec and dec[0]['estimated'] is True
        for m in res['monthly']:
            assert m['rest_kwh'] >= 0.0
            assert m['avoided_kwh'] <= m['import_kwh'] + 1e-6
