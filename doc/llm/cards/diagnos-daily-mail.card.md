---
title: Diagnos Daily-Mail (Sunset-Tagesbericht + Alarm-Mails)
domain: diagnos
role: D
applyTo: "automation/engine/event_notifier.py"
tags: [mail, sunset, tagesbericht, smtp, credential]
status: stable
last_review: 2026-08-04
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

## Fehlerbild — Credential fehlt nach Host-Migration (2026-08-04 behoben)
- **Symptom:** Seit Pi5-Umzug keine Tagesmail; Test-Mail in pv-config zeigt „Passwort ✗ FEHLT".
- **Log:** jeden Sunset `event_notifier ERROR: Sunset-Bericht FEHLGESCHLAGEN: SMTP-Passwort nicht gesetzt (credential_store)`.
- **Ursache:** `smtp_pass.key` ist Machine-ID-gebunden → beim Host-Wechsel nicht mitgewandert, `/etc/pv-system/` fehlt komplett.
- **Nachhaltig sichtbar:** `check_notification_ready` meldet den Zustand jetzt als CRIT im Health-Report/Dashboard (kein stiller Log-Tod mehr).
- **Fix (Operator, Secret):** `sudo python3 pv-config.py` → Benachrichtigungen → „SMTP-Passwort setzen" → danach Test-Mail. Nach jeder Host-Migration/SD-Neuinstallation erneut setzen.

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
