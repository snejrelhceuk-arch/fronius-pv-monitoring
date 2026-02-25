# Veröffentlichungs- und Compliance-Richtlinie

**Stand:** 22. Februar 2026  
**Status:** Governance-Dokument  
**Geltungsbereich:** Externe Veröffentlichung von Code, Doku, Screenshots, Daten und Beispielen aus dem Repo `pv-system`

---

## 1. Zweck

Diese Richtlinie definiert, wie Inhalte aus diesem Projekt veröffentlicht werden,
ohne Urheberrechte, Nutzungsbedingungen, Geheimhaltungsinteressen oder
Sicherheitsgrenzen zu verletzen.

Sie ergänzt die technische Architektur und ist bewusst getrennt von
`doc/ABC_TRENNUNGSPOLICY.md`.

---

## 2. Grundsatz

- **Eigene Darstellung ja, fremde Originalinhalte nein.**
- Technische Fakten dürfen erklärt werden, aber keine wörtliche oder
  strukturgetreue Übernahme geschützter Herstellerinhalte.
- Nicht-kommerzielle Veröffentlichung ist kein automatischer Rechtsschutz.

---

## 3. Zulässig / Nicht zulässig

### Zulässig
- Eigene Formulierungen, eigene Diagramme, eigene Codebeispiele.
- Verlinkung auf öffentlich zugängliche Herstellerdokumentation (Link statt Kopie).
- Eigene Integrationslogik für legitimen Eigenbetrieb.

### Nicht zulässig
- Copy/Paste aus Hersteller-PDFs, Portalen, Handbüchern oder geschützten Tabellen.
- Screenshots/Abbildungen aus Herstellerportalen ohne ausdrückliche Freigabe.
- Veröffentlichung von Secrets, Tokens, Seriennummern, Kundendaten,
  internen Hostdetails oder privaten Zugangsinformationen.
- Anleitungen zur Umgehung von Schutzmechanismen, Zugriffsbeschränkungen
  oder Vertrags-/ToS-Vorgaben.

---

## 4. Redaktionsregeln für kritische Inhalte

Wenn ein Abschnitt auf Herstellerwissen basiert:

1. in eigene Worte überführen,
2. auf notwendiges Minimum kürzen,
3. auf öffentliche Quelle verlinken,
4. keine Originaltabellen/Originalgrafiken übernehmen.

---

## 5. Pre-Release-Check (Pflicht)

Vor jedem öffentlichen Push/Release:

- [ ] Keine wörtlich übernommenen Herstellertexte in `README.md`, `doc/*`, `automation/*`.
- [ ] Keine fremden Tabellen/Grafiken/Screenshots ohne Nutzungsrecht.
- [ ] Keine Secrets/Tokens/Kundendaten/Seriennummern im Repository.
- [ ] Keine Umgehungsanleitungen für Hersteller-Schutzmechanismen.
- [ ] Kritische Passagen durch 4-Augen-Prüfung gegengecheckt.

---

## 6. Kommunikationsprinzip

- Sachlich und interoperabilitätsorientiert kommunizieren.
- Projekt nicht als Ersatz/Abwerbung eines Herstellerdiensts darstellen.
- Bei berechtigter Beanstandung schnell reagieren und dokumentieren.

---

## 7. Takedown- und Eskalationsprozess

1. Eingang einer Beanstandung dokumentieren.
2. Betroffene Inhalte temporär depublizieren.
3. Sachverhalt und Rechte-/Vertragslage prüfen.
4. Bereinigte Fassung veröffentlichen und Entscheidung nachvollziehbar festhalten.

---

## 8. Abgrenzung zu technischer Architektur

- **Technische Systemgrenzen (A/B/C):** `doc/ABC_TRENNUNGSPOLICY.md`
- **Betriebs- und Schutzregeln:** `doc/SCHUTZREGELN.md`
- **Rollen/Failover-Betrieb:** `doc/DUAL_HOST_ARCHITECTURE.md`
- **Recht/Veröffentlichung/Compliance:** diese Datei

---

## 9. Hinweis

Diese Richtlinie ist eine operative Governance-Hilfe und ersetzt keine
individuelle Rechtsberatung.
