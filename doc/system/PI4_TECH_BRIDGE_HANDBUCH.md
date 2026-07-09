# Pi4-Tech WP-Hardware-Bridge — Betriebshandbuch

> Rolle: **HW-Bridge** (keine eigene Engine). Stellt die WP-Modbus-Schnittstelle
> (RS485/tty) als abgesicherten HTTP-Dienst für den entfernten Primary bereit.
> Quelle: [wp_bridge/wp_bridge_api.py](../../wp_bridge/wp_bridge_api.py),
> Client-Seite: [wp_modbus.py](../../wp_modbus.py).

## Zweck

Nach der REFORMATION besitzt der neue Primary (Pi5) **keine** WP-Hardware mehr.
Rolle C (Automation) spricht die WP über HTTP an; die physische RS485-Verbindung
(`/dev/ttyACM0`, 19200 8N1, Slave 1) hängt an **Pi4-Tech** (alter Primary, 192.0.2.181).

- Primary/Failover: `PV_WP_BACKEND_MODE=remote` → `wp_modbus` ruft die Bridge.
- Pi4-Tech: `PV_WP_BACKEND_MODE=local` → `wp_modbus` spricht direkt die Serial-HW.

Die Bridge führt **keine** Regel-/Entscheidungslogik aus — nur Hardwarezugriff auf Kommando.

## Endpunkte

| Methode | Pfad | Auth | Zweck |
|---|---|---|---|
| GET  | `/health`        | nein | Liveness (kein Serial-Zugriff) |
| GET  | `/api/wp/status` | Bearer | WP-Register lesen → `{ok,data}` |
| POST | `/api/wp/write`  | Bearer | Whitelist-Register schreiben `{name,value}` → `{ok}` |

Schreib-Whitelist (aus `wp_modbus._WRITE_REGS`): `heiz_soll` (18–60 °C, Reg 5037),
`ww_soll` (10–85 °C, Reg 5047). Alles andere → HTTP 400.

## Sicherheit

- **Token, fail-closed:** Ohne konfiguriertes `PV_WP_BRIDGE_TOKEN` liefern die
  geschützten Endpunkte HTTP 503 (kein offener HW-Schreibzugang). Vergleich per
  `hmac.compare_digest`.
- **Whitelist + Wertebereich** werden serverseitig geprüft (Defense-in-Depth;
  der Client `wp_modbus` prüft zusätzlich vor dem HTTP-Call).
- **Rate-Limit:** global `PV_WP_BRIDGE_RATE_LIMIT_PER_MIN` (Default 60),
  Schreiben separat `PV_WP_BRIDGE_WRITE_LIMIT_PER_MIN` (Default 12) → HTTP 429.
- **Audit-Log:** jede Schreibaktion nach `logs/wp_bridge_audit.log`
  (Zeitpunkt, Quelle-IP, Register, Wert, Ergebnis; **keine** Secrets).
- **UFW:** Port `8091/tcp` nur für den Primary (und Failover) freigeben:
  `sudo ufw allow from 192.0.2.204 to any port 8091 proto tcp`.
- **Kein Split-Brain:** `main()` verweigert den Start bei `WP_BACKEND_MODE=remote`.

## Installation (Pi4-Tech)

```bash
# 1) .infra.local / .secrets setzen
echo 'PV_WP_BACKEND_MODE=local'            >> .infra.local
echo 'PV_WP_BRIDGE_BIND=0.0.0.0'           >> .infra.local
echo 'PV_WP_BRIDGE_PORT=8091'              >> .infra.local
echo 'PV_WP_BRIDGE_TOKEN=<32+ zeichen>'    >> .secrets   # Secret, NICHT in Git

# 2) Unit installieren
sudo cp config/systemd/pv-wp-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pv-wp-bridge.service

# 3) UFW
sudo ufw allow from 192.0.2.204 to any port 8091 proto tcp
```

**Wichtig:** Die Bridge darf die serielle WP-Schnittstelle **nicht** gleichzeitig
mit einer lokalen `pv-automation` nutzen (Serial-Contention). Auf Pi4-Tech läuft
daher **keine** Automation/Collector-Engine mehr.

## Smoke-Test

```bash
TOKEN=$(grep PV_WP_BRIDGE_TOKEN .secrets | cut -d= -f2)
curl -s http://192.0.2.181:8091/health
curl -s -H "Authorization: Bearer $TOKEN" http://192.0.2.181:8091/api/wp/status
# Schreibtest (verändert Sollwert!) nur bewusst:
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name":"ww_soll","value":50}' http://192.0.2.181:8091/api/wp/write
```

Erwartung: `/health` → `{"ok":true,...}`; ohne Token → 401; unbekanntes Register → 400;
Wert außerhalb Bereich → 400; zu viele Anfragen → 429.

## Fail-safe-Verhalten

- Bridge-Ausfall: `wp_modbus` (remote) liefert `get_wp_status()=None` bzw.
  `write_register()=False`. Der Aktor (`aktor_waermepumpe`) hat bounded Retry —
  **keine** unkontrollierten Wiederholungen, klare Fehlerlogs, kein Split-Brain.
- Serial-Fehler auf Pi4-Tech: Bridge liefert HTTP 502, keine Retries.

## Tests

`python3 tests/test_wp_transport.py` (Transport-Dispatch, Fail-safe, Bridge-Auth/
Whitelist/Range/Rate-Limit).
