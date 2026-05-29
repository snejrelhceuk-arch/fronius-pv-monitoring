"""Blueprint: System-Status-APIs (Package).

Aufgeteilt aus der frueheren Monolith-Datei ``routes/system.py`` (2026-05-29):
  - ``info.py``      : /api/system_info, /api/ticker
  - ``battery.py``   : /api/battery_status, /api/flow_status (+ Fetch-Helfer)
  - ``automation.py``: Automation-State/Phasen-Helfer (von ``battery.py`` genutzt)
  - ``ha.py``        : /api/ha, /api/ha/* (Home-Assistant-Lesepfade)
  - ``wattpilot.py`` : /api/wattpilot/status, /api/wattpilot/history
  - ``failover.py``  : /api/failover_status, /api/backup_status
  - ``_shared.py``   : geteilte Read-Helfer (Wattpilot-DB-Summary)

Alle Endpunkte registrieren sich am gemeinsamen Blueprint ``bp``.
``bp`` wird zuerst definiert, danach werden die Submodule importiert, damit
deren ``@bp.route(...)``-Dekoratoren greifen (Standard-Flask-Muster).
"""
from flask import Blueprint

bp = Blueprint('system', __name__)

# Submodule importieren -> Routen registrieren sich am bp.
# Reihenfolge: reine Helfer-Module vor ihren Nutzern.
from routes.system import automation  # noqa: E402,F401
from routes.system import battery  # noqa: E402,F401
from routes.system import ha  # noqa: E402,F401
from routes.system import wattpilot  # noqa: E402,F401
from routes.system import failover  # noqa: E402,F401
from routes.system import info  # noqa: E402,F401

__all__ = ['bp']
