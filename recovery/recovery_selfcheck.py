#!/usr/bin/env python3
"""recovery/recovery_selfcheck.py — Aktualitaets-/Integritaets-Selbstcheck (Rolle R).

Prueft, ob das lokale Recovery-Paket und der zuletzt bespielte USB-Stick noch zur
aktuellen **Major-Version** (Ganzzahl aus git-Tag vN) passen, und mahnt per Mail,
wenn ein Major-Sprung die Neu-Erstellung/Neu-Uebertragung verlangt. Zusaetzlich:
Host-Manifeste parsebar? Recovery-Paket vorhanden?

Koppelt an die MAJOR-Version (Betreiber-Vorgabe: ganzzahlige Versionswechsel sind
Ausloeser). Neustart-fest/defensiv: Exit immer 0 (Oneshot-Timer).

Nutzung: recovery/recovery_selfcheck.py [--no-mail] [--build] [--status]
  --build   fehlendes/veraltetes Paket gleich neu bauen (build_recovery_bundle.sh)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
RECOVERY_DIR = os.path.join(REPO_ROOT, "recovery")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pv_notify import host_label, send_mail  # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, "backup", "recovery")
HOSTS_DIR = os.path.join(RECOVERY_DIR, "hosts")


def _current_major() -> int:
    try:
        out = subprocess.run(["git", "-C", REPO_ROOT, "tag"], capture_output=True,
                             text=True, timeout=30).stdout
        tags = [t for t in out.split() if re.match(r"^v\d+\.", t)]
        tags.sort(key=lambda t: [int(x) for x in t[1:].split(".")])
        return int(tags[-1][1:].split(".")[0]) if tags else 0
    except Exception:
        return 0


def _marker_major(path: str) -> int | None:
    try:
        with open(path) as f:
            first = f.read().split()[0]  # "vN" or "N"
        return int(first.lstrip("v"))
    except Exception:
        return None


def _manifests_ok() -> tuple[int, list[str]]:
    import yaml
    ok, bad = 0, []
    for fn in sorted(os.listdir(HOSTS_DIR)):
        if not fn.endswith(".yaml"):
            continue
        try:
            yaml.safe_load(open(os.path.join(HOSTS_DIR, fn)))
            ok += 1
        except Exception as e:  # noqa: BLE001
            bad.append(f"{fn}: {e}")
    return ok, bad


def main() -> int:
    args = sys.argv[1:]
    major = _current_major()
    pkg_major = _marker_major(os.path.join(OUT_DIR, "LATEST_RECOVERY"))
    usb_major = _marker_major(os.path.join(OUT_DIR, "USB_LAST_EXPORT"))
    n_ok, bad = _manifests_ok()

    issues = []
    if pkg_major is None:
        issues.append("Kein lokales Recovery-Paket (recovery/build_recovery_bundle.sh ausfuehren).")
    elif pkg_major < major:
        issues.append(f"Recovery-Paket veraltet: Paket v{pkg_major} < aktuell v{major} — neu bauen.")
    if usb_major is None:
        issues.append("Kein USB-Export vermerkt (recovery/export_usb.sh) — USB-Stick bespielen.")
    elif usb_major < major:
        issues.append(f"USB veraltet: USB v{usb_major} < aktuell v{major} — Stick NEU uebertragen "
                      "und raeumlich getrennt lagern.")
    if bad:
        issues.append("Manifest-Parsefehler: " + "; ".join(bad))

    if "--build" in args and (pkg_major is None or (pkg_major < major)):
        subprocess.run(["bash", os.path.join(RECOVERY_DIR, "build_recovery_bundle.sh")],
                      cwd=REPO_ROOT, timeout=600)
        pkg_major = _marker_major(os.path.join(OUT_DIR, "LATEST_RECOVERY"))

    host = host_label()
    lines = [
        f"PV-System Recovery-Selfcheck — {host}",
        f"Datum: {date.today().isoformat()}",
        f"Aktuelle Major-Version: v{major}",
        f"Recovery-Paket: v{pkg_major if pkg_major is not None else '-'}",
        f"USB-Export:     v{usb_major if usb_major is not None else '-'}",
        f"Host-Manifeste OK: {n_ok}",
        "",
    ]
    lines += (["HANDLUNGSBEDARF:"] + [f"  - {x}" for x in issues]) if issues else ["Alles aktuell — kein Handlungsbedarf."]
    body = "\n".join(lines)
    if "--status" in args:
        print(body)
        return 0
    print(body)

    if issues and "--no-mail" not in args:
        send_mail(f"[PV-Recovery] {host}: {len(issues)} Punkt(e) — Paket/USB pruefen",
                  body, event="recovery_selfcheck")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Unerwarteter Fehler (defensiv geschluckt): {e}")
        sys.exit(0)
