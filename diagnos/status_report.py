#!/usr/bin/env python3
"""
diagnos/status_report.py — menschenlesbare Status-Markdown-Dateien.

Schicht D (Report-Output). Nimmt bereits gesammelte read-only Snapshots
(`diagnos.integrity.run_all()`, `diagnos.health.run_all()`) und schreibt
kompakte Markdown-Statusdateien nach `logs/diagnos/`. Dieses Modul greift
selbst NICHT auf DB oder Hardware zu — es formatiert nur übergebene Dicts.

Zweck: Die tägliche Sunset-Mail bleibt knapp und für Außenstehende
verständlich; Details (jede Datenlücke mit Zeitstempel/Größe/Ursache, die
Systemkennwerte) landen in dauerhaft abrufbaren Statusdateien, auf die die
Mail nur verweist.

Erzeugte Dateien:
  - RAW-Status.md      Datenlücken (raw_data/data_1min/…) mit Ursachenheuristik.
  - System-Status.md   Host-Kennwerte (CPU-Temp, RAM, SD/Disk, Last, Throttle).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_DIR = os.path.join(BASE_DIR, 'logs', 'diagnos')

RAW_STATUS_FILE = 'RAW-Status.md'
SYSTEM_STATUS_FILE = 'System-Status.md'

_SEV_LABEL = {'ok': 'OK', 'warn': 'WARN', 'crit': 'KRITISCH', 'fail': 'FEHLER'}

_GAP_TABLE_LABEL = {
    'integrity:gaps:raw_data': 'raw_data (7-Tage-Rohpuffer, 5-s-Raster)',
    'integrity:gaps:data_1min': 'data_1min (1-Minuten-Aggregat)',
    'integrity:gaps:data_15min': 'data_15min (15-Minuten-Aggregat)',
    'integrity:gaps:hourly_data': 'hourly_data (Stundenaggregat)',
}


def _human_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 90:
        return f'{s} s'
    if s < 5400:
        return f'{s // 60} min'
    if s < 172800:
        return f'{s / 3600:.1f} h'
    return f'{s / 86400:.1f} d'


def _sev(value: Optional[str]) -> str:
    return _SEV_LABEL.get((value or '').lower(), (value or '—'))


def _parse_utc(ts_str: str) -> Optional[float]:
    try:
        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _boot_ts(health_data: Optional[dict]) -> Optional[float]:
    """Ungefährer Boot-Zeitpunkt aus dem uptime-Check (für Ursachenheuristik)."""
    if not health_data:
        return None
    for c in health_data.get('checks', []):
        if c.get('check') == 'uptime' and c.get('seconds'):
            return datetime.now(timezone.utc).timestamp() - float(c['seconds'])
    return None


def _gap_cause(sample: dict, check: dict, boot_ts: Optional[float]) -> str:
    """Best-effort-Ursache einer Datenlücke (Mehrfachnennung möglich)."""
    if sample.get('expected_night'):
        return 'WR-Nachtstandby (normal)'
    causes = []
    if check.get('version_change_near_gap') is True:
        causes.append('WR-Firmware-Update')
    end_ts = _parse_utc(sample.get('end_utc', ''))
    if boot_ts is not None and end_ts is not None and abs(end_ts - boot_ts) <= 900:
        causes.append('Neustart/Stromausfall')
    if not causes:
        causes.append('unbekannt')
    return ', '.join(causes)


def _build_raw_status(integrity_data: Optional[dict], health_data: Optional[dict]) -> str:
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    host = (integrity_data or {}).get('host', os.uname().nodename)
    boot_ts = _boot_ts(health_data)

    lines = [
        '# RAW-Status — Datenlücken-Protokoll',
        '',
        f'_Stand: {now} · Host: {host}_',
        '',
        'Datenlücken sind **kein Dauerfehler**: Sobald ein Tag abgeschlossen und in',
        'die Aggregationen übernommen ist, gilt eine Lücke als historischer',
        'Normalzustand und löst keinen Alarm mehr aus. Nur **frische** Lücken',
        '(jünger als ~1 Tag, noch behandelbar) sind alarmrelevant.',
        '',
        '| Quelle | frische Lücken | gesetzt (historisch) | Nacht-Standby | max. Lücke |',
        '| --- | ---: | ---: | ---: | ---: |',
    ]

    gap_checks = []
    detail_blocks = []
    for c in (integrity_data or {}).get('checks', []):
        name = c.get('check', '')
        if not name.startswith('integrity:gaps:'):
            continue
        gap_checks.append(c)
        label = _GAP_TABLE_LABEL.get(name, name)
        lines.append(
            f'| {label} | {c.get("fresh_gap_count", 0)} | '
            f'{c.get("settled_gap_count", 0)} | {c.get("night_gap_count", 0)} | '
            f'{_human_duration(c.get("max_gap_s", 0))} |'
        )
        samples = c.get('samples') or []
        if samples:
            block = [
                '',
                f'### {label} — Severity {_sev(c.get("severity"))}',
                '',
                '| Beginn (UTC) | Ende (UTC) | Größe | Klasse | Status | Ursache (heuristisch) |',
                '| --- | --- | ---: | --- | --- | --- |',
            ]
            for s in samples:
                if s.get('expected_night'):
                    status = 'Nacht-Standby'
                elif s.get('settled'):
                    status = 'gesetzt'
                else:
                    status = 'frisch'
                block.append(
                    f'| {s.get("start_utc","?")} | {s.get("end_utc","?")} | '
                    f'{_human_duration(s.get("gap_s", 0))} | {s.get("class","?")} | '
                    f'{status} | {_gap_cause(s, c, boot_ts)} |'
                )
            detail_blocks.extend(block)

    if not gap_checks:
        lines += ['', '_Keine Lücken-Checks im Snapshot._']

    lines += detail_blocks
    lines += [
        '',
        '---',
        'Ursachen-Legende: **WR-Nachtstandby** = Wechselrichter nachts offline (erwartet);',
        '**WR-Firmware-Update** = Lücke nahe einem dokumentierten Versionswechsel;',
        '**Neustart/Stromausfall** = Lücke endet nahe dem letzten Systemstart;',
        '**unbekannt** = nicht eindeutig zuordenbar (z. B. kurzer Pollausfall, stale process).',
        '',
        'Vollstatus: `python3 -m diagnos.integrity --pretty`',
    ]
    return '\n'.join(lines) + '\n'


def _build_system_status(health_data: Optional[dict]) -> str:
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    host = (health_data or {}).get('host', os.uname().nodename)
    by = {c.get('check'): c for c in (health_data or {}).get('checks', [])}

    def g(name, key, default='—'):
        return (by.get(name) or {}).get(key, default)

    lines = [
        '# System-Status — Host-Kennwerte',
        '',
        f'_Stand: {now} · Host: {host} · Gesamt: {_sev((health_data or {}).get("overall"))}_',
        '',
        '| Kennwert | Wert | Status |',
        '| --- | --- | --- |',
        f'| CPU-Temperatur | {g("cpu_temp","value_c")} °C | {_sev(g("cpu_temp","severity"))} |',
        f'| Throttle (seit Boot) | {g("throttle","hex")} (aktiv: {g("throttle","active_now")}) | {_sev(g("throttle","severity"))} |',
        f'| RAM | {g("ram","used_pct")} % ({g("ram","available_mb")} MB frei) | {_sev(g("ram","severity"))} |',
        f'| SD/Disk / | {g("disk_root","used_pct")} % ({g("disk_root","free_gb")} GB frei) | {_sev(g("disk_root","severity"))} |',
        f'| Last (1/5/15 min) | {g("load","load_1m")} / {g("load","load_5m")} / {g("load","load_15m")} ({g("load","cpus")} CPU) | {_sev(g("load","severity"))} |',
        f'| Uptime | {g("uptime","human")} | {_sev(g("uptime","severity"))} |',
    ]

    # Dienste / sonstige Checks mit Auffälligkeit
    bad = [
        c for c in (health_data or {}).get('checks', [])
        if (c.get('severity') or '').lower() in ('warn', 'crit', 'fail')
        and c.get('check') not in ('cpu_temp', 'throttle', 'ram', 'disk_root', 'load', 'uptime')
    ]
    lines += ['', '## Auffälligkeiten (Dienste/Frische/Backup)', '']
    if bad:
        lines += ['| Check | Status | Detail |', '| --- | --- | --- |']
        for c in bad:
            detail = c.get('error') or c.get('active_state') or c.get('detail') or ''
            lines.append(f'| {c.get("check")} | {_sev(c.get("severity"))} | {detail} |')
    else:
        lines.append('_Keine — alle Dienste, Frischewerte und Backups im grünen Bereich._')

    lines += ['', '---', 'Vollstatus: `python3 -m diagnos.health --pretty`']
    return '\n'.join(lines) + '\n'


def _write(path: str, content: str) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.replace(tmp, path)
    return {'path': path, 'size': os.path.getsize(path)}


def write_status_reports(
    integrity_data: Optional[dict] = None,
    health_data: Optional[dict] = None,
    out_dir: Optional[str] = None,
) -> dict:
    """Schreibt RAW-Status.md + System-Status.md und liefert {name: {path,size}}."""
    out_dir = out_dir or STATUS_DIR
    result = {}
    try:
        result[RAW_STATUS_FILE] = _write(
            os.path.join(out_dir, RAW_STATUS_FILE),
            _build_raw_status(integrity_data, health_data),
        )
        result[SYSTEM_STATUS_FILE] = _write(
            os.path.join(out_dir, SYSTEM_STATUS_FILE),
            _build_system_status(health_data),
        )
    except OSError:
        # Statusdateien sind Beiwerk; Fehler dürfen die Mail nicht verhindern.
        pass
    return result


def main():
    """Standalone: aktuelle Snapshots ziehen und Statusdateien schreiben."""
    from diagnos import health, integrity
    written = write_status_reports(integrity.run_all(), health.run_all())
    for name, info in written.items():
        print(f'{name}: {info["path"]} ({info["size"]} Bytes)')


if __name__ == '__main__':
    main()
