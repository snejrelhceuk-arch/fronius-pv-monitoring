# Tägliche Mail (Tagesbericht) & Alarm-Mails

Kurzreferenz für Betrieb und Fehlersuche. LLM-Card:
[`doc/llm/cards/diagnos-daily-mail.card.md`](../llm/cards/diagnos-daily-mail.card.md).

## Was ist die „tägliche Mail"?

Es ist **kein** 06:00-Cron, sondern der **Tagesbericht**: ein reiner
Energie-Auszug für den **abgelaufenen Kalendertag** (00:00→00:00), ausgelöst beim
Tageswechsel um 00:00 vom Automation-Daemon. Vier Abschnitte mit je fünf
Kernwerten (Erzeugung, Verbrauch, Netzbezug, Einspeisung, Batterie):

- **Tag** — abgelaufener Kalendertag; zusätzlich Stresszeit-% (SOC außerhalb des
  Komfortbands) und Verbraucher (WP/HP/Wattpilot/Haushalt).
- **Monat / Jahr / Gesamt** — aufgelaufene Stände bis zum Ende des abgelaufenen Tages.

**Keine** Health-/Integrität-/Netzqualität-/Warn-Inhalte: Systemfehler laufen
ausschließlich über die separaten Sofort-Alarme (dieselbe SMTP-Infrastruktur).

Ablauf:

1. Der `automation_daemon` ruft je Zyklus `EventNotifier.sende_tagesbericht()`;
   Dedup (1×/Tag) und das daily_data-Gate steuern die Fälligkeit.
2. `_sammle_tagesdaten()` liest die Energiewerte aus `daily_data` (Tag + Monat-/
   Jahr-Summen), `yearly_statistics` (historische Jahre → Gesamt), `data_1min`
   (Stresszeit) und `heizpatrone_daily`/`wattpilot_daily` (Verbraucher). Fehlt die
   daily_data-Zeile des Vortags noch, wird verschoben (Karenz 1 h, danach
   `hourly_data`-Fallback).
3. Die Textzeilen baut [`notify/report_format.py`](../../automation/engine/notify/report_format.py) (`tagesbericht`);
   `_sende_tagesbericht_mail()` verschickt via `notify/mail.py:smtp_versand`.
4. Best-effort und **entkoppelt** aktualisiert `_aktualisiere_statusdateien()`
   danach `logs/diagnos/{RAW,System,Netz}-Status.md` (nicht mehr in der Mail verlinkt).
5. Dedup-Marker in `config/event_notifier_dedup.json` verhindert Doppelversand
   (1×/Tag, Reset bei Tageswechsel).

Dieselbe Infrastruktur trägt auch die Sofort-/Integrity-Alarme (CRIT/FAIL).

## Konfiguration

Alles über `sudo python3 pv-config.py` → **Benachrichtigungen**:

- **Empfänger** (`NOTIFICATION_EMAIL`)
- **Events** (`NOTIFICATION_EVENTS`) — für den Tagesbericht muss
  `tagesbericht` aktiv sein.
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
2. **Logs:** `journalctl -u pv-automation | grep -i tagesbericht`.
   `SMTP-Passwort nicht gesetzt (credential_store)` → Passwort neu setzen.
3. **Test-Mail:** pv-config → Benachrichtigungen → „Test-Mail senden".
   Zeigt „Passwort ✗ FEHLT", solange kein Credential gesetzt ist.

### Fix (Standardfall: Credential fehlt)

```bash
sudo python3 pv-config.py
# → Benachrichtigungen → „SMTP-Passwort setzen" → danach Test-Mail
```
