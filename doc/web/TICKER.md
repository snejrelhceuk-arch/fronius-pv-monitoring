# Ticker im Web/Flow

Diese Seite dokumentiert nur die Einbindung im Web-Bereich.

## Verortung

- Die eigentliche Ticker-Implementierung und Betriebsdoku liegt im Service-Ordner:
  - `tools/ticker_service/README.md`
- Wenn intern von `tools/ticker/README` gesprochen wird, ist damit in diesem Repo
  die Datei `tools/ticker_service/README.md` gemeint.

## Laufzeitverhalten (Kurzfassung)

- Quellen: ARD/Tagesschau und Heise.
- Quoten im Ticker: ARD 12, Heise 3.
- Nur neue Meldungen werden vorne einsortiert.
- Pro Quelle gilt Rolling-Top-N:
  - neue Heise-Meldung rein -> aelteste Heise-Meldung raus (bei bereits 3 Heise)
  - neue ARD-Meldung rein -> aelteste ARD-Meldung raus (bei bereits 12 ARD)

## API-Anbindung im Web

- Web-Endpunkt: `/api/ticker` (Proxy auf den Ticker-Microservice)
- Konfiguration ueber `PV_TICKER_API_ENDPOINT`
