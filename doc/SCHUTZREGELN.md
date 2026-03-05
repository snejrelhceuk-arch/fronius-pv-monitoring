# Schutzregeln — PV-Anlage Erlau

**Erstellt:** 2026-02-20  
**Geltungsbereich:** Alle automatisch gesteuerten Komponenten  
**Priorität:** Schutzregeln sind **deterministisch und nicht übersteuerbar** — sie gelten vor allen Strategiealgorithmen

---

## Grundprinzip

> **Schutzregeln sind Hardgrenzen, keine Empfehlungen.**  
> Sie werden in jedem Engine-Zyklus geprüft, *bevor* Optimierungs-Algorithmen laufen.  
> Kein manueller Override, kein Fuzzy-Score kann eine Schutzregel außer Kraft setzen.  
> Bei Widerspruch: Schutzregel gewinnt immer.

---

## 1. Heimspeicher 2× BYD HVS 20.48 kWh (F1)

### SR-BAT-01: Tiefentladeschutz

| Feld | Wert |
|---|---|
| **Auslöser** | SOC < 5 % |
| **Aktion** | Sofort-Ladung aus PV erzwingen (OutWRte = 0 %) |
| **Zusatz** | SOC_MIN auf 10 % setzen (Modbus MinRsvPct) |
| **Freigabe** | SOC > 20 % für > 5 min |
| **Protokoll** | DB-Eintrag + Log: `protection_bat_low_soc` |
| **Status** | ✅ Implementiert — `RegelSocSchutz` in `automation/engine/regeln/schutz.py` |

### SR-BAT-02: Übertemperatur-Schutz

| Feld | Wert |
|---|---|
| **Auslöser** | Batterie-Temperatur > 40 °C |
| **Aktion** | Laderate auf 50 % reduzieren (InWRte = 50 %) |
| **Auslöser 2** | Temp > 45 °C |
| **Aktion 2** | Laden komplett stoppen (InWRte = 0 %) |
| **Freigabe** | Temp < 38 °C |
| **Protokoll** | `protection_bat_overtemp` |
| **Status** | ✅ Implementiert — `RegelTempSchutz` in `automation/engine/regeln/schutz.py` (stufenweise Reduktion bei 25/30/35/40°C) |

### SR-BAT-03: RvrtTms = 0 — Dauerhafte Modbus-Werte

| Feld | Wert |
|---|---|
| **Hintergrund** | Fronius-Modbus M124 kennt `RvrtTms` (Revert-Timer). Bei `RvrtTms = 0` gelten geschriebene Werte **dauerhaft** bis zum nächsten Schreibzugriff oder WR-Neustart. |
| **Risiko** | Wenn Automation ausfällt nachdem sie `OutWRte = 0 %` gesetzt hat → Batterie entlädt nie wieder! |
| **Schutzmaßnahme** | Nach jedem Neustart: Modbus-Status lesen und plausibilisieren. Komfort-Defaults wiederherstellen. |
| **Monitoring** | Actuator Read-Back-Verifikation in `automation/engine/actuator.py` |
| **Status** | ✅ Implementiert (verify_consistency) |

### SR-BAT-04: SOC_MODE-Konsistenz

| Feld | Wert |
|---|---|
| **Auslöser** | `SOC_MODE = "auto"` aber Engine erwartet Manual-Modus |
| **Problem** | Im Auto-Modus sind SOC_MIN/MAX nicht steuerbar (siehe FRONIUS_SOC_MODUS.md) |
| **Aktion** | Warnung im Log; beim nächsten Engine-Lauf auf Manual zurücksetzen |
| **Status** | ✅ Implementiert — Engine prüft SOC_MODE-Konsistenz |

---

## 2. E-Auto (Wattpilot / NMC-Zellen)

### SR-EV-01: NMC Überladeschutz

| Feld | Wert |
|---|---|
| **Hintergrund** | NMC-Zellen (Renault Zoe, Citroën) degradieren bei SOC > 85–90 % schnell |
| **Auslöser** | Geschätzter E-Auto-SOC > 85 % |
| **Aktion** | Wattpilot-Freigabe deaktivieren (Ladefreigabe = false) |
| **Freigabe** | Fahrzeug wieder verbunden mit SOC-Schätzung < 85 % (neue Session) |
| **Protokoll** | `protection_ev_soc_limit` |
| **Status** | Geplant (SOC-Schätzung noch nicht implementiert) |

### SR-EV-02: Minimale Ladezeit

| Feld | Wert |
|---|---|
| **Auslöser** | Ladevorgang aktiv |
| **Minimum** | Wattpilot mindestens 15 min laden lassen bevor Abschalten |
| **Grund** | BMS-Kommunikation, Fahrzeug-Eigensteuerung braucht Zeit |
| **Status** | Geplant |

### SR-EV-03: Überlastschutz Hauptsicherung

| Feld | Wert |
|---|---|
| **Auslöser** | Netz-Bezug > 24 kW |
| **Aktion 1** | Wattpilot auf max. 16 A (= 11 kW) drosseln |
| **Auslöser 2** | Netz-Bezug > 26 kW |
| **Aktion 2** | Wattpilot auf 6 A (= 1.4 kW) = Minimum |
| **Freigabe** | Netz-Bezug < 20 kW für > 2 min |
| **Protokoll** | `protection_grid_overload` |
| **Hintergrund** | Hauptsicherung 3 × 40 A = 27.6 kW. WP (4.3) + EV (22) + Haushalt (2) = 28.3 kW → Überlast möglich! |
| **Status** | Geplant |

---

## 3. Wärmepumpe Dimplex SIK 11 TES (geplant)

> **Hinweis:** WP Modbus RTU noch nicht integriert (LWPM 410 Modul bestellt). Regeln sind Planung.

### SR-WP-01: Warmwasser-Übertemperatur

| Feld | Wert |
|---|---|
| **Auslöser** | WW-Speicher Temp > 80 °C |
| **Aktion** | WP sofort abschalten (SG-Ready OFF) |
| **Auslöser Soft** | WW-Temp > 78 °C |
| **Aktion Soft** | WP in Wartemodus, Hysterese 5 °C |
| **Protokoll** | `protection_wp_overtemp` |
| **Status** | Geplant, Temp-Sensor fehlt |

### SR-WP-02: Pflichtlauf-Schutz

| Feld | Wert |
|---|---|
| **Hintergrund** | WP muss mindestens 1× täglich laufen (Legionellenschutz, Viskositätserhalt) |
| **Auslöser** | WP seit > 23 h nicht gelaufen |
| **Aktion** | WP-Freigabe erzwingen für min. 30 min |
| **Protokoll** | `protection_wp_mandatory_run` |
| **Status** | Geplant |

### SR-WP-03: SG-Ready bei Eigenbedarfs-Mangel

| Feld | Wert |
|---|---|
| **Auslöser** | PV-Ertrag < Hausverbrauch für > 15 min UND Batterie-SOC < 30 % |
| **Aktion** | WP auf SG-Ready-0 (minimaler Betrieb) wechseln |
| **Freigabe** | PV > Verbrauch oder SOC > 40 % |
| **Status** | Geplant |

---

## 4. Netz-Schutzregeln

### SR-NET-01: Export-Begrenzung

| Feld | Wert |
|---|---|
| **Konzept** | Nulleinspeiser — Export ins Netz nur als Übergangsmaßnahme |
| **Auslöser** | Netz-Einspeisung > 500 W für > 5 min |
| **Aktion 1** | Wattpilot-Leistung erhöhen (wenn EV verbunden) |
| **Aktion 2** | WP SG-Ready erhöhen |
| **Aktion 3** | Wenn alles voll: F2 oder F3 Leistung reduzieren |
| **Protokoll** | `protection_net_export_limit` |
| **Status** | Geplant |

### SR-NET-02: Frequenz-Grenzwert

| Feld | Wert |
|---|---|
| **Auslöser** | Netzfrequenz < 49.0 Hz oder > 51.0 Hz |
| **Aktion** | Log-Alarm; keine automatische Abschaltung (WR regelt selbst nach VDE AR N 4105) |
| **Status** | Monitoring vorhanden, keine Automation |

---

## 5. Modbus-Sicherheit

### SR-MODBUS-01: WriteLock nach Fehler

| Feld | Wert |
|---|---|
| **Auslöser** | 3× Modbus-Schreibfehler in Folge |
| **Aktion** | Modbus-Schreibversuche für 5 min pausieren |
| **Protokoll** | `protection_modbus_write_lock` |
| **Status** | Geplant |

### SR-MODBUS-02: Konsistenzprüfung (implementiert)

| Feld | Wert |
|---|---|
| **Funktion** | Actuator Read-Back-Verifikation in `automation/engine/actuator.py` |
| **Prüft** | SOC_MIN vs. erwarteter Wert, StorCtl_Mod vs. erwartetem Modus |
| **Auslöser** | Jeder Engine-Zyklus (1 min fast / 15 min strategic) |
| **Risiko** | Überschreibt manuell gesetzte Werte! |
| **Schutz** | `manual_override` Flag verhindert Überschreiben |
| **Status** | ✅ Implementiert |

---

## Failover & Dual-Host Schutzregeln

> Hintergrund: Das PV-System läuft auf zwei Pi4-Hosts (Primary: 181, Failover: fronipi 105).
> Die `.role`-Datei steuert, welche Prozesse aktiv sind.
> Siehe [DUAL_HOST_ARCHITECTURE.md](DUAL_HOST_ARCHITECTURE.md) für die komplette Architektur.

### SR-FO-01 — Doppel-Collector-Schutz (Kritisch)

| Eigenschaft | Wert |
|---|---|
| **Regel** | Es darf zu keinem Zeitpunkt auf zwei Hosts gleichzeitig ein Collector (`collector.py`) mit Modbus-Schreibzugriff auf den Fronius-Wechselrichter laufen. |
| **Begründung** | Zwei konkurrierende Modbus-Writer können widersprüchliche Batterie-Befehle senden und den Wechselrichter in einen Fehlerzustand versetzen. |
| **Umsetzung** | `host_role.py` + `role_guard.sh` — Collector/Scheduler starten nur bei `.role = primary`. Failover-Collector ist per Default gestoppt. Aktivierung NUR über `failover_activate.sh`. |
| **Status** | ✅ Implementiert (2026-02-20) |

### SR-FO-02 — Failover-Scripts NIE auf Primary ausführen (Kritisch)

| Eigenschaft | Wert |
|---|---|
| **Regel** | Die Scripts `failover_set_mode.sh`, `failover_activate.sh`, `failover_passive.sh` dürfen NIEMALS auf dem Production-Pi ausgeführt werden. |
| **Begründung** | `failover_set_mode.sh` setzt `PV_MIRROR_MODE=1` und stoppt Collector + Wattpilot. Auf dem Primary ausgeführt → Produktionsausfall! (Vorfall 2026-02-19) |
| **Umsetzung** | Manuell (Disziplin). Die Scripts prüfen `.role`, aber das schützt nicht bei falscher `.role`. |
| **Status** | ⚠️ Organisatorisch (kein technischer Automatismus) |

### SR-FO-03 — .role Datei Schutz (Hoch)

| Eigenschaft | Wert |
|---|---|
| **Regel** | Die `.role`-Datei darf auf dem Production-Pi (181) NUR den Wert `primary` enthalten (oder fehlen, Default=primary). |
| **Begründung** | `.role = failover` auf Production blockiert: Aggregation (5 Jobs), Battery-Scheduler, Monitor-Scripts, reduziert Gunicorn auf 1 Worker. (Vorfall 2026-02-19, 20:19 Uhr) |
| **Umsetzung** | Manuell. Prüfung: `cat .role` sollte `primary` zeigen oder Datei nicht existieren. |
| **Status** | ⚠️ Organisatorisch |

### SR-FO-04 — Mirror-Freshness (Mittel)

| Eigenschaft | Wert |
|---|---|
| **Regel** | Die Mirror-DB auf dem Failover-Host darf nicht älter als 15 Minuten sein (Sync-Intervall: 10 Min). |
| **Begründung** | Bei einem Failover-Schwenk wäre eine veraltete DB ein Datenverlust-Risiko. |
| **Umsetzung** | `failover_health_check.sh` (systemd-Timer, 1× pro Minute) überwacht Sync-Marker-Alter und schreibt Empfehlung in `health_recommendation.json`. |
| **Status** | ✅ Implementiert (2026-02-20) |

### SR-FO-05 — Keine SD-Writes im Normalbetrieb (Mittel)

| Eigenschaft | Wert |
|---|---|
| **Regel** | Der Failover-Host (fronipi) darf im Normalbetrieb KEINE SD-Card-Writes für die Datenbank erzeugen. |
| **Begründung** | fronipi dient zusätzlich als Küchen-Display. SD-Wear muss minimiert werden. Die DB liegt in tmpfs (/dev/shm). |
| **Umsetzung** | Mirror-Sync schreibt ausschließlich nach `/dev/shm/`. SD-Persistenz nur alle 2 Tage via `backup_db_every2d`. |
| **Status** | ✅ Implementiert (2026-02-20) |

---

## Prioritäten-Hierarchie

```
1. SR-EV-03  Hauptsicherung (Hardware-Limit — sofortige Aktion)
2. SR-BAT-02 Batterietemperatur (Brandschutz)
3. SR-FO-01  Doppel-Collector-Schutz (Modbus-Konflikt)
4. SR-FO-02  Failover-Scripts NIE auf Primary
5. SR-BAT-01 Tiefentladeschutz
6. SR-WP-01  WP Übertemperatur
7. SR-WP-02  WP Pflichtlauf
8. SR-NET-01 Export-Begrenzung
9. SR-EV-01  NMC Überladeschutz
10. SR-EV-02  Mindest-Ladezeit
11. SR-NET-02 Frequenzüberwachung (Monitoring)
```

---

## Status-Übersicht

| Regel | Priorität | Status |
|---|---|---|
| SR-BAT-01 | Hoch | ✅ Implementiert (`RegelSocSchutz`) |
| SR-BAT-02 | Kritisch | ✅ Implementiert (`RegelTempSchutz`) |
| SR-BAT-03 | Hoch | ✅ Implementiert |
| SR-BAT-04 | Mittel | ✅ Implementiert (Engine-Konsistenzprüfung) |
| SR-MODBUS-02 | Mittel | ✅ Implementiert (Actuator Read-Back) |
| SR-FO-01 | Kritisch | ✅ Implementiert |
| SR-FO-02 | Kritisch | ⚠️ Organisatorisch |
| SR-FO-03 | Hoch | ⚠️ Organisatorisch |
| SR-FO-04 | Mittel | ✅ Implementiert |
| SR-FO-05 | Mittel | ✅ Implementiert |
| SR-HP-01 | Hoch | ✅ Implementiert (`RegelHeizpatrone` Notaus: SOC-abhängig) |
| SR-EV-BATT | Hoch | ✅ Implementiert (`RegelWattpilotBattSchutz`) |
| SR-EV-03 | Kritisch | 🔲 Geplant (AktorWattpilot ist Stub) |
| SR-EV-01 | Mittel | 🔲 Geplant |
| SR-EV-02 | Niedrig | 🔲 Geplant |
| SR-WP-01 | Kritisch | 🔲 Geplant (WP-Modbus fehlt) |
| SR-WP-02 | Mittel | 🔲 Geplant (WP-Modbus fehlt) |
| SR-WP-03 | Niedrig | 🔲 Geplant (WP-Modbus fehlt) |
| SR-NET-01 | Mittel | 🔲 Geplant |
| SR-NET-02 | Niedrig | 🔲 Monitoring |
| SR-MODBUS-01 | Niedrig | 🔲 Geplant |

---

*Letzte Aktualisierung: 2026-03-01*  
*Verwandte Dokumente:* [PARAMETER_MATRIZEN.md](PARAMETER_MATRIZEN.md) · [BEOBACHTUNGSKONZEPT.md](BEOBACHTUNGSKONZEPT.md) · [FRONIUS_SOC_MODUS.md](FRONIUS_SOC_MODUS.md) · [BATTERY_ALGORITHM.md](BATTERY_ALGORITHM.md) · [DUAL_HOST_ARCHITECTURE.md](DUAL_HOST_ARCHITECTURE.md)
