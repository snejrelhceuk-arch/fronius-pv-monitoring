# WR-Fernsteuerung — Möglichkeiten, Grenzen, Reset-Strategie

> **Status: ANALYSE/DESIGN (2026-07-02).** Kein autonomer Hardware-Eingriff implementiert.
> Antwort auf Task A: „Neustart/Standby der 3 WR möglich?"

## Kernbefund (topologisch belegt)

Aus `collector/quellen.py` (Modbus-Unit-Map) und `doc/collector/COLLECTOR_HARDENING.md`:

| „WR" | Modbus-Unit | Rolle in unserem System | Direkt steuerbar von uns? |
|---|---|---|---|
| **F1** | Unit 1 = `INVERTER` (GEN24 12.0) | Hybrid-WR + Batterie + **SmartMeter-Master** | **Ja** — SunSpec + HTTP |
| Netz | Unit 2 = `PRIM_SM_F1` | Zähler am Netzübergabepunkt (Modell 203) | — (Messung) |
| **F2** | Unit 3 = `SEC_SM_F2` | **SmartMeter** vor dem F2-Wechselrichter (Modell 203) | **Nein** — nur Messung |
| WP | Unit 4 = `SEC_SM_WP` | SmartMeter Wärmepumpe (Modell 203) | — (Messung) |
| **F3** | Unit 6 = `SEC_SM_F3` | **SmartMeter** vor dem F3-Wechselrichter (Modell 203) | **Nein** — nur Messung |

**Entscheidend:** `P_F2`/`P_F3` sind **Messwerte sekundärer SmartMeter**, nicht die Wechselrichter selbst. Die F2-/F3-Wechselrichter sind eigenständige Geräte, deren **Produktion wir nur messen**. Die Abregelung von F2/F3 macht der GEN24 (F1) intern über „Mehrere Wechselrichter limitieren" (Fronius Dynamic Power Reduction) — **wir haben keinen digitalen Befehlskanal zu F2/F3.**

→ Das ändert die vom Nutzer skizzierte Reset-Reihenfolge grundlegend: **F3 und F2 können softwareseitig NICHT deaktiviert werden.** Für einen erzwungenen Standby von F2/F3 ist zwingend **Hardware (Relais/Schütz) auf deren AC-Ausgang** nötig — nicht als „letztes Mittel", sondern als **einziger** uns möglicher Weg.

## Steuerbarkeit je WR

### F1 (GEN24) — digital steuerbar
SunSpec **Model 123 (Controls)** ist im Register-Map vorhanden (`collector/quellen.py:168`), aktuell nur **gelesen**. Relevante Register:
- `Conn` (enum16, offset 2): **Connect/Disconnect** → **erzwungener Standby (0) und Ende-Standby (1)**. Standard-SunSpec → **update-sicher** (überlebt Firmware-Updates besser als die undokumentierte interne API). Mit `Conn_WinTms`/`Conn_RvrtTms` (Zeitfenster/Timeout).
- `WMaxLimPct` + `WMaxLim_Ena`: Leistungsdrosselung in % — **No-Go** (AGENTS.md #3: keine SW-Ratenlimits; GEN24-HW-Limit ist die Wahrheit). **Nicht** verwenden.
- Zusätzlich HTTP-Config-API (`fronius_api.py`) für Batterie (SOC) — bereits produktiv.

**Ein echter Power-Cycle (Hard-Reset) des GEN24 ist digital nicht möglich** — nur `Conn`-Disconnect (Soft-Standby). Ein Hard-Reset bräuchte ebenfalls ein Relais in der Versorgung (bei einem Batterie-WR riskant → nur mit Bedacht).

### F2 / F3 — NICHT digital steuerbar
- Kein SunSpec-Control-Model, kein erreichbarer Befehlspfad über die aktuelle Modbus-Kette.
- **Erzwungener Standby nur per Relais/Schütz** auf dem AC-Ausgang des jeweiligen WR.
- Offene Frage (Hardware-Aufnahme nötig): Sind F2/F3 eigenständige Fronius-WR mit eigener IP/LAN-Anbindung? Falls ja, wäre deren **eigene** Solar-API/Modbus-Schnittstelle ein möglicher Kanal — **zu ermitteln vor Ort** (nicht aus den Daten ableitbar).

## Reset-Strategie (überarbeitet)

Die vom Nutzer gewünschte Reihenfolge (von den kleinen WR her) bleibt richtig, weil ein F1-Neustart die Regelung für F2/F3 kurz aufhebt und diese sonst hochziehen. Umsetzbar aber **nur mit Relais**:

```
a) F3 trennen          → Relais/Schütz F3 = AUS
b) F2 trennen          → Relais/Schütz F2 = AUS
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
