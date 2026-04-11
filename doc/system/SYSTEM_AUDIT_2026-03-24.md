# Systemprüfung — 24. März 2026

Durchgeführt: Copilot-gestützte Prüfung aller Schichten.
Schwerpunkte: Web-API, Automations-Engine, Code-Qualität, Sensible Daten.

Weiterführend (Urheberschaft/KI-Anteile):
- `doc/meta/KI_BEITRAGSANALYSE.md` (gepflegt)
- `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md` (historische Langfassung)

---

## 1  Web API — Sicherheit

| Schwere | Befund | Ort |
|---------|--------|-----|
| **KRITISCH** | Alle API-Endpunkte ohne Authentifizierung | Alle Routen |
| **HOCH** | CORS default `*` — jede Origin erlaubt | `web_api.py` L49-54 |
| **HOCH** | XSS im Mirror-Banner: `MIRROR_SOURCE` wird nicht HTML-escaped | `web_api.py` L86 |
| **MITTEL** | `str(e)` in Error-Responses → leakt DB-Schema, Pfade | Alle Blueprints |
| **MITTEL** | `/api/mirror_status` exponiert Failover-Topologie | `web_api.py` L104 |
| **MITTEL** | `/api/bulk_load` ohne Pagination → DoS-Risiko | `routes/realtime.py` L245 |
| **MITTEL** | Keine Input-Validierung auf `year`/`month` → ValueError | `routes/erzeuger.py`, `routes/visualization.py` |
| **MITTEL** | `0.0.0.0`-Binding in Produktion | `config.py` L77 |
| **NIEDRIG** | Kein Rate-Limiting | — |

**Empfehlung:** API-Key für `/api/*`, `html.escape()` für Banner, Error-Messages generisch, CORS einschränken.

---

## 2  Automations-Engine

| Schwere | Befund | Ort |
|---------|--------|-----|
| **HOCH** | Fritz!Box offline → HP-Sicherheitsabschaltung scheitert still | `aktor_fritzdect.py` L180 |
| **HOCH** | WW-Temp `None` (Modbus-Ausfall) → Notaus greift nie | `regeln/geraete.py` L430 |
| **MITTEL** | `soc = None` → `TypeError` in `batt_rest_kwh`-Berechnung | `regeln/geraete.py` L630 |
| **MITTEL** | Burst-Timer bei Daemon-Restart verloren | `regeln/geraete.py` L248 |
| **MITTEL** | `_grid_history` (deque) nicht thread-safe gg. Tier-3 | `regeln/geraete.py` L293 |
| **MITTEL** | Forecast-Fehler still → HP-Entscheidungen auf leeren Daten | `automation_daemon.py` L286 |
| **MITTEL** | `sunrise/sunset = None` → TypeError | `regeln/geraete.py` L325 |
| **NIEDRIG** | HP-Nennleistung 2000 W an 4+ Stellen hardcoded | `regeln/geraete.py` L278 |
| **NIEDRIG** | Extern-Respekt + Notaus: kein Reset von `_extern_ein_ts` | `regeln/geraete.py` L442 |

**Empfehlung:** Sofort: Null-Guards für `soc`, `ww_temp_c`, `sunrise/sunset`.
Fritz!Box-Heartbeat + Tier-1-Alarm. Burst-State persistieren.

---

## 3  Code-Qualität — Ergebnis

Bereinigung durchgeführt am 28. März 2026 (ruff --fix + gezielte Einzelfixes).

**Ausgangslage:** 369 Findings → **Ergebnis:** 103 verbleibend
(davon 43 E402 bewusst, 31 F841 teils gewollt, 23 E701/E702 Stilwahl,
3 E741 fachliche Variablennamen, 6 S324 protokollbedingt MD5).

Wesentliche Fixes:
- 60 unbenutzte Imports entfernt (F401)
- 106 f-strings ohne Platzhalter bereinigt (F541)
- 5× `raise X from exc` (B904), 2× `random` → `secrets` (S311)
- 47× try-except-pass reviewt (1 gefixt, 46 bewusst OK)

---

## 4  Sensible Daten

| Prüfpunkt | Ergebnis |
|-----------|----------|
| IP-Adressen im Repo | ✅ Nur 192.0.2.x (TEST-NET-1/RFC 5737) |
| E-Mail-Adressen | ✅ `@example.invalid` |
| `.secrets`-Datei | ✅ In `.gitignore`, nie committet |
| `fritz_config.json` | ✅ In `.gitignore`, nie committet |
| Fritz!DECT AINs | ✅ Nur Platzhalter in tracked Files |
| SMTP-Provider | ✅ Bereinigt (History + Dateien) |

Schutzmaßnahmen: `.publish-guard` Pattern-Matching + `commit-msg`-Hook aktiv.

---

## 5  Offene Maßnahmen

- [ ] API-Authentifizierung implementieren (API-Key oder Token)
- [ ] Fritz!Box-Heartbeat + Tier-1-Alarm bei Ausfall
- [ ] Burst-State nach JSON persistieren
