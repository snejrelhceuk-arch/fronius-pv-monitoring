#!/usr/bin/env python3
"""
Monatlicher PDF-Versand (Netzbetreiber/Betreiberbericht).

Eigenschaften:
- Neustartsicher: Ausfuehrung via systemd timer mit Persistent=true.
- Stale-Prozess-sicher: exklusiver Dateilock (flock).
- Deduplizierung: pro Berichtsmonat nur ein Versand (State-Datei).
- Rollenbewusst: auf Failover-Host wird uebersprungen.

Standard:
- Berichtsmonat = Vormonat.
- PDF-Quelle: tools/generate_anlagendoku_pdf.py
- Versand an config.NOTIFICATION_EMAIL via SMTP-Konfiguration in config.py.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import logging
import os
import shutil
import smtplib
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, List, Tuple, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from host_role import is_failover
from automation.engine import credential_store
from automation.engine.event_notifier import EventNotifier

LOG_FILE = Path('/tmp/pv_monthly_pdf_report.log')
LOCK_FILE = Path('/tmp/pv_monthly_pdf_report.lock')
STATE_DIR = BASE_DIR / '.state'
STATE_FILE = STATE_DIR / 'monthly_pdf_report_state.json'
REPORT_DIR = BASE_DIR / 'reports' / 'monthly'
PDF_GENERATOR = BASE_DIR / 'tools' / 'generate_anlagendoku_pdf.py'
PDF_GENERATED = BASE_DIR / 'tools' / 'PV_Anlagendokumentation.pdf'
WP_LIMIT_W = float(getattr(config, 'WP_LEISTUNG_LIMIT_W', 4200))
WP_PROTOCOL_FILE = Path(
    getattr(config, 'WP_POWER_PROTOCOL_FILE', BASE_DIR / 'logs' / 'wp_netzbetreiber_leistung.csv')
)


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


@dataclass
class TargetMonth:
    year: int
    month: int

    @property
    def key(self) -> str:
        return f'{self.year:04d}-{self.month:02d}'

    @property
    def label(self) -> str:
        return f'{self.month:02d}.{self.year:04d}'


class FileLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.fd = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.lock_path, 'w')
        try:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Monatsversand laeuft bereits (Lock aktiv)')
        self.fd.write(f'{os.getpid()}\n')
        self.fd.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd:
            try:
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            finally:
                self.fd.close()


def parse_target_month(value: Optional[str]) -> TargetMonth:
    if value:
        try:
            year_s, month_s = value.split('-', 1)
            year = int(year_s)
            month = int(month_s)
            if year < 2020 or not 1 <= month <= 12:
                raise ValueError
            return TargetMonth(year=year, month=month)
        except Exception as exc:
            raise ValueError('--month muss YYYY-MM sein') from exc

    now = datetime.now()
    first_this_month = datetime(now.year, now.month, 1)
    prev_month_last_day = first_this_month - timedelta(days=1)
    return TargetMonth(year=prev_month_last_day.year, month=prev_month_last_day.month)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def select_db_path() -> Path:
    db_candidates = [Path(config.DB_PATH), Path(getattr(config, 'DB_PERSIST_PATH', config.DB_PATH))]
    for p in db_candidates:
        if not p.exists():
            continue
        try:
            conn = sqlite3.connect(str(p), timeout=3.0)
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM monthly_statistics')
            cur.fetchone()
            conn.close()
            return p
        except Exception:
            continue
    return Path(getattr(config, 'DB_PERSIST_PATH', config.DB_PATH))


def load_month_summary(target: TargetMonth) -> dict:
    db_path = select_db_path()
    summary = {
        'db_path': str(db_path),
        'solar_erzeugung_kwh': None,
        'gesamt_verbrauch_kwh': None,
        'netz_bezug_kwh': None,
        'autarkie_prozent': None,
        'waermepumpe_kwh': None,
    }
    if not db_path.exists():
        return summary

    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT solar_erzeugung_kwh,
                   gesamt_verbrauch_kwh,
                   netz_bezug_kwh,
                   autarkie_prozent,
                   waermepumpe_kwh
            FROM monthly_statistics
            WHERE year = ? AND month = ?
            """,
            (target.year, target.month),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            summary['solar_erzeugung_kwh'] = row[0]
            summary['gesamt_verbrauch_kwh'] = row[1]
            summary['netz_bezug_kwh'] = row[2]
            summary['autarkie_prozent'] = row[3]
            summary['waermepumpe_kwh'] = row[4]
    except Exception as exc:
        logging.warning('Monatswerte konnten nicht geladen werden: %s', exc)

    return summary


def generate_pdf_archive(target: TargetMonth) -> Path:
    if not PDF_GENERATOR.exists():
        raise RuntimeError(f'PDF-Generator fehlt: {PDF_GENERATOR}')

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    logging.info('Starte PDF-Erzeugung via %s', PDF_GENERATOR)
    result = subprocess.run(
        [sys.executable, str(PDF_GENERATOR)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logging.error('PDF-Generator stderr: %s', result.stderr.strip())
        raise RuntimeError(f'PDF-Erzeugung fehlgeschlagen (exit={result.returncode})')

    if not PDF_GENERATED.exists():
        raise RuntimeError(f'Erwartetes PDF nicht gefunden: {PDF_GENERATED}')

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    target_pdf = REPORT_DIR / f'PV_Monatsbericht_{target.key}_{ts}.pdf'
    shutil.copy2(PDF_GENERATED, target_pdf)
    logging.info('PDF archiviert: %s', target_pdf)
    return target_pdf


def _fmt(v: Optional[float], suffix: str) -> str:
    if v is None:
        return '--'
    return f'{v:.1f} {suffix}'


def _month_bounds(target: TargetMonth) -> Tuple[int, int]:
    start = datetime(target.year, target.month, 1)
    if target.month == 12:
        end = datetime(target.year + 1, 1, 1)
    else:
        end = datetime(target.year, target.month + 1, 1)
    return int(start.timestamp()), int(end.timestamp())


def _read_wp_rows_from_protocol(start_ts: int, end_ts: int) -> List[Tuple[int, float, int, str]]:
    if not WP_PROTOCOL_FILE.exists():
        return []

    rows: List[Tuple[int, float, int, str]] = []
    with open(WP_PROTOCOL_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(float(row.get('ts_epoch') or 0))
                if ts < start_ts or ts >= end_ts:
                    continue
                power = abs(float(row.get('wp_max_w') or 0.0))
                within = int(float(row.get('within_limit') or (1 if power <= WP_LIMIT_W else 0)))
                rows.append((ts, power, 1 if within != 0 else 0, 'protocol_csv'))
            except Exception:
                continue
    return rows


def _read_wp_rows_from_db(start_ts: int, end_ts: int) -> List[Tuple[int, float, int, str]]:
    db_path = select_db_path()
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path), timeout=5.0)
    cur = conn.cursor()
    table = 'data_1min'
    try:
        cur.execute("SELECT COUNT(*) FROM data_1min WHERE ts >= ? AND ts < ?", (start_ts, end_ts))
        n = cur.fetchone()[0]
        if n <= 0:
            table = 'data_15min'
    except Exception:
        table = 'data_15min'

    rows: List[Tuple[int, float, int, str]] = []
    try:
        cur.execute(
            f"""
            SELECT ts, ABS(COALESCE(P_WP_max, 0))
            FROM {table}
            WHERE ts >= ? AND ts < ? AND P_WP_max IS NOT NULL
            ORDER BY ts
            """,
            (start_ts, end_ts),
        )
        for ts, power in cur.fetchall():
            p = abs(float(power or 0.0))
            rows.append((int(ts), p, 1 if p <= WP_LIMIT_W else 0, f'db_{table}'))
    finally:
        conn.close()

    return rows


def build_wp_power_proof(target: TargetMonth) -> Dict[str, object]:
    start_ts, end_ts = _month_bounds(target)
    rows = _read_wp_rows_from_protocol(start_ts, end_ts)
    if not rows:
        rows = _read_wp_rows_from_db(start_ts, end_ts)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = REPORT_DIR / f'WP_Leistungsnachweis_{target.key}_{ts_tag}.csv'

    if not rows:
        with open(csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['record_type', 'date', 'ts_epoch', 'ts_local', 'wp_power_w', 'limit_w', 'within_limit', 'source'])
            w.writerow(['summary', target.key, '', '', '', f'{WP_LIMIT_W:.1f}', '', 'no_data'])
        return {
            'count': 0,
            'max_w': None,
            'max_ts': None,
            'violations': 0,
            'source': 'none',
            'csv_path': csv_path,
        }

    max_row = max(rows, key=lambda r: r[1])
    violations = [r for r in rows if r[2] == 0]

    day_max: Dict[str, Tuple[int, float, int, str]] = {}
    for r in rows:
        d = datetime.fromtimestamp(r[0]).strftime('%Y-%m-%d')
        if d not in day_max or r[1] > day_max[d][1]:
            day_max[d] = r

    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['record_type', 'date', 'ts_epoch', 'ts_local', 'wp_power_w', 'limit_w', 'within_limit', 'source'])
        w.writerow([
            'summary',
            target.key,
            str(max_row[0]),
            datetime.fromtimestamp(max_row[0]).strftime('%Y-%m-%d %H:%M:%S'),
            f'{max_row[1]:.1f}',
            f'{WP_LIMIT_W:.1f}',
            '1' if max_row[1] <= WP_LIMIT_W else '0',
            max_row[3],
        ])

        for d in sorted(day_max.keys()):
            r = day_max[d]
            w.writerow([
                'daily_max',
                d,
                str(r[0]),
                datetime.fromtimestamp(r[0]).strftime('%Y-%m-%d %H:%M:%S'),
                f'{r[1]:.1f}',
                f'{WP_LIMIT_W:.1f}',
                str(r[2]),
                r[3],
            ])

        for r in violations:
            w.writerow([
                'violation',
                datetime.fromtimestamp(r[0]).strftime('%Y-%m-%d'),
                str(r[0]),
                datetime.fromtimestamp(r[0]).strftime('%Y-%m-%d %H:%M:%S'),
                f'{r[1]:.1f}',
                f'{WP_LIMIT_W:.1f}',
                str(r[2]),
                r[3],
            ])

    return {
        'count': len(rows),
        'max_w': round(max_row[1], 1),
        'max_ts': int(max_row[0]),
        'violations': len(violations),
        'source': max_row[3],
        'csv_path': csv_path,
    }


def build_mail(target: TargetMonth, pdf_path: Path, summary: dict, wp_proof: dict) -> MIMEMultipart:
    recipient = getattr(config, 'NOTIFICATION_EMAIL', '')
    if not recipient:
        raise RuntimeError('NOTIFICATION_EMAIL ist leer')

    msg = MIMEMultipart()
    msg['Subject'] = f'[PV-System] Monatsbericht {target.label} - WP-Leistungsnachweis'
    msg['From'] = getattr(config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
    msg['To'] = recipient
    msg['X-PV-Event'] = 'monthly_pdf_report'

    body = (
        f'Monatlicher PV-Bericht fuer {target.label}.\n\n'
        f'Kurzwerte ({target.label}):\n'
        f'- Solar-Erzeugung: {_fmt(summary.get("solar_erzeugung_kwh"), "kWh")}\n'
        f'- Gesamtverbrauch: {_fmt(summary.get("gesamt_verbrauch_kwh"), "kWh")}\n'
        f'- Netzbezug: {_fmt(summary.get("netz_bezug_kwh"), "kWh")}\n'
        f'- Waermepumpe: {_fmt(summary.get("waermepumpe_kwh"), "kWh")}\n'
        f'- Autarkie: {_fmt(summary.get("autarkie_prozent"), "%")}\n\n'
        f'WP-Leistungsnachweis ({target.label}):\n'
        f'- Grenzwert: {WP_LIMIT_W:.1f} W\n'
        f'- Monats-Maximum: {_fmt(wp_proof.get("max_w"), "W")}\n'
        f'- Zeitpunkt Maximum: {datetime.fromtimestamp(wp_proof.get("max_ts")).strftime("%d.%m.%Y %H:%M:%S") if wp_proof.get("max_ts") else "--"}\n'
        f'- Ueberschreitungen > Grenzwert: {wp_proof.get("violations", 0)}\n'
        f'- Messpunkte ausgewertet: {wp_proof.get("count", 0)}\n\n'
        f'Datenquelle: {summary.get("db_path")}\n'
        f'Anhang: {pdf_path.name}\n'
        f'Anhang Nachweis: {Path(wp_proof.get("csv_path", "")).name if wp_proof.get("csv_path") else "--"}\n'
    )
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(pdf_path, 'rb') as f:
        attachment = MIMEApplication(f.read(), _subtype='pdf')
    attachment.add_header('Content-Disposition', 'attachment', filename=pdf_path.name)
    msg.attach(attachment)

    csv_path = wp_proof.get('csv_path')
    if csv_path and Path(csv_path).exists():
        with open(csv_path, 'rb') as f:
            attachment_csv = MIMEApplication(f.read(), _subtype='csv')
        attachment_csv.add_header('Content-Disposition', 'attachment', filename=Path(csv_path).name)
        msg.attach(attachment_csv)

    return msg


def send_mail(msg: MIMEMultipart) -> None:
    # Gleicher Versandpfad wie beim taeglichen Sunset-Bericht (event_notifier).
    notifier = EventNotifier()
    smtp_host = notifier._smtp_host
    smtp_port = notifier._smtp_port
    smtp_user = notifier._smtp_user
    smtp_from = notifier._from
    smtp_to = notifier._email
    smtp_pass = credential_store.lade('smtp_pass')

    if smtp_user and not smtp_pass:
        raise RuntimeError('SMTP-Passwort fehlt (credential_store: smtp_pass)')

    if smtp_from:
        if msg.get('From'):
            msg.replace_header('From', smtp_from)
        else:
            msg['From'] = smtp_from
    if smtp_to:
        if msg.get('To'):
            msg.replace_header('To', smtp_to)
        else:
            msg['To'] = smtp_to

    if smtp_port == 465:
        smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
    else:
        smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        if smtp_port == 587:
            smtp.starttls()

    try:
        if smtp_user and smtp_pass:
            smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(msg['From'], [msg['To']], msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description='Monatlichen PDF-Bericht erzeugen und versenden')
    parser.add_argument('--month', help='Berichtsmonat im Format YYYY-MM (default: Vormonat)')
    parser.add_argument('--force', action='store_true', help='Versand auch wenn Monat bereits gesendet')
    parser.add_argument('--dry-run', action='store_true', help='PDF erzeugen, keine E-Mail senden')
    parser.add_argument('--verbose', action='store_true', help='Debug-Logging')
    args = parser.parse_args()

    setup_logging(args.verbose)

    if is_failover():
        logging.info('Failover-Rolle erkannt: Monatsbericht wird hier nicht versendet')
        return 0

    target = parse_target_month(args.month)
    logging.info('Monatsbericht-Job gestartet fuer %s', target.key)

    with FileLock(LOCK_FILE):
        state = load_state()
        sent_map = state.get('sent_months', {}) if isinstance(state, dict) else {}

        if not args.force and sent_map.get(target.key):
            logging.info('Monatsbericht %s wurde bereits versendet am %s', target.key, sent_map.get(target.key))
            return 0

        pdf_path = generate_pdf_archive(target)
        summary = load_month_summary(target)
        wp_proof = build_wp_power_proof(target)

        if args.dry_run:
            logging.info('Dry-Run aktiv: kein Mailversand')
            return 0

        msg = build_mail(target, pdf_path, summary, wp_proof)
        send_mail(msg)

        sent_map[target.key] = datetime.now().isoformat(timespec='seconds')
        state = {
            'last_run': datetime.now().isoformat(timespec='seconds'),
            'last_month': target.key,
            'last_pdf': str(pdf_path),
            'last_wp_proof_csv': str(wp_proof.get('csv_path')) if wp_proof.get('csv_path') else '',
            'sent_months': sent_map,
        }
        save_state(state)
        logging.info('Monatsbericht %s erfolgreich gesendet an %s', target.key, msg['To'])
        return 0


def _entry() -> int:
    try:
        return main()
    except Exception as exc:
        logging.exception('Monatsbericht fehlgeschlagen: %s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(_entry())
