# Audit — System / Ops

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Übergreifend: Hosts/UFW, Rollenmodell-Doku, IP-Strategie, Cards-Code-Anchor-Integrität, Publish-Guard.

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| S-01 | HOCH | [AGENTS.md](../../AGENTS.md) nannte Pi4-Primary-UFW „noch nicht aktiviert (TODO)". | **Korrigiert** auf „aktiv (seit 2026-05-03)" — deckt sich mit User-Memory (UFW seit 2026-05-03 auf .181 aktiv). |
| S-02 | NIEDRIG | Dateiname `ABCD_ROLLENMODELL.md` (kosmetische Legacy, Modell ist A–E). | **Erledigt 2026-07-11:** umbenannt in `ABCDEN_ROLLENMODELL.md` (Rolle N ergänzt); alle Verweise nachgezogen. |
| S-03 | INFO | IP-Platzhalter-Strategie (`192.0.2.x` in Doku vs. `192.168.2.x` real). | **Bewusst/konsistent** — Publish-Guard maskiert sensible IPs. |
| S-04 | INFO | Code-Anchor aller geprüften Cards (11 Stichproben) gültig. | OK. |
| S-05 | INFO | `last_review`-Pflicht bei Card-Edits (Pre-commit). | Eingehalten: einzige editierte Card (collector-db-schema) auf 2026-05-29 gesetzt. |

## Konsistenz & Pflege

- TODO-Disziplin „keine TODOs in Subdirectories" eingehalten; alle Code-Punkte in [doc/TODO.md](../TODO.md).
- `ollama/system_prompt_kern.md` enthielt nicht-existente `battery_control_log`-Retention → korrigiert.

## Fazit

Wichtigster Ops-Befund (UFW-Status in AGENTS.md) behoben. IP-Strategie und ABCD-Dateiname sind bewusste/kosmetische Punkte ohne Handlungsdruck. Keine Code-Änderung im Audit.

---

## Update 2026-06-06 — 64bit-OS Tauglichkeitspruefung (Primary)

**Datum:** 2026-06-06  
**Audit-ID:** SYSCAP-2026-06-06  
**Anlass:** Systemwechsel auf 64bit-OS; Validierung der Produktionsfaehigkeit fuer PV-System inkl. Python/SQLite-Historie.

### Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| S-06 | HOCH | Laufendes System auf Debian 13 (trixie), `arm64`, Python `3.13.5`, systemd `257`; zentrale PV-Services aktiv. | **OK**: Produktionsbetrieb intakt nach OS-Wechsel (Collector/Web/Automation/Wattpilot/Steuerbox `active`). |
| S-07 | MITTEL | Historischer Sonderpfad "manuell kompiliertes Python/SQLite + Upgrade-Block" ist im aktuellen Host nicht mehr gegeben. Python stammt aus `python3-minimal`, keine lokalen `/usr/local/bin/python*` Binaries. | **Neu bewertet**: Altregel nur noch als Legacy-Hinweis fuehren, nicht als operative Pflicht fuer diesen Host. |
| S-08 | MITTEL | `sqlite3` CLI und mehrere Ops-Tools fehlten initial (`rg`, `jq`, `tmux`, `tree`, `shellcheck`, `fzf`, `yq`). | **Behoben**: Pakete installiert (siehe Massnahmen). |
| S-09 | NIEDRIG | Fremdarchitektur `armhf` war noch konfiguriert, obwohl keine `:armhf` Pakete installiert waren. | **Behoben**: `armhf` als unnötige Legacy-Konfiguration entfernt. |
| S-10 | INFO | Lokaler Python-Interpreter meldet SQLite `3.46.1`; `.venv`-Abhaengigkeiten sind konsistent (`pip check` in `.venv` ohne Fehler). | **OK** |
| S-11 | INFO | Systemweite `pip check`-Warnungen betreffen vor allem optionale Typ-Stubs/Tooling ausserhalb des produktiven `.venv`-Stacks. | **Beobachten**, kein produktiver Blocker. |
| S-12 | INFO | Peers (Pi4-Failover, Pi5-Backup, Pi5-NQ) waren vom Primary in dieser Session nicht erreichbar (DNS/Route). | **Nicht verifizierbar von hier**; Remote-Capability-Check separat auf den Zielhosts ausfuehren. |

### Durchgefuehrte Massnahmen

Ausgefuehrt auf Primary:

```bash
sudo apt update
sudo apt install -y sqlite3 ripgrep jq fd-find tmux tree shellcheck fzf bat yq
sudo dpkg --remove-architecture armhf
```

Installiert wurden 19 neue Pakete (inkl. Abhaengigkeiten). Resultat:

- `sqlite3`, `rg`, `jq`, `tmux`, `tree`, `shellcheck`, `fzf`, `yq` verfuegbar
- `armhf` nicht mehr als foreign architecture gesetzt
- Alle produktiven PV-Services weiterhin `active`

Hinweis Debian-Namenskonventionen:

- `fd` wird als `fdfind` installiert (Paket `fd-find`)
- `bat` wird als `batcat` installiert (Paket `bat`)

### Deinstallation / Entfernen unnötiger SW

- Durchgefuehrt: Entfernung unnötiger Multiarch-Konfiguration (`armhf`).
- Nicht durchgefuehrt: pauschale Paket-Deinstallationen ohne klaren Nachweis, um Produktionsrisiko (Abhaengigkeiten/seiteneffekte) zu vermeiden.
- `apt -s autoremove` zeigte in diesem Lauf keine offensichtlichen Kandidaten.

### Multi-Host Sicht (nur Capability-Blick)

Geplanter SSH-Quick-Check fuer Pi4-Failover, Pi5-Backup und Pi5-NQ konnte nicht ausgefuehrt werden:

- Hostnamen nicht aufloesbar (`Could not resolve hostname`)
- IP-Ziele nicht routbar (`Network is unreachable`)

Empfehlung fuer Vor-Ort-Check auf jedem Host:

```bash
uname -m
cat /etc/os-release | head -n 5
python3 --version
sqlite3 --version
command -v rg jq tmux fdfind batcat
dpkg --print-foreign-architectures
systemctl --failed --no-legend
```

### Risiko- und Betriebsbewertung

- Kein Hinweis auf weiterhin noetiges self-compiled Python/SQLite auf dem Primary.
- Der fruehere harte Update-Block sollte auf "gezielte, manuelle Security-Updates" umgestellt bleiben, statt blindem Voll-Upgrade.
- Vor groesseren Upgrades weiterhin Pflicht: Backup-Pruefung + Service/Freshness-Checks.

### Fazit

Der 64bit-Primary ist fuer das PV-System aktuell betriebsfaehig. Kritische Betriebsluecken aus dem Wechsel wurden geschlossen (Tooling + sqlite3 + bereinigte Architekturkonfiguration), ohne laufende Produktionsdienste zu stoeren. Offener Punkt ist ausschliesslich die getrennte, lokale Verifikation der System-Capabilities auf Failover/Backup/NQ bei wiederhergestellter Erreichbarkeit.

---

## Update 2026-06-06 — Naming, LAN-Autodetect, Access-Hardening, Update-Policy

**Datum:** 2026-06-06  
**Audit-ID:** OPS-HARDEN-2026-06-06  
**Anlass:** Konsolidierung nach Operator-Vorgaben (Primary-Naming, geschuetzte LAN-Daten, Wartungsfaehigkeit, Passwortlos-Setup, UFW, Upgrade-Block-Reset).

### Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| S-13 | MITTEL | Hostname ist bereits `Pi4-primary`; Doku enthaelt parallel neutrale Platzhalter wie `primary-host`. | **Kein Rename noetig**. Empfehlung: `Pi4-primary` als operativen Anzeigenamen beibehalten, Platzhalter in Public-Doku unveraendert lassen. |
| S-14 | HOCH | Kritische LAN-Topologie war nicht zentral fuer Wartungschecks nutzbar. | **Behoben**: Schutzwuerdige Topologie in `.infra.local` (gitignored) hinterlegt und per Script fuer Checks nutzbar gemacht. |
| S-15 | MITTEL | `admin` hatte kein `authorized_keys`, daher kein lokaler key-only Loginpfad. | **Behoben**: `~/.ssh/authorized_keys` mit lokalem ED25519-Key eingerichtet; localhost-SSH per Key erfolgreich. |
| S-16 | MITTEL | `sudo` verlangte Passwort bei jedem Lauf; gewuenscht war passwortloser Betriebsmodus. | **Behoben**: `/etc/sudoers.d/90-admin-nopasswd` erstellt und per `visudo -cf` validiert. |
| S-17 | HOCH | UFW war nicht aktiv installiert/konfiguriert auf diesem Host. | **Behoben**: UFW installiert und rollback-gesichert aktiviert (`deny incoming`, LAN-Allow fuer SSH+Web). |
| S-18 | MITTEL | Historischer Voll-Update-Block war nach 64bit-Migration nicht mehr professionell austariert. | **Behoben**: konservative Produktions-Policy mit Security-Unattended-Updates, Blacklist fuer Python/SQLite/Kernel, ohne Auto-Reboot. |
| S-19 | INFO | Peer-Capability-Checks: ein Host per SSH geprueft, andere wegen fehlender Auth nicht per SSH auslesbar. | **Teilweise**: Reachability im LAN OK, SSH-Capability-Detailpruefung fuer verbleibende Hosts nach Key-Verteilung wiederholen. |

### Durchgefuehrte Massnahmen

Code/Automation:

- `scripts/load_infra_env.sh`: Auto-Detection fuer `PV_LAN_IFACE`, `PV_LAN_CIDR`, `PV_LAN_GATEWAY`, `PV_DNS_PRIMARY`, `PV_PRIMARY_IP`.
- `scripts/safe_ufw_apply.sh`: robustere Fehlerpfade + Nutzung autodetektierter LAN-Werte.
- `scripts/check_network_capabilities.sh` neu: Wartungscheck fuer Netzbasis + kritische Hosts (ICMP).
- `scripts/enable_passwordless_sudo_admin.sh` neu: idempotente Einrichtung `NOPASSWD` fuer Admin.
- `scripts/apply_prod_update_policy.sh` neu: konservative APT/Unattended-Policy fuer Produktion.
- `.infra.local.example`: neue optionale Schluessel fuer LAN und Host-Checks dokumentiert.

Lokale geschuetzte Konfiguration (gitignored):

- `.infra.local` um LAN-Basis und kritische Host-Liste erweitert.
- Reale Infrastrukturwerte verbleiben ausschliesslich in lokalen, nicht versionierten Dateien.

Systemzustand nach Umsetzung:

- `sudo -n true` erfolgreich (passwortlos aktiv)
- UFW `active` mit LAN-Regeln fuer SSH/Web
- `unattended-upgrades.service` aktiviert
- Pi5-Backup (via SSH) um zentrale Ops-Tools erweitert: `ripgrep`, `jq`, `tmux`, `fzf`, `shellcheck` (und Abhaengigkeiten)

Peer-Status (kurz):

- Pi5-Backup: SSH-Zugriff + sudo ohne Passwort vorhanden, Capability-Verbesserung direkt umgesetzt.
- Failover/Ollama/NQ: Netzwerk-Reachability vorhanden, SSH-Login mit aktuellem Key noch nicht freigeschaltet.

### Risiko- und Betriebsbewertung

- "Teppich unter den Fuessen"-Risiko minimiert: UFW wurde ausschliesslich ueber rollback-gesicherten Apply-Prozess aktiviert.
- Security-Updates laufen kontrolliert; risikoreiche Kernpakete (Python/SQLite/Kernel) bleiben fuer manuelle Wartungsfenster reserviert.
- Sensible Topologie wird fuer Wartung genutzt, ohne in getrackter Doku offengelegt zu werden.

### Fazit

Primary-Naming ist bereits konsistent genug (`Pi4-primary`) und benoetigt keine Umbenennung. Die geforderten Betriebsmaßnahmen wurden umgesetzt: geschuetzte LAN-Nutzung fuer Wartung, passwortloser Admin/Sudo-Betrieb, aktive Firewall mit Safety-Rollback und ein professioneller, konservativer Update-Betriebsmodus fuer das Produktionssystem.

### Zusatz 2026-06-06 (Failover-105 Rebuild-Readiness)

- Direkte Fernvorbereitung auf den Failover-Host (`PV_FAILOVER_IP`) war in dieser Session nicht moeglich (SSH-Auth verweigert).
- Zur sofortigen Umsetzbarkeit wurden zwei Bausteine erstellt:
	- Runbook: `doc/system/FAILOVER_64BIT_REBUILD_RUNBOOK.md`
	- Automationsskript (auf 105 nach erstem Boot): `scripts/failover_postswap_quickstart.sh`
- Zielbild bleibt strikt ABCDE-konform: gleicher Code-Stand wie Primary, aber `failover`-Rolle und PASSIVE-Modus als Default.

### Zusatz 2026-06-06 (Pi4-Failover Software-Stand)

- Host ist aktuell ein frisch geflashtes Failover-System (`<failover-hostname>`), 64-bit `aarch64`.
- `.role` fehlt aktuell; der Host faellt damit auf den Default `primary` zurueck, was fuer Failover nicht ideal ist.
- GUI/Kiosk ist aktiv ueber `lightdm` + `lxsession` + `openbox` + `chromium-browser`.
- Kiosk-/Browser-Autostart ist gesetzt in der Display-Session-Autostart-Datei und startet den Browser auf `http://<primary-ip>:8000`.
- Bluetooth ist aktiv und nicht rfkill-blockiert; PulseAudio ist aktiv, PipeWire ist installiert.
- Typische GUI-/Kiosk-Helfer sind vorhanden: `unclutter`, `lxterminal`, `xserver-xorg`, `chromium-codecs-ffmpeg-extra`.
- Fuers reine Failover-/Info-System-Setup wirken eher entbehrlich: `onboard`, `cups`, `cups-browsed`, `snapd`, `ntp` neben `systemd-timesyncd`.
- `blueman` war nicht installiert; Bluetooth laeuft ueber `bluez` direkt, was fuer Audio ausreichend ist.
- Chromium wurde entfernt; Firefox ESR ist jetzt der Browser fuer den Info-Monitor.

### Bewertung

- Die aktuelle Software passt zu einem Desktop-/Info-Display mit Audio, ist aber **noch kein sauberes 64bit-Failover-Zielbild**.
- Vor einem produktiven Failover-Neuaufbau sollten GUI/Kiosk und Bluetooth erhalten bleiben, aber die Legacy-Altlasten im Desktop-Stack getrennt bewertet werden.
