# Steuerbox Arbeitsfortschritt 2026-04-11

## Umgesetzt

- Steuerbox-Konfiguration in config.py erweitert:
  - Host/Port (Default Port 11933)
  - Allowlist und Token-Auth-Schalter
  - Action-Whitelist
  - Hard-Guard-Konstanten
  - Respekt-Zeitgrenzen (900 bis 7200s)
- Neue Module angelegt:
  - steuerbox/validators.py
  - steuerbox/intent_handler.py
  - steuerbox/steuerbox_api.py
- API-Endpunkte:
  - GET /api/ops/health
  - GET /api/ops/status
  - GET /api/ops/audit
  - POST /api/ops/intent
- Port 11933 geprueft: aktuell frei (kein LISTEN-Eintrag)
- Sicherheitsreihenfolge umgesetzt:
  - zuerst IP-Allowlist
  - dann Auth-Check
- Failover-Verhalten umgesetzt:
  - POST auf Failover blockiert (read-only)
- Persistenz in /dev/shm/automation_obs.db vorbereitet:
  - operator_overrides
  - steuerbox_audit
- Neutral-Release umgesetzt:
  - UNBETAETIGT schliesst offene Overrides derselben Aktion und bleibt nutzbar
  - Statuswechsel auf released statt dauerhaft open
- UI-Cockpit umgesetzt (grosse Schalter):
  - WP-Modus mit Neutralstellung UNBETAETIGT
  - HP, Klimageraet, Lueftung als einheitliche AN/AUS Schalter mit neutraler Mitte
  - Wattpilot-Gruppe mit drei Schaltern:
    - ECO/Default
    - Start/Stop
    - 8A/24A
  - Start hat Doppelfunktion in Schicht C vorbereitet; keine externe Pause mehr in Schicht E
  - Schalterposition bleibt in der UI als Soll-Stellung sichtbar
  - Bei jedem Seitenaufruf initial alle Schalter auf UNBETAETIGT
- systemd Unit hinzugefuegt:
  - pv-steuerbox.service

## Noch offen

- Vertiefung der Schicht-C-Integration (Feinlogik je Aktor/Regelkreis)
- Enforcer (Schicht E Safety) mit Diagnos-Daten
- End-to-End-Tests laut LLM_AUSFUEHRUNG.md
- Produktive UFW-Regeln fuer den neuen Port 11933

## Integration gestartet (neu)

- Neuer Processor: automation/engine/operator_overrides.py
  - liest offene operator_overrides
  - mappt auf bestehende Aktor-Kommandos
  - fuehrt via Actuator aus
  - setzt Status auf done/failed
  - schreibt Audit in steuerbox_audit
- automation_daemon.py verarbeitet Overrides jetzt zyklisch vor Engine-Regeln
- wattpilot-Aktor erweitert um Lademodus-Kommandos:
  - set_charge_mode_eco
  - set_charge_mode_default
- Lueftung integriert (neu):
  - HA-Pfad verworfen (kein gueltiger Fritz-AIN)
  - verifizierte Fritz-AIN aus Readings: 00000 0000000
  - Mapping aktiv: lueftung_toggle -> fritzdect lueftung_ein/lueftung_aus -> device_id fussbodenheizung

## Rueckfragen

1. Soll die Browser-UI den Bearer-Token per Eingabefeld senden, oder soll der Zugriff nur ueber ein vorgeschaltetes Gateway/Proxy erfolgen?
2. Soll beim Klick auf UNBETAETIGT ein eigener Override geschrieben werden, oder soll das als rein visuelle Neutralstellung ohne DB-Eintrag gelten?
3. Soll beim Wattpilot-Start die 10s Pause fest sein, oder pro Aufruf konfigurierbar bleiben?
