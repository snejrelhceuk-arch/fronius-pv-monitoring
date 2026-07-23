#!/usr/bin/env python3
"""
Skript zur Synchronisation des pv-system auf allen Pis.
Stellt sicher, dass das Repository auf allen Hosts vorhanden ist und nur auf Primary entwickelt wird.
"""
import subprocess
import sys

def run_ssh_command(host, user, command):
    """Führt einen SSH-Befehl auf einem Remote-Host aus."""
    try:
        result = subprocess.run(
            ["ssh", f"{user}@{host}", command],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Fehler auf {host}: {e.stderr}")
        return None

def sync_repo(host, user, repo_path):
    """Synchronisiert das Repository auf einem Host."""
    print(f"\nSynchronisiere {host}...")
    
    # Prüfe, ob das Repository existiert
    exists = run_ssh_command(host, user, f"test -d {repo_path} && echo 'exists' || echo 'not_exists'")
    if exists != "exists":
        print(f"Repository nicht gefunden auf {host}. Klone Repository...")
        run_ssh_command(host, user, f"git clone git@github.com:snejrelhceuk-arch/fronius-pv-monitoring.git {repo_path}")
    else:
        # Pull die neuesten Änderungen
        print(f"Pull die neuesten Änderungen auf {host}...")
        run_ssh_command(host, user, f"cd {repo_path} && git pull")
    
    # Prüfe die Rolle des Hosts
    role = run_ssh_command(host, user, f"cd {repo_path} && cat .role")
    print(f"Host-Rolle: {role}")
    
    return True

def main():
    # NOTE: Vor Verwendung IPs/Pfade an lokale Infrastruktur anpassen
    # (siehe .infra.local.example für Mapping)
    repo_paths = {
        "192.0.2.204": ("admin", "/opt/pv-system"),  # Pi5-Primary
        "192.0.2.195": ("admin", "/opt/pv-system"),  # Pi5-FB
        "192.0.2.105": ("user", "/opt/pv-system"),   # Pi4-Küche
        "192.0.2.181": ("admin", "/opt/pv-system")   # Pi4-Tech
    }
    
    print("Synchronisiere pv-system auf allen Pis...")
    
    for host, (user, repo_path) in repo_paths.items():
        sync_repo(host, user, repo_path)
    
    print("\nSynchronisation abgeschlossen.")

if __name__ == "__main__":
    main()