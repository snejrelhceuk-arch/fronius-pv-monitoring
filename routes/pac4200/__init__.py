"""Blueprint: PAC4200 Netzqualitäts-Messgerät (read-only Live-Anzeige, Package).

Aufgeteilt aus der frueheren Monolith-Datei ``routes/pac4200.py`` (2026-09-28):
  - ``_shared.py``       : NQ-DB-Verzeichnisse, Plausibilitaetsgrenzen, DB-Oeffner
  - ``pages.py``         : Seiten-Routen + Live-/Realtime-API
  - ``analyse.py``       : DFD-/Tages-/Wochenprofil + Event-Liste
  - ``energy.py``        : Energie-Fixpunkte + Vergleich PAC4200/SM/iMSys
  - ``spectral.py``      : Muster-/Spektral-/Reflexions-Analyse + Event-Drilldown
  - ``netzkriterien.py`` : Langzeit-Aggregate, Chart-Seite, Netzkriterien-API

Alle Endpunkte registrieren sich am gemeinsamen Blueprint ``bp``.
``bp`` wird zuerst definiert, danach werden die Submodule importiert, damit
deren ``@bp.route(...)``-Dekoratoren greifen (Standard-Flask-Muster).
``web_api.py`` bezieht das Blueprint weiterhin via ``from routes.pac4200 import bp``.
"""
from flask import Blueprint

bp = Blueprint('pac4200', __name__)

# Submodule importieren -> Routen registrieren sich am bp.
# Reihenfolge: reine Helfer (_shared) vor den Route-Modulen.
from routes.pac4200 import _shared  # noqa: E402,F401
from routes.pac4200 import pages  # noqa: E402,F401
from routes.pac4200 import analyse  # noqa: E402,F401
from routes.pac4200 import energy  # noqa: E402,F401
from routes.pac4200 import spectral  # noqa: E402,F401
from routes.pac4200 import netzkriterien  # noqa: E402,F401

__all__ = ['bp']
