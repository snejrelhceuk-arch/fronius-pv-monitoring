#!/usr/bin/env python3
"""
Skript zur Überprüfung der Rollenverteilung auf allen Pis.
Stellt sicher, dass die .role-Dateien korrekt konfiguriert sind.
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

def check_role(host, user, repo_path, expected_role):
    """Prüft die Rolle eines Hosts."""
    print(f"\nPrüfe Rolle auf {host}...")
    
    # Prüfe, ob das Repository existiert
    exists = run_ssh_command(host, user, f"test -d {repo_path} && echo 'exists' || echo 'not_exists'")
    if exists != "exists":
        print(f"Repository nicht gefunden auf {host}.")
        return False
    
    # Prüfe die Rolle des Hosts
    role = run_ssh_command(host, user, f"cd {repo_path} && cat .role")
    print(f"Host-Rolle: {role}")
    
    if role == expected_role:
        print(f"Rolle korrekt: {role}")
        return True
    else:
        print(f"Rolle falsch: Erwartet {expected_role}, gefunden {role}")
        return False

def main():
    # NOTE: Vor Verwendung IPs/Pfade/Rollen an lokale Infrastruktur anpassen
    repo_paths = {
        "192.0.2.204": ("admin", "/opt/pv-system", "primary"),    # Pi5-Primary
        "192.0.2.195": ("admin", "/opt/pv-system", "failover"),   # Pi5-FB
        "192.0.2.105": ("user", "/opt/pv-system", "kiosk"),       # Pi4-Küche
        "192.0.2.181": ("admin", "/opt/pv-system", "tech")        # Pi4-Tech
    }
    
    print("Prüfe Rollenverteilung auf allen Pis...")
    
    for host, (user, repo_path, expected_role) in repo_paths.items():
        check_role(host, user, repo_path, expected_role)
    
    print("\nPrüfung abgeschlossen.")

if __name__ == "__main__":
    main()