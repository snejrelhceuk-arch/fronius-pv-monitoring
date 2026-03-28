#!/usr/bin/env python3
"""
Energy Data Validator
Validiert Konsistenz zwischen Deltas und Absolutwerten
Erkennt Lücken und kumulative Abweichungen

Prüfungen:
1. Delta-Konsistenz: SUM(deltas) == (end - start) für jedes Intervall
2. Lücken-Detektion: Fehlende Zeitstempel in Aggregationen
3. Checkpoint-Abgleich: Langfrist-Bilanz mit Checkpoints
4. Gap-Filling-Report: Rekonstruierbare Lücken identifizieren

Datum: 07.02.2026
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import config

DB_PATH = config.DB_PATH

class EnergyValidator:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.errors = []
        self.warnings = []
        self.stats = defaultdict(int)
    
    def validate_interval_consistency(self, table_name, interval_seconds):
        """Prüft ob start/end Werte mit delta übereinstimmen"""
        print(f"\n[DATA] Validiere {table_name} (Intervall: {interval_seconds}s)...")
        
        cur = self.conn.cursor()
        
        # Prüfe ob die Spalten existieren
        cur.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cur.fetchall()]
        
        if 'W_AC_Inv_start' not in columns:
            print(f"[SKIP]  Keine Absolut-Spalten in {table_name} - überspringe")
            return
        
        # Baue SELECT dynamisch basierend auf verfügbaren Spalten
        select_parts = ["ts"]
        check_fields = []
        
        # W_AC_Inv / W_PV_total (je nach Tabelle)
        # data_1min: W_AC_Inv_delta (AC-Counter), data_15min/hourly/monthly: W_PV_total_delta
        delta_col = None
        if 'W_AC_Inv_delta' in columns and 'W_AC_Inv_start' in columns and 'W_AC_Inv_end' in columns:
            delta_col = 'W_AC_Inv_delta'
            select_parts.extend(['W_AC_Inv_delta', 'W_AC_Inv_start', 'W_AC_Inv_end'])
            check_fields.append(('W_AC_Inv', len(select_parts)-3, len(select_parts)-2, len(select_parts)-1))
        elif 'W_PV_total_delta' in columns and 'W_AC_Inv_start' in columns and 'W_AC_Inv_end' in columns:
            delta_col = 'W_PV_total_delta'
            select_parts.extend(['W_PV_total_delta', 'W_AC_Inv_start', 'W_AC_Inv_end'])
            check_fields.append(('W_PV_total', len(select_parts)-3, len(select_parts)-2, len(select_parts)-1))
        
        # W_DC1 (optional)
        if 'W_DC1_delta' in columns and 'W_DC1_start' in columns and 'W_DC1_end' in columns:
            select_parts.extend(['W_DC1_delta', 'W_DC1_start', 'W_DC1_end'])
            check_fields.append(('W_DC1', len(select_parts)-3, len(select_parts)-2, len(select_parts)-1))
        
        # W_Exp_Netz
        if 'W_Exp_Netz_delta' in columns and 'W_Exp_Netz_start' in columns and 'W_Exp_Netz_end' in columns:
            select_parts.extend(['W_Exp_Netz_delta', 'W_Exp_Netz_start', 'W_Exp_Netz_end'])
            check_fields.append(('W_Exp_Netz', len(select_parts)-3, len(select_parts)-2, len(select_parts)-1))
        
        if not check_fields:
            print(f"[SKIP]  Keine vollständigen delta/start/end Tripel in {table_name}")
            return
        
        # Hole Daten
        select_sql = f"SELECT {', '.join(select_parts)} FROM {table_name} WHERE W_AC_Inv_start IS NOT NULL ORDER BY ts DESC LIMIT 100"
        cur.execute(select_sql)
        
        rows = cur.fetchall()
        if not rows:
            print(f"[SKIP]  Keine Daten mit Absolutwerten in {table_name}")
            return
        
        inconsistencies = []
        for row in rows:
            ts = row[0]
            dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
            
            # Prüfe alle verfügbaren Felder
            for field_name, delta_idx, start_idx, end_idx in check_fields:
                delta = row[delta_idx] or 0
                calc = (row[end_idx] or 0) - (row[start_idx] or 0) if row[start_idx] and row[end_idx] else None
                
                if calc is not None and abs(delta - calc) > 1.0:  # 1 Wh Toleranz
                    inconsistencies.append(f"{dt}: {field_name} delta={delta:.0f} vs calc={calc:.0f} (Δ={abs(delta-calc):.1f}Wh)")
        
        if inconsistencies:
            print(f"[WARN]  {len(inconsistencies)} Inkonsistenzen gefunden:")
            for inc in inconsistencies[:5]:  # Zeige nur erste 5
                print(f"   {inc}")
            if len(inconsistencies) > 5:
                print(f"   ... und {len(inconsistencies)-5} weitere")
            self.warnings.extend(inconsistencies)
        else:
            print(f"[OK] Alle geprüften Intervalle konsistent ({len(rows)} Einträge)")
        
        self.stats[f'{table_name}_checked'] = len(rows)
        self.stats[f'{table_name}_inconsistent'] = len(inconsistencies)
    
    def detect_gaps(self, table_name, interval_seconds, max_age_days=None):
        """Erkennt Lücken in Zeitreihen"""
        print(f"\n[SEARCH] Suche Lücken in {table_name}...")
        
        cur = self.conn.cursor()
        
        # Zeitfenster festlegen
        if max_age_days:
            earliest_ts = (datetime.now() - timedelta(days=max_age_days)).timestamp()
            cur.execute(f"SELECT ts FROM {table_name} WHERE ts >= ? ORDER BY ts ASC", (earliest_ts,))
        else:
            cur.execute(f"SELECT ts FROM {table_name} ORDER BY ts ASC")
        
        timestamps = [row[0] for row in cur.fetchall()]
        
        if len(timestamps) < 2:
            print(f"[SKIP]  Zu wenig Daten in {table_name}")
            return
        
        gaps = []
        for i in range(len(timestamps) - 1):
            expected_next = timestamps[i] + interval_seconds
            actual_next = timestamps[i + 1]
            gap_seconds = actual_next - expected_next
            
            # Lücke nur melden wenn > Intervall (erlaubt kleine Abweichungen)
            if gap_seconds > interval_seconds:
                gap_start = datetime.fromtimestamp(timestamps[i])
                gap_end = datetime.fromtimestamp(timestamps[i+1])
                gap_duration = actual_next - timestamps[i]
                missing_intervals = int(gap_duration / interval_seconds) - 1
                
                gaps.append({
                    'start': gap_start,
                    'end': gap_end,
                    'duration_hours': gap_duration / 3600,
                    'missing_intervals': missing_intervals
                })
        
        if gaps:
            print(f"[WARN]  {len(gaps)} Lücken gefunden:")
            for gap in gaps[:10]:  # Zeige max 10
                print(f"   {gap['start'].strftime('%Y-%m-%d %H:%M')} -> {gap['end'].strftime('%H:%M')}: "
                      f"{gap['duration_hours']:.1f}h ({gap['missing_intervals']} fehlende Intervalle)")
            if len(gaps) > 10:
                print(f"   ... und {len(gaps)-10} weitere Lücken")
            self.warnings.extend([f"Gap in {table_name}: {g['start']} - {g['end']}" for g in gaps])
        else:
            print("[OK] Keine Lücken gefunden")
        
        self.stats[f'{table_name}_gaps'] = len(gaps)
    
    def validate_monthly_with_checkpoints(self):
        """Validiert Monats-Summen gegen Checkpoint-Differenzen"""
        print("\n[CHECK] Validiere Monats-Summen mit Checkpoints...")
        
        cur = self.conn.cursor()
        
        # Hole alle Monats-Checkpoints
        cur.execute("""
            SELECT ts, W_AC_Inv, W_Exp_Netz, W_Imp_Netz, source
            FROM energy_checkpoints
            WHERE checkpoint_type = 'monthly'
            ORDER BY ts ASC
        """)
        
        checkpoints = cur.fetchall()
        
        if len(checkpoints) < 2:
            print("[SKIP]  Zu wenig Checkpoints für Validierung (min. 2 benötigt)")
            return
        
        print(f"[INFO] {len(checkpoints)} Monats-Checkpoints gefunden")
        
        # Vergleiche aufeinanderfolgende Monate
        for i in range(len(checkpoints) - 1):
            ts_start, w_ac_start, w_exp_start, w_imp_start, source_start = checkpoints[i]
            ts_end, w_ac_end, w_exp_end, w_imp_end, source_end = checkpoints[i+1]
            
            dt_start = datetime.fromtimestamp(ts_start)
            dt_end = datetime.fromtimestamp(ts_end)
            month_str = dt_start.strftime('%Y-%m')
            
            # Berechne Delta aus Checkpoints
            checkpoint_delta_ac = w_ac_end - w_ac_start
            checkpoint_delta_exp = w_exp_end - w_exp_start
            checkpoint_delta_imp = w_imp_end - w_imp_start
            
            # Hole Summe aus data_monthly
            cur.execute("""
                SELECT SUM(W_PV_total_delta), SUM(W_Exp_Netz_delta), SUM(W_Imp_Netz_delta)
                FROM data_monthly
                WHERE ts >= ? AND ts < ?
            """, (ts_start, ts_end))
            
            monthly_sum = cur.fetchone()
            if monthly_sum and monthly_sum[0]:
                monthly_ac = monthly_sum[0] or 0
                monthly_exp = monthly_sum[1] or 0
                monthly_imp = monthly_sum[2] or 0
                
                diff_ac = abs(checkpoint_delta_ac - monthly_ac)
                
                if diff_ac > 100:  # Toleranz 100 Wh
                    print(f"[WARN]  {month_str}: AC Abweichung = {diff_ac:.0f} Wh "
                          f"(Checkpoints: {checkpoint_delta_ac:.0f}, Monthly: {monthly_ac:.0f})")
                    self.warnings.append(f"Monthly mismatch {month_str}: {diff_ac:.0f}Wh")
                else:
                    print(f"[OK] {month_str}: Konsistent (Δ={diff_ac:.0f}Wh)")
    
    def generate_report(self):
        """Erstellt Validierungs-Report"""
        print("\n" + "="*70)
        print("[INFO] VALIDIERUNGS-REPORT")
        print("="*70)
        
        print("\n[OK] Geprüfte Intervalle:")
        for key, value in self.stats.items():
            if '_checked' in key:
                table = key.replace('_checked', '')
                inconsistent = self.stats.get(f'{table}_inconsistent', 0)
                gaps = self.stats.get(f'{table}_gaps', 0)
                print(f"   {table:20s}: {value:5d} Einträge, {inconsistent:3d} Inkonsistenzen, {gaps:3d} Lücken")
        
        if self.errors:
            print(f"\n[ERROR] FEHLER ({len(self.errors)}):")
            for err in self.errors[:10]:
                print(f"   {err}")
        
        if self.warnings:
            print(f"\n[WARN]  WARNUNGEN ({len(self.warnings)}):")
            for warn in self.warnings[:10]:
                print(f"   {warn}")
            if len(self.warnings) > 10:
                print(f"   ... und {len(self.warnings)-10} weitere")
        
        if not self.errors and not self.warnings:
            print("\n[OK] Alle Validierungen erfolgreich - keine Probleme gefunden!")
        
        print("="*70)
    
    def run_full_validation(self):
        """Führt alle Validierungen durch"""
        print("[SEARCH] STARTE ENERGIE-DATEN-VALIDIERUNG")
        print("="*70)
        
        # 1. Intervall-Konsistenz
        self.validate_interval_consistency('data_1min', 60)
        self.validate_interval_consistency('data_15min', 900)
        self.validate_interval_consistency('hourly_data', 3600)
        self.validate_interval_consistency('daily_data', 86400)
        
        # 2. Lücken-Detektion
        self.detect_gaps('data_1min', 60, max_age_days=7)
        self.detect_gaps('data_15min', 900, max_age_days=30)
        self.detect_gaps('daily_data', 86400)
        
        # 3. Checkpoint-Validierung
        self.validate_monthly_with_checkpoints()
        
        # 4. Report
        self.generate_report()
        
        self.conn.close()

if __name__ == '__main__':
    validator = EnergyValidator()
    validator.run_full_validation()
