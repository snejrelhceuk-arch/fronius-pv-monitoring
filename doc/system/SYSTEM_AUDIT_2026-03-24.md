# Systemprüfung — 24. März 2026

Durchgeführt: Copilot-gestützte Prüfung aller Schichten.
Schwerpunkte: Web-API, Automations-Engine, Code-Qualität, Sensible Daten.

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

## 3  Code-Qualität (ruff, 369 Findings)

| Kategorie | Anzahl | Bewertung |
|-----------|--------|-----------|
| f-string ohne Platzhalter (F541) | 106 | Kosmetisch |
| Unbenutzte Imports (F401) | 59 | `ruff --fix` |
| `try-except-pass` (S110) | **47** | **Risiko: stille Fehler** |
| Unbenutzte Variablen (F841) | 31 | Teils gewollt |
| MD5-Nutzung (S324) | 6 | Protokollbedingt (Fritz, Fronius Digest Auth) |
| `raise` ohne `from` (B904) | 5 | Traceback geht verloren |
| `random` statt `secrets` (S311) | 2 | Token-Generierung |
| Doppelter Dict-Key (F601) | 1 | Bug in `tools/wattpilot_read.py` |
| Bind `0.0.0.0` (S104) | 1 | Bewusst, aber ohne Firewall riskant |

**Top-10 nach Dateigröße:** `pv-config.py` (2085 Z.), `solar_geometry.py` (1979 Z.),
`solar_forecast.py` (1353 Z.), `routes/system.py` (1349 Z.), `regeln/geraete.py` (1143 Z.).

**Empfehlung:** `ruff check --fix --select F401,F541,W292` (170+ Auto-Fixes).
47× try-except-pass gezielt überprüfen.

### 3.1  Durchgeführte Bereinigung (28. März 2026)

**ruff --fix Auto-Fixes (169 Stellen):**
- F401: 60 unbenutzte Imports entfernt
- F541: 106 f-strings ohne Platzhalter bereinigt
- E401: 3 Mehrfach-Imports aufgeteilt

**Gezielte Fixes (8 Stellen):**
- B904: 5× `raise X from exc` in `wattpilot_api.py` (Traceback-Kette bewahrt)
- S311: 2× `random.randrange` → `secrets.token_hex` in Auth-Token-Generierung
  (`wattpilot_api.py`, `tools/wattpilot_read.py`)
- F601: 1× doppelter Dict-Key `'ust'` in `tools/wattpilot_read.py` entfernt

**try-except-pass Review (47 Stellen):**
- 46× als OK-OPTIONAL eingestuft (Cleanup-Blöcke, optionale Tabellen, graceful degradation)
- 1× FIX-LOG: `automation_daemon.py` L322 — RAM-DB-Reconnect-Fehler wird jetzt geloggt

**Ergebnis:** 273 Findings → 103 (davon 43 E402 bewusst, 31 F841 teils gewollt,
23 E701 Stilwahl, 3 E702 Stilwahl, 3 E741 fachliche Variablennamen).

---

## 4  Sensible Daten in Commits

| Prüfpunkt | Ergebnis |
|-----------|----------|
| IP-Adressen im Repo | ✅ Nur 192.0.2.x (TEST-NET-1/RFC 5737) |
| E-Mail-Adressen | ✅ `@example.invalid` |
| `.secrets`-Datei | ✅ In `.gitignore`, nie committet |
| `fritz_config.json` | ✅ In `.gitignore`, nie committet |
| Fritz!DECT AINs | ✅ Nur Platzhalter `00000 0000000` |
| Fritz!Box-Default-IP `192.168.178.1` | ⚠️ Standard, kein echter Leak |
| **SMTP-Provider (Name redacted)** | **🔴 War in 1 Commit-Message + 3 Datei-Diffs** |

### Durchgeführte Bereinigung

1. **Docstring** in `pv-config.py` L1874: Providername entfernt → „konfigurierten SMTP-Server"
2. **Git-History** vollständig umgeschrieben via `git filter-repo --replace-text --replace-message`
   - Ersetzungen: Providername → generische Bezeichnung in allen Varianten
   - Betroffen: 3 Commits (Blobs) + 1 Commit-Message
   - Backup-Tag: `backup/pre-filter-smtp-provider` (alte Hashes, lokal)
3. **`.publish-guard`** erweitert um Providername-Pattern (case-insensitive)
4. **`commit-msg`-Hook** erstellt — prüft Commit-Messages gegen dieselben Sperrmuster

### Verifizierung nach Bereinigung

```
Commit-Messages mit Providername: 0
Datei-Diffs mit Providername:    0
.publish-guard Pattern-Test:  ✅ blockiert
```

---

## 5  Offene Maßnahmen

### Sofort nötig

- [ ] `chmod +x .git/hooks/commit-msg` (Hook muss ausführbar sein)
- [ ] `git push --force-with-lease origin main` (umgeschriebene History publizieren)
- [ ] Failover-Host: `git fetch origin && git reset --hard origin/main`

### Kurzfristig

- [ ] API-Authentifizierung implementieren (API-Key oder Token)
- [ ] Fritz!Box-Heartbeat + Tier-1-Alarm bei Ausfall
- [ ] Burst-State nach JSON persistieren

### Erledigt (28. März 2026)

- [x] `html.escape(MIRROR_SOURCE)` in `web_api.py` — XSS-Fix
- [x] Error-Responses generisch (35 Stellen in 7 Dateien → `api_error_response()`)
- [x] WW-Temp Null-Guard + 300s-Watchdog in `regeln/geraete.py`
- [x] CORS default `*` → same-origin (explizites Opt-in via `PV_API_CORS_ORIGINS`)
- [x] Input-Validierung `year`/`month` in 9 Endpoints (4 Blueprints + visualization)
- [x] `/api/bulk_load` mit max 7d Zeitfenster + 200k Row-Limit + truncated-Flag
- [x] `ruff --fix` für F401, F541, E401 (169 Auto-Fixes)
- [x] 47× try-except-pass systematisch reviewt (1 gefixt, 46 bewusst OK)
- [x] B904 (5×), S311 (2×), F601 (1×) — gezielte Einzelfixes
- [x] `random` → `secrets` für Auth-Token-Generierung (Wattpilot)
