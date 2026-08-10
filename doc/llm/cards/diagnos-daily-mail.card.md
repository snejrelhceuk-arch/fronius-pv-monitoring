---
title: Diagnos Daily-Mail (Sunset-Tagesbericht + Alarm-Mails)
domain: diagnos
role: D
applyTo: "automation/engine/event_notifier.py,automation/engine/nq_notifier.py,automation/engine/notify/report_format.py,automation/engine/diagnos_alert_state.py"
tags: [mail, sunset, tagesbericht, smtp, credential, nq]
status: stable
last_review: 2026-08-10
---

# Diagnos Daily-Mail

## Zweck
Die „tägliche Mail" ist der **Sunset-Tagesbericht**: eine 24h-Zusammenfassung
(Sunset gestern → Sunset heute) mit Energiebilanz + Diagnos-Auffälligkeiten.
Kein 06:00-Cron — der Versand wird beim **Sunset** (Übergang `is_day` True→False)
vom Automation-Daemon ausgelöst. Dieselbe Mail-Infrastruktur trägt auch die
Sofort-/Integrity-Alarme.

## Code-Anchor
- **Bericht + Versand:** `automation/engine/event_notifier.py:sende_sunset_bericht`, `_sende_sunset_mail`
- **Textformatierung:** `automation/engine/notify/report_format.py` (Energie-/Health-/Integrity-/NQ-Sektionen)
- **NQ-Anteil:** `automation/engine/nq_notifier.py:diff_nq_befunde` + `diagnos/nq_health.py` (eigener Diff-State `nq_alert_state.json` unter `config/`)
- **Diff-Filter:** `automation/engine/diagnos_alert_state.py:filter_reportable`
- **Trigger (Sunset-Erkennung):** `automation/engine/automation_daemon.py` (`is_day` True→False, `_war_tag`)
- **is_day-Berechnung:** `automation/engine/collectors/forecast_collector.py:_refresh_is_day`
- **SMTP-Low-Level:** `automation/engine/notify/mail.py:smtp_versand`
- **Passwort (verschlüsselt):** `automation/engine/credential_store.py:lade` → `/etc/pv-system/smtp_pass.key`
- **Dedup 1×/Tag:** `automation/engine/notify/dedup.py`, State `config/event_notifier_dedup.json`
- **Config:** `config.py` (`NOTIFICATION_EMAIL`, `NOTIFICATION_SMTP_*`, `NOTIFICATION_EVENTS`, `EVENT_THRESHOLDS`)
- **Bereitschafts-Check:** `diagnos/health.py:check_notification_ready`
- **Operator-UI:** `pv-config.py:menu_benachrichtigung` (Empfänger/Events/Test-Mail/Passwort)

## Inputs / Outputs
- **Inputs:** `ObsState` (Sunset-Zeit, Live-Werte), `hourly_data` (read-only), Diagnos-Health/Integrity-Snapshot, `NOTIFICATION_EVENTS`, SMTP-Passwort aus `credential_store`.
- **Outputs:** E-Mail an `NOTIFICATION_EMAIL` (Betreff `[PV-System] Tagesbericht <Datum>` + optional `— FAIL(n)/KRIT(n)/WARN(n)`), Dedup-Marker, Log.

## Invarianten
- Versand genau 1×/Tag/Event (Dedup in `config/event_notifier_dedup.json`, Reset bei Tageswechsel).
- `sunset_tagesbericht` muss in `NOTIFICATION_EVENTS` stehen, sonst kein Bericht.
- Alle Daemon-Mails (Sunset, Sofort-Alarm, Integrity-Alarm) brauchen das **Machine-ID-gebundene** `smtp_pass`-Credential. Es ist NICHT migrierbar und muss pro Host neu gesetzt werden.
- Datenquelle des Berichts ist `hourly_data` direkt (kein `daily_data`/Aggregat), read-only.

## No-Gos
- Keine Klartext-Passwörter in `config.py`/Repo — nur `credential_store` (`/etc/pv-system/`).
- Keine Änderung von Empfänger/Events/Versandzeitpunkt ohne Freigabe.
- Kein zweiter, konkurrierender Mail-Trigger (Cron) — der Daemon ist maßgeblich.

## Bekanntes Fehlerbild — SMTP-Credential fehlt (nach Host-Wechsel)
- **Symptom:** keine Tagesmail; Test-Mail in pv-config zeigt „Passwort ✗ FEHLT".
- **Log:** jeden Sunset `event_notifier ERROR: Sunset-Bericht FEHLGESCHLAGEN: SMTP-Passwort nicht gesetzt (credential_store)`.
- **Ursache:** `smtp_pass.key` ist Machine-ID-gebunden → wandert bei Host-Wechsel/SD-Neuinstallation nicht mit.
- **Sichtbar:** `check_notification_ready` meldet den Zustand als CRIT im Health-Report/Dashboard.
- **Fix (Operator, Secret):** `sudo python3 pv-config.py` → Benachrichtigungen → „SMTP-Passwort setzen" → Test-Mail. Nach jeder Host-Migration/SD-Neuinstallation erneut setzen.

## Häufige Aufgaben
- Kein Versand? → Health-Check `notification_ready` prüfen; `journalctl -u pv-automation | grep -i sunset`.
- Neuen Empfänger/Event → über `pv-config.py` (schreibt `config.py` + Live-Objekt), nicht per Hand.
- Neuen Host provisionieren → `credential_store` setzen (Teil des Failover-/Reformation-Runbooks).

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`diagnos-integrity.card.md`](./diagnos-integrity.card.md)
- [`automation-engine.card.md`](./automation-engine.card.md)

## Human-Doku
- [`doc/diagnos/MAIL.md`](./../../doc/diagnos/MAIL.md)
