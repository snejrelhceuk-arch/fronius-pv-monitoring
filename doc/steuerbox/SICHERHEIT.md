# Steuerbox — Sicherheitskonzept

**Stand:** 2026-04-11
**Status:** Planungsdokument

---

## 1. Bedrohungsmodell

Die Steuerbox ist der einzige Weg, ueber den ein Endgeraet schreibende
Eingriffe ins PV-System ausloesen kann. Alle anderen Wege (Web-API, Diagnos)
bleiben read-only.

### Angriffsflaeche

| Vektor | Risiko | Gegenmassnahme |
|---|---|---|
| Netzwerk-Scan findet Port | Mittel | Nicht-Standard-Port + UFW IP-Allowlist |
| Unauthorisierter LAN-Client | Mittel | IP-Allowlist + Auth-Token |
| Replay-Angriff | Niedrig (LAN) | Nonce/Timestamp in Auth, Rate-Limit |
| Manipulation von Parametern | Hoch | Hard Guards serverseitig, Validator vor Aktion |
| Denial of Service | Niedrig (LAN) | Rate-Limit, Cooldown pro Aktion |
| Split-Brain (2 Schreiber) | Hoch | role_guard + Heartbeat-Fencing |

---

## 2. Netzwerksicherheit

### UFW-Regeln (auf Primary .181)

```bash
# Steuerbox-Port nur fuer freigegebene Endgeraete
sudo ufw allow from <GERAETE_IP>/32 to any port 8001 proto tcp \
  comment 'Steuerbox: Laptop Admin'
sudo ufw allow from <GERAETE_IP>/32 to any port 8001 proto tcp \
  comment 'Steuerbox: Handy Admin'

# NICHT: allow from <LAN_CIDR>
# Nur explizit freigegebene IPs!
```

### Port-Wahl

- Nicht-Standard-Port (z.B. 8001, konfigurierbar)
- Kein Internet-Exposure (nur LAN)
- Optional: Binding auf 127.0.0.1 + nginx Reverse-Proxy mit Client-Cert

---

## 3. Authentifizierung

### Einheitliches Modell (kein mTLS, kein Step-up)

- **API-Key** (langer zufaelliger String, in `.secrets` oder ENV)
- Uebertragung via HTTP-Header: `Authorization: Bearer <key>`
- Ein Key pro berechtigtem Endgeraet (oder ein geteilter Operator-Key)
- Key-Rotation: manuell, bei Verdacht auf Kompromittierung

### Warum kein mTLS

- Aufwand: Zertifikatsverwaltung, Rotation, Revocation fuer 2-3 Endgeraete
  uebersteigt den Nutzen im geschlossenen LAN
- IP-Allowlist + API-Key + UFW bieten vergleichbaren Schutz bei viel geringerem Betriebsaufwand

### Warum keine Zweitbestaetigung per Mail

- Unbequem fuer Alltagsschalter (HP, WP)
- Sicherheit kommt stattdessen von: serverseitigen Hard Guards,
  unausweichlichen Timeouts, Audit-Logging und Rate-Limiting

---

## 4. Eingabe-Validierung

### Hard-Guard-Validator (vor jeder Aktion)

```python
HARD_GUARDS = {
    'soc_min_pct':     {'min': 5},
    'soc_max_pct':     {'max': 100},
    'wp_offset_k':     {'min': -15, 'max': 0},
}
# Zeitbasierte Grenzen sind KEINE Hard Guards, sondern
# Teil des Respekt-Verfahrens (ARCHITEKTUR.md §5).
# Hard Guards pruefen nur physikalische Grenzen.
```

Ungueltige Werte werden **abgelehnt** (HTTP 422) mit klarer Fehlermeldung.
Kein stilles Clamping — der Operator soll wissen, dass sein Wunsch
unzulaessig war.

**Laufzeit-Guards (immer aktiv, auch bei Override):**
- HP bei SOC <= `extern_notaus_soc_pct` (15%): SOFORT AUS
- HP bei Uebertemperatur >= 78°C: SOFORT AUS
- Diese werden nicht vom Validator, sondern von der Automation (Engine fast-cycle)
  durchgesetzt — auch waehrend einer Respekt-Periode.

### Aktions-Whitelist

Nur explizit freigegebene Aktionen sind moeglich:

```python
ALLOWED_ACTIONS = {
    'hp_toggle',
    'wp_offset_mode',
    'battery_mode',
    'wattpilot_ctrl',
    'regelkreis_toggle',
}
```

Alles andere → HTTP 403.

---

## 5. Audit-Logging

Jede Aktion wird vollstaendig protokolliert:

| Feld | Inhalt |
|---|---|
| `ts` | Zeitstempel |
| `client_ip` | Absender-IP |
| `action` | Aktionsname |
| `params` | Uebergebene Parameter |
| `result` | Ergebnis (ok/error + Detail) |
| `guard_checks` | Welche Guards geprueft wurden |
| `override_id` | Referenz auf operator_overrides |
| `expires_at` | Wann der Override automatisch ablaeuft |

Audit-Log in `automation_obs.db` (Tabelle `steuerbox_audit`).
Zusaetzlich persistentes Log in `logs/schaltlog.txt` (SD).

---

## 6. Rate-Limiting und Cooldown

| Aktion | Rate-Limit | Cooldown |
|---|---|---|
| HP toggle | 1x pro 60s | 5 min nach AUS |
| WP Offset | 1x pro 120s | — |
| Batterie-Mode | 1x pro 120s | — |
| Wattpilot | 1x pro 60s | — |
| Regelkreis-Toggle | 1x pro 300s | — |

Bei Ueberschreitung: HTTP 429 mit Wartezeit in Sekunden.

---

## 7. Verwandte Dokumente

| Dokument | Zweck |
|---|---|
| [ARCHITEKTUR.md](ARCHITEKTUR.md) | Gesamtarchitektur Steuerbox |
| [TODO.md](TODO.md) | Implementierungsplan |
| [doc/system/ABCD_ROLLENMODELL.md](../system/ABCD_ROLLENMODELL.md) | Rollenmodell |
| [scripts/safe_ufw_apply.sh](../../scripts/safe_ufw_apply.sh) | UFW-Setup mit Rollback |
