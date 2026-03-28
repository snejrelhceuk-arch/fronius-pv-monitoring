#!/usr/bin/env python3
"""
fronius_api.py — Fronius Gen24 Internal API Client
===================================================
Steuert Batterie-Parameter (SOCmin, SOCmax, SOCmode, etc.)
über die interne HTTP-API des Fronius Gen24 Wechselrichters.

Authentifizierung:
  Fronius Gen24 verwendet eine NICHT-STANDARD Digest-Authentifizierung:
  - Challenge kommt über den Header "X-WWW-Authenticate" (nicht "WWW-Authenticate")
  - HA1 = MD5(username:realm:password)  — wenn technicianHashingVersion=1
  - HA2 = SHA256(METHOD:URI)
  - response = SHA256(HA1:nonce:nc:cnonce:qop:HA2)
  
  Das ist ein Hybrid-Schema: HA1 mit MD5, Rest mit SHA256.
  Standard-HTTP-Clients (curl --digest, requests HTTPDigestAuth) scheitern daran.

Nutzung:
  # Lesen
  python3 fronius_api.py --read
  
  # SOC-Limits setzen
  python3 fronius_api.py --set-soc-min 5 --confirm
  python3 fronius_api.py --set-soc-max 80 --confirm
  
  # SOC-Modus
  python3 fronius_api.py --set-soc-mode manual --confirm
  python3 fronius_api.py --set-soc-mode auto --confirm

Autor: PV-Anlage Batterie-Management
Datum: 2026-02-09
"""

import sys
import os
import hashlib
import json
import re
import argparse
import time

# Encoding fix für RPi5 mit latin-1 locale
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import requests
except ImportError:
    print("FEHLER: 'requests' nicht installiert. pip3 install requests")
    sys.exit(1)


# ─── Konfiguration ─────────────────────────────────────────────
try:
    import config as _cfg
    _DEFAULT_HOST = _cfg.INVERTER_IP
except ImportError:
    _DEFAULT_HOST = "192.0.2.122"

INVERTER_HOST = os.environ.get("FRONIUS_HOST", _DEFAULT_HOST)
INVERTER_URL  = f"http://{INVERTER_HOST}"
USERNAME      = os.environ.get("FRONIUS_USER", "technician")
REALM         = "Webinterface area"

# Passwort aus zentraler Secrets-Verwaltung laden
def _load_fronius_password():
    """Passwort aus Umgebungsvariable oder .secrets-Datei laden."""
    try:
        from config import load_secret
        pw = load_secret('FRONIUS_PASS')
    except ImportError:
        pw = os.environ.get('FRONIUS_PASS')
    if pw:
        return pw
    raise RuntimeError(
        "Kein Fronius-Passwort gefunden! "
        "Setze FRONIUS_PASS als Umgebungsvariable oder in .secrets"
    )

PASSWORD = _load_fronius_password()

# API Endpoints (reverse-engineered aus Angular SPA)
API_BATTERIES = "/api/config/batteries"
API_COMMON    = "/api/config/common"
API_STATUS    = "/status/common"


# ─── Fronius Hybrid Digest Auth ────────────────────────────────

class FroniusAuth:
    """
    Fronius Gen24 Hybrid Digest Authentication.
    
    Besonderheiten:
    - Server sendet Challenge über "X-WWW-Authenticate" Header
    - HA1 = MD5(user:realm:pass) wenn HashingVersion=1
    - HA2 = SHA256(METHOD:URI)
    - Response = SHA256(HA1:nonce:nc:cnonce:qop:HA2)
    """
    
    def __init__(self, host=INVERTER_URL, username=USERNAME, password=PASSWORD,
                 realm=REALM, ha1_algo="md5"):
        self.host = host
        self.username = username
        self.password = password
        self.realm = realm
        self.ha1_algo = ha1_algo
        self._nonce = None
        self._nc = 0
        
        # Vorberechne HA1 (bleibt konstant während der Lebensdauer)
        ha1_input = f"{username}:{realm}:{password}"
        if ha1_algo == "md5":
            self._ha1 = hashlib.md5(ha1_input.encode()).hexdigest()
        else:
            self._ha1 = hashlib.sha256(ha1_input.encode()).hexdigest()
    
    def _get_nonce(self, uri):
        """Hole frische Nonce vom Server via 401 Challenge."""
        r = requests.get(f"{self.host}{uri}", timeout=5)
        auth_header = r.headers.get("X-WWW-Authenticate", "")
        match = re.search(r'nonce="([^"]+)"', auth_header)
        if not match:
            raise ConnectionError(
                f"Keine Nonce erhalten. Status={r.status_code}, "
                f"Header: {auth_header}"
            )
        self._nonce = match.group(1)
        self._nc = 0
        return self._nonce
    
    def _build_auth_header(self, method, uri):
        """Erstelle Authorization Header mit Fronius Hybrid Digest."""
        if not self._nonce:
            self._get_nonce(uri)
        
        self._nc += 1
        nc = f"{self._nc:08x}"
        cnonce = hashlib.md5(f"{time.time()}:{os.getpid()}".encode()).hexdigest()[:16]
        qop = "auth"
        
        # HA2 = SHA256(METHOD:URI) — immer SHA256
        ha2 = hashlib.sha256(f"{method.upper()}:{uri}".encode()).hexdigest()
        
        # Response = SHA256(HA1:nonce:nc:cnonce:qop:HA2)
        response_data = f"{self._ha1}:{self._nonce}:{nc}:{cnonce}:{qop}:{ha2}"
        response = hashlib.sha256(response_data.encode()).hexdigest()
        
        return (
            f'Digest username="{self.username}", realm="{self.realm}", '
            f'nonce="{self._nonce}", uri="{uri}", response="{response}", '
            f'qop={qop}, nc={nc}, cnonce="{cnonce}"'
        )
    
    def get(self, uri, retry=True):
        """Authentifizierter GET Request."""
        auth = self._build_auth_header("GET", uri)
        r = requests.get(
            f"{self.host}{uri}",
            headers={"Authorization": auth},
            timeout=5
        )
        
        # Bei 401 neue Nonce holen und nochmal versuchen
        if r.status_code == 401 and retry:
            self._nonce = None
            return self.get(uri, retry=False)
        
        return r
    
    def put(self, uri, data, retry=True):
        """Authentifizierter PUT Request."""
        auth = self._build_auth_header("PUT", uri)
        r = requests.put(
            f"{self.host}{uri}",
            json=data,
            headers={"Authorization": auth},
            timeout=10
        )
        
        if r.status_code == 401 and retry:
            self._nonce = None
            return self.put(uri, data, retry=False)
        
        return r
    
    def post(self, uri, data, retry=True):
        """Authentifizierter POST Request."""
        auth = self._build_auth_header("POST", uri)
        r = requests.post(
            f"{self.host}{uri}",
            json=data,
            headers={"Authorization": auth},
            timeout=10
        )
        
        if r.status_code == 401 and retry:
            self._nonce = None
            return self.post(uri, data, retry=False)
        
        return r


# ─── Battery Config API ────────────────────────────────────────

class BatteryConfig:
    """Lese und schreibe Batterie-Konfiguration über Fronius API."""
    
    # Parameter-Referenz (aus /api/config/batteries Response)
    PARAMS = {
        # SOC-Steuerung
        'BAT_M0_SOC_MIN':    {'type': 'int',    'unit': '%',  'desc': 'Minimaler Ladezustand'},
        'BAT_M0_SOC_MAX':    {'type': 'int',    'unit': '%',  'desc': 'Maximaler Ladezustand'},
        'BAT_M0_SOC_MODE':   {'type': 'string', 'unit': '',   'desc': 'SOC-Modus (auto/manual)'},
        
        # Lade-Steuerung
        'HYB_EVU_CHARGEFROMGRID': {'type': 'bool', 'unit': '', 'desc': 'Netzladung erlaubt'},
        'HYB_BM_CHARGEFROMAC':    {'type': 'bool', 'unit': '', 'desc': 'AC-Ladung (Generator)'},
        'HYB_BM_PACMIN':          {'type': 'int',  'unit': 'W','desc': 'Min. Ladeleistung (negativ=Laden)'},
        
        # Backup / Notstrom
        'HYB_BACKUP_CRITICALSOC': {'type': 'int',  'unit': '%', 'desc': 'Kritischer SOC für Backup'},
        'HYB_BACKUP_RESERVED':    {'type': 'int',  'unit': '%', 'desc': 'Reservierter SOC für Backup'},
        
        # Energiemanagement
        'HYB_EM_MODE':   {'type': 'int',  'unit': '', 'desc': 'Energiemanagement Modus (0=auto,1=manual)'},
        'HYB_EM_POWER':  {'type': 'int',  'unit': 'W','desc': 'Energiemanagement Leistung'},
        
        # Support SOC (Grid-Ladung um SOC zu halten)
        'supportSoc':              {'type': 'int',  'unit': '%', 'desc': 'Support-SOC Sollwert'},
        'supportSocActive':        {'type': 'bool', 'unit': '',  'desc': 'Support-SOC aktiv'},
        'supportSocMode':          {'type': 'string','unit': '',  'desc': 'Support-SOC Modus'},
        'supportSocHysteresisMin': {'type': 'int',  'unit': '%', 'desc': 'Support-SOC Hysterese'},
    }
    
    def __init__(self, auth=None):
        self.auth = auth or FroniusAuth()
        self._cache = None
        self._cache_time = 0
    
    def read(self, force=False):
        """Lese aktuelle Batterie-Konfiguration."""
        if not force and self._cache and (time.time() - self._cache_time < 5):
            return self._cache
        
        r = self.auth.get(API_BATTERIES)
        if r.status_code != 200:
            raise ConnectionError(
                f"Batterie-Konfiguration nicht lesbar: HTTP {r.status_code}\n"
                f"{r.text[:500]}"
            )
        
        self._cache = r.json()
        self._cache_time = time.time()
        return self._cache
    
    def get_values(self):
        """Nur die Parameter-Werte (ohne _meta)."""
        data = self.read()
        return {k: v for k, v in data.items() if not k.startswith('_')}
    
    def write(self, params: dict, dry_run=False):
        """
        Schreibe Parameter zur Batterie-Konfiguration.
        
        Args:
            params: Dict mit Parameter-Name → Wert
            dry_run: Wenn True, nur anzeigen was geschrieben würde
        
        Returns:
            Response-Objekt oder None bei dry_run
        """
        # Validierung
        current = self.get_values()
        changes = {}
        
        for key, value in params.items():
            if key not in current:
                raise ValueError(f"Unbekannter Parameter: {key}")
            if current[key] == value:
                print(f"  {key}: bereits {value} — übersprungen")
                continue
            changes[key] = value
        
        if not changes:
            print("Keine Änderungen nötig.")
            return None
        
        # Anzeigen
        print("Geplante Änderungen:")
        for key, new_val in changes.items():
            old_val = current.get(key)
            info = self.PARAMS.get(key, {})
            unit = info.get('unit', '')
            desc = info.get('desc', key)
            print(f"  {desc}:")
            print(f"    {key}: {old_val} → {new_val} {unit}")
        
        if dry_run:
            print("\n[DRY RUN] Keine Änderungen durchgeführt.")
            return None
        
        # Schreiben (POST, nicht PUT — Fronius akzeptiert nur POST)
        r = self.auth.post(API_BATTERIES, changes)
        
        if r.status_code in (200, 204):
            body = r.json() if r.text else {}
            successes = body.get('writeSuccess', [])
            failures = body.get('writeFailure', [])
            errors = body.get('validationErrors', [])
            
            if failures or errors:
                print("\nTEILWEISE FEHLGESCHLAGEN:")
                if successes:
                    print(f"  Erfolgreich: {', '.join(successes)}")
                if failures:
                    print(f"  Fehlgeschlagen: {', '.join(failures)}")
                if errors:
                    print(f"  Validierungsfehler: {errors}")
            else:
                print(f"\nErfolgreich geschrieben: {', '.join(successes)}")
            
            # Cache invalidieren
            self._cache = None
        else:
            print(f"\nFEHLER beim Schreiben: HTTP {r.status_code}")
            print(f"Response: {r.text[:500]}")
        
        return r
    
    def set_soc_min(self, value: int, dry_run=False):
        """Setze minimalen Ladezustand (0-100%)."""
        if not 0 <= value <= 100:
            raise ValueError(f"SOC_MIN muss 0-100% sein, nicht {value}")
        return self.write({'BAT_M0_SOC_MIN': value}, dry_run=dry_run)
    
    def set_soc_max(self, value: int, dry_run=False):
        """Setze maximalen Ladezustand (0-100%)."""
        if not 0 <= value <= 100:
            raise ValueError(f"SOC_MAX muss 0-100% sein, nicht {value}")
        return self.write({'BAT_M0_SOC_MAX': value}, dry_run=dry_run)
    
    def set_soc_mode(self, mode: str, dry_run=False):
        """Setze SOC-Modus ('auto' oder 'manual')."""
        mode = mode.lower()
        if mode not in ('auto', 'manual'):
            raise ValueError(f"SOC_MODE muss 'auto' oder 'manual' sein, nicht '{mode}'")
        return self.write({'BAT_M0_SOC_MODE': mode}, dry_run=dry_run)
    
    def set_grid_charge(self, enabled: bool, dry_run=False):
        """Netzladung erlauben/verbieten."""
        return self.write({'HYB_EVU_CHARGEFROMGRID': enabled}, dry_run=dry_run)
    
    def print_status(self):
        """Zeige aktuelle Batterie-Konfiguration formatiert an."""
        values = self.get_values()
        
        print("=" * 60)
        print("  FRONIUS GEN24 — Batterie-Konfiguration")
        print("=" * 60)
        
        # SOC-Einstellungen
        print("\n  SOC-Steuerung:")
        mode = values.get('BAT_M0_SOC_MODE', '?')
        soc_min = values.get('BAT_M0_SOC_MIN', '?')
        soc_max = values.get('BAT_M0_SOC_MAX', '?')
        print(f"    Modus:          {mode.upper()}")
        print(f"    SOC Min:        {soc_min}%")
        print(f"    SOC Max:        {soc_max}%")
        
        # Lade-Einstellungen
        print("\n  Lade-Steuerung:")
        grid = values.get('HYB_EVU_CHARGEFROMGRID', '?')
        ac = values.get('HYB_BM_CHARGEFROMAC', '?')
        pacmin = values.get('HYB_BM_PACMIN', '?')
        print(f"    Netzladung:     {'EIN' if grid else 'AUS'}")
        print(f"    AC-Ladung:      {'EIN' if ac else 'AUS'}")
        print(f"    Min. Leistung:  {pacmin} W")
        
        # Backup
        print("\n  Notstrom-Reserve:")
        critical = values.get('HYB_BACKUP_CRITICALSOC', '?')
        reserved = values.get('HYB_BACKUP_RESERVED', '?')
        print(f"    Kritischer SOC: {critical}%")
        print(f"    Reserviert:     {reserved}%")
        
        # Energiemanagement
        print("\n  Energiemanagement:")
        em_mode = values.get('HYB_EM_MODE', '?')
        em_power = values.get('HYB_EM_POWER', '?')
        em_modes = {0: 'AUTOMATIK', 1: 'MANUELL'}
        print(f"    Modus:          {em_modes.get(em_mode, em_mode)}")
        print(f"    Leistung:       {em_power} W")
        
        # Support SOC
        print("\n  Support-SOC (Grid-Ladung):")
        ssoc = values.get('supportSoc', '?')
        sactive = values.get('supportSocActive', '?')
        smode = values.get('supportSocMode', '?')
        shyst = values.get('supportSocHysteresisMin', '?')
        print(f"    Aktiv:          {'JA' if sactive else 'NEIN'}")
        print(f"    Sollwert:       {ssoc}%")
        print(f"    Modus:          {smode}")
        print(f"    Hysterese:      {shyst}%")
        
        # Batterie-Info
        print("\n  Batterie-Hardware:")
        print(f"    Typ:            {values.get('BAT_TYPE', '?')}")
        print(f"    Modell:         {values.get('BAT_MODEL', '?')}")
        print(f"    Aktiviert:      {'JA' if values.get('BAT_ENABLED') else 'NEIN'}")
        print(f"    Kalibrierung:   {'LÄUFT' if values.get('BAT_CALIBRATION') else 'Nein'}")
        print(f"    Service-Modus:  {'EIN' if values.get('BAT_SERVICE_ON') else 'AUS'}")
        
        print("=" * 60)


# ─── CLI Interface ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Fronius Gen24 Batterie-Konfiguration via interner API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s --read                      Aktuelle Konfiguration anzeigen
  %(prog)s --json                      Konfiguration als JSON ausgeben
  %(prog)s --set-soc-min 5 --confirm   SOC-Minimum auf 5%% setzen
  %(prog)s --set-soc-max 80 --confirm  SOC-Maximum auf 80%% setzen
  %(prog)s --set-soc-mode auto --confirm   Auto-Modus aktivieren
  %(prog)s --set-param BAT_M0_SOC_MIN=10 HYB_EM_MODE=1 --confirm
        """
    )
    
    # Lese-Operationen
    parser.add_argument('--read', '-r', action='store_true',
                       help='Aktuelle Batterie-Konfiguration anzeigen')
    parser.add_argument('--json', '-j', action='store_true',
                       help='Konfiguration als JSON ausgeben')
    
    # Schreib-Operationen
    parser.add_argument('--set-soc-min', type=int, metavar='PERCENT',
                       help='Minimalen SOC setzen (0-100)')
    parser.add_argument('--set-soc-max', type=int, metavar='PERCENT',
                       help='Maximalen SOC setzen (0-100)')
    parser.add_argument('--set-soc-mode', choices=['auto', 'manual'],
                       help='SOC-Modus setzen')
    parser.add_argument('--set-grid-charge', choices=['on', 'off'],
                       help='Netzladung ein/ausschalten')
    parser.add_argument('--set-param', nargs='+', metavar='KEY=VALUE',
                       help='Beliebige Parameter setzen (KEY=VALUE)')
    
    # Sicherheit
    parser.add_argument('--confirm', action='store_true',
                       help='Änderungen tatsächlich durchführen (sonst Dry-Run)')
    
    # Verbindung
    parser.add_argument('--host', default=INVERTER_HOST,
                       help=f'Inverter IP (default: {INVERTER_HOST})')
    
    args = parser.parse_args()
    
    # Keine Argumente → --read
    if not any([args.read, args.json, args.set_soc_min is not None,
                args.set_soc_max is not None, args.set_soc_mode,
                args.set_grid_charge, args.set_param]):
        args.read = True
    
    # Auth und Config initialisieren
    auth = FroniusAuth(host=f"http://{args.host}")
    bat = BatteryConfig(auth)
    
    # Lese-Operationen
    if args.json:
        data = bat.get_values()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    
    if args.read:
        bat.print_status()
    
    # Schreib-Operationen sammeln
    changes = {}
    
    if args.set_soc_min is not None:
        if not 0 <= args.set_soc_min <= 100:
            print("FEHLER: SOC_MIN muss 0-100% sein")
            sys.exit(1)
        changes['BAT_M0_SOC_MIN'] = args.set_soc_min
    
    if args.set_soc_max is not None:
        if not 0 <= args.set_soc_max <= 100:
            print("FEHLER: SOC_MAX muss 0-100% sein")
            sys.exit(1)
        changes['BAT_M0_SOC_MAX'] = args.set_soc_max
    
    if args.set_soc_mode:
        changes['BAT_M0_SOC_MODE'] = args.set_soc_mode
    
    if args.set_grid_charge:
        changes['HYB_EVU_CHARGEFROMGRID'] = (args.set_grid_charge == 'on')
    
    if args.set_param:
        for param in args.set_param:
            if '=' not in param:
                print(f"FEHLER: Parameter muss KEY=VALUE sein, nicht '{param}'")
                sys.exit(1)
            key, value = param.split('=', 1)
            # Auto-Typ-Konvertierung
            if value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                value = int(value)
            changes[key] = value
    
    # Schreiben
    if changes:
        dry_run = not args.confirm
        if dry_run:
            print("\n⚠ DRY RUN — Füge --confirm hinzu um tatsächlich zu schreiben\n")
        
        bat.write(changes, dry_run=dry_run)
        
        if not dry_run:
            # Verifiziere
            print("\nVerifiziere...")
            time.sleep(1)
            bat.print_status()


if __name__ == '__main__':
    main()
