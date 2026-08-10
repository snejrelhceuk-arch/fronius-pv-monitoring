# Tägliche Mail (Sunset-Tagesbericht) & Alarm-Mails

Kurzreferenz für Betrieb und Fehlersuche. LLM-Card:
[`doc/llm/cards/diagnos-daily-mail.card.md`](../llm/cards/diagnos-daily-mail.card.md).

## Was ist die „tägliche Mail"?

Es ist **kein** 06:00-Cron, sondern der **Sunset-Tagesbericht**: eine
24h-Zusammenfassung (Sunset gestern → Sunset heute) aus `hourly_data` plus den
neuen/eskalierten Diagnos-Auffälligkeiten. Ausgelöst wird der Versand vom
Automation-Daemon, sobald `is_day` von `True` auf `False` kippt (Sonnenuntergang).

Ablauf:

1. `automation_daemon` erkennt Sunset (`is_day` True→False).
2. `EventNotifier.sende_sunset_bericht()` sammelt Energie-/Health-Daten.
3. `_sende_sunset_mail()` verschickt via `notify/mail.py:smtp_versand`.
4. Dedup-Marker in `config/event_notifier_dedup.json` verhindert Doppelversand
   (1×/Tag, Reset bei Tageswechsel).

Dieselbe Infrastruktur trägt auch Sofort- und Integrity-Alarme.

## Konfiguration

Alles über `sudo python3 pv-config.py` → **Benachrichtigungen**:

- **Empfänger** (`NOTIFICATION_EMAIL`)
- **Events** (`NOTIFICATION_EVENTS`) — für den Tagesbericht muss
  `sunset_tagesbericht` aktiv sein.
- **SMTP** (`NOTIFICATION_SMTP_HOST/PORT/USER`, `NOTIFICATION_FROM`) in `config.py`.
- **SMTP-Passwort** — AES-verschlüsselt, Machine-ID-gebunden, in
  `/etc/pv-system/smtp_pass.key` (`credential_store`). Steht **nie** im Repo.

## Wichtig: Passwort ist hostgebunden

Das SMTP-Passwort wird mit der `/etc/machine-id` verschlüsselt und lässt sich
auf **keinem anderen Host** entschlüsseln. Nach jeder Host-Migration,
SD-Neuinstallation oder jedem Failover-Swap **muss es neu gesetzt werden** —
Kopieren der Datei genügt nicht.

## Fehlersuche

1. **Health-Check zuerst:** `python3 -m diagnos.health --pretty` →
   `notification_ready`. CRIT = Credential fehlt (häufigste Ursache).
2. **Logs:** `journalctl -u pv-automation | grep -iE "sunset|tagesbericht"`.
   `SMTP-Passwort nicht gesetzt (credential_store)` → Passwort neu setzen.
3. **Test-Mail:** pv-config → Benachrichtigungen → „Test-Mail senden".
   Zeigt „Passwort ✗ FEHLT", solange kein Credential gesetzt ist.

### Fix (Standardfall: Credential fehlt)

```bash
sudo python3 pv-config.py
# → Benachrichtigungen → „SMTP-Passwort setzen" → danach Test-Mail
```
