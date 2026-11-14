#!/usr/bin/env python3
"""recovery/offsite_data_reminder.py — Monatliche Off-site-Datensicherungs-Mahnung (Rolle R).

Erinnert monatlich per Mail daran, einen Datensnapshot auf ein externes Medium zu
kopieren und **raeumlich getrennt** (anderes Gebaeude auf dem Grundstueck) zu lagern,
um Totalverlust durch Brand/Raub zu ueberstehen. Nennt konkret, was zu sichern ist
und wo die juengsten Kopien liegen.

Rein informativ (schreibt nichts, steuert nichts). Neustart-fest: Exit immer 0.

Nutzung: recovery/offsite_data_reminder.py [--no-mail]
"""
from __future__ import annotations

import os
import sys
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pv_notify import host_label, send_mail  # noqa: E402


def main() -> int:
    host = host_label()
    body = "\n".join([
        f"PV-System — Off-site-Datensicherung faellig ({date.today().isoformat()})",
        f"Host: {host}",
        "",
        "Bitte einen Datensnapshot auf ein EXTERNES Medium kopieren und raeumlich",
        "getrennt (anderes Gebaeude auf dem Grundstueck) lagern — Schutz vor Brand/Raub.",
        "",
        "Zu sichern (juengste Kopien):",
        "  1. Longterm-GFS (monthly/yearly)   -> Pi4-Kueche: ~/pv-longterm-archive/",
        "  2. Aktuelle Produktions-DB         -> FB: backup/db/daily/ (neueste data_*.db.gz)",
        "  3. Permanente DBs (monitoring/analysis) -> FB: backup/tiered/",
        "  4. Recovery-Paket (Code+Doku)      -> recovery/export_usb.sh (Major-gekoppelt)",
        "",
        "Pruefung nach Wiederherstellung:",
        "  gunzip -k data_YYYY-MM.db.gz && sqlite3 data.db 'PRAGMA integrity_check;'",
        "",
        "Siehe doc/system/BACKUP_STRATEGY.md und doc/system/RECOVERY.md.",
    ])
    print(body)
    if "--no-mail" not in sys.argv[1:]:
        send_mail(f"[PV-Off-site] {host}: Monatliche Datensicherung extern lagern",
                  body, event="offsite_reminder")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Unerwarteter Fehler (defensiv geschluckt): {e}")
        sys.exit(0)
