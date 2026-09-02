---
title: Diagnos Daily-Mail (Täglicher Energiebericht + Alarm-Mails)
domain: diagnos
role: D
applyTo: "automation/engine/event_notifier.py,automation/engine/notify/report_format.py"
tags: [mail, tagesbericht, energie, smtp, credential, alarm]
status: stable
last_review: 2026-09-02
---

# Diagnos Daily-Mail

## Zweck
Die „tägliche Mail" ist der **Tagesbericht**: ein reiner Energie-Auszug, ausgelöst
um **00:00** (Tageswechsel) vom Automation-Daemon, für den **abgelaufenen
Kalendertag** (00:00→00:00). Vier Abschnitte — **Tag / Monat / Jahr / Gesamt** —
mit je 5 Kernwerten (Erzeugung, Verbrauch, Netzbezug, Einspeisung, Batterie);
im Tag zusätzlich **Stresszeit-%** (SOC außerhalb Komfortband) und **Verbraucher**
(WP/HP/Wattpilot/Haushalt). **Keine** Health-/Integrity-/NQ-/Warn-Inhalte —
Systemfehler laufen über die separaten Sofort-Alarme (dieselbe SMTP-Infrastruktur).

## Code-Anchor
- **Bericht + Versand:** `automation/engine/event_notifier.py:sende_tagesbericht`, `_sende_tagesbericht_mail`
- **Datensammlung:** `automation/engine/event_notifier.py:_sammle_tagesdaten` (daily_data + yearly_statistics; hourly_data-Fallback; Stresszeit aus data_1min; Verbraucher aus heizpatrone_daily/wattpilot_daily)
- **Textformatierung:** `automation/engine/notify/report_format.py:tagesbericht` (4 Abschnitte, 5 Kernwerte)
- **Trigger (00:00):** `automation/engine/automation_daemon.py` (Aufruf je Zyklus; Dedup + daily_data-Gate steuern Fälligkeit)
- **Sofort-Alarme (getrennt):** `automation/engine/event_notifier.py:pruefe_health_alarme`, `pruefe_integrity_alarme`, `_sende_diagnos_alarm`
- **Statusdateien (entkoppelt):** `automation/engine/event_notifier.py:_aktualisiere_statusdateien` → `diagnos/status_report.py:write_status_reports`
- **SMTP-Low-Level:** `automation/engine/notify/mail.py:smtp_versand`
- **Passwort (verschlüsselt):** `automation/engine/credential_store.py:lade` → `/etc/pv-system/smtp_pass.key`
- **Dedup 1×/Tag:** `automation/engine/notify/dedup.py`, State `config/event_notifier_dedup.json`
- **Config:** `config.py` (`NOTIFICATION_EMAIL`, `NOTIFICATION_SMTP_*`, `NOTIFICATION_EVENTS` mit Key `tagesbericht`)
- **Bereitschafts-Check:** `diagnos/health.py:check_notification_ready`
- **Operator-UI:** `pv-config.py:menu_benachrichtigung` (Empfänger/Events/Test-Mail/Passwort)

## Inputs / Outputs
- **Inputs:** `daily_data` (Tag + Monat-/Jahr-Summen, Counter-nah), `yearly_statistics` (historische Jahre für Gesamt), `heizpatrone_daily`/`wattpilot_daily` (Verbraucher), `data_1min` `SOC_Batt_avg` (Stresszeit), `config/battery_control.json` `soc_grenzen` (Komfortband), SMTP-Passwort aus `credential_store`.
- **Outputs:** E-Mail an `NOTIFICATION_EMAIL` (Betreff `[PV-System] Tagesbericht <Datum>`, **ohne** Severity-Suffix), Dedup-Marker, Log; nebenbei aktualisierte Status-Markdown.

## Invarianten
- Versand genau 1×/Tag (Dedup `config/event_notifier_dedup.json`, Reset bei Tageswechsel).
- `tagesbericht` muss in `NOTIFICATION_EVENTS` stehen, sonst kein Bericht.
- Der Tag wird erst gemeldet, sobald die `daily_data`-Zeile des Vortags vorliegt (Tagesaggregation kurz nach Mitternacht); Karenz 1 h, danach `hourly_data`-Fallback (Kopf zeigt „vorläufig").
- Tagesgrenze ist **00:00→00:00** (lokaler Kalendertag), nicht Sunset. `daily_data` ist per UTC-Mitternacht verschlüsselt, repräsentiert aber den lokalen Tag.
- **Keine** Warnungen/Diagnos-Befunde im Bericht — kritische Zustände (CRIT/FAIL) laufen über die Sofort-Alarme.
- Alle Daemon-Mails brauchen das **Machine-ID-gebundene** `smtp_pass`-Credential (nicht migrierbar, pro Host setzen).

## No-Gos
- Keine Klartext-Passwörter in `config.py`/Repo — nur `credential_store` (`/etc/pv-system/`).
- Keine Health-/Integrity-/NQ-/Warn-Sektionen zurück in den Bericht holen (bewusst entfernt).
- Keine Änderung von Empfänger/Events/Versandzeitpunkt ohne Freigabe.
- Kein zweiter, konkurrierender Mail-Trigger (Cron) — der Daemon ist maßgeblich.

## Bekanntes Fehlerbild — SMTP-Credential fehlt (nach Host-Wechsel)
- **Symptom:** keine Tagesmail; Test-Mail in pv-config zeigt „Passwort ✗ FEHLT".
- **Log:** `event_notifier ERROR: Tagesbericht FEHLGESCHLAGEN: SMTP-Passwort nicht gesetzt (credential_store)`.
- **Ursache:** `smtp_pass.key` ist Machine-ID-gebunden → wandert bei Host-Wechsel/SD-Neuinstallation nicht mit.
- **Sichtbar:** `check_notification_ready` meldet den Zustand als CRIT im Health-Report/Dashboard.
- **Fix (Operator, Secret):** `sudo python3 pv-config.py` → Benachrichtigungen → „SMTP-Passwort setzen" → Test-Mail.

## Häufige Aufgaben
- Kein Versand? → `journalctl -u pv-automation | grep -i tagesbericht`; Health-Check `notification_ready`.
- Änderung greift erst nach `pv-automation`-Restart (EventNotifier bei Daemon-Start geladen).
- Neuen Empfänger/Event → über `pv-config.py` (schreibt `config.py` + Live-Objekt), nicht per Hand.

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`diagnos-integrity.card.md`](./diagnos-integrity.card.md)
- [`automation-engine.card.md`](./automation-engine.card.md)

## Human-Doku
- [`doc/diagnos/MAIL.md`](./../../doc/diagnos/MAIL.md)
