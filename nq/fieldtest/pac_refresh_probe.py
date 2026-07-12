"""nq.fieldtest.pac_refresh_probe — Phase 0: PAC4200-Refresh-Raten messen.

Read-only. Pollt den **verifizierten** Messwertblock (RMS/Leistung/PF/f + THD)
in engem Takt und misst, **wie oft sich die Registerwerte real ändern**.
Erkenntnisziel: reale interne Aktualisierungsrate je Größe → legt die
endgültigen Poll-Raten für den Collector (Phase 1) fest.

**Speichert nichts** (kein DB-/SD-Write). Ausgabe nur nach stdout.

Start (kurzer Smoke-Test):   python3 -m nq.fieldtest.pac_refresh_probe --duration-s 60
Feldtest (48 h auf Tech):    python3 -m nq.fieldtest.pac_refresh_probe --duration-h 48 --interval-ms 250

Siehe .github/prompts/nq-0-fieldtest.prompt.md und doc/netzqualitaet/MESSTECHNIK.md.
"""
from __future__ import annotations

import argparse
import signal
import time

import config
from collector.modbus_client import RawModbusClient, read_registers_safe
from nq.pac_live import FLOAT_MAP, _FLOAT_READ_START, _FLOAT_READ_COUNT, _f32

# Gruppierung der verifizierten Größen (Slow/Harmonik-Adressen noch unbestätigt)
FAST_KEYS = [k for k in FLOAT_MAP if k.split("_")[0] in
             {"U", "I", "S", "P", "Q", "PF", "Uavg", "Iavg", "FREQ", "Unbal"}]
MEDIUM_KEYS = [k for k in FLOAT_MAP if k.startswith("THD")]

_STOP = False


def _handle_sigint(_sig, _frm):
    global _STOP
    _STOP = True


def probe(host: str, port: int, unit_id: int, interval_ms: int, duration_s: float,
          report_every_s: float = 15.0) -> None:
    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    last: dict[str, float | None] = {}
    changes: dict[str, int] = {k: 0 for k in FLOAT_MAP}
    reads: dict[str, int] = {k: 0 for k in FLOAT_MAP}
    last_change_ts: dict[str, float] = {}
    intervals: dict[str, list] = {k: [] for k in FLOAT_MAP}

    interval = interval_ms / 1000.0
    t_start = time.time()
    t_report = t_start + report_every_s
    polls = 0
    errors = 0

    print(f"[probe] host={host} interval={interval_ms}ms dauer={duration_s:.0f}s "
          f"(read-only, kein Speichern)\n")

    while not _STOP and (time.time() - t_start) < duration_s:
        loop_t = time.time()
        client = RawModbusClient(host, port, timeout=2.0)
        if client.connect():
            regs = read_registers_safe(client, _FLOAT_READ_START, _FLOAT_READ_COUNT, unit_id)
            client.close()
            if regs:
                polls += 1
                now = time.time()
                for name, (addr, _unit) in FLOAT_MAP.items():
                    v = _f32(regs, _FLOAT_READ_START, addr)
                    if v is None:
                        continue
                    reads[name] += 1
                    if name in last and v != last[name]:
                        changes[name] += 1
                        if name in last_change_ts:
                            intervals[name].append(now - last_change_ts[name])
                        last_change_ts[name] = now
                    elif name not in last:
                        last_change_ts[name] = now
                    last[name] = v
            else:
                errors += 1
        else:
            errors += 1

        if time.time() >= t_report:
            _report(polls, errors, reads, changes, intervals)
            t_report = time.time() + report_every_s

        sleep = interval - (time.time() - loop_t)
        if sleep > 0:
            time.sleep(sleep)

    print("\n===== ABSCHLUSS =====")
    _report(polls, errors, reads, changes, intervals, final=True)


def _median(xs: list) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _report(polls, errors, reads, changes, intervals, final=False):
    def grp(keys, title):
        print(f"  [{title}]")
        for k in keys:
            r = reads.get(k, 0)
            ch = changes.get(k, 0)
            frac = (ch / r * 100) if r else 0.0
            med = _median(intervals.get(k, []))
            print(f"    {k:<9} reads={r:<5} changes={ch:<5} "
                  f"changed={frac:4.0f}%  dt_med={med:5.2f}s")
    print(f"--- polls={polls} errors={errors} "
          f"({'FINAL' if final else 'zwischenstand'}) ---")
    grp(FAST_KEYS, "Fast (RMS/Leistung/PF/f)")
    grp(MEDIUM_KEYS, "Medium (THD)")
    print()


def main() -> int:
    import sys
    try:
        # line_buffering=True: periodische Reports werden auch bei Umleitung in
        # eine Datei (nohup/tee) sofort geschrieben, nicht block-gepuffert.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="PAC4200 Refresh-Raten-Feldtest (read-only)")
    ap.add_argument("--host", default=getattr(config, "PAC_IP", "192.0.2.111"))
    ap.add_argument("--port", type=int, default=getattr(config, "PAC_MODBUS_PORT", 502))
    ap.add_argument("--unit-id", type=int, default=getattr(config, "PAC_UNIT_ID", 1))
    ap.add_argument("--interval-ms", type=int, default=250)
    ap.add_argument("--duration-s", type=float, default=None)
    ap.add_argument("--duration-h", type=float, default=None)
    ap.add_argument("--report-every-s", type=float, default=15.0)
    a = ap.parse_args()
    dur = a.duration_s if a.duration_s is not None else \
        (a.duration_h * 3600 if a.duration_h is not None else 60.0)
    probe(a.host, a.port, a.unit_id, a.interval_ms, dur, a.report_every_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
