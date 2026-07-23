#!/usr/bin/env python3
"""
Skript zur Aktualisierung der Rollenverteilung auf allen Pis.
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

def set_role(host, user, repo_path, role):
    """Setzt die Rolle eines Hosts."""
    print(f"\nSetze Rolle auf {host} auf {role}...")
    
    # Prüfe, ob das Repository existiert
    exists = run_ssh_command(host, user, f"test -d {repo_path} && echo 'exists' || echo 'not_exists'")
    if exists != "exists":
        print(f"Repository nicht gefunden auf {host}.")
        return False
    
    # Setze die Rolle des Hosts
    run_ssh_command(host, user, f"cd {repo_path} && echo {role} > .role")
    
    # Prüfe die Rolle des Hosts
    current_role = run_ssh_command(host, user, f"cd {repo_path} && cat .role")
    print(f"Host-Rolle: {current_role}")
    
    return True

def main():
    # NOTE: Vor Verwendung IPs/Pfade/Rollen an lokale Infrastruktur anpassen
    repo_paths = {
        "192.0.2.204": ("admin", "/opt/pv-system", "primary"),    # Pi5-Primary
        "192.0.2.195": ("admin", "/opt/pv-system", "failover"),   # Pi5-FB
        "192.0.2.105": ("user", "/opt/pv-system", "kiosk"),       # Pi4-Küche
        "192.0.2.181": ("admin", "/opt/pv-system", "tech")        # Pi4-Tech
    }
    
    print("Setze Rollenverteilung auf allen Pis...")
    
    for host, (user, repo_path, role) in repo_paths.items():
        set_role(host, user, repo_path, role)
    
    print("\nRollenverteilung aktualisiert.")

if __name__ == "__main__":
    main()