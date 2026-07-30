# Diagnos-Daily-Mail-Card

## Code-Anchor

- [`diagnos/mail.py`](./../../diagnos/mail.py)

## Invarianten

- Die tägliche Mail wird jeden Tag um 06:00 Uhr versendet.
- Die Mail enthält die täglichen Daten der PV-Anlage.
- Die Mail wird an die konfigurierte E-Mail-Adresse versendet.

## No-Gos

- Keine Änderungen an der Mail-Versendungszeit ohne explizite Freigabe.
- Keine Änderungen an der Mail-Inhalt ohne explizite Freigabe.
- Keine Änderungen an der Mail-Empfänger ohne explizite Freigabe.

## Häufige Aufgaben

- **Überprüfen der Mail-Logs**: Überprüfen Sie die Logs der Mail-Funktion, um festzustellen, warum die Mails nicht mehr versendet werden.
- **Überprüfen der Cron-Jobs**: Überprüfen Sie die Cron-Jobs, um festzustellen, ob der Cron-Job, der die tägliche Mail versendet, noch aktiv ist und zu der richtigen Zeit ausgeführt wird.
- **Überprüfen der Netzwerkverbindung**: Überprüfen Sie die Netzwerkverbindung, um festzustellen, ob die Netzwerkverbindung zum Mail-Server noch funktioniert.
- **Überprüfen der Mail-Konfiguration**: Überprüfen Sie die Mail-Konfiguration, um festzustellen, ob die Mail-Konfiguration noch korrekt ist.
- **Überprüfen der Fehlerbehandlung**: Überprüfen Sie die Fehlerbehandlung, um festzustellen, ob die Fehlerbehandlung in der Funktion, die die Mails versendet, noch korrekt ist.
- **Überprüfen der Mail-Queue**: Überprüfen Sie die Mail-Queue, um festzustellen, ob die Mail-Queue noch funktioniert und ob die Mails nicht in der Queue hängen bleiben.

## Verwandte Cards

- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`diagnos-integrity.card.md`](./diagnos-integrity.card.md)

## Human-Doku-Link

- [`doc/diagnos/MAIL.md`](./../../doc/diagnos/MAIL.md)

## Meta

- **last_review**: 2024-07-11
- **status**: experimental
