#!/usr/bin/env python3
"""scripts/pv_auto_update_guard.py — Bewachter Auto-Update-Ausloeser.

Laeuft taeglich als systemd-Timer (``pv-auto-update.timer``) und setzt die
gewuenschte Logik um:

  1. Stehen Paket-Updates an und ist noch keine Warnung aktiv -> **Warn-Mail**
     ("Auto-Update in 72 h, sofern keine Aktivitaet") und Zustand "armed".
  2. Danach wird gewartet, bis der Nutzer **72 h inaktiv** war. Als Aktivitaet
     gilt ein **neuer git-Commit auf Primary HEAD** (Entwicklung = Aktivitaet).
     Jeder Commit nach der Warnung schiebt den Ausloeser um 72 h nach hinten.
  3. Nach 72 h Inaktivitaet laeuft ``pv_update_all_hosts.sh`` (apt full-upgrade
     auf allen erreichbaren Pis) und es geht eine **Erfolgs-Mail** raus.
  4. Verschwinden die Updates vorher (Nutzer hat manuell aktualisiert), wird die
     Warnung sauber zurueckgesetzt.

Neustart-fest & selbstpruefend: Der Zustand liegt in ``.state/auto_update_state.json``.
Fehlt/korrupt -> Neu-Initialisierung. Jeder Fehler -> Exit 0 (Timer nie "failed").

Flags:
  --status      nur aktuellen Zustand ausgeben, nichts tun
  --dry-run     Entscheidungen zeigen, aber kein Upgrade/keine Mail
  --force-run   72 h-Gate ueberspringen und sofort rollout (Ops/Test)
  --reset       Zustand auf "idle" zuruecksetzen
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pv_notify import host_label, send_mail  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

STATE_DIR = os.path.join(REPO_ROOT, ".state")
STATE_FILE = os.path.join(STATE_DIR, "auto_update_state.json")
ROLLOUT = os.path.join(REPO_ROOT, "scripts", "pv_update_all_hosts.sh")
INACTIVITY_SECONDS = 72 * 3600

_DEFAULT_STATE = {
    "phase": "idle",          # idle | armed
    "warn_epoch": 0,
    "warn_head": "",
    "last_update_epoch": 0,
    "last_update_result": "",
}


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 1, f"<exec-fehler: {e}>"


def _git_head() -> str:
    rc, out = _run(["git", "-c", f"safe.directory={REPO_ROOT}",
                    "rev-parse", "HEAD"], timeout=30)
    return out.strip() if rc == 0 else ""


def _last_commit_epoch() -> int:
    rc, out = _run(["git", "-c", f"safe.directory={REPO_ROOT}",
                    "log", "-1", "--format=%ct"], timeout=30)
    try:
        return int(out.strip()) if rc == 0 else 0
    except ValueError:
        return 0


def _pending_apt() -> list[str]:
    rc, out = _run(["apt-get", "-s", "dist-upgrade"], timeout=180)
    pkgs = []
    for line in out.splitlines():
        if line.startswith("Inst "):
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(parts[1])
    return sorted(set(pkgs))


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("kein dict")
        merged = dict(_DEFAULT_STATE)
        merged.update({k: data[k] for k in _DEFAULT_STATE if k in data})
        if merged["phase"] not in ("idle", "armed"):
            merged["phase"] = "idle"
        return merged
    except FileNotFoundError:
        return dict(_DEFAULT_STATE)
    except Exception:
        # Korrupt -> selbstheilen
        return dict(_DEFAULT_STATE)


def _save_state(state: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: Zustand nicht speicherbar: {e}")


def _fmt(epoch: int) -> str:
    return datetime.fromtimestamp(epoch).strftime("%F %T") if epoch else "-"


def _do_rollout() -> tuple[bool, str]:
    rc, out = _run(["bash", ROLLOUT], timeout=3 * 3600)
    results = [l for l in out.splitlines() if l.startswith("RESULT ")]
    ok = rc == 0 and not any("FEHLER" in l for l in results)
    return ok, out


def main() -> int:
    args = sys.argv[1:]
    state = _load_state()
    head = _git_head()
    last_commit = _last_commit_epoch()
    now = int(time.time())
    host = host_label()

    if "--reset" in args:
        _save_state(dict(_DEFAULT_STATE))
        print("Zustand auf idle zurueckgesetzt.")
        return 0

    if "--status" in args:
        print(f"Host: {host}")
        print(json.dumps(state, indent=2))
        print(f"HEAD: {head[:12]}  letzter Commit: {_fmt(last_commit)}")
        print(f"anstehende apt-Updates: {len(_pending_apt())}")
        return 0

    dry = "--dry-run" in args
    force = "--force-run" in args
    pending = _pending_apt()

    # --- armed: warten bzw. ausloesen ---------------------------------
    if state["phase"] == "armed" and not force:
        if not pending:
            print("Updates verschwunden (manuell aktualisiert?) -> Warnung zurueckgesetzt.")
            state.update(phase="idle", warn_epoch=0, warn_head="")
            _save_state(state)
            return 0
        trigger_base = max(int(state.get("warn_epoch", 0)), last_commit)
        wait_left = INACTIVITY_SECONDS - (now - trigger_base)
        if wait_left > 0:
            print(f"Armed seit {_fmt(state['warn_epoch'])}; letzter Commit {_fmt(last_commit)}; "
                  f"Auto-Update in ~{wait_left // 3600} h (Aktivitaet verschiebt).")
            return 0
        print("72 h Inaktivitaet erreicht -> Rollout.")

    if state["phase"] == "idle" and not force:
        if pending:
            msg = (
                f"PV-System Auto-Update — Warnung\nHost: {host}\n"
                f"Zeit: {_fmt(now)}\n\n"
                f"{len(pending)} Paket-Update(s) stehen an. Sofern in den naechsten "
                f"72 Stunden KEIN neuer git-Commit auf Primary erfolgt (= Inaktivitaet), "
                f"wird automatisch `scripts/pv_update_all_hosts.sh` ausgefuehrt "
                f"(apt full-upgrade auf allen erreichbaren Pis). Jeder Commit verschiebt "
                f"den Lauf um weitere 72 h.\n\n"
                f"Jetzt selbst upgraden:\n  cd {REPO_ROOT}\n"
                f"  sudo bash scripts/pv_update_all_hosts.sh\n\n"
                "Betroffene Pakete (max. 40):\n  " + "\n  ".join(pending[:40])
            )
            print(msg)
            if dry:
                print("[dry-run] keine Warn-Mail, kein Zustandswechsel.")
                return 0
            send_mail(f"[PV-Auto-Update] {host}: {len(pending)} Updates — Rollout in 72 h",
                      msg, event="auto_update_warning")
            state.update(phase="armed", warn_epoch=now, warn_head=head)
            _save_state(state)
            return 0
        print("Keine anstehenden Updates — nichts zu tun.")
        return 0

    # --- Rollout (armed+gate erreicht ODER --force-run) ---------------
    if dry:
        print("[dry-run] wuerde jetzt pv_update_all_hosts.sh ausfuehren.")
        return 0
    ok, out = _do_rollout()
    results = "\n".join(l for l in out.splitlines() if l.startswith("RESULT "))
    status = "ERFOLG" if ok else "MIT FEHLERN"
    body = (
        f"PV-System Auto-Update — {status}\nHost: {host}\nZeit: {_fmt(int(time.time()))}\n\n"
        f"Ergebnis je Host:\n{results or '(keine RESULT-Zeilen)'}\n\n"
        f"--- Rollout-Ausgabe (gekuerzt) ---\n" + "\n".join(out.splitlines()[-40:])
    )
    print(body)
    send_mail(f"[PV-Auto-Update] {host}: Rollout {status}", body,
              event="auto_update_done")
    state.update(phase="idle", warn_epoch=0, warn_head="",
                 last_update_epoch=int(time.time()),
                 last_update_result=status)
    _save_state(state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — Timer darf nie "failed" melden
        print(f"Unerwarteter Fehler (defensiv geschluckt): {e}")
        sys.exit(0)
