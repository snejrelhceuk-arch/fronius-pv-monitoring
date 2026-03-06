# Batterie-Management-Strategien (A–F)

## Systemübersicht

**Hardware:**
- Fronius Gen24 12 kW (F1) — Firmware PS: 1.6.1-30738, PS2: 3.5.6-23416
- 2× BYD Battery-Box Premium HVS 20,48 kWh (LFP-Chemie, parallel seit März 2026)
- SOH: 96% (BMS-Live), Zelltemp: 15–25 °C, Systemspannung: ~430 V

**Steuerungskanäle:**

| Kanal | Tool | Parameter | Latenz |
|-------|------|-----------|--------|
| **Fronius HTTP API** | `fronius_api.py` | SOCmin, SOCmax, SOCmode, Netzladung | ~200 ms |
| **SunSpec Modbus (Model 124)** | `battery_control.py` | Lade-/Entladerate, StorCtl_Mod, MinRsvPct, ChaGriSet | ~50 ms |

**Aktuelle Konfiguration (Stand 2026-02-12):**
```
SOC-Modus:          MANUAL
SOC Min:            25%  (Komfort)
SOC Max:            75%  (Komfort)
Netzladung:         EIN
AC-Ladung:          EIN
HYB_EM_MODE:        0 (AUTOMATIK)
StorCtl_Mod:        0 (kein Limit aktiv)
InWRte:             100% (≙ 20.480 W)
OutWRte:            100% (≙ 20.480 W)
ChaGriSet:          1 (Grid ON)
MinRsvPct:          25%
RvrtTms:            0 (KEIN Auto-Revert!)
```

**Scheduler:** **`pv-automation.service`** (systemd, Score-basierte Engine mit 12 Regelkreisen)
**Config:** `config/soc_param_matrix.json` (12 Regelkreise, 50+ Parameter)
**State:** `config/battery_scheduler_state.json` (Legacy)

---

## Strategien A–F (Kurzuebersicht)


> [BATTERY_ALGORITHM.md](BATTERY_ALGORITHM.md) dokumentiert.

| Strategie | Kurzbeschreibung | Details |
|----------|------------------|---------|
| A | SOC_MIN morgens oeffnen (tiefer entladen) | BATTERY_ALGORITHM.md, Abschnitt 3 |
| B | SOC_MAX an sonnigen Tagen begrenzen | BATTERY_ALGORITHM.md, Abschnitt 4 |
| C | Abends SOC_MIN anheben (Reserve) | BATTERY_ALGORITHM.md, Abschnitt 6/7 (Beispiele) |
| D | Abend-Entladebegrenzung (~3 kW) | BATTERY_ALGORITHM.md, Abschnitt 5b |
| E | Sommer-Ladebegrenzung (temperaturbasiert) | BATTERY_ALGORITHM.md, Abschnitt 5b + Konfig | 
| F | Nacht-Entladebegrenzung (~1 kW) | BATTERY_ALGORITHM.md, Abschnitt 5b |

## Tages-Zeitplan (nur Referenz)

Der konkrete Ablauf variiert nach Prognose. Siehe die Beispiele in
[BATTERY_ALGORITHM.md](BATTERY_ALGORITHM.md) Abschnitt 6 und 7.
---

## Technische Kontroll-Matrix

| Strategie | Parameter | Steuerkanal | Tool |
|-----------|-----------|-------------|------|
| A – Morgen-Freigabe | `BAT_M0_SOC_MIN` | HTTP API POST | `fronius_api.py` |
| B – Sonnentag-SOCmax | `BAT_M0_SOC_MAX` | HTTP API POST | `fronius_api.py` |
| C – Abend-Reserve | `BAT_M0_SOC_MIN/MAX` | HTTP API POST | `fronius_api.py` |
| D – Abend-Entlade | `OutWRte`, `StorCtl_Mod` | SunSpec Modbus | `battery_control.py` |
| E – Sommer-Lade | `InWRte`, `StorCtl_Mod` | SunSpec Modbus | `battery_control.py` |
| F – Nacht-Entlade | `OutWRte`, `StorCtl_Mod` | SunSpec Modbus | `battery_control.py` |

---

## Sicherheitshinweise

### RvrtTms = 0 (Kein Auto-Revert!)

**KRITISCH:** Der Wechselrichter hat `RvrtTms = 0`, d.h. gesetzte Modbus-Limits
werden NICHT automatisch zurückgesetzt. Wenn der Scheduler abstürzt, bleiben die
Limits aktiv!

**Mitigierung:**
1. **Tages-Reset:** `_apply_comfort_defaults()` setzt SOC + Modbus bei neuem Tag auf Komfort
2. **Konsistenz-Prüfung:** Actuator Read-Back verifiziert jede Änderung
3. **Retry-Logik:** `AktorBatterie` wiederholt API/Modbus-Calls 2× mit 1.5s Delay
4. **Engine-Zyklus:** Fast-Cycle 1 min, Strategic 15 min — versäumte Aktionen werden nachgeholt
5. **Fail-Safe Default:** Bei Engine-Ausfall → Komfort-Bereich bleibt aktiv:
   ```python
   # Komfort-Defaults (sicher für alle Szenarien)
   SOC_MIN=25%, SOC_MAX=75%, StorCtl_Mod=0
   ```

### ChaGriSet = 1 (Netzladung bleibt EIN)

Netzladung darf NICHT deaktiviert werden! Sie wird benötigt für:
- Notladung bei kritisch niedrigem SOC
- Support-SOC Funktion (falls aktiviert)
- Batterie-Kalibrierung

### Batterie-Schutz

- BYD HVS hat eigenes BMS mit Schutzmechanismen
- `HYB_BACKUP_CRITICALSOC = 10%` — Unterhalb wird nicht entladen
- LFP-Chemie: 3000+ Zyklen, robust gegen Tiefentladung
- **Empfehlung:** SOCmin nie unter 5% setzen

---

## Authentifizierung (Fronius HTTP API)

Die Fronius Gen24 interne API verwendet eine **nicht-standard HTTP Digest Auth**:

```
Server-Challenge:  X-WWW-Authenticate (nicht WWW-Authenticate!)
Algorithmus:       SHA256 für Response-Hash
HA1:               MD5(username:realm:password)  ← technicianHashingVersion=1
HA2:               SHA256(METHOD:URI)
Response:          SHA256(HA1:nonce:nc:cnonce:qop:HA2)
Realm:             "Webinterface area"
User:              "technician"
```

Dies ist ein **Hybrid-Schema** — HA1 mit MD5, Rest mit SHA256.
Standard-Clients (curl --digest, requests.HTTPDigestAuth) scheitern daran.

Die Implementierung ist in `fronius_api.py`, Klasse `FroniusAuth`.

---

## API-Referenz

### Lesen: GET /api/config/batteries
```bash
python3 fronius_api.py --read
python3 fronius_api.py --json
```

### Schreiben: POST /api/config/batteries
```bash
python3 fronius_api.py --set-soc-min 5 --confirm
python3 fronius_api.py --set-soc-max 80 --confirm
python3 fronius_api.py --set-soc-mode auto --confirm
python3 fronius_api.py --set-param BAT_M0_SOC_MIN=5 HYB_EM_MODE=1 --confirm
```

### Modbus-Steuerung
```bash
python3 battery_control.py                      # Status
python3 battery_control.py --set-charge 68      # Laderate 68%
python3 battery_control.py --set-discharge 29   # Entladerate 29%
python3 battery_control.py --hold               # Batterie halten
python3 battery_control.py --auto               # Automatik
```

---

## Status (2026-03-01)

- [x] Engine produktiv (`pv-automation.service`, systemd, 12 Regelkreise)
- [x] PV-Prognose via Geometrie-Engine (`solar_geometry` / `solar_forecast`)
- [x] Tages-Reset mit Komfort-Defaults (SOC + Modbus)
- [x] Score-basierte Entscheidungen mit Cascade-Mechanismus
- [x] Fuzzy-Scoring für nachmittag_soc_max (Clear-Sky-Peak + Leistungsschwelle)
- [x] Verbraucher-Kontext: 30-min-Mittelwerte für EV/WP in Schwellenberechnung
- [x] Retry-Logik für API + Modbus (AktorBatterie)
- [x] Abend-/Nacht-Entladeraten (29% / 10%)
- [x] Monatlicher Zellausgleich (prognosegesteuert)
- [x] Heizpatrone via Fritz!DECT (RegelHeizpatrone + AktorFritzDECT)
- [x] Logging in SQLite (`automation_log`)
- [x] SOC-Extern-Toleranz: Fremde SOC-Änderungen (Fronius App) werden 30 min respektiert
- [x] Morgen-Vorlauf: Batterielogik wird morgen_vorlauf_min (default 15 min) vor Sunrise getriggert
- [ ] Sommer-Ladebegrenzung (temperaturbasiert, Strategie E)
- [ ] Wattpilot-Steuerung (AktorWattpilot ist Stub)
