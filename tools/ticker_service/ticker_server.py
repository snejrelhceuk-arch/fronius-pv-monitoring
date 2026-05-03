import re
import os
import time
import json
import logging
import threading
import requests
import xml.etree.ElementTree as ET
from urllib.error import URLError
from http.server import BaseHTTPRequestHandler, HTTPServer

# Logging-Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Konfiguration
PORT = int(os.environ.get("TICKER_PORT", 8050))
UPDATE_INTERVAL_SEC = 15 * 60  # 15 Minuten
DETAIL_MAX_CHARS = int(os.environ.get("TICKER_DETAIL_MAX_CHARS", 256))
# Optionale zweite Zeile: Erlaeuterungen vom externen Ubuntu-Ollama.
EXPLAIN_REMOTE_ENABLE = os.environ.get("TICKER_EXPLAIN_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EXPLAIN_REMOTE_URL = os.environ.get("TICKER_EXPLAIN_OLLAMA_URL", "http://192.0.2.116:11434/api/generate")
EXPLAIN_REMOTE_MODEL = os.environ.get("TICKER_EXPLAIN_MODEL", "qwen2.5:7b")
EXPLAIN_TIMEOUT_SEC = int(os.environ.get("TICKER_EXPLAIN_TIMEOUT_SEC", 20))
EXPLAIN_TEMPERATURE = float(os.environ.get("TICKER_EXPLAIN_TEMPERATURE", 0.12))
EXPLAIN_TOP_P = float(os.environ.get("TICKER_EXPLAIN_TOP_P", 0.6))
EXPLAIN_MIN_WORDS = int(os.environ.get("TICKER_EXPLAIN_MIN_WORDS", 20))
EXPLAIN_MAX_WORDS = int(os.environ.get("TICKER_EXPLAIN_MAX_WORDS", 35))

# Globale Variable für den aktuellen Ticker-Zustand
_CURRENT_TICKER_TEXT = "Ticker lädt Neuigkeiten..."
_CURRENT_TICKER_EXPLAIN_TEXT = ""
_LAST_UPDATE = 0

# RSS-Feeds (Öffentlich, frei, stabil) - Format: (URL, Max_Anzahl)
FEEDS = [
    ("https://www.tagesschau.de/xml/rss2/", 12),
    ("https://www.heise.de/rss/heise-atom.xml", 3)
]


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
    for feed_url, limit in FEEDS:
        try:
            logging.info(f"Hole {limit} RSS-Meldungen von: {feed_url}")
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
                    items.append({"topic": topic, "details": details})
            
            # Atom Format
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:limit]:
                title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                desc_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
                if title_elem is not None and title_elem.text:
                    topic = title_elem.text.strip()
                    details = _clean_desc(desc_elem.text if desc_elem is not None else "")
                    items.append({"topic": topic, "details": details})
                    
        except Exception as e:
            logging.error(f"Fehler beim Holen von {feed_url}: {e}")
    
    return items


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
        return ""

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

        return " +++ ".join(explain_parts)
    except Exception as e:
        # Gewuenschtes Verhalten fuer Experiment: Zeile bleibt leer, wenn Ubuntu/Ollama aus ist.
        logging.warning(f"Erklaerungszeile deaktiviert (Ubuntu-Ollama nicht erreichbar): {e}")
        return ""

def background_updater():
    """Hintergrund-Thread, der zyklisch neue Meldungen holt."""
    global _CURRENT_TICKER_TEXT, _CURRENT_TICKER_EXPLAIN_TEXT, _LAST_UPDATE
    
    while True:
        try:
            items = fetch_rss_items()
            if items:
                # Deduplizieren
                seen = set()
                dedup_items = []
                for item in items:
                    topic = (item.get("topic") or "").strip()
                    if topic and topic not in seen:
                        seen.add(topic)
                        dedup_items.append(item)

                new_text = format_raw_topics(dedup_items)
                explain_text = explain_topics_with_remote_ollama(dedup_items)
                
                if new_text:
                    _CURRENT_TICKER_TEXT = new_text + " +++"
                    _CURRENT_TICKER_EXPLAIN_TEXT = (explain_text + " +++") if explain_text else ""
                    _LAST_UPDATE = time.time()
                    mode = "RAW+EXPLAIN" if _CURRENT_TICKER_EXPLAIN_TEXT else "RAW"
                    logging.info(f"Ticker erfolgreich aktualisiert ({len(dedup_items)} Quellen, Modus={mode})")
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
