import re
import os
import sys
import time
import json
import logging
import threading
import requests
import xml.etree.ElementTree as ET
from urllib.error import URLError
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Pfad zu config.py (Parent-Dir des Parent-Dir von ticker_service)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
try:
    from config import load_local_setting
except ImportError:
    def load_local_setting(key, default=''):
        return os.environ.get(key, default)

# Logging-Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Konfiguration
PORT = int(os.environ.get("TICKER_PORT", 8050))
# Increase default update interval by 15% to slow system speed slightly
UPDATE_INTERVAL_SEC = int(os.environ.get("TICKER_UPDATE_INTERVAL_SEC", int(5 * 60 * 1.15)))
# Zeichen des RSS-Detailtexts: dient dem LLM als Kontext für die 2. Zeile UND
# erscheint im Fallback (Ollama offline) direkt als 2. Zeile. 2026-08-04 von 256
# auf 512 verdoppelt (mehr Kontext -> bessere Erklärungen). Maßgeblich = systemd-
# Override auf .195 (Env hat Vorrang); dieser Default gilt nur ohne Override.
DETAIL_MAX_CHARS = int(os.environ.get("TICKER_DETAIL_MAX_CHARS", 512))
# Optionale zweite Zeile: Erlaeuterungen vom externen Ubuntu-Ollama.
EXPLAIN_REMOTE_ENABLE = os.environ.get("TICKER_EXPLAIN_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EXPLAIN_REMOTE_URL = os.environ.get("TICKER_EXPLAIN_OLLAMA_URL") or load_local_setting("PV_TICKER_EXPLAIN_OLLAMA_URL", "http://ollama-host:11434/api/generate")
EXPLAIN_REMOTE_MODEL = os.environ.get("TICKER_EXPLAIN_MODEL") or load_local_setting("PV_TICKER_EXPLAIN_MODEL", "qwen2.5:7b")
EXPLAIN_REMOTE_MODEL_FALLBACK = os.environ.get("TICKER_EXPLAIN_MODEL_FALLBACK") or load_local_setting("PV_TICKER_EXPLAIN_MODEL_FALLBACK", "qwen2.5:7b")
EXPLAIN_TIMEOUT_SEC = int(os.environ.get("TICKER_EXPLAIN_TIMEOUT_SEC", 25))  # erhöht für Mistral 25GB
EXPLAIN_TIMEOUT_FALLBACK_SEC = int(os.environ.get("TICKER_EXPLAIN_TIMEOUT_FALLBACK_SEC", 15))
EXPLAIN_TEMPERATURE = float(os.environ.get("TICKER_EXPLAIN_TEMPERATURE", 0.12))
EXPLAIN_TOP_P = float(os.environ.get("TICKER_EXPLAIN_TOP_P", 0.6))
EXPLAIN_MIN_WORDS = int(os.environ.get("TICKER_EXPLAIN_MIN_WORDS", 20))
EXPLAIN_MAX_WORDS = int(os.environ.get("TICKER_EXPLAIN_MAX_WORDS", 35))
# Resilienz: Wenn keine KI-Erklaerung vorliegt (Ollama offline/Modell fehlt),
# wird die RSS-Detailzusammenfassung als zweite Zeile genutzt (self-contained,
# ohne externe Abhaengigkeit). Standard: aktiv.
EXPLAIN_FALLBACK_DETAILS = os.environ.get("TICKER_EXPLAIN_FALLBACK_DETAILS", "1").lower() in ("1", "true", "yes", "on")
TICKER_RESET_EXPLANATIONS_ONCE = os.environ.get("TICKER_RESET_EXPLANATIONS_ONCE", "0").lower() in ("1", "true", "yes", "on")
TICKER_RESET_BACKFILL_IMMEDIATELY = os.environ.get(
    "TICKER_RESET_BACKFILL_IMMEDIATELY", "0"
).lower() in ("1", "true", "yes", "on")

# Globale Variable für den aktuellen Ticker-Zustand
_CURRENT_TICKER_TEXT = "Ticker lädt Neuigkeiten..."
_CURRENT_TICKER_EXPLAIN_TEXT = ""
_LAST_UPDATE = 0
_CURRENT_TICKER_ITEMS = []
_SEEN_TOPICS = set()
_SEEN_TOPIC_ORDER = []

# RSS-Feeds (oeffentlich, frei, stabil)
# Das geplante Verhaeltnis im Ticker bleibt 12:3 (ARD:Heise).
FEEDS = [
    {"source": "ard", "url": "https://www.tagesschau.de/xml/rss2/", "limit": 12},
    {"source": "heise", "url": "https://www.heise.de/rss/heise-atom.xml", "limit": 3},
]
SOURCE_LIMITS = {feed["source"]: int(feed["limit"]) for feed in FEEDS}
MAX_STORED_ITEMS = int(os.environ.get("TICKER_MAX_ITEMS", sum(feed["limit"] for feed in FEEDS)))
SEEN_TOPIC_HISTORY = int(os.environ.get("TICKER_SEEN_TOPIC_HISTORY", 200))


def _clean_desc(text):
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.strip().replace("\n", " ").replace("\r", "")
    clean = re.sub(r"\s+", " ", clean)
    # Autor-Signaturen am Ende entfernen: "Von Max Mustermann." / "Von ..."
    clean = re.sub(r"\s+Von\s+[A-ZÄÖÜ][^\.\!\?]*[\.!\?]?$", "", clean)
    if len(clean) > DETAIL_MAX_CHARS:
        clean = clean[: max(0, DETAIL_MAX_CHARS - 3)] + "..."
    return clean


def fetch_rss_items():
    """Holt RSS-Meldungen als strukturierte Items (topic/details)."""
    items = []
    for feed in FEEDS:
        source = (feed.get("source") or "").strip().lower()
        feed_url = (feed.get("url") or "").strip()
        limit = int(feed.get("limit") or 0)
        if not feed_url or limit <= 0:
            continue
        try:
            logging.info(f"Hole {limit} RSS-Meldungen von [{source}]: {feed_url}")
            resp = requests.get(feed_url, timeout=10)
            resp.raise_for_status()
            
            # Simple Parsing, ob RSS2 oder Atom
            root = ET.fromstring(resp.content)
            
            # RSS2 Format
            for item in root.findall(".//item")[:limit]:
                title_elem = item.find("title")
                desc_elem = item.find("description")
                if title_elem is not None and title_elem.text:
                    topic = title_elem.text.strip()
                    details = _clean_desc(desc_elem.text if desc_elem is not None else "")
                    items.append({"topic": topic, "details": details, "source": source})
            
            # Atom Format
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:limit]:
                title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                desc_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
                if title_elem is not None and title_elem.text:
                    topic = title_elem.text.strip()
                    details = _clean_desc(desc_elem.text if desc_elem is not None else "")
                    items.append({"topic": topic, "details": details, "source": source})
                    
        except Exception as e:
            logging.error(f"Fehler beim Holen von {feed_url}: {e}")
    
    return items


def _dedup_items(items):
    seen = set()
    dedup_items = []
    for item in items:
        topic = (item.get("topic") or "").strip()
        if topic and topic not in seen:
            seen.add(topic)
            dedup_items.append(item)
    return dedup_items


def _remember_topics(items):
    for item in items:
        topic = (item.get("topic") or "").strip()
        if not topic or topic in _SEEN_TOPICS:
            continue
        _SEEN_TOPICS.add(topic)
        _SEEN_TOPIC_ORDER.append(topic)

    while len(_SEEN_TOPIC_ORDER) > SEEN_TOPIC_HISTORY:
        expired_topic = _SEEN_TOPIC_ORDER.pop(0)
        _SEEN_TOPICS.discard(expired_topic)


def _enforce_source_ratio(items):
    """Begrenzt die Anzeige pro Quelle auf die geplanten Feed-Kontingente."""
    counts = {source: 0 for source in SOURCE_LIMITS}
    balanced = []

    for item in items:
        source = (item.get("source") or "").strip().lower()
        source_limit = SOURCE_LIMITS.get(source)
        if source_limit is None:
            balanced.append(item)
            continue

        if counts[source] < source_limit:
            counts[source] += 1
            balanced.append(item)

    return balanced[:MAX_STORED_ITEMS]


def _refresh_ticker_strings():
    global _CURRENT_TICKER_TEXT, _CURRENT_TICKER_EXPLAIN_TEXT

    topics = []
    explain_parts = []
    for item in _CURRENT_TICKER_ITEMS:
        topic = (item.get("topic") or "").strip()
        explain = (item.get("explain") or "").strip()
        if topic:
            topics.append(topic)
        # Resilienz-Fallback: fehlt die KI-Erklaerung, nutze die RSS-Details.
        # Das Feld 'explain' bleibt leer, damit der Backfill spaeter echte
        # Erklaerungen nachziehen kann, sobald Ollama wieder erreichbar ist.
        if not explain and EXPLAIN_FALLBACK_DETAILS:
            explain = (item.get("details") or "").strip()
        if explain:
            explain_parts.append(explain)

    _CURRENT_TICKER_TEXT = (" +++ ".join(topics) + " +++") if topics else "Ticker lädt Neuigkeiten..."
    _CURRENT_TICKER_EXPLAIN_TEXT = (" +++ ".join(explain_parts) + " +++") if explain_parts else ""


def _backfill_missing_explanations():
    missing_items = []
    missing_indexes = []

    for idx, item in enumerate(_CURRENT_TICKER_ITEMS):
        if (
            (item.get("topic") or "").strip()
            and not (item.get("explain") or "").strip()
            and not item.get("skip_backfill")
        ):
            missing_items.append(item)
            missing_indexes.append(idx)

    if not missing_items:
        return 0

    explain_parts = explain_topics_with_remote_ollama(missing_items)
    if not explain_parts:
        return 0

    updated = 0
    for idx, explain in zip(missing_indexes, explain_parts):
        if explain:
            _CURRENT_TICKER_ITEMS[idx]["explain"] = explain
            updated += 1

    if updated:
        _refresh_ticker_strings()

    return updated


def _reset_all_explanations():
    """Loescht alle Erklaerungszeilen aus bestehenden Items (für Modellwechsel)."""
    global _CURRENT_TICKER_ITEMS
    count = 0
    for item in _CURRENT_TICKER_ITEMS:
        # Verhalten abhängig von TICKER_RESET_BACKFILL_IMMEDIATELY:
        # - Wenn True: keine Skip-Markierung setzen => anschliessendes Backfill
        #   (so werden die Erklaerungen sofort neu vom LLM erzeugt)
        # - Wenn False: markiere mit skip_backfill, damit alte Eintraege
        #   nicht sofort per Backfill wiederbefuellt werden (Standard)
        if TICKER_RESET_BACKFILL_IMMEDIATELY:
            item.pop("skip_backfill", None)
        else:
            item["skip_backfill"] = True
        if item.get("explain"):
            item["explain"] = ""
            count += 1
    if count:
        _refresh_ticker_strings()
        logging.info(f"[RESET] Alle {count} Erklaerungszeilen geloescht (Modellwechsel). Zweite Tickerzeile ist jetzt leer.")
    return count


def format_raw_topics(items):
    """Liefert direkte Themenzeilen ohne KI-Umformulierung."""
    topics = []
    for item in items:
        topic = (item.get("topic") or "").strip()
        if topic:
            topics.append(topic)
    return " +++ ".join(topics)


def explain_topics_with_remote_ollama(items):
    """Erzeugt eine zweite, optionale Erklaerungszeile via externem Ollama."""
    if not EXPLAIN_REMOTE_ENABLE or not EXPLAIN_REMOTE_URL:
        return []

    def _word_count(text):
        return len([w for w in re.split(r"\s+", (text or "").strip()) if w])

    def _contains_cjk(text):
        # CJK + Kana + Hangul
        return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]", text or ""))

    def _enforce_word_window(line, details):
        words = [w for w in re.split(r"\s+", (line or "").strip()) if w]
        if len(words) < EXPLAIN_MIN_WORDS:
            detail_words = [w for w in re.split(r"\s+", (details or "").strip()) if w]
            needed = EXPLAIN_MIN_WORDS - len(words)
            words.extend(detail_words[:needed])

        if len(words) < EXPLAIN_MIN_WORDS:
            filler = "Weitere bestaetigte Details stehen in der Meldung.".split()
            needed = EXPLAIN_MIN_WORDS - len(words)
            words.extend(filler[:needed])

        if len(words) > EXPLAIN_MAX_WORDS:
            words = words[:EXPLAIN_MAX_WORDS]

        normalized = " ".join(words).strip()
        if normalized and normalized[-1] not in ".!?":
            normalized += "."
        return normalized

    prompt_template = (
        "Du schreibst Erlaeuterungen fuer einen Nachrichtenticker.\n"
        f"Formuliere genau einen sachlichen deutschen Satz mit mindestens {EXPLAIN_MIN_WORDS} bis {EXPLAIN_MAX_WORDS} Woertern.\n"
        "Antworte ausschliesslich auf Deutsch und nur in lateinischer Schrift.\n"
        "Nutze nur die gegebenen Fakten. Keine Spekulation, keine Wertung, keine Einleitung.\n"
        "Verwende keinen Konjunktiv und keine Unsicherheitswoerter (z.B. vermutlich, koennte, moeglicherweise).\n"
        "Lass Autorennamen weg.\n\n"
        "Thema: {topic}\n"
        "Details: {details}\n\n"
        "Antwort nur als Satz:"
    )

    explain_parts = []
    try:
        logging.info(f"Sende {len(items)} Meldungen an Ubuntu-Ollama fuer Erklaerungszeile...")
        for idx, item in enumerate(items):
            topic = (item.get("topic") or "").strip()
            details = (item.get("details") or "").strip() or "Keine weiteren Details."
            prompt = prompt_template.format(topic=topic, details=details)

            payload = {
                "model": EXPLAIN_REMOTE_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": EXPLAIN_TEMPERATURE,
                    "top_p": EXPLAIN_TOP_P,
                    "num_predict": 170,
                },
            }
            if idx == len(items) - 1:
                payload["keep_alive"] = 0

            resp = requests.post(EXPLAIN_REMOTE_URL, json=payload, timeout=EXPLAIN_TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()

            line = (data.get("response") or "").strip()
            line = re.sub(r"\s*[\n\+]+\s*", " ", line)
            line = re.sub(r"\s+", " ", line).strip()

            # Einmalige Nachsteuerung, falls die Wortzahl ausserhalb des Zielkorridors liegt.
            wc = _word_count(line)
            if line and (wc < EXPLAIN_MIN_WORDS or wc > EXPLAIN_MAX_WORDS or _contains_cjk(line)):
                retry_prompt = (
                    prompt
                    + "\n\n"
                    + f"KORREKTUR: Deine Antwort muss zwischen {EXPLAIN_MIN_WORDS} und {EXPLAIN_MAX_WORDS} Woertern liegen. "
                    + "Antworte jetzt neu mit genau einem Satz und nur Fakten aus Thema und Details. "
                    + "WICHTIG: NUR Deutsch, NUR lateinische Schrift, keine chinesischen Zeichen."
                )
                retry_payload = dict(payload)
                retry_payload["prompt"] = retry_prompt
                resp_retry = requests.post(EXPLAIN_REMOTE_URL, json=retry_payload, timeout=EXPLAIN_TIMEOUT_SEC)
                resp_retry.raise_for_status()
                retry_data = resp_retry.json()
                retry_line = (retry_data.get("response") or "").strip()
                retry_line = re.sub(r"\s*[\n\+]+\s*", " ", retry_line)
                retry_line = re.sub(r"\s+", " ", retry_line).strip()
                if retry_line:
                    line = retry_line

            if line:
                # Harte Absicherung: Falls trotzdem CJK-Zeichen enthalten sind,
                # nehmen wir deterministisch Topic+Details (deutscher Feed) als Grundlage.
                if _contains_cjk(line):
                    line = f"{topic}. {details}".strip()
                line = _enforce_word_window(line, details)
                explain_parts.append(line)

        return explain_parts
    except requests.exceptions.Timeout as te:
        # Timeout kann wichtig sein beim Modell-Experiment (mi24ins8)
        logging.warning(f"Ollama TIMEOUT nach {EXPLAIN_TIMEOUT_SEC}s (Modell: {EXPLAIN_REMOTE_MODEL}). "
                       f"Erklaerungszeile bleibt leer. Ggf. Rollback noetig: siehe .infra.local")
        return []
    except requests.exceptions.RequestException as req_exc:
        logging.warning(f"Ollama HTTP-Fehler: {req_exc}")
        return []
    except Exception as e:
        # Alle anderen Fehler (JSON-Parse, etc.)
        logging.warning(f"Erklaerungszeile deaktiviert (Ubuntu-Ollama nicht erreichbar oder Fehler): {type(e).__name__}: {e}")
        return []

def background_updater():
    """Hintergrund-Thread, der zyklisch neue Meldungen holt."""
    global _CURRENT_TICKER_ITEMS, _LAST_UPDATE
    
    # Beim Start prüfen: falls Reset-Flag gesetzt, alle Erklaerungen loeschen
    if TICKER_RESET_EXPLANATIONS_ONCE:
        _reset_all_explanations()
        logging.info(f"[INIT] TICKER_RESET_EXPLANATIONS_ONCE war gesetzt. Zweite Zeile wird jetzt vom neuen Modell ({EXPLAIN_REMOTE_MODEL}) gefüllt.")
        if TICKER_RESET_BACKFILL_IMMEDIATELY:
            try:
                backfilled = _backfill_missing_explanations()
                if backfilled:
                    _LAST_UPDATE = time.time()
                    logging.info(f"[INIT] Nach Reset {backfilled} Erklaerungen sofort nachgefüllt.")
            except Exception as e:
                logging.warning(f"[INIT] Sofortiges Backfill fehlgeschlagen: {type(e).__name__}: {e}")
    
    while True:
        try:
            items = fetch_rss_items()
            if items:
                dedup_items = _dedup_items(items)
                backfilled = _backfill_missing_explanations()
                if backfilled:
                    _LAST_UPDATE = time.time()
                    logging.info(f"Ticker-Erklaerungen nachgezogen ({backfilled} bestehende Meldungen).")

                new_items = []
                for item in dedup_items:
                    topic = (item.get("topic") or "").strip()
                    if topic and topic not in _SEEN_TOPICS:
                        new_items.append(item)

                if new_items:
                    explain_parts = explain_topics_with_remote_ollama(new_items)
                    new_entries = []
                    for idx, item in enumerate(new_items):
                        new_entries.append({
                            "topic": (item.get("topic") or "").strip(),
                            "details": (item.get("details") or "").strip(),
                            "source": (item.get("source") or "").strip().lower(),
                            "explain": explain_parts[idx] if idx < len(explain_parts) else "",
                            "skip_backfill": False,
                        })

                    _CURRENT_TICKER_ITEMS = _enforce_source_ratio(new_entries + _CURRENT_TICKER_ITEMS)
                    _remember_topics(new_items)
                    _refresh_ticker_strings()
                    _LAST_UPDATE = time.time()
                    mode = "RAW+EXPLAIN" if _CURRENT_TICKER_EXPLAIN_TEXT else "RAW"
                    logging.info(f"Ticker erweitert ({len(new_items)} neue Meldungen, gesamt {len(_CURRENT_TICKER_ITEMS)}, Modus={mode})")
                else:
                    logging.info("Keine neuen Ticker-Meldungen gefunden; bestehender Lauftext bleibt unveraendert.")
        except Exception as e:
            logging.error(f"Hintergrund-Updater Fehler: {e}")
            
        time.sleep(UPDATE_INTERVAL_SEC)

class TickerRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ticker":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            # CORS erlauben (Sicher, da nur Lesezugriff auf öffentliche News)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            resp = {
                "text": _CURRENT_TICKER_TEXT,
                "explain_text": _CURRENT_TICKER_EXPLAIN_TEXT,
                "last_update": _LAST_UPDATE,
                "status": "ok"
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            
    def log_message(self, format, *args):
        # Unterdrücke Access-Logs für Ticker-Abfragen, um Logs sauber zu halten
        pass

def start_server():
    server = HTTPServer(("0.0.0.0", PORT), TickerRequestHandler)
    logging.info(f"Ticker-Microservice gestartet auf Port {PORT}")
    
    updater_thread = threading.Thread(target=background_updater, daemon=True)
    updater_thread.start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server wird beendet...")
        server.server_close()

if __name__ == "__main__":
    start_server()
