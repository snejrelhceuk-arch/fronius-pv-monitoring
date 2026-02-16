# Darstellungskonventionen für Fronius PV-Monitoring

> **Version 2.0** — 9. Februar 2026  
> Verbindlich für alle Frontend-Anzeigen (tag_view, echtzeit_view, analyse).

---

## 1. Universelle Wert-Formatierung (`formatValue`)

### Implementiert in: `templates/tag_view.html`

Zentrale JS-Funktion `formatValue(value, unit)` mit automatischer SI-Präfix-Skalierung.

### Formatierungs-Regeln

| Absoluter Wert | Dezimalstellen | Beispiel |
|----------------|---------------|----------|
| < 10 | 2 | `3,47 kWh` |
| 10 – 999 | 1 | `142,5 kWh` |
| 1.000 – 99.999 | 0 (Tausendertrenner) | `15.940 kWh` |
| ≥ 100.000 | Nächster SI-Präfix, dann o.g. Regeln | `123,4 MWh` |

### SI-Präfix-Kette

```
(Basis) → k → M → G → T
```

**Beispiele für verschiedene Einheiten:**

| Wert | Einheit | Ausgabe |
|------|---------|---------|
| 345 | W | `345,0 W` |
| 1234 | W | `1.234 W` |
| 150000 | W | `150,0 kW` |
| 3.47 | kWh | `3,47 kWh` |
| 4905 | kWh | `4.905 kWh` |
| 123456 | kWh | `123,5 MWh` |
| 1234 | EUR | `1.234 EUR` |
| 150000 | EUR | `150,0 kEUR` |
| 456 | VA | `456,0 VA` |
| 2340 | VA | `2.340 VA` |
| 150000 | VA | `150,0 kVA` |

### Hilfs-Funktionen

| Funktion | Zweck | Beispiel |
|----------|-------|---------|
| `formatValue(val, unit)` | Universell, beliebige Einheit | `formatValue(4905, 'kWh')` → `4.905 kWh` |
| `formatEnergy(val)` | Kurzform für kWh | `formatEnergy(4905)` → `4.905 kWh` |
| `formatAxisValue(val)` | Y-Achse (ohne Einheit) | `formatAxisValue(15940)` → `15.940` |

### Besonderheiten

- **Locale:** `de-DE` (Komma als Dezimaltrennzeichen, Punkt als Tausendertrenner)
- **null/undefined/NaN:** → `–` (Gedankenstrich)
- **forceDecimals:** Optionaler Parameter erzwingt fixe Nachkommastellen
- **Einheiten-Erkennung:** Bestehender Präfix wird erkannt (`kWh` hat bereits `k`, Skalierung startet bei `k`)

---

## 2. Einheiten nach Mess-Typ

| Präfix | Physikalische Größe | Basis-Einheit | Auto-Skalierung |
|--------|---------------------|---------------|-----------------|
| `U_*` | Spannung | V | nein (immer < 1000) |
| `I_*` | Stromstärke | A | nein (immer < 1000) |
| `P_*` | Wirkleistung | W | W → kW → MW |
| `S_*` | Scheinleistung | VA | VA → kVA |
| `Q_*` | Blindleistung | VAr | VAr → kVAr |
| `W_*` | Energie | Wh / kWh | kWh → MWh → GWh |
| `f_*` | Frequenz | Hz | nein (immer 49-51) |
| `PF_*` | Leistungsfaktor | – | nein |
| `SOC_*` | State of Charge | % | nein |
| `T_*` | Temperatur | °C | nein |

---

## 3. Anwendungsbereiche

### Tag-/Monat-/Jahr-/Gesamt-View (tag_view.html)

**Daten kommen als kWh vom Server.** Formatierung via `formatEnergy()`:

| Ansicht | Typischer Bereich | Beispiel |
|---------|-------------------|---------|
| Tag (Summary) | 5–80 kWh | `47,32 kWh` |
| Monat (Tooltip) | 30–2000 kWh | `1.922 kWh` |
| Jahr (Tooltip) | 500–16000 kWh | `15.940 kWh` |
| Gesamt (Summary) | 500–60000 kWh | `48.165 kWh` |

### Echtzeit-View (echtzeit_view.html)

**Daten kommen als W/A/V/Hz vom Server.** Aktuell noch ohne `formatValue()`.

| Typ | Typischer Bereich | Aktuell | TODO |
|-----|-------------------|---------|------|
| P_AC | 0–10.000 W | `5395 W` | `5.395 W` |
| P_Netz | -6000..+6000 W | `-2146 W` | `-2.146 W` |
| U_Netz | 230–240 V | OK | OK |
| f_Netz | 49.8–50.2 Hz | OK (2 Dez.) | OK |

### Analyse-View (analyse.html)

**Server-seitiges Jinja2-Formatting** mit `{:,.0f}` (Komma als Tausendertrenner):

```jinja2
{{ "{:,.0f}".format(year.solar) }} kWh    →  "15,940 kWh"
{{ "{:,.2f}".format(year.kosten_strom) }} €  →  "1,618.53 €"
```

> ⚠️ **Achtung:** Jinja2 nutzt US-Komma (`,` = Tausender). Für deutsche Ausgabe (`15.940`)
> müsste ein Custom-Filter implementiert werden. Aktuell toleriert.

---

## 4. Bedingte Einfärbung

| Feld | Bedingung | Farbe | Bedeutung |
|------|-----------|-------|-----------|
| `P_Netz` | > 0 | 🔴 Rot | Bezug |
| `P_Netz` | < 0 | 🟢 Grün | Einspeisung |
| `SOC_Batt` | > 40% | 🟢 Grün | OK |
| `SOC_Batt` | 20-40% | 🟠 Orange | Niedrig |
| `SOC_Batt` | < 20% | 🔴 Rot | Kritisch |

---

## 5. CSS-Konventionen

```css
.value-aligned {
    font-variant-numeric: tabular-nums;
    text-align: right;
    font-family: 'Courier New', Consolas, monospace;
}
.label { font-family: Arial; color: #333; }
.value { font-family: 'Courier New'; font-weight: bold; }
.unit  { font-family: Arial; font-size: 0.9em; color: #666; margin-left: 0.2em; }
```

---

## 6. Nicht implementiert / Nicht geplant

| Feature | Status | Grund |
|---------|--------|-------|
| `units.py` (Python-seitig) | ❌ Verworfen | Formatierung gehört ins Frontend |
| Trend-Indikatoren (↗↘→) | 💬 Offen | Noch nicht priorisiert |
| Sparklines | 💬 Offen | |
| Responsive Genauigkeit | ❌ | Zu komplex |
| Komma→Punkt Umstellung | ❌ | JSON-Kompatibilität |
