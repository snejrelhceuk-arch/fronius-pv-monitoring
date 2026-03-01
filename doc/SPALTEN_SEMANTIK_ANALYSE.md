# Spalten-Semantik-Analyse: `solar_erzeugung_kwh` im Archiv

**Datum:** 2025-02-23  
**Status:** Analyse abgeschlossen — KEINE Code-Änderungen  
**Auslöser:** Jährliche PV-Diskrepanz DB vs. Solarweb (−200 bis −455 kWh/Jahr)

---

## 1. Problemstellung

Beim Vergleich der Jahreswerte fiel auf, dass die DB-Spalte `solar_erzeugung_kwh`
systematisch niedriger liegt als Solarweb `gesamt_prod_kwh`:

| Jahr | Archiv Solar | Solarweb Prod | Δ (kWh) |
|------|-------------|---------------|---------|
| 2022 | 9 267       | 9 470         | −203    |
| 2023 | 9 798       | 10 100        | −302    |
| 2024 | 11 986      | 12 440        | −455    |
| 2025 | 15 940      | 16 330        | −390    |

Erste Vermutung war, dass F2/F3-Wechselrichter fehlen. 
Der Benutzer erkannte aber: „Spalte Solar ist OHNE Einspeisung und mit outBatt."

---

## 2. Hypothesen

Getestet über alle 48 Archivmonate (2022-01 bis 2025-12):

| Hypothese | Formel | Bedeutung |
|-----------|--------|-----------|
| **H1** | Dir + BattCh + Einsp | Echte Erzeugung (ohne WP) |
| **H2** | Dir + BattDis | Eigenverbrauch PV-Seite (ohne WP) |
| **H3** | Dir + BattCh | Teil-Erzeugung ohne Einsp (ohne WP) |
| **H1wp** | Dir + BattCh + Einsp + WP | Echte Erzeugung (mit WP) |
| **H2wp** | Dir + BattDis + WP | Eigenverbrauch PV-Seite (mit WP) |
| **H3wp** | Dir + BattCh + WP | Teil-Erzeugung ohne Einsp (mit WP) |

---

## 3. Ergebnis: H2wp ist eindeutiger Gewinner

### Aggregierte Fehler über 48 Monate

| Hypothese | ∑|Δ| (kWh) | Ø|Δ| (kWh/Monat) |
|-----------|------------|-------------------|
| H1        | 7 923.6    | 165.08            |
| H2        | 8 150.1    | 169.79            |
| H3        | 8 185.9    | 170.54            |
| **H1wp**  | 1 301.1    | 27.11             |
| **H2wp**  | **0.8**    | **0.02**          |
| H3wp      | 655.7      | 13.66             |

**H2wp trifft exakt:** Durchschnittliche Abweichung nur 0.02 kWh/Monat.

### Phasenverhalten

- **Phase 1 (2022-01 bis 2024-03):** Wattpilot = 0 → H2 (ohne WP) trifft exakt,
  jeder Monat ✓ (< 1 kWh).
- **Phase 2 (2024-04 bis 2025-12):** Wattpilot > 0 → nur H2wp trifft, jeder Monat
  |Δ| ≤ 0.1 kWh.

---

## 4. Bewiesene Identität

```
solar_erzeugung_kwh ≡ Direktverbrauch + Batterieentladung + Wattpilot
                    ≡ Eigenverbrauch (PV-seitig, NICHT echte Erzeugung)
```

Die Spalte enthält NICHT die PV-Erzeugung, sondern den PV-seitigen
Eigenverbrauch-Anteil. Der Name `solar_erzeugung_kwh` ist **irreführend**.

### Vergleich der Definitionen

| Metrik | Formel | Enthält Einspeisung? | Batteriekomponente |
|--------|--------|---------------------|--------------------|
| **Archiv „Solar"** | Dir + Dis + WP | Nein | Entladung (Output) |
| **Solarweb „Erzeugung"** | Dir + Ch + Einsp + WP | Ja | Ladung (Input) |

### Mathematische Differenz

```
Δ = Solar_Archiv − SW_Erzeugung
  = (Dir + Dis + WP) − (Dir + Ch + Einsp + WP)
  = Dis − Ch − Einsp
  = −(Netto-Batterieladung) − Einspeisung
```

Geprüft pro Jahr:

| Jahr | Erwartet (Archiv) | Tatsächlich (vs SW) | Rest-Δ |
|------|-------------------|---------------------|--------|
| 2022 | −196.6            | −202.6              | 6.0    |
| 2023 | −310.7            | −301.9              | 8.8    |
| 2024 | −452.3            | −454.5              | 2.2    |
| 2025 | −377.7            | −390.0              | 12.3   |

Die Rest-Δ (2–12 kWh) sind vollständig durch Solarwebs Rundung auf ~10 kWh erklärt.

---

## 4b. ⚠️ Solarweb-Wattpilot ist KEIN echter Verbrauchswert

**Kritische Erkenntnis (2026-03-01):** Die Solarweb-Spalte `wattpilot_kwh` enthält
**ausschließlich den PV-Direkt-Anteil** der EV-Ladung. Netz→EV-Strom wird von Solarweb
nicht als Wattpilot ausgewiesen — er verschwindet im allgemeinen `netzbezug_kwh`.

Daraus folgt:
- `solarweb.wattpilot_kwh` ist eine **Teilmenge** von `solarweb.direkt_kwh + solarweb.wattpilot_kwh`
- Unser `wattpilot_daily` zählt einfach den Gesamtverbrauch des Wattpilot (PV + Netz, keine Quellenunterscheidung)
- Ein direkter Vergleich `solarweb.wattpilot ↔ unser.wattpilot_daily` ist **ungültig**
- Solarweb-Wattpilot darf nur **addiert zum Direktverbrauch** verglichen werden:
  ```
  solarweb.direkt + solarweb.wattpilot  ≈  unser.W_PV_Direct / 1000
  ```
- Ein eigenständiger Vergleich der Wattpilot-Spalte liefert systematisch falsche Deltas

---

## 5. Komponentenvergleich Archiv vs. Solarweb

Alle Einzelkomponenten stimmen hervorragend überein (Δ = SW-Rundung):

| Jahr | Δ-Direkt | Δ-Einsp | Δ-BattCh | Δ-BattDis | Δ-WP  | Δ-Bezug |
|------|----------|---------|----------|-----------|-------|---------|
| 2022 | +0.1     | −3.9    | −0.6     | −1.1      | 0.0   | −10.5   |
| 2023 | −7.5     | +16.6   | −0.1     | −4.2      | 0.0   | −7.3    |
| 2024 | +2.6     | −0.5    | −0.7     | −3.6      | −3.7  | −8.9    |
| 2025 | +6.6     | −0.7    | −1.7     | −0.0      | +3.2  | +4.7    |

**Fazit:** Die Archivdaten selbst sind korrekt. Alle Komponenten stimmen mit
Solarweb überein. Nur die Spalte `solar_erzeugung_kwh` bildet eine andere
Kennzahl als Solarwebs „Erzeugung".

---

## 6. Konsequenzen

### Was NICHT das Problem ist
- ❌ F2/F3-Wechselrichter fehlen — Daten stimmen, es ist ein Definitionsproblem
- ❌ Datenqualität der Archiv-CSVs — Einzelkomponenten sind korrekt
- ❌ Aggregationsfehler — Monatssummen stimmen auf 0.02 kWh

### Was das Problem ist
- ⚠️ Der Spaltenname `solar_erzeugung_kwh` suggeriert „PV-Erzeugung", enthält
  aber Eigenverbrauch
- ⚠️ In der DB/Web-Anzeige wird damit die PV-Erzeugung unterschätzt
- ⚠️ Eigenverbrauchsquote, Autarkiegrad und ähnliche KPIs können falsch berechnet
  werden, wenn `solar_erzeugung_kwh` als Erzeugung interpretiert wird

### Korrekte Erzeugung aus Archivdaten ableitbar

Die echte PV-Erzeugung lässt sich aus den vorhandenen Archiv-Komponenten berechnen:
```
PV_Erzeugung = Direktverbrauch + Batterieladung + Einspeisung + Wattpilot
             = H1wp
```

Jahresvergleich H1wp vs. Solarweb:

| Jahr | H1wp (Archiv) | SW-Prod | Δ     |
|------|---------------|---------|-------|
| 2022 | 9 465.6       | 9 470   | −4.4  |
| 2023 | 10 109.0      | 10 100  | +9.0  |
| 2024 | 12 437.7      | 12 440  | −2.3  |
| 2025 | 16 317.5      | 16 330  | −12.5 |

Δ = 2–13 kWh → exzellente Übereinstimmung (Solarweb-Rundung).

---

## 7. F2/F3-Thema

Der Benutzer stellte fest: „F2/F3 zählen erst seit Okt. 2026."

Das F2/F3-Thema ist **unabhängig** von dieser Spalten-Semantik-Analyse:
- Die hier analysierten Archivdaten (2022–2025) stammen aus F1 über Solarweb
- F2/F3 betreffen erst zukünftige Monate
- Wenn F2/F3 hinzukommen, wird die „echte Erzeugung" höher als F1 allein

---

## 8. Offene Entscheidung

Ob und wie die Spalte `solar_erzeugung_kwh` korrigiert werden soll, ist
eine **bewusste Designentscheidung** und wird hier nur dokumentiert:

### Option A: Spalte umbenennen
- `solar_erzeugung_kwh` → `solar_eigenverbrauch_kwh`
- Neue Spalte `pv_erzeugung_kwh` = Dir + Ch + Einsp + WP

### Option B: Spalteninhalt korrigieren
- `solar_erzeugung_kwh` behält den Namen
- Inhalt wird auf Dir + Ch + Einsp + WP umgestellt  
- Betrifft: `aggregate_statistics.py`, Import-Logik, Web-Anzeige

### Option C: Status quo beibehalten
- Spalte bleibt wie sie ist
- Dokumentiere die Semantik explizit
- Leite Erzeugung in der Anzeige dynamisch ab

**Aktuell gewählt: Keine Änderung (nur Analyse + Dokumentation).**
