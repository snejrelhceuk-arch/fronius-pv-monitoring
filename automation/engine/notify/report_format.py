"""
notify/report_format.py — Reine Textformatierung des Sunset-Tagesberichts.

Nimmt fertige read-only Snapshots (Energie-Dict + Diagnos-Health/Integrity/NQ)
und baut die E-Mail-Textzeilen. **Kein** DB-/Hardware-Zugriff, keine
Seiteneffekte — dadurch aus ``event_notifier.py`` ausgelagert und einzeln
testbar. Der ``EventNotifier`` sammelt die Snapshots und schreibt die
Statusdateien; hier wird nur formatiert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

_SEV = {'ok': 'OK', 'warn': 'WARN', 'crit': 'KRIT', 'fail': 'FAIL'}


def _sev(value: Optional[str]) -> str:
    return _SEV.get((value or '').lower(), value or '—')


def _age(seconds) -> str:
    if seconds is None:
        return '—'
    if seconds < 3600:
        return f'{int(seconds // 60)} min'
    return f'{seconds / 3600:.1f} h'


# ── Energie-Kopf (24h Sunset→Sunset) ───────────────────────
def energy_section(d: dict) -> list:
    start_str = datetime.fromtimestamp(d['start_ts']).strftime('%d.%m. %H:%M')
    end_str = datetime.fromtimestamp(d['end_ts']).strftime('%d.%m. %H:%M')

    def _fmt(val, einheit='kWh', dez=1):
        return '—' if val is None else f'{val:.{dez}f} {einheit}'

    def _pct(val):
        return '—' if val is None else f'{val:.1f}%'

    verbrauch = d['pv_kwh'] + d['netzbezug_kwh'] - d['einspeisung_kwh']
    autarkie = max(0, (1 - d['netzbezug_kwh'] / verbrauch)) * 100 if verbrauch > 0 else 0

    zeilen = [
        'PV-System Sunset-Tagesbericht',
        '',
        f'{start_str}  →  {end_str}  ({d["stunden"]} h Daten)',
        f'  SOC:                  {_pct(d["soc_start"])} → {_pct(d["soc_end"])}'
        f'  (min/max {_pct(d["soc_min"])}/{_pct(d["soc_max"])})',
        f'  Batterie Ladung:      {_fmt(d["batt_ladung_kwh"])}',
        f'  Batterie Entladung:   {_fmt(d["batt_entladung_kwh"])}',
        '',
        f'  PV-Erzeugung:         {_fmt(d["pv_kwh"])}',
        f'  Verbrauch:            {_fmt(verbrauch)}',
        f'  Netzbezug:            {_fmt(d["netzbezug_kwh"])}',
        f'  Einspeisung:          {_fmt(d["einspeisung_kwh"])}',
        f'  Autarkie:             {autarkie:.0f}%',
        '',
        f'  Wärmepumpe:           {_fmt(d["wp_kwh"])}',
    ]
    if d.get('wattpilot_kwh') is not None:
        zeilen.append(f'  Wattpilot (EV):       {_fmt(d["wattpilot_kwh"])}')
    return zeilen


# ── Systemgesundheit (Diagnos Health) ──────────────────────
def diagnos_summary(health_data: Optional[dict], reportable_names: Optional[set] = None) -> list:
    if not health_data:
        return ['', 'Systemgesundheit (Diagnos D)', '  Snapshot nicht verfügbar.']

    checks = health_data.get('checks', [])
    by = {c.get('check'): c for c in checks}
    bad = [c for c in checks if c.get('severity') in ('warn', 'crit', 'fail')]
    if reportable_names is not None:
        shown = [c for c in bad if c.get('check') in reportable_names]
        stale = len(bad) - len(shown)
    else:
        shown, stale = bad, 0

    def val(name, key, unit=''):
        v = (by.get(name) or {}).get(key)
        return '—' if v is None else f'{v}{unit}'

    def age(name):
        return _age((by.get(name) or {}).get('age_s'))

    lines = [
        '',
        'Systemgesundheit (Diagnos D)',
        f'  Gesamt:               {_sev(health_data.get("overall"))}',
        f'  CPU / RAM / Disk:     {val("cpu_temp","value_c","°C")} / '
        f'{val("ram","used_pct","%")} / {val("disk_root","used_pct","%")}',
        f'  Frische raw / 1min:   {age("freshness:raw_data")} / {age("freshness:data_1min")}',
        f'  Frische 15min / Tag:  {age("freshness:data_15min")} / {age("freshness:daily_data")}',
        f'  Lokales GFS-Backup:   {val("backup_local_gfs_daily","age_h"," h")}',
    ]

    mirror = by.get('mirror_sync_age')
    if mirror and not mirror.get('skipped'):
        lines.append(f'  Mirror-Sync:          {val("mirror_sync_age","age_s"," s")} '
                     f'({_sev(mirror.get("severity"))})')

    if shown:
        lines += ['', '  Auffälligkeiten (neu/eskaliert):']
        for c in shown[:6]:
            detail = c.get('error')
            if detail is None and 'age_s' in c:
                detail = f'Alter {_age(c.get("age_s"))}'
            elif detail is None and 'age_h' in c:
                detail = f'Alter {c.get("age_h")} h'
            elif detail is None:
                detail = c.get('state') or 'siehe Diagnos-Report'
            reason = c.get('_alert_reason')
            tag = f' [{reason}]' if reason and reason != 'new' else ''
            lines.append(f'    [{_sev(c.get("severity"))}] {c.get("check")}: {detail}{tag}')
    if stale > 0:
        lines.append(f'  ({stale} stabiler Befund unterdrückt — Details: diagnos.health)')
    return lines


# ── Datenintegrität (Diagnos Integrity) ────────────────────
def integrity_summary(integrity_data: Optional[dict], reportable_names: Optional[set] = None) -> list:
    if not integrity_data:
        return ['', 'Datenintegrität (Diagnos D)', '  Snapshot nicht verfügbar.']

    checks = integrity_data.get('checks', [])
    by = {c.get('check'): c for c in checks}
    bad = [c for c in checks if c.get('severity') in ('warn', 'crit', 'fail')]
    stale = sum(1 for c in bad if reportable_names is not None
                and c.get('check') not in reportable_names)

    attachment = by.get('integrity:fronius_attachment_state', {})
    poll_age = attachment.get('last_poll_age_s')
    if poll_age is not None:
        collector = (f'aktiv (Poll vor {poll_age} s)' if attachment.get('collector_live')
                     else f'INAKTIV seit {poll_age} s!')
    else:
        collector = '—'

    lines = [
        '',
        'Datenintegrität (Diagnos D)',
        f'  Gesamt:               {_sev(integrity_data.get("overall"))}',
        f'  Tagesbilanz:          {_sev((by.get("integrity:daily_energy_balance") or {}).get("severity"))}',
        f'  Monats-/Jahresrollup: {_sev((by.get("integrity:monthly_rollup") or {}).get("severity"))} / '
        f'{_sev((by.get("integrity:yearly_rollup") or {}).get("severity"))}',
        f'  WR-Version F1:        {attachment.get("inverter_vr") or "—"}',
        f'  WR-Anknüpfung:        {attachment.get("assessment") or "—"}',
        f'  Collector:            {collector}',
    ]

    consec = attachment.get('consecutive_errors', 0)
    if consec > 0:
        lines.append(f'  Fehlerstrang:         {consec} Polls in Folge')

    gap_shown = 0
    for name in ('integrity:gaps:raw_data', 'integrity:gaps:data_1min',
                 'integrity:gaps:data_15min', 'integrity:gaps:hourly_data'):
        gap = by.get(name)
        if not gap or gap.get('gap_count', 0) <= 0:
            continue
        if reportable_names is not None and name not in reportable_names:
            continue
        gap_shown += 1
        lines.append(
            f'  [{_sev(gap.get("severity"))}] {name}: '
            f'{gap.get("gap_count")} Lücke(n), max {gap.get("max_gap_s")} s')
        if gap.get('followup_assessment'):
            lines.append(f'    Folge: {gap.get("followup_assessment")}')

    if not bad:
        lines.append('  Keine Integritätsabweichung im Prüffenster.')
    elif stale > 0 and gap_shown == 0:
        lines.append('  Keine neuen Befunde — bekannte, stabile Zustände nur protokolliert (s. u.).')
    return lines


# ── Netzqualität (Diagnos NQ, Rolle N) ─────────────────────
def nq_summary(nq_checks: Optional[list], reportable_names: Optional[set] = None) -> list:
    lines = ['', 'Netzqualität (PAC4200, Rolle N)']
    active = any(not c.get('skipped') for c in (nq_checks or []))
    if not nq_checks or not active:
        lines.append('  Modul nicht aktiv (keine NQ-Daten).')
        return lines

    by = {c.get('check'): c for c in nq_checks}
    pf = by.get('nq:pipeline_freshness', {})
    ef = by.get('nq:energy_freshness', {})
    ev = by.get('nq:events_recent', {})

    lines.append(f'  Pipeline:             {_sev(pf.get("severity"))} '
                 f'(letzte Aggregate vor {_age(pf.get("age_s"))})')
    lines.append(f'  Tagesenergie:         {_sev(ef.get("severity"))} '
                 f'(Stand {ef.get("last_day", "—")})')
    if ev and not ev.get('skipped'):
        lines.append(f'  Netzereignisse 24 h:  {ev.get("count", 0)}')

    bad = [c for c in nq_checks if (c.get('severity') or '') in ('warn', 'crit', 'fail')]
    if reportable_names is not None:
        shown = [c for c in bad if c.get('check') in reportable_names]
        stale = len(bad) - len(shown)
    else:
        shown, stale = bad, 0
    for c in shown[:6]:
        lines.append(f'  [{_sev(c.get("severity"))}] {c.get("check")}: '
                     f'{c.get("error") or c.get("detail") or ""}')
    if stale > 0:
        lines.append(f'  ({stale} stabiler NQ-Befund unterdrückt)')
    return lines


# ── Statusquellen + Diff-Zähler + Fuß ──────────────────────
def status_quellen(written: Optional[dict]) -> list:
    lines = ['', 'Weiterführende Statusquellen']
    if written:
        for name in ('RAW-Status.md', 'System-Status.md', 'Netz-Status.md'):
            info = written.get(name)
            if info:
                lines.append(f'  {info["path"]}  ({info["size"] / 1024.0:.1f} KB)')
    else:
        lines.append('  (Statusdateien konnten nicht geschrieben werden)')
    lines += [
        '  Laufzeit-Logs:  journalctl -u pv-web -u pv-automation -u pv-collector',
        '  Voll-Status:    python3 -m diagnos.health|integrity|nq_health --pretty',
    ]
    return lines


def diff_counter(alert_summary: Optional[dict]) -> list:
    if not alert_summary:
        return []
    return [
        '',
        'Diagnos-Filter (Diff zur letzten Mail)',
        f'  neu={alert_summary.get("new", 0)}  geändert={alert_summary.get("changed", 0)}  '
        f'erinnerung={alert_summary.get("reminder", 0)}  '
        f'unterdrückt={alert_summary.get("suppressed", 0)}  geheilt={alert_summary.get("healed", 0)}',
        '  Stabile Zustände werden nicht erneut gemeldet, nur nach 7 Tagen erinnert; '
        '„geheilt" = Rückkehr auf OK.',
    ]


FOOTER = [
    '',
    'Automatisch generiert bei Sonnenuntergang.',
    'Konfiguration: pv-config.py → Benachrichtigungen',
]
