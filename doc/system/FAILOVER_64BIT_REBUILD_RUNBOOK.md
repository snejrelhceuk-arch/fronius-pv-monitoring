# Failover 105 Rebuild Runbook (64bit)

Stand: 2026-06-06
Ziel: Neue 32GB-Karte von Host 116 fuer Pi4-Failover (105) vorbereiten, danach Kartenwechsel und Sofortstart im PASSIVE-Modus.

## 0. Sicherheitsprinzip

- Kein 1:1-Klon von 181.
- Gleichheit ueber gleichen Repo-Stand herstellen.
- Hostspezifisch bleiben nur Rolle, Hostname, lokale Infra-Datei, SSH/FW.

## 1. Vorbereitung auf Host 116 (mit eingelegter Ziel-SD)

1. Optionales Rueckfall-Image der alten Karte ziehen.
2. Raspberry Pi OS Lite 64bit auf die 32GB-Karte flashen (Raspberry Pi Imager empfohlen).
3. Imager-Advanced-Options setzen:
   - Hostname: Pi4-failover
   - User: jk (oder dein gewuenschter Failover-User)
   - SSH aktivieren
   - LAN/WLAN nach Bedarf
4. Karte sauber auswerfen.
5. Erst danach die Karte in Pi4-105 einsetzen.

## 1a. Wann der Tausch stattfinden soll

- Den Tausch erst machen, wenn das Image fertig geschrieben und der Auswurf ohne Fehler abgeschlossen ist.
- Nicht vorher umstecken, sonst ist die Karte potenziell unvollstaendig beschrieben.
- Nach dem Einsetzen auf 105 einmal komplett neu booten, damit der neue Stand sauber anlaeuft.

## 2. Erster Boot auf 105

1. Auf 105 einloggen.
   - Falls SSH schon aktiv ist: per SSH einloggen.
   - Falls nicht: lokal an Konsole/HDMI anmelden.
2. Basiswerkzeuge installieren:

   sudo apt update
   sudo apt install -y git curl rsync

3. Repo auschecken:

   mkdir -p ~/Documents/PV-Anlage
   cd ~/Documents/PV-Anlage
   git clone <dein-repo-url> pv-system
   cd pv-system

4. Lokale Infrastrukturdatei erstellen (sensibel, nicht committen):

   cp .infra.local.example .infra.local

5. Werte in .infra.local lokal eintragen (mindestens Primary/Failover/Wattpilot/Backup Hosts).
   - Wenn `sudo` nach einem Passwort fragt: das Passwort des beim Imager angelegten Users eingeben.
   - Ohne diese Werte bleibt der Host zwar bootfaehig, aber nicht betriebsbereit fuer den Mirror-/Health-Betrieb.

## 3. Sofortstart fuer Failover

Auf 105 im Repo-Root ausfuehren:

  bash scripts/failover_postswap_quickstart.sh --hostname Pi4-failover

Das Script erledigt:

- Paketbasis fuer den Betrieb
- .role = failover
- Install failover services/timer
- PASSIVE-Modus erzwingen
- Netz-/Host-Reachability-Check starten

## 4. Pflicht-Checks nach dem Start

1. Role pruefen:

   cat .role

   Erwartet: failover

2. Timer/Services pruefen:

   systemctl status pv-mirror-sync.timer --no-pager
   systemctl status pv-failover-health.timer --no-pager
   systemctl status pv-web.service --no-pager

3. Kein lokaler Writer aktiv im PASSIVE-Modus:

   systemctl is-active pv-collector.service
   systemctl is-active pv-wattpilot.service

   Erwartet: inactive (oder failed/unknown je nach Hostzustand, aber nicht active)

## 5. Wie sich das System beim Start verhaelt

- Vor dem Quickstart ist es ein normales Raspberry-Pi-OS-Lite-System mit Login auf Konsole bzw. per SSH.
- Nach `failover_postswap_quickstart.sh` ist die Rolle auf `failover` gesetzt und der Host bleibt im PASSIVE-Modus.
- Die Mirror- und Health-Timer starten automatisch.
- Wenn die GUI-/Kiosk-Komponenten installiert sind, startet der Display-Manager danach den Info-Bildschirm und der Browser oeffnet automatisch die Seite `http://<primary-ip>:8000` (aus `.infra.local`: `PV_PRIMARY_IP`).
- Was du selbst noch eingeben musst:
   - User-Login auf dem frischen System
   - ggf. `sudo`-Passwort
   - den Repo-Clone-Befehl mit deiner Repo-URL
   - die lokalen Werte in `.infra.local`
   - den Quickstart-Befehl

## 6. Optional: Schluesselzugriff von 181 auf 105

Von 181 den Admin-Key auf 105 einspielen und danach remote pruefen.

## 7. Rollback

Bei Problemen alte SD wieder in 105 einsetzen und rebooten.
