"""Versioniertes Korrekturregister fuer monthly_statistics.

Die Datei config/statistics_corrections.json ist die kanonische Stelle fuer
manuell freigegebene Monatskorrekturen. Sie enthaelt Quelle, Begruendung und
Semantik der Korrektur (fester Monatswert oder laufender Offset).
"""

import json
import logging
import os

import config

logger = logging.getLogger(__name__)

CORRECTIONS_FILE = os.path.join(config.BASE_DIR, 'config', 'statistics_corrections.json')
SUPPORTED_FIELDS = {'waermepumpe_kwh', 'wattpilot_kwh'}
SUPPORTED_MODES = {'fixed', 'offset'}


def load_monthly_stat_corrections(file_path=CORRECTIONS_FILE):
    """Lade und validiere Monatskorrekturen aus JSON.

    Returns:
        dict[(year, month, field)] -> correction metadata
    """
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.error(f"Statistik-Korrekturen konnten nicht geladen werden: {exc}")
        return {}

    corrections = {}
    entries = payload.get('monthly_statistics', [])
    for index, entry in enumerate(entries, start=1):
        try:
            year = int(entry['year'])
            month = int(entry['month'])
            field = str(entry['field']).strip()
            mode = str(entry['mode']).strip().lower()
            value = float(entry['value'])
            source = str(entry.get('source', 'unspecified')).strip() or 'unspecified'
            reason = str(entry.get('reason', '')).strip()
            active = bool(entry.get('active', True))
        except Exception as exc:
            logger.warning(f"Statistik-Korrektur #{index} ungueltig: {exc}")
            continue

        if not active:
            continue
        if field not in SUPPORTED_FIELDS:
            logger.warning(f"Statistik-Korrektur #{index}: Feld nicht unterstuetzt: {field}")
            continue
        if mode not in SUPPORTED_MODES:
            logger.warning(f"Statistik-Korrektur #{index}: Modus nicht unterstuetzt: {mode}")
            continue
        if not 1 <= month <= 12:
            logger.warning(f"Statistik-Korrektur #{index}: Monat ungueltig: {month}")
            continue

        corrections[(year, month, field)] = {
            'mode': mode,
            'value': value,
            'source': source,
            'reason': reason,
        }

    return corrections


def apply_monthly_stat_correction(year, month, field, source_value, corrections):
    """Wende eine geladene Monatskorrektur an.

    Returns:
        (corrected_value, metadata_or_none)
    """
    correction = corrections.get((year, month, field))
    if not correction:
        return source_value, None

    if correction['mode'] == 'fixed':
        corrected_value = correction['value']
    else:
        corrected_value = source_value + correction['value']

    metadata = dict(correction)
    metadata['source_value'] = source_value
    metadata['corrected_value'] = corrected_value
    return corrected_value, metadata