#!/usr/bin/env python3
"""scripts/pv_post_reboot_check.py — Datenverlust-/Wiederanlauf-Prüfung nach Reboot.

Vergleicht Timestamps vor vs. nach dem Reboot und prüft alle kritischen Services
auf allen Hosts. Aufruf nach dem Wiederverbinden:
  .venv/bin/python scripts/pv_post_reboot_check.py
"""
from __future__ import annotations

import datetime
import os
import socket
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _ssh(host, cmd, timeout=15):
    rc, out = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                    host, cmd], timeout=timeout)
    return rc, out


def _load_infra():
    env_file = os.path.join(REPO_ROOT, ".infra.local")
    env = {}
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def check_primary():
    print("\n── Primary (lokal) ──────────────────────────────────")
    # Services
    services = ["pv-web", "pv-collector", "pv-automation", "pv-wattpilot",
                "pv-steuerbox"]
    for svc in services:
        rc, _ = _run(["systemctl", "is-active", svc + ".service"], timeout=5)
        status = "✓ aktiv" if rc == 0 else "✗ INAKTIV"
        print(f"  {svc:25s}: {status}")

    # reboot-required?
    rr = os.path.exists("/var/run/reboot-required")
    print(f"  reboot-required: {'JA (weitere Updates)' if rr else 'nein ✓'}")

    # Datenfrische
    try:
        import config
        db = config.DB_PATH
        if os.path.exists(db):
            c = sqlite3.connect(db, timeout=5)
            row = c.execute("SELECT MAX(ts), COUNT(*) FROM raw_data "
                            "WHERE ts > strftime('%s','now','-30 minutes')").fetchone()
            ts, cnt = row
            if ts:
                age = int(time.time()) - int(ts)
                print(f"  raw_data jüngster Eintrag: {datetime.datetime.fromtimestamp(ts).strftime('%F %T')} "
                      f"(Alter {age}s), letzte 30 min: {cnt} Rows")
                if age > 90:
                    print(f"  ✗ raw_data-Lücke: Collector schreibt seit {age}s nicht!")
                else:
                    print(f"  ✓ Collector schreibt")
            else:
                print("  ✗ raw_data: keine Einträge in letzten 30 min")
            c.close()
    except Exception as e:  # noqa: BLE001
        print(f"  DB-Check: {e}")

    # tmpfs-DB
    tmpfs = "/dev/shm/fronius_data.db"
    if os.path.exists(tmpfs):
        sz = os.path.getsize(tmpfs)
        print(f"  tmpfs-DB: {sz // 1024 // 1024} MB ✓")
    else:
        print("  ✗ tmpfs-DB fehlt — Collector schreibt noch nicht auf RAM")

    # failed units
    rc, out = _run(["systemctl", "--failed", "--no-legend", "--plain"], timeout=5)
    pv_failed = [l for l in out.splitlines() if "pv-" in l]
    if pv_failed:
        print(f"  ✗ failed pv-Units: {', '.join(pv_failed)}")
    else:
        print("  ✓ keine failed pv-Units")


def check_remote(label, host, services_check):
    print(f"\n── {label} ({host}) ─────────────────────────────")
    rc, _ = _ssh(host, "echo ok", timeout=8)
    if rc != 0:
        print(f"  ✗ NICHT ERREICHBAR via SSH")
        return
    # Services
    for svc in services_check:
        rc2, out2 = _ssh(host, f"systemctl is-active {svc}", timeout=10)
        status = "✓ aktiv" if rc2 == 0 else f"✗ {out2.strip() or 'inaktiv'}"
        print(f"  {svc:35s}: {status}")
    # reboot-required
    rc3, rr = _ssh(host, "[ -f /var/run/reboot-required ] && echo JA || echo nein", timeout=8)
    print(f"  reboot-required: {rr}")
    # failed
    rc4, failed = _ssh(host, "systemctl --failed --no-legend --plain 2>/dev/null | grep 'pv-' | head -5", timeout=8)
    if failed.strip():
        print(f"  ✗ failed pv-Units: {failed.strip()}")
    else:
        print("  ✓ keine failed pv-Units")


def check_fb_mirror(fb_host):
    print(f"\n── FB Mirror (Failover-Bereitschaft) ─────────────")
    rc, out = _ssh(fb_host,
        "[ -f /dev/shm/fronius_data.db ] && "
        "echo \"vorhanden $(( ($(date +%s) - $(stat -c %Y /dev/shm/fronius_data.db)) / 60 )) min alt\" "
        "|| echo FEHLT", timeout=10)
    if "FEHLT" in out:
        print(f"  ✗ tmpfs-Mirror FEHLT — Failover nicht übernahmebereit!")
    else:
        print(f"  tmpfs-Mirror: {out} ✓")


def main():
    print("=" * 60)
    print(f"  PV Post-Reboot-Check — {datetime.datetime.now().strftime('%F %T')}")
    print(f"  Host: {socket.gethostname()}")
    print("=" * 60)

    env = _load_infra()
    fb = env.get("PV_FAILOVER_HOST") or \
         f"{env.get('PV_FAILOVER_USER','admin')}@{env.get('PV_FAILOVER_IP','')}"
    tech = f"{env.get('PV_TECH_USER','admin')}@{env.get('PV_TECH_IP','')}"
    kueche = env.get("PV_KUECHE_HOST") or \
             f"{env.get('PV_KUECHE_USER','jk')}@{env.get('PV_KUECHE_IP','')}"

    check_primary()
    check_remote("Tech", tech, [
        "pv-nq-poller.service", "pv-nq-energy.service", "pv-wp-bridge.service"])
    check_remote("Küche", kueche, [
        "pv-failover-init.service", "pv-backup-2d.timer",
        "pv-failover-health.timer"])
    check_remote("FB", fb, [
        "pv-web.service", "pv-ticker.service",
        "pv-mirror-sync.timer", "pv-failover-init.service"])
    check_fb_mirror(fb)

    print("\n" + "=" * 60)
    print("Prüfung abgeschlossen. Fehlende Services mit:")
    print("  sudo systemctl start <unit>")
    print("Datenverlust-Details: letzte raw_data-Timestamps in DB prüfen.")
    print("=" * 60)


if __name__ == "__main__":
    main()
