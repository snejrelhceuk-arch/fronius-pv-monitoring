# WR-Fernsteuerung — Möglichkeiten, Grenzen, Reset-Strategie

> **Status: ANALYSE (2026-07-02, korrigiert).** Kein autonomer Hardware-Eingriff implementiert.
> Antwort auf Task A: „Neustart/Standby der 3 WR möglich?"

## Kernbefund (verifiziert 2026-07-02)

Zwei getrennte Ebenen sauber unterscheiden:
1. **Messung** über die Modbus-Kette des GEN24 (`collector/quellen.py`): Unit 1 = Inverter (F1), Unit 2 = `PRIM_SM_F1` (Netz), Unit 3 = `SEC_SM_F2`, Unit 4 = `SEC_SM_WP`, Unit 6 = `SEC_SM_F3`. **`P_F2`/`P_F3` sind SmartMeter-Messwerte** — über diese Kette gibt es KEINEN Befehlskanal zu F2/F3.
2. **Steuerung** über die **eigenen Netzwerk-Endpunkte** der Wechselrichter (jeder WR hat eine eigene IP):

| WR | Eigener Netzwerk-Zugang | Direkt steuerbar? |
|---|---|---|
| **F1** (GEN24 12.0) | Modbus TCP + interne HTTP-API | **Ja** — SunSpec Model 123 `Conn` + HTTP (SOC produktiv) |
| **F2** (Fronius, DT=1, „Running", ~12 kW) | **eigene IP**, Modbus TCP **:502 offen**, Solar-API v1 erreichbar | **Ja — analog zu F1** (SunSpec Model 123 `Conn`), verifiziert 2026-07-02 |
| **F3** | vorhanden im LAN, Zugang aber **noch nicht ermittelt** | **noch offen** — Zugänge/Protokoll recherchieren (Web + ggf. reverse-engineering am Gerät) |

**Korrektur zur ersten Analyse:** F2 ist **nicht** nur ein SmartMeter — der SmartMeter (Unit 3) misst nur; der **F2-Wechselrichter selbst hat eine eigene Modbus-/Solar-API-Schnittstelle** und ist damit direkt steuerbar. Für **F3** ist der Zugang noch zu ermitteln; bis dahin bleibt für F3 der **Relais/Schütz-Fallback** die abgesicherte Option.

## Steuerbarkeit je WR

### F1 (GEN24) — digital steuerbar
SunSpec **Model 123 (Controls)** ist im Register-Map vorhanden (`collector/quellen.py:168`), aktuell nur **gelesen**. Relevante Register:
- `Conn` (enum16, offset 2): **Connect/Disconnect** → **erzwungener Standby (0) und Ende-Standby (1)**. Standard-SunSpec → **update-sicher**. Mit `Conn_WinTms`/`Conn_RvrtTms` (Zeitfenster/Timeout).
- `WMaxLimPct` + `WMaxLim_Ena`: Leistungsdrosselung in % — **No-Go** (AGENTS.md #3). **Nicht** verwenden.
- Zusätzlich HTTP-Config-API (`fronius_api.py`) für Batterie (SOC) — bereits produktiv.

**Ein echter Power-Cycle (Hard-Reset) des GEN24 ist digital nicht möglich** — nur `Conn`-Disconnect (Soft-Standby). Ein Hard-Reset bräuchte ein Relais in der Versorgung (Batterie-WR → riskant, nur mit Bedacht).

### F2 — digital steuerbar (eigener Endpunkt, verifiziert)
- Eigene IP: **Ping OK, HTTP :80 offen, Modbus TCP :502 offen**, Solar-API v1 (`/solar_api/v1/`, Compatibility 1.8-0), `GetInverterInfo` → CustomName „F2", DT=1, InverterState „Running", PVPower ~12,4 kW.
- **Standby/Ende-Standby** über SunSpec **Model 123 `Conn`** auf F2s eigenem Modbus — analog zu F1. Zusätzlich Solar-API vorhanden.
- Schreibpfad ist **neu** und noch nicht implementiert; erst nach Einzelvalidierung, gated, nie autonom ohne Freigabe.

### F3 — Zugang noch zu ermitteln
- Physisch im LAN vorhanden, aber IP/Protokoll noch **nicht konfiguriert/bekannt** (`.infra.local` kennt nur F2 = `PV_SECONDARY_INVERTER_API`).
- Vorgehen: Fronius-/Geräte-Doku im Web, Netz-Scan im LAN, ggf. reverse-engineering direkt am F3.
- **Bis F3 digital erreichbar ist: Relais/Schütz auf F3s AC-Ausgang** (abgesicherter Fallback, HW-Projekt, siehe MEGA-BAS-HAT in `doc/TODO.md`).

## Reset-Strategie

Die vom Nutzer skizzierte Reihenfolge (von den kleinen WR her) bleibt richtig, weil ein F1-Neustart die Regelung für F2/F3 kurz aufhebt und diese sonst hochziehen:

```
a) F3 trennen          → Relais/Schütz F3 = AUS  (bis F3-Digitalzugang ermittelt)
b) F2 trennen          → SunSpec Conn=0 auf F2s eigenem Modbus (oder Relais)
c) F1 neu starten      → SunSpec Conn=Disconnect, warten, Conn=Connect
                         (Hard-Reset nur mit Relais F1)
d) +3 min: F2 zu       → Relais F2 = EIN  (GEN24-Limiting greift erst wieder,
                         wenn F1 „connected" + Master-Link steht)
e) +Zeit: F3 zu        → Relais F3 = EIN
```

**Reihenfolge-Begründung (bestätigt):** F1 zuerst „connected" und Master-Link aktiv, DANN die Sekundären schrittweise zuschalten — sonst laufen F2/F3 ungeregelt auf Maximum (genau der Zwischenfall).

## „Sicherstellen, dass F2/F3-Steuerung im Master F1 aktiv+connected ist"

Read-only-Monitoring (implementierbar, ungefährlich), Vorschlag:
1. **Config-Read** der internen Fronius-API (`/api/config/...`, Digest-Auth) → prüfen, ob „Mehrere Wechselrichter limitieren" + Soft-Limit=0 W noch gesetzt sind; bei Drift alarmieren. (Attachment-State-Check existiert bereits: `collector/attachment_state.py`.)
2. **Runaway-Frühsignatur:** F3-Leistung (SEC_SM_F3) hoch, während Netz einspeist UND Batterie nicht aufnehmen kann (voll oder SOC_MAX gedeckelt) UND F1/F2 abgeregelt → F3 gehorcht dem Limit nicht. Als eigener, langsamer Health-Check (kein Aktor).
3. Der **Netto-Einspeise-Guard** (`automation-einspeise-schutz.card.md`) fängt das Symptom bereits ab; der Health-Check würde die Ursache früher sichtbar machen.

## Update-Sicherheit

- **Nur Standard-SunSpec** (Model 123 `Conn`) für F1-Standby verwenden — überlebt Firmware-Updates. Die interne undokumentierte API kann nach Updates ihre Auth/Endpunkte ändern (siehe Hardening-Doku 2026-04-03).
- Relais-Steuerung ist **inhärent update-sicher** (Hardware, unabhängig von Fronius-Firmware) — Hauptargument für den Relais-Weg bei F2/F3.

## Fazit / Empfehlung

1. **F2/F3 sind nur per Relais/Schütz abschaltbar** — die Relais-Karte ist damit Kern der Lösung, nicht Notnagel. Hardware-Projekt (MEGA-BAS-HAT ist bereits in `doc/TODO.md` gelistet → dort andocken).
2. **F1-Soft-Standby** (SunSpec `Conn`) ist digital machbar und update-sicher, aber ein Schreibpfad zum GEN24 ist neu und risikobehaftet (Batterie-WR) → erst nach separater Validierung, gated, nie autonom ohne Freigabe.
3. **Kein autonomer WR-Reset** wird jetzt scharfgeschaltet. Vorbedingungen: Relais-Hardware + Einzelvalidierung jedes Schritts.
4. Nächster ungefährlicher Schritt: Read-only-Health-Check (Punkt oben) + Fronius-Support-Klärung (F3-Curtailment, `FRONIUS_SUPPORT_EINSPEISUNG_2026-07-02.md`).
