from routes.pages import _build_energy_costs_data


def test_energy_costs_use_pv_only_price_and_additional_investments():
    years_data = {
        2021: {
            'solar': 1000,
            'direkt': 1000,
            'wattpilot': 0,
            'heizpatrone': 1000,
            'heizpatrone_el': 100,
            'gesamt_verbr': 5000,
            'netz_bezug': 1000,
        },
        2024: {
            'solar': 1000,
            'direkt': 500,
            'wattpilot': 500,
            'heizpatrone': 1000,
            'heizpatrone_el': 100,
            'gesamt_verbr': 5000,
            'netz_bezug': 1000,
        },
    }

    rows = _build_energy_costs_data(
        years_data,
        invest_pv_2021=24000,
        invest_pv_2024=8000,
        invest_wp_2021=12000,
        invest_wallbox_2024=2000,
        scop=3.7,
        eta_holz=0.5,
        bev_100km=15.0,
        verbrenner_l=6.0,
        kraftstoff_kwh_l=10.0,
    )

    assert rows[0]['eur_kwh_real'] == 24.0
    assert rows[0]['heating_investment'] == 12000
    assert rows[1]['mobility_investment'] == 2000
    assert rows[0]['heating_cost_year'] == 0
    assert rows[0]['heating_cost_per_kwh_net'] == 24.0  # Spalte 1 - Spalte 2
    assert rows[0]['household_cost_per_kwh'] == 24.0  # identisch mit Spalte 1


def test_heating_fallback_uses_estimated_wp_energy_and_wood_costs():
    rows = _build_energy_costs_data(
        {
            2021: {
                'solar': 0,
                'direkt': 0,
                'wattpilot': 0,
                'heizpatrone': 0,
                'heizpatrone_el': 0,
                'gesamt_verbr': 0,
                'netz_bezug': 0,
                'heizmonate': 2,
            },
            2022: {
                'solar': 0,
                'direkt': 0,
                'wattpilot': 0,
                'heizpatrone': 0,
                'heizpatrone_el': 0,
                'gesamt_verbr': 0,
                'netz_bezug': 0,
                'heizmonate': 6,
            },
        },
        invest_pv_2021=24000,
        invest_pv_2024=8000,
        invest_wp_2021=12000,
        scop=3.7,
        eta_holz=0.5,
        bev_100km=15.0,
        verbrenner_l=6.0,
        kraftstoff_kwh_l=10.0,
        wp_basis={2021: 0, 2022: 0},
        heizkosten_ersparnis={2021: 750, 2022: 1500},
    )

    assert rows[0]['heating_kwh_electric'] == 1500
    assert rows[0]['heating_kwh_useful'] == 5550.0
    assert rows[0]['heating_cost_year'] == 750
    assert rows[0]['heating_cost_per_kwh_nutzenergie'] == 750 / 5550.0
    assert abs(rows[0]['heating_cost_per_kwh_net'] - (4.0 - 750/5550.0)) < 0.01  # eur_kwh_real - Nutzenergie

    assert rows[1]['heating_kwh_electric'] == 3000
    assert rows[1]['heating_kwh_useful'] == 3000.0
    assert rows[1]['heating_cost_year'] == 1500
    assert rows[1]['heating_cost_per_kwh_nutzenergie'] == 1500 / 3000.0
    assert abs(rows[1]['heating_cost_per_kwh_net'] - (4.0 - 1500/3000.0)) < 0.01  # eur_kwh_real - Nutzenergie
