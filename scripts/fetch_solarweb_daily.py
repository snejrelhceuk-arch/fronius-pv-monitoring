#!/usr/bin/env python3
"""
Holt tägliche Energiedaten aus dem Fronius Solarweb-Portal und schreibt sie
in imports/solarweb/solarweb_daily_YYYY-MM_working.csv.

Authentifizierung: Solarweb-Username/Passwort aus .secrets (Schlüssel: Passwort)
API: Interne Solarweb Chart-API (/Chart/GetChartNew) über Browser-Session.

USAGE:
  python3 scripts/fetch_solarweb_daily.py --year 2026 --months 3-5
  python3 scripts/fetch_solarweb_daily.py --year 2026 --month 4
  python3 scripts/fetch_solarweb_daily.py  # → aktueller Monat

Feldmapping Chart-API → CSV:
  production-View: Energie in Batterie gespeichert → in_batt_kwh
                   Energie ins Netz eingespeist     → einspeisung_kwh
                   Energie Wattpilot                → wattpilot_kwh
                   Direkt verbraucht                → direkt_kwh
                   Summe production-View            → gesamt_prod_kwh
  consumption-View: Energie vom Netz bezogen        → netzbezug_kwh
                    Energie aus Batterie bezogen     → out_batt_kwh
                    Direkt verbraucht (inkl. WP)     → für verbrauch_kwh
"""

import sys
import os
import csv
import re
import argparse
import logging
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
LOG = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = REPO_ROOT / '.secrets'
SOLARWEB_DIR = REPO_ROOT / 'imports' / 'solarweb'

PV_SYSTEM_ID = 'e8220064-2767-4646-a534-12f14c07ebb9'
SOLARWEB_BASE = 'https://www.solarweb.com'
FRONIUS_LOGIN_URL = 'https://login.fronius.com'

CSV_HEADER = [
    'date', 'einspeisung_kwh', 'in_batt_kwh', 'wattpilot_kwh',
    'direkt_kwh', 'gesamt_prod_kwh', 'netzbezug_kwh', 'out_batt_kwh', 'verbrauch_kwh'
]


def load_secrets():
    secrets = {}
    if not SECRETS_PATH.exists():
        return secrets
    with open(SECRETS_PATH) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                secrets[k.strip()] = v.strip()
    return secrets


def parse_months(year, month_arg):
    """Parst '3', '3-5', '3,4,5' -> [(year, 3), (year, 4), ...]"""
    months = []
    if '-' in month_arg:
        start, end = month_arg.split('-', 1)
        for m in range(int(start), int(end) + 1):
            months.append((year, m))
    elif ',' in month_arg:
        for m in month_arg.split(','):
            months.append((year, int(m.strip())))
    else:
        months.append((year, int(month_arg)))
    return months


# --------------------------------------------------------------------------- #
# Solarweb Browser-Session Client                                              #
# --------------------------------------------------------------------------- #

class SolarwebClient:
    """Authentifiziert sich via Fronius OAuth2 und ruft die Chart-API ab."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) '
                'AppleWebKit/537.36 Chrome/120.0.0.0'
            )
        })
        self._aft = None  # antiForgeryToken (gecacht pro Monat)

    def login(self):
        """5-Schritt OAuth2 Login: ExternalLogin -> commonauth -> ExternalLoginCallback."""
        self.session.get(SOLARWEB_BASE, timeout=15)

        r1 = self.session.get(
            f'{SOLARWEB_BASE}/Account/ExternalLogin?ReturnUrl=%2F',
            timeout=15, allow_redirects=False
        )
        if 'Location' not in r1.headers:
            raise RuntimeError('ExternalLogin: keine Weiterleitung')

        r2 = self.session.get(
            r1.headers['Location'], timeout=15, allow_redirects=True
        )
        sdk_match = re.search(r'sessionDataKey=([^&"\']+)', r2.url)
        if not sdk_match:
            raise RuntimeError('sessionDataKey nicht in Redirect-URL gefunden')
        session_data_key = urllib.parse.unquote(sdk_match.group(1))

        r3 = self.session.post(
            f'{FRONIUS_LOGIN_URL}/commonauth',
            data={
                'username': self.username,
                'password': self.password,
                'sessionDataKey': session_data_key,
                'authWith': 'FroniusBasicAuthenticator',
            },
            timeout=15, allow_redirects=False
        )
        if 'Location' not in r3.headers:
            raise RuntimeError(
                'commonauth: keine Weiterleitung -- falsche Credentials?'
            )

        r4 = self.session.get(
            r3.headers['Location'], timeout=15, allow_redirects=False
        )
        form_data = {}
        for m in re.finditer(
            r'<input type="hidden" name="(\w+)"value="([^"]+)"', r4.text
        ):
            form_data[m.group(1)] = m.group(2)
        if not form_data:
            raise RuntimeError('Auto-Submit-Formular nicht gefunden')

        r5 = self.session.post(
            f'{SOLARWEB_BASE}/Account/ExternalLoginCallback',
            data=form_data, timeout=15, allow_redirects=True
        )
        if '.AspNet.Auth' not in self.session.cookies:
            raise RuntimeError(f'Login fehlgeschlagen, letzte URL: {r5.url}')

        LOG.info(f'Login erfolgreich.')

    def _get_aft(self, year, month):
        """Antiforgery-Token von der Chart-Seite holen."""
        url = (
            f'{SOLARWEB_BASE}/Chart/Chart'
            f'?pvSystemId={PV_SYSTEM_ID}'
            f'&interval=day&view=month&year={year}&month={month}'
        )
        r = self.session.get(url, timeout=15)
        m = re.search(r'"antiForgeryToken":"([^"]+)"', r.text)
        if not m:
            raise RuntimeError('antiForgeryToken nicht in Chart-Seite gefunden')
        return m.group(1)

    def _get_chart(self, view, year, month, aft):
        """Ruft /Chart/GetChartNew fuer einen Monat ab (interval=month)."""
        params = {
            'pvSystemId': PV_SYSTEM_ID,
            'year': year,
            'month': month,
            'day': 1,
            'interval': 'month',
            'view': view,
            '__RequestVerificationToken': aft,
        }
        r = self.session.get(
            f'{SOLARWEB_BASE}/Chart/GetChartNew',
            params=params,
            headers={'X-Requested-With': 'XMLHttpRequest'},
            timeout=30
        )
        if r.status_code != 200:
            raise RuntimeError(
                f'GetChartNew view={view}: HTTP {r.status_code}'
            )
        return r.json()

    def get_monthly_daily_data(self, year, month):
        """
        Holt Tagesdaten fuer einen Monat aus beiden Chart-Views.
        Gibt eine Liste von Dicts mit CSV-Feldern zurueck.
        """
        aft = self._get_aft(year, month)

        prod = self._get_chart('production', year, month, aft)
        cons = self._get_chart('consumption', year, month, aft)

        def series_dict(data, name):
            for s in data.get('settings', {}).get('series', []):
                if s['name'] == name:
                    return {int(ts): (v or 0) for ts, v in s['data']}
            return {}

        in_batt  = series_dict(prod, 'Energie in Batterie gespeichert')
        einsp    = series_dict(prod, 'Energie ins Netz eingespeist')
        wp       = series_dict(prod, 'Energie Wattpilot')
        direkt   = series_dict(prod, 'Direkt verbraucht')
        out_batt = series_dict(cons, 'Energie aus Batterie bezogen')
        netz     = series_dict(cons, 'Energie vom Netz bezogen')
        direkt_c = series_dict(cons, 'Direkt verbraucht')

        today = date.today()
        rows = []
        all_ts = sorted(
            set(in_batt) | set(einsp) | set(direkt) | set(out_batt) | set(netz)
        )
        for ts in all_ts:
            day_date = datetime.fromtimestamp(
                ts / 1000, tz=timezone.utc
            ).date()
            if day_date > today:
                continue  # keine Zukunftsdaten
            d = day_date.strftime('%Y-%m-%d')
            _in_b  = in_batt.get(ts, 0)
            _einsp = einsp.get(ts, 0)
            _wp    = wp.get(ts, 0)
            _dir   = direkt.get(ts, 0)
            _out_b = out_batt.get(ts, 0)
            _netz  = netz.get(ts, 0)
            _dir_c = direkt_c.get(ts, 0)
            _prod  = round(_in_b + _einsp + _wp + _dir, 2)
            _verbr = round(_out_b + _dir_c + _netz, 2)
            rows.append({
                'date':            d,
                'einspeisung_kwh': round(_einsp, 2),
                'in_batt_kwh':     round(_in_b, 2),
                'wattpilot_kwh':   round(_wp, 2),
                'direkt_kwh':      round(_dir, 2),
                'gesamt_prod_kwh': _prod,
                'netzbezug_kwh':   round(_netz, 2),
                'out_batt_kwh':    round(_out_b, 2),
                'verbrauch_kwh':   _verbr,
            })
        return rows


# --------------------------------------------------------------------------- #
# CSV schreiben                                                                #
# --------------------------------------------------------------------------- #

def write_csv(year, month, rows, dry_run=False):
    filename = SOLARWEB_DIR / f'solarweb_daily_{year}-{month:02d}_working.csv'
    if dry_run:
        LOG.info(f'[DRY] wuerde {len(rows)} Zeilen in {filename.name} schreiben')
        for row in rows[:3]:
            LOG.info(f"  {row['date']}: prod={row['gesamt_prod_kwh']} netz={row['netzbezug_kwh']}")
        return

    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    LOG.info(f'Geschrieben: {filename.name} ({len(rows)} Tage)')


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description='Solarweb Tagesdaten -> CSV')
    parser.add_argument('--year', type=int, default=date.today().year)
    parser.add_argument('--month', type=str,
                        help='Monat(e): "3", "3-5", "3,4,5"')
    parser.add_argument('--months', type=str, help='Alias fuer --month')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    month_arg = args.month or args.months
    if not month_arg:
        month_arg = str(date.today().month)

    secrets = load_secrets()
    username = secrets.get('Benutzer') or secrets.get('Bezutzer')
    password = secrets.get('Passwort')
    if not username:
        LOG.error('Benutzer nicht in .secrets gefunden')
        sys.exit(1)
    if not password:
        LOG.error('Passwort nicht in .secrets gefunden')
        sys.exit(1)

    month_list = parse_months(args.year, month_arg)

    client = SolarwebClient(username, password)
    LOG.info('Login...')
    client.login()

    for year, month in month_list:
        LOG.info(f'Hole Daten fuer {year}-{month:02d}...')
        try:
            rows = client.get_monthly_daily_data(year, month)
        except Exception as e:
            LOG.error(f'Fehler bei {year}-{month:02d}: {e}')
            continue
        if not rows:
            LOG.warning(f'Keine Daten fuer {year}-{month:02d}')
            continue
        write_csv(year, month, rows, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
