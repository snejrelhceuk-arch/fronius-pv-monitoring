# Prompt: PAC4200-Browser-Clone vervollständigen

**Kontext:** Du arbeitest am pv-system (repo `{REPO_DIR}`,
branch `feat/reformation-wp-bridge`). Lies zuerst AGENTS.md vollständig. Dann:
- `doc/netzqualitaet/NQ_MODUL.md`
- `doc/netzqualitaet/MESSTECHNIK.md` (verifizierte Registeradressen)
- `doc/netzqualitaet/PAC4200-Modbus.md` (vollständige Registerreferenz)
- `nq/pac_live.py` (aktueller Snapshot-Code, FLOAT_MAP, FLOAT2_MAP, DOUBLE_MAP)
- `templates/pac4200_view.html` (aktueller Clone)
- `doc/llm/cards/netzqualitaet-nq-collector.card.md`

---

## Nutzeranforderungen (aus Gespräch)

1. **F-Tasten-Beschriftung zentrieren:** Die Beschriftungen „ESC", „▲ +", „▼ −", „Menü/OK"
   unter den F1–F4-Tasten sind nicht zentriert. In der CSS-Klasse `.key small` die
   Textausrichtung `text-align: center` sicherstellen. `display: block` ist gesetzt,
   aber `text-align` fehlt. Fix minimal, kein Refactor der key-Klasse.

2. **Zeigerdiagramm-Darstellung (Phasor Diagram):**
   Das reale PAC4200-Gerät zeigt einen Vektordiagramm-Bildschirm mit den drei
   Spannungszeigern (U_L1, U_L2, U_L3, je 120° versetzt) und den drei Stromzeigern
   (I_L1, I_L2, I_L3 mit Phasenverschiebung φ). Die Daten liefert der vorhandene
   Snapshot (`ang_L1/L2/L3` = Phasenverschiebungswinkel in °, `cosphi_L1/2/3`,
   vorzeichenbehaftete Ströme `Is_L1/2/3`, Spannungen `U_L1N/L2N/L3N`).
   Aufgabe: Einen neuen Screen `{"id": "phasor", "title": "Zeigerdiagramm"}` hinzufügen,
   der in der PAC-Display-Box mittels **inline SVG** (nicht Canvas, kein ECharts) ein
   einfaches Zeigerdiagramm mit folgenden Eigenschaften zeichnet:
   - 3 Spannungszeiger (blau, 120° versetzt, Länge = U_Lx / max(U) skaliert)
   - 3 Stromzeiger (rot, Länge = |Is_Lx| / max(|I|) skaliert, Winkel = Spannungswinkel + φ)
   - Phasenwinkel φ-Beschriftung (cos φ je Phase)
   - Read-only, rein aus den vorhandenen API-Daten (`/api/pac4200/live`)
   Der SVG-Code gehört in `_build_screens()` als `"svg"` statt `"lines"`, und der
   JS-Renderer in `pac4200_view.html` muss den Typ erkennen und den SVG-String direkt
   einfügen (kein weiterer Backend-Aufruf).

3. **THD-Anzeigen für einzelne Harmonische (H2..H64) — BLOCKIER-KLARSTELLUNG:**
   Der bisherige Kommentar „Harmonische 2..64 blockiert — Adressen fehlen" ist
   **inhaltlich falsch**. Die Modbus-Referenz `doc/netzqualitaet/PAC4200-Modbus.md`
   enthält **keine** Register für Einzelharmonische H2..H64! Das Dokument listet
   nur **THD-Gesamtwerte** (§7/§38/§39) und **Verzerrungsstrom** (§40), aber
   **keine Amplitudenwerte der einzelnen Harmonischen-Ordnungen 2..64**.
   Dies ist ein bekanntes Siemens-Verhalten: Das PAC4200 exportiert per Modbus
   keine Einzelharmonik-Spektren in der öffentlichen Register-Map.

   **Konsequenz + Aufgabe:**
   a) Korrigiere den Kommentar in `doc/netzqualitaet/MESSTECHNIK.md` Abschnitt
      „Gemessene Refresh-Raten": Nicht „Adressen noch offen", sondern
      „**PAC4200 liefert per Modbus keine Einzelharmonischen 2..64** — nur THD-
      Gesamtwert (§38/§39) und Verzerrungsstrom (§40). Kein Slow-Block möglich."
   b) Entferne den `nq_raw_slow`-Teilbereich aus der aktiven Poller-Logik (er ist
      in `nq/collector/nq_poller.py` noch als Kommentar präsent); das Schema
      `nq_tech_schema.sql` darf die Tabelle behalten (für zukünftige Daten aus
      anderen Quellen), aber kein Code darf versuchen, sie zu befüllen.
   c) Aktualisiere die `config/nq_config.json`: `"slow_ms"` bleibt als Konfig-
      Option (für externe Messgeräte), ist aber im Poller disabled.

4. **Weitere verfügbare Screens** (aus `PAC4200-Modbus.md` ableitbar, noch nicht
   implementiert):
   - Min/Max-Werte (§12–§22): neuer Screen „Extremwerte" mit U_max/U_min je Phase,
     I_max, P_max/min — direkt aus den verifizierten Adressen @75..143 lesen,
     analog zum bestehenden Block-B-Read (FLOAT2_MAP erweitern, neuer Block C
     @75..143, ca. 35 Werte).
   - Gleitende Mittelwerte (§44–§52): Screen „Gleitende Mittelwerte" mit MW-Spannung,
     MW-Strom, MW-Leistung (Adr. @301..367). Sinnvoll für Trending.
   - Demand/Periode (§54–§55): Screen „Demand / Periode" mit Mittelwert P/Q/S in
     aktueller Abrechnungsperiode, Max P (Adr. @489..515). Relevant für Netzvertrag.
   Implementierungsreihenfolge: Extremwerte zuerst (einfachster Mehrwert).

5. **Gerätegröße:** Die Darstellung ist gut. Auf sehr kleinen Screens (<400px) soll
   die Breite auf 100vw aufgehen (bereits mit `max-width: 97vw` fast erreicht — prüfen
   ob `width: 460px` auf Mobile korrekt auf 100% springt). Breakpoint bei 480px.

---

## Keine Änderungen an
- Der Modbus-Read-Logik (read-only, verifiziert)
- Den anderen `.service`-Dateien oder der Tech-Deployment-Kette
- `data.db` oder der Produktions-Pipeline

## Definition of Done
- F-Tasten-Beschriftung korrekt zentriert (CSS fix, 1 Zeile).
- Zeigerdiagramm-Screen vorhanden, korrekt aus Live-Daten berechnet.
- Kommentar Harmonische 2..64 in MESSTECHNIK.md korrigiert.
- Neue Screens (Extremwerte) live via `/api/pac4200/live` abrufbar.
- `python3 -m py_compile nq/pac_live.py` und Doc-Check exit 0.
- `pv-web.service` neu gestartet, `/pac4200` HTTP 200.
