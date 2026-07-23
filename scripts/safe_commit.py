#!/usr/bin/env python3
"""
Skript zum sicheren Committen von Änderungen.
Stellt sicher, dass keine sensiblen Daten in den gestagten Dateien enthalten sind.
"""
import subprocess
import sys

def run_command(command):
    """Führt einen Befehl aus und gibt das Ergebnis zurück."""
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Fehler: {e.stderr}")
        return None

def check_sensitive_data():
    """Prüft, ob sensible Daten in den gestagten Dateien enthalten sind."""
    print("Prüfe auf sensible Daten...")
    
    # Prüfe die gestagten Änderungen
    diff = run_command(["git", "diff", "--cached"])
    if diff:
        sensitive_keywords = [
            "password",
            "secret",
            "token",
            "key",
            "192.168.2.",
            "admin@",
            "yourdomain.com"  # Beispiel-Domain
        ]
        
        for keyword in sensitive_keywords:
            if keyword.lower() in diff.lower():
                print(f"Sensible Daten gefunden: {keyword}")
                return False
    
    print("Keine sensiblen Daten gefunden.")
    return True

def safe_commit(message):
    """Führt einen sicheren Commit durch."""
    if not check_sensitive_data():
        print("Commit abgebrochen: Sensible Daten gefunden.")
        return False
    
    print("Führe Commit durch...")
    run_command(["git", "commit", "-m", message])
    print("Commit erfolgreich.")
    return True

def main():
    if len(sys.argv) < 2:
        print('Verwendung: python3 safe_commit.py "<Commit-Nachricht>"')
        sys.exit(1)
    
    message = sys.argv[1]
    safe_commit(message)

if __name__ == "__main__":
    main()