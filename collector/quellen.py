"""
modbus_quellen.py
"""
import config

# Konfiguration (aus zentraler config.py)
IP_ADDRESS = config.INVERTER_IP
PORT = config.MODBUS_PORT

# Unit IDs (Topologie)
INVERTER = 1
PRIM_SM_F1 = 2
SEC_SM_F2 = 3
SEC_SM_WP = 4
SEC_SM_F3 = 6

# Definitionen der Modelle
# Format: ID -> Liste von Feldern
# Jedes Feld: {'field': 'Name', 'type': 'Datentyp', 'offset': 0-basierter Index, 'notes': 'Beschreibung', ...}

MODELS = {
    # --- Model 1: Common ---
    1: [
        {'field': 'Mn', 'type': 'string', 'offset': 0, 'length': 16, 'notes': 'Manufacturer'}, # speichern
        {'field': 'Md', 'type': 'string', 'offset': 16, 'length': 16, 'notes': 'Device'}, # speichern
        {'field': 'Opt', 'type': 'string', 'offset': 32, 'length': 8, 'notes': 'Options'},
        {'field': 'Vr', 'type': 'string', 'offset': 40, 'length': 8, 'notes': 'SW version of inverter'},
        {'field': 'SN', 'type': 'string', 'offset': 48, 'length': 16, 'notes': 'Serialnumber of the inverter'},
        {'field': 'DA', 'type': 'uint16', 'offset': 64, 'notes': 'Modbus Device Address'},
    ],

    # --- Model 103: Inverter (Three Phase Integer) ---
    # CSV lists ID 101, 103. Using 103 as key.
    103: [
        {'field': 'A', 'type': 'uint16', 'offset': 0, 'units': 'A', 'scale': 'A_SF', 'notes': 'AC Current'}, # speichern
        {'field': 'AphA', 'type': 'uint16', 'offset': 1, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase A Current'}, # speichern
        {'field': 'AphB', 'type': 'uint16', 'offset': 2, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase B Current'}, # speichern
        {'field': 'AphC', 'type': 'uint16', 'offset': 3, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase C Current'}, # speichern
        {'field': 'A_SF', 'type': 'sunssf', 'offset': 4, 'notes': 'Scale factor'},
        {'field': 'PPVphAB', 'type': 'uint16', 'offset': 5, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage AB'}, # speichern
        {'field': 'PPVphBC', 'type': 'uint16', 'offset': 6, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage BC'}, # speichern
        {'field': 'PPVphCA', 'type': 'uint16', 'offset': 7, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage CA'}, # speichern
        {'field': 'PhVphA', 'type': 'uint16', 'offset': 8, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage AN'}, # speichern
        {'field': 'PhVphB', 'type': 'uint16', 'offset': 9, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage BN'}, # speichern
        {'field': 'PhVphC', 'type': 'uint16', 'offset': 10, 'units': 'V', 'scale': 'V_SF', 'notes': 'Phase Voltage CN'}, # speichern
        {'field': 'V_SF', 'type': 'sunssf', 'offset': 11, 'notes': 'Scale factor'},
        {'field': 'W', 'type': 'int16', 'offset': 12, 'units': 'W', 'scale': 'W_SF', 'notes': 'AC Power'}, # speichern
        {'field': 'W_SF', 'type': 'sunssf', 'offset': 13, 'notes': 'Scale factor'},
        {'field': 'Hz', 'type': 'uint16', 'offset': 14, 'units': 'Hz', 'scale': 'Hz_SF', 'notes': 'Line Frequency'},
        {'field': 'Hz_SF', 'type': 'sunssf', 'offset': 15, 'notes': 'Scale factor'},
        {'field': 'VA', 'type': 'int16', 'offset': 16, 'units': 'VA', 'scale': 'VA_SF', 'notes': 'AC Apparent Power'}, # speichern
        {'field': 'VA_SF', 'type': 'sunssf', 'offset': 17, 'notes': 'Scale factor'},
        {'field': 'VAr', 'type': 'int16', 'offset': 18, 'units': 'var', 'scale': 'VAr_SF', 'notes': 'AC Reactive Power'}, # speichern
        {'field': 'VAr_SF', 'type': 'sunssf', 'offset': 19, 'notes': 'Scale factor'},
        {'field': 'PF', 'type': 'int16', 'offset': 20, 'units': 'Pct', 'scale': 'PF_SF', 'notes': 'AC Power Factor'}, # speichern
        {'field': 'PF_SF', 'type': 'sunssf', 'offset': 21, 'notes': 'Scale factor'},
        {'field': 'WH', 'type': 'acc32', 'offset': 22, 'units': 'Wh', 'scale': 'WH_SF', 'notes': 'AC Energy'}, # speichern
        {'field': 'WH_SF', 'type': 'sunssf', 'offset': 24, 'notes': 'Scale factor'},
        {'field': 'DCA', 'type': 'uint16', 'offset': 25, 'units': 'A', 'scale': 'DCA_SF', 'notes': 'DC Current'}, # speichern
        {'field': 'DCA_SF', 'type': 'sunssf', 'offset': 26, 'notes': 'Scale factor'},
        {'field': 'DCV', 'type': 'uint16', 'offset': 27, 'units': 'V', 'scale': 'DCV_SF', 'notes': 'DC Voltage'}, # speichern
        {'field': 'DCV_SF', 'type': 'sunssf', 'offset': 28, 'notes': 'Scale factor'},
        {'field': 'DCW', 'type': 'int16', 'offset': 29, 'units': 'W', 'scale': 'DCW_SF', 'notes': 'DC Power'}, # speichern
        {'field': 'DCW_SF', 'type': 'sunssf', 'offset': 30, 'notes': 'Scale factor'},
        {'field': 'TmpCab', 'type': 'int16', 'offset': 31, 'units': 'C', 'scale': 'Tmp_SF', 'notes': 'Cabinet Temperature'}, # speichern
        {'field': 'TmpSnk', 'type': 'int16', 'offset': 32, 'units': 'C', 'scale': 'Tmp_SF', 'notes': 'Heat Sink Temperature'}, # speichern
        {'field': 'TmpTrns', 'type': 'int16', 'offset': 33, 'units': 'C', 'scale': 'Tmp_SF', 'notes': 'Transformer Temperature'}, # speichern
        {'field': 'TmpOt', 'type': 'int16', 'offset': 34, 'units': 'C', 'scale': 'Tmp_SF', 'notes': 'Other Temperature'}, # speichern
        {'field': 'Tmp_SF', 'type': 'sunssf', 'offset': 35, 'notes': 'Scale factor'},
        {'field': 'St', 'type': 'enum16', 'offset': 36, 'notes': 'Operating state'},
        {'field': 'StVnd', 'type': 'enum16', 'offset': 37, 'notes': 'Vendor specific operating state code'},
        {'field': 'Evt1', 'type': 'bitfield32', 'offset': 38, 'notes': 'Event fields'},
        {'field': 'Evt2', 'type': 'bitfield32', 'offset': 40, 'notes': 'Reserved for future use'},
        {'field': 'EvtVnd1', 'type': 'bitfield32', 'offset': 42, 'notes': 'Vendor defined events'},
        {'field': 'EvtVnd2', 'type': 'bitfield32', 'offset': 44, 'notes': 'Vendor defined events'},
        {'field': 'EvtVnd3', 'type': 'bitfield32', 'offset': 46, 'notes': 'Vendor defined events'},
        {'field': 'EvtVnd4', 'type': 'bitfield32', 'offset': 48, 'notes': 'Vendor defined events'},
    ],

    # --- Model 120: Nameplate ---
    120: [
        {'field': 'DERTyp', 'type': 'enum16', 'offset': 0, 'notes': 'Type of DER device'},
        {'field': 'WRtg', 'type': 'uint16', 'offset': 1, 'units': 'W', 'scale': 'WRtg_SF', 'notes': 'Continuous power output capability'},
        {'field': 'WRtg_SF', 'type': 'sunssf', 'offset': 2, 'notes': 'Scale factor'},
        {'field': 'VARtg', 'type': 'uint16', 'offset': 3, 'units': 'VA', 'scale': 'VARtg_SF', 'notes': 'Continuous Volt-Ampere capability'},
        {'field': 'VARtg_SF', 'type': 'sunssf', 'offset': 4, 'notes': 'Scale factor'},
        {'field': 'VArRtgQ1', 'type': 'int16', 'offset': 5, 'units': 'var', 'scale': 'VArRtg_SF', 'notes': 'Continuous VAR capability Q1'},
        {'field': 'VArRtgQ2', 'type': 'int16', 'offset': 6, 'units': 'var', 'scale': 'VArRtg_SF', 'notes': 'Continuous VAR capability Q2'},
        {'field': 'VArRtgQ3', 'type': 'int16', 'offset': 7, 'units': 'var', 'scale': 'VArRtg_SF', 'notes': 'Continuous VAR capability Q3'},
        {'field': 'VArRtgQ4', 'type': 'int16', 'offset': 8, 'units': 'var', 'scale': 'VArRtg_SF', 'notes': 'Continuous VAR capability Q4'},
        {'field': 'VArRtg_SF', 'type': 'sunssf', 'offset': 9, 'notes': 'Scale factor'},
        {'field': 'ARtg', 'type': 'uint16', 'offset': 10, 'units': 'A', 'scale': 'ARtg_SF', 'notes': 'Maximum RMS AC current level'},
        {'field': 'ARtg_SF', 'type': 'sunssf', 'offset': 11, 'notes': 'Scale factor'},
        {'field': 'PFRtgQ1', 'type': 'int16', 'offset': 12, 'units': 'cos()', 'scale': 'PFRtg_SF', 'notes': 'Minimum power factor Q1'},
        {'field': 'PFRtgQ2', 'type': 'int16', 'offset': 13, 'units': 'cos()', 'scale': 'PFRtg_SF', 'notes': 'Minimum power factor Q2'},
        {'field': 'PFRtgQ3', 'type': 'int16', 'offset': 14, 'units': 'cos()', 'scale': 'PFRtg_SF', 'notes': 'Minimum power factor Q3'},
        {'field': 'PFRtgQ4', 'type': 'int16', 'offset': 15, 'units': 'cos()', 'scale': 'PFRtg_SF', 'notes': 'Minimum power factor Q4'},
        {'field': 'PFRtg_SF', 'type': 'sunssf', 'offset': 16, 'notes': 'Scale factor'},
        {'field': 'WHRtg', 'type': 'uint16', 'offset': 17, 'units': 'Wh', 'scale': 'WHRtg_SF', 'notes': 'Nominal energy rating'},
        {'field': 'WHRtg_SF', 'type': 'sunssf', 'offset': 18, 'notes': 'Scale factor'},
        {'field': 'AhrRtg', 'type': 'uint16', 'offset': 19, 'units': 'AH', 'scale': 'AhrRtg_SF', 'notes': 'Usable capacity'},
        {'field': 'AhrRtg_SF', 'type': 'sunssf', 'offset': 20, 'notes': 'Scale factor'},
        {'field': 'MaxChaRte', 'type': 'uint16', 'offset': 21, 'units': 'W', 'scale': 'MaxChaRte_SF', 'notes': 'Maximum charge rate'},
        {'field': 'MaxChaRte_SF', 'type': 'sunssf', 'offset': 22, 'notes': 'Scale factor'},
        {'field': 'MaxDisChaRte', 'type': 'uint16', 'offset': 23, 'units': 'W', 'scale': 'MaxDisChaRte_SF', 'notes': 'Maximum discharge rate'},
        {'field': 'MaxDisChaRte_SF', 'type': 'sunssf', 'offset': 24, 'notes': 'Scale factor'},
        {'field': 'Pad', 'type': 'pad', 'offset': 25, 'notes': 'Pad register'},
    ],

    # --- Model 121: Settings ---
    121: [
        {'field': 'WMax', 'type': 'uint16', 'offset': 0, 'units': 'W', 'scale': 'WMax_SF', 'notes': 'Setting for maximum power output'},
        {'field': 'VRef', 'type': 'uint16', 'offset': 1, 'units': 'V', 'scale': 'VRef_SF', 'notes': 'Voltage at the PCC'},
        {'field': 'VRefOfs', 'type': 'int16', 'offset': 2, 'units': 'V', 'scale': 'VRefOfs_SF', 'notes': 'Offset from PCC to inverter'},
        {'field': 'VMax', 'type': 'uint16', 'offset': 3, 'units': 'V', 'scale': 'VMinMax_SF', 'notes': 'Setpoint for maximum voltage'},
        {'field': 'VMin', 'type': 'uint16', 'offset': 4, 'units': 'V', 'scale': 'VMinMax_SF', 'notes': 'Setpoint for minimum voltage'},
        {'field': 'VAMax', 'type': 'uint16', 'offset': 5, 'units': 'VA', 'scale': 'VAMax_SF', 'notes': 'Setpoint for maximum apparent power'},
        {'field': 'VArMaxQ1', 'type': 'int16', 'offset': 6, 'units': 'var', 'scale': 'VArMax_SF', 'notes': 'Setting for maximum reactive power Q1'},
        {'field': 'VArMaxQ2', 'type': 'int16', 'offset': 7, 'units': 'var', 'scale': 'VArMax_SF', 'notes': 'Setting for maximum reactive power Q2'},
        {'field': 'VArMaxQ3', 'type': 'int16', 'offset': 8, 'units': 'var', 'scale': 'VArMax_SF', 'notes': 'Setting for maximum reactive power Q3'},
        {'field': 'VArMaxQ4', 'type': 'int16', 'offset': 9, 'units': 'var', 'scale': 'VArMax_SF', 'notes': 'Setting for maximum reactive power Q4'},
        {'field': 'WGra', 'type': 'uint16', 'offset': 10, 'units': '% WMax/sec', 'scale': 'WGra_SF', 'notes': 'Default ramp rate'},
        {'field': 'PFMinQ1', 'type': 'int16', 'offset': 11, 'units': 'cos()', 'scale': 'PFMin_SF', 'notes': 'Setpoint for minimum power factor Q1'},
        {'field': 'PFMinQ2', 'type': 'int16', 'offset': 12, 'units': 'cos()', 'scale': 'PFMin_SF', 'notes': 'Setpoint for minimum power factor Q2'},
        {'field': 'PFMinQ3', 'type': 'int16', 'offset': 13, 'units': 'cos()', 'scale': 'PFMin_SF', 'notes': 'Setpoint for minimum power factor Q3'},
        {'field': 'PFMinQ4', 'type': 'int16', 'offset': 14, 'units': 'cos()', 'scale': 'PFMin_SF', 'notes': 'Setpoint for minimum power factor Q4'},
        {'field': 'VArAct', 'type': 'enum16', 'offset': 15, 'notes': 'VAR action on change'},
        {'field': 'ClcTotVA', 'type': 'enum16', 'offset': 16, 'notes': 'Calculation method for total apparent power'},
        {'field': 'MaxRmpRte', 'type': 'uint16', 'offset': 17, 'units': '% WGra', 'scale': 'MaxRmpRte_SF', 'notes': 'Setpoint for maximum ramp rate'},
        {'field': 'ECPNomHz', 'type': 'uint16', 'offset': 18, 'units': 'Hz', 'scale': 'ECPNomHz_SF', 'notes': 'Setpoint for nominal frequency'},
        {'field': 'ConnPh', 'type': 'enum16', 'offset': 19, 'notes': 'Identity of connected phase'},
        {'field': 'WMax_SF', 'type': 'sunssf', 'offset': 20, 'notes': 'Scale factor'},
        {'field': 'VRef_SF', 'type': 'sunssf', 'offset': 21, 'notes': 'Scale factor'},
        {'field': 'VRefOfs_SF', 'type': 'sunssf', 'offset': 22, 'notes': 'Scale factor'},
        {'field': 'VMinMax_SF', 'type': 'sunssf', 'offset': 23, 'notes': 'Scale factor'},
        {'field': 'VAMax_SF', 'type': 'sunssf', 'offset': 24, 'notes': 'Scale factor'},
        {'field': 'VArMax_SF', 'type': 'sunssf', 'offset': 25, 'notes': 'Scale factor'},
        {'field': 'WGra_SF', 'type': 'sunssf', 'offset': 26, 'notes': 'Scale factor'},
        {'field': 'PFMin_SF', 'type': 'sunssf', 'offset': 27, 'notes': 'Scale factor'},
        {'field': 'MaxRmpRte_SF', 'type': 'sunssf', 'offset': 28, 'notes': 'Scale factor'},
        {'field': 'ECPNomHz_SF', 'type': 'sunssf', 'offset': 29, 'notes': 'Scale factor'},
    ],

    # --- Model 122: Status ---
    122: [
        {'field': 'PVConn', 'type': 'bitfield16', 'offset': 0, 'notes': 'PV inverter present/available status'},
        {'field': 'StorConn', 'type': 'bitfield16', 'offset': 1, 'notes': 'Storage inverter present/available status'},
        {'field': 'ECPConn', 'type': 'bitfield16', 'offset': 2, 'notes': 'ECP connection status'},
        {'field': 'ActWh', 'type': 'acc64', 'offset': 3, 'units': 'Wh', 'notes': 'AC lifetime active energy output'},
        {'field': 'ActVAh', 'type': 'acc64', 'offset': 7, 'units': 'VAh', 'notes': 'AC lifetime apparent energy output'},
        {'field': 'ActVArhQ1', 'type': 'acc64', 'offset': 11, 'units': 'varh', 'notes': 'AC lifetime reactive energy output Q1'},
        {'field': 'ActVArhQ2', 'type': 'acc64', 'offset': 15, 'units': 'varh', 'notes': 'AC lifetime reactive energy output Q2'},
        {'field': 'ActVArhQ3', 'type': 'acc64', 'offset': 19, 'units': 'varh', 'notes': 'AC lifetime negative energy output Q3'},
        {'field': 'ActVArhQ4', 'type': 'acc64', 'offset': 23, 'units': 'varh', 'notes': 'AC lifetime reactive energy output Q4'},
        {'field': 'VArAval', 'type': 'int16', 'offset': 27, 'units': 'var', 'scale': 'VArAval_SF', 'notes': 'Amount of VARs available'},
        {'field': 'VArAval_SF', 'type': 'sunssf', 'offset': 28, 'notes': 'Scale factor'},
        {'field': 'WAval', 'type': 'uint16', 'offset': 29, 'units': 'var', 'scale': 'WAval_SF', 'notes': 'Amount of Watts available'},
        {'field': 'WAval_SF', 'type': 'sunssf', 'offset': 30, 'notes': 'Scale factor'},
        {'field': 'StSetLimMsk', 'type': 'bitfield32', 'offset': 31, 'notes': 'Bit Mask indicating setpoint limit(s) reached'},
        {'field': 'StActCtl', 'type': 'bitfield32', 'offset': 33, 'notes': 'Bit Mask indicating active inverter controls'},
        {'field': 'TmSrc', 'type': 'string', 'offset': 35, 'length': 8, 'notes': 'Source of time synchronization'},
        {'field': 'Tms', 'type': 'uint32', 'offset': 39, 'units': 'Secs', 'notes': 'Seconds since 01-01-2000'},
        {'field': 'RtSt', 'type': 'bitfield16', 'offset': 41, 'notes': 'Bit Mask indicating active ride-through status'},
        {'field': 'Ris', 'type': 'uint16', 'offset': 42, 'units': 'ohms', 'scale': 'Ris_SF', 'notes': 'Isolation resistance'},
        {'field': 'Ris_SF', 'type': 'sunssf', 'offset': 43, 'notes': 'Scale factor'},
    ],

    # --- Model 123: Controls ---
    123: [
        {'field': 'Conn_WinTms', 'type': 'uint16', 'offset': 0, 'units': 'Secs', 'notes': 'Time window for connect/disconnect'},
        {'field': 'Conn_RvrtTms', 'type': 'uint16', 'offset': 1, 'units': 'Secs', 'notes': 'Timeout period for connect/disconnect'},
        {'field': 'Conn', 'type': 'enum16', 'offset': 2, 'notes': 'Connection control'},
        {'field': 'WMaxLimPct', 'type': 'uint16', 'offset': 3, 'units': '% WMax', 'scale': 'WMaxLimPct_SF', 'notes': 'Set power output to specified level'},
        {'field': 'WMaxLimPct_WinTms', 'type': 'uint16', 'offset': 4, 'units': 'Secs', 'notes': 'Time window for power limit change'},
        {'field': 'WMaxLimPct_RvrtTms', 'type': 'uint16', 'offset': 5, 'units': 'Secs', 'notes': 'Timeout period for power limit'},
        {'field': 'WMaxLimPct_RmpTms', 'type': 'uint16', 'offset': 6, 'units': 'Secs', 'notes': 'Ramp time for power limit'},
        {'field': 'WMaxLim_Ena', 'type': 'enum16', 'offset': 7, 'notes': 'Throttle enable/disable control'},
        {'field': 'OutPFSet', 'type': 'int16', 'offset': 8, 'units': 'cos()', 'scale': 'OutPFSet_SF', 'notes': 'Set power factor'},
        {'field': 'OutPFSet_WinTms', 'type': 'uint16', 'offset': 9, 'units': 'Secs', 'notes': 'Time window for power factor change'},
        {'field': 'OutPFSet_RvrtTms', 'type': 'uint16', 'offset': 10, 'units': 'Secs', 'notes': 'Timeout period for power factor'},
        {'field': 'OutPFSet_RmpTms', 'type': 'uint16', 'offset': 11, 'units': 'Secs', 'notes': 'Ramp time for power factor'},
        {'field': 'OutPFSet_Ena', 'type': 'enum16', 'offset': 12, 'notes': 'Fixed power factor enable/disable control'},
        {'field': 'VArWMaxPct', 'type': 'int16', 'offset': 13, 'units': '% WMax', 'scale': 'VArPct_SF', 'notes': 'Reactive power in percent of WMax'},
        {'field': 'VArMaxPct', 'type': 'int16', 'offset': 14, 'units': '% VArMax', 'scale': 'VArPct_SF', 'notes': 'Reactive power in percent of VArMax'},
        {'field': 'VArAvalPct', 'type': 'int16', 'offset': 15, 'units': '% VArAval', 'scale': 'VArPct_SF', 'notes': 'Reactive power in percent of VArAval'},
        {'field': 'VArPct_WinTms', 'type': 'uint16', 'offset': 16, 'units': 'Secs', 'notes': 'Time window for VAR limit change'},
        {'field': 'VArPct_RvrtTms', 'type': 'uint16', 'offset': 17, 'units': 'Secs', 'notes': 'Timeout period for VAR limit'},
        {'field': 'VArPct_RmpTms', 'type': 'uint16', 'offset': 18, 'units': 'Secs', 'notes': 'Ramp time for VAR limit'},
        {'field': 'VArPct_Mod', 'type': 'enum16', 'offset': 19, 'notes': 'VAR percent limit mode'},
        {'field': 'VArPct_Ena', 'type': 'enum16', 'offset': 20, 'notes': 'Percent limit VAr enable/disable control'},
        {'field': 'WMaxLimPct_SF', 'type': 'sunssf', 'offset': 21, 'notes': 'Scale factor'},
        {'field': 'OutPFSet_SF', 'type': 'sunssf', 'offset': 22, 'notes': 'Scale factor'},
        {'field': 'VArPct_SF', 'type': 'sunssf', 'offset': 23, 'notes': 'Scale factor'},
    ],

    # --- Model 160: MPPT (Multiple Modules) ---
    # Note: Flattened structure for 4 modules as per CSV
    160: [
        {'field': 'DCA_SF', 'type': 'sunssf', 'offset': 0, 'notes': 'Current Scale Factor'},
        {'field': 'DCV_SF', 'type': 'sunssf', 'offset': 1, 'notes': 'Voltage Scale Factor'},
        {'field': 'DCW_SF', 'type': 'sunssf', 'offset': 2, 'notes': 'Power Scale Factor'},
        {'field': 'DCWH_SF', 'type': 'sunssf', 'offset': 3, 'notes': 'Energy Scale Factor'},
        {'field': 'Evt', 'type': 'bitfield32', 'offset': 4, 'notes': 'Global Events'},
        {'field': 'N', 'type': 'count', 'offset': 6, 'notes': 'Number of Modules'},
        {'field': 'TmsPer', 'type': 'uint16', 'offset': 7, 'notes': 'Timestamp Period'},
        
        # Module 1
        {'field': '1_ID', 'type': 'uint16', 'offset': 8, 'notes': 'Input ID 1'},
        {'field': '1_IDStr', 'type': 'string', 'offset': 9, 'length': 16, 'notes': 'Input ID String 1'},
        {'field': '1_DCA', 'type': 'uint16', 'offset': 17, 'units': 'A', 'scale': 'DCA_SF', 'notes': 'DC Current 1'}, # speichern
        {'field': '1_DCV', 'type': 'uint16', 'offset': 18, 'units': 'V', 'scale': 'DCV_SF', 'notes': 'DC Voltage 1'}, # speichern
        {'field': '1_DCW', 'type': 'uint16', 'offset': 19, 'units': 'W', 'scale': 'DCW_SF', 'notes': 'DC Power 1'}, # speichern
        {'field': '1_DCWH', 'type': 'acc32', 'offset': 20, 'units': 'Wh', 'scale': 'DCWH_SF', 'notes': 'Lifetime Energy 1'}, # speichern
        {'field': '1_Tms', 'type': 'uint32', 'offset': 22, 'units': 'Secs', 'notes': 'Timestamp 1'},
        {'field': '1_Tmp', 'type': 'int16', 'offset': 24, 'units': 'C', 'notes': 'Temperature 1'},
        {'field': '1_DCSt', 'type': 'enum16', 'offset': 25, 'notes': 'Operating State 1'},
        {'field': '1_DCEvt', 'type': 'bitfield32', 'offset': 26, 'notes': 'Module Events 1'},

        # Module 2 (Offset +20 from Module 1)
        {'field': '2_ID', 'type': 'uint16', 'offset': 28, 'notes': 'Input ID 2'},
        {'field': '2_IDStr', 'type': 'string', 'offset': 29, 'length': 16, 'notes': 'Input ID String 2'},
        {'field': '2_DCA', 'type': 'uint16', 'offset': 37, 'units': 'A', 'scale': 'DCA_SF', 'notes': 'DC Current 2'}, # speichern
        {'field': '2_DCV', 'type': 'uint16', 'offset': 38, 'units': 'V', 'scale': 'DCV_SF', 'notes': 'DC Voltage 2'}, # speichern
        {'field': '2_DCW', 'type': 'uint16', 'offset': 39, 'units': 'W', 'scale': 'DCW_SF', 'notes': 'DC Power 2'}, # speichern
        {'field': '2_DCWH', 'type': 'acc32', 'offset': 40, 'units': 'Wh', 'scale': 'DCWH_SF', 'notes': 'Lifetime Energy 2'}, # speichern
        {'field': '2_Tms', 'type': 'uint32', 'offset': 42, 'units': 'Secs', 'notes': 'Timestamp 2'},
        {'field': '2_Tmp', 'type': 'int16', 'offset': 44, 'units': 'C', 'notes': 'Temperature 2'},
        {'field': '2_DCSt', 'type': 'enum16', 'offset': 45, 'notes': 'Operating State 2'},
        {'field': '2_DCEvt', 'type': 'bitfield32', 'offset': 46, 'notes': 'Module Events 2'},

        # Module 3
        {'field': '3_ID', 'type': 'uint16', 'offset': 48, 'notes': 'Input ID 3'},
        {'field': '3_IDStr', 'type': 'string', 'offset': 49, 'length': 16, 'notes': 'Input ID String 3'},
        {'field': '3_DCA', 'type': 'uint16', 'offset': 57, 'units': 'A', 'scale': 'DCA_SF', 'notes': 'DC Current 3'},
        {'field': '3_DCV', 'type': 'uint16', 'offset': 58, 'units': 'V', 'scale': 'DCV_SF', 'notes': 'DC Voltage 3'},
        {'field': '3_DCW', 'type': 'uint16', 'offset': 59, 'units': 'W', 'scale': 'DCW_SF', 'notes': 'DC Power 3'},
        {'field': '3_DCWH', 'type': 'acc32', 'offset': 60, 'units': 'Wh', 'scale': 'DCWH_SF', 'notes': 'Lifetime Energy 3'},
        {'field': '3_Tms', 'type': 'uint32', 'offset': 62, 'units': 'Secs', 'notes': 'Timestamp 3'},
        {'field': '3_Tmp', 'type': 'int16', 'offset': 64, 'units': 'C', 'notes': 'Temperature 3'},
        {'field': '3_DCSt', 'type': 'enum16', 'offset': 65, 'notes': 'Operating State 3'},
        {'field': '3_DCEvt', 'type': 'bitfield32', 'offset': 66, 'notes': 'Module Events 3'},

        # Module 4
        {'field': '4_ID', 'type': 'uint16', 'offset': 68, 'notes': 'Input ID 4'},
        {'field': '4_IDStr', 'type': 'string', 'offset': 69, 'length': 16, 'notes': 'Input ID String 4'},
        {'field': '4_DCA', 'type': 'uint16', 'offset': 77, 'units': 'A', 'scale': 'DCA_SF', 'notes': 'DC Current 4'},
        {'field': '4_DCV', 'type': 'uint16', 'offset': 78, 'units': 'V', 'scale': 'DCV_SF', 'notes': 'DC Voltage 4'},
        {'field': '4_DCW', 'type': 'uint16', 'offset': 79, 'units': 'W', 'scale': 'DCW_SF', 'notes': 'DC Power 4'},
        {'field': '4_DCWH', 'type': 'acc32', 'offset': 80, 'units': 'Wh', 'scale': 'DCWH_SF', 'notes': 'Lifetime Energy 4'},
        {'field': '4_Tms', 'type': 'uint32', 'offset': 82, 'units': 'Secs', 'notes': 'Timestamp 4'},
        {'field': '4_Tmp', 'type': 'int16', 'offset': 84, 'units': 'C', 'notes': 'Temperature 4'},
        {'field': '4_DCSt', 'type': 'enum16', 'offset': 85, 'notes': 'Operating State 4'},
        {'field': '4_DCEvt', 'type': 'bitfield32', 'offset': 86, 'notes': 'Module Events 4'},
    ],

    # --- Model 124: Storage ---
    124: [
        {'field': 'WChaMax', 'type': 'uint16', 'offset': 0, 'units': 'W', 'scale': 'WChaMax_SF', 'notes': 'Setpoint for maximum charge'},
        {'field': 'WChaGra', 'type': 'uint16', 'offset': 1, 'units': '% WChaMax/sec', 'scale': 'WChaDisChaGra_SF', 'notes': 'Setpoint for maximum charging rate'},
        {'field': 'WDisChaGra', 'type': 'uint16', 'offset': 2, 'units': '% WChaMax/sec', 'scale': 'WChaDisChaGra_SF', 'notes': 'Setpoint for maximum discharge rate'},
        {'field': 'StorCtl_Mod', 'type': 'bitfield16', 'offset': 3, 'notes': 'Activate hold/discharge/charge storage control mode'},
        {'field': 'VAChaMax', 'type': 'uint16', 'offset': 4, 'units': 'VA', 'scale': 'VAChaMax_SF', 'notes': 'Setpoint for maximum charging VA'},
        {'field': 'MinRsvPct', 'type': 'uint16', 'offset': 5, 'units': '% WChaMax', 'scale': 'MinRsvPct_SF', 'notes': 'Setpoint for minimum reserve'},
        {'field': 'ChaState', 'type': 'uint16', 'offset': 6, 'units': '% AhrRtg', 'scale': 'ChaState_SF', 'notes': 'Currently available energy'}, # speichern
        {'field': 'StorAval', 'type': 'uint16', 'offset': 7, 'units': 'AH', 'scale': 'StorAval_SF', 'notes': 'State of charge minus reserve'},
        {'field': 'InBatV', 'type': 'uint16', 'offset': 8, 'units': 'V', 'scale': 'InBatV_SF', 'notes': 'Internal battery voltage'}, # speichern
        {'field': 'ChaSt', 'type': 'enum16', 'offset': 9, 'notes': 'Charge status of storage device'}, # speichern
        {'field': 'OutWRte', 'type': 'int16', 'offset': 10, 'units': '% WChaMax', 'scale': 'InOutWRte_SF', 'notes': 'Percent of max discharge rate'},
        {'field': 'InWRte', 'type': 'int16', 'offset': 11, 'units': '% WChaMax', 'scale': 'InOutWRte_SF', 'notes': 'Percent of max charging rate'},
        {'field': 'InOutWRte_WinTms', 'type': 'uint16', 'offset': 12, 'units': 'Secs', 'notes': 'Time window for rate change'},
        {'field': 'InOutWRte_RvrtTms', 'type': 'uint16', 'offset': 13, 'units': 'Secs', 'notes': 'Timeout period for rate'},
        {'field': 'InOutWRte_RmpTms', 'type': 'uint16', 'offset': 14, 'units': 'Secs', 'notes': 'Ramp time for rate'},
        {'field': 'ChaGriSet', 'type': 'enum16', 'offset': 15, 'notes': 'Grid Charge Setting'},
        {'field': 'WChaMax_SF', 'type': 'sunssf', 'offset': 16, 'notes': 'Scale factor'},
        {'field': 'WChaDisChaGra_SF', 'type': 'sunssf', 'offset': 17, 'notes': 'Scale factor'},
        {'field': 'VAChaMax_SF', 'type': 'sunssf', 'offset': 18, 'notes': 'Scale factor'},
        {'field': 'MinRsvPct_SF', 'type': 'sunssf', 'offset': 19, 'notes': 'Scale factor'},
        {'field': 'ChaState_SF', 'type': 'sunssf', 'offset': 20, 'notes': 'Scale factor'},
        {'field': 'StorAval_SF', 'type': 'sunssf', 'offset': 21, 'notes': 'Scale factor'},
        {'field': 'InBatV_SF', 'type': 'sunssf', 'offset': 22, 'notes': 'Scale factor'},
        {'field': 'InOutWRte_SF', 'type': 'sunssf', 'offset': 23, 'notes': 'Scale factor'},
    ],

    # --- Model 201-203: Meter ---
    # Definition gilt für 201 (Single Phase), 202 (Split Phase), 203 (Three Phase)
    203: [
        {'field': 'A', 'type': 'int16', 'offset': 0, 'units': 'A', 'scale': 'A_SF', 'notes': 'AC Total Current'}, # speichern P_SM_Netz
        {'field': 'AphA', 'type': 'int16', 'offset': 1, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase A Current'}, # speichern P_SM_Netz
        {'field': 'AphB', 'type': 'int16', 'offset': 2, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase B Current'}, # speichern P_SM_Netz
        {'field': 'AphC', 'type': 'int16', 'offset': 3, 'units': 'A', 'scale': 'A_SF', 'notes': 'Phase C Current'}, # speichern P_SM_Netz
        {'field': 'A_SF', 'type': 'sunssf', 'offset': 4, 'notes': 'Scale factor'},
        {'field': 'PhV', 'type': 'int16', 'offset': 5, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Average Phase-to-neutral'}, # speichern P_SM_Netz
        {'field': 'PhVphA', 'type': 'int16', 'offset': 6, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-A-to-neutral'}, # speichern P_SM_Netz
        {'field': 'PhVphB', 'type': 'int16', 'offset': 7, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-B-to-neutral'}, # speichern P_SM_Netz
        {'field': 'PhVphC', 'type': 'int16', 'offset': 8, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-C-to-neutral'}, # speichern P_SM_Netz
        {'field': 'PPV', 'type': 'int16', 'offset': 9, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Average Phase-to-phase'}, # speichern P_SM_Netz
        {'field': 'PPVphAB', 'type': 'int16', 'offset': 10, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-AB'}, # speichern P_SM_Netz
        {'field': 'PPVphBC', 'type': 'int16', 'offset': 11, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-BC'}, # speichern P_SM_Netz
        {'field': 'PPVphCA', 'type': 'int16', 'offset': 12, 'units': 'V', 'scale': 'V_SF', 'notes': 'AC Voltage Phase-CA'}, # speichern P_SM_Netz
        {'field': 'V_SF', 'type': 'sunssf', 'offset': 13, 'notes': 'Scale factor'},
        {'field': 'Hz', 'type': 'int16', 'offset': 14, 'units': 'Hz', 'scale': 'Hz_SF', 'notes': 'AC Frequency'}, # speichern P_SM_Netz
        {'field': 'Hz_SF', 'type': 'sunssf', 'offset': 15, 'notes': 'Scale factor'},
        {'field': 'W', 'type': 'int16', 'offset': 16, 'units': 'W', 'scale': 'W_SF', 'notes': 'AC Power'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'WphA', 'type': 'int16', 'offset': 17, 'units': 'W', 'scale': 'W_SF', 'notes': 'AC Power Phase A'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'WphB', 'type': 'int16', 'offset': 18, 'units': 'W', 'scale': 'W_SF', 'notes': 'AC Power Phase B'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'WphC', 'type': 'int16', 'offset': 19, 'units': 'W', 'scale': 'W_SF', 'notes': 'AC Power Phase C'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'W_SF', 'type': 'sunssf', 'offset': 20, 'notes': 'Scale factor'},
        {'field': 'VA', 'type': 'int16', 'offset': 21, 'units': 'VA', 'scale': 'VA_SF', 'notes': 'AC Apparent Power'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'VAphA', 'type': 'int16', 'offset': 22, 'units': 'VA', 'scale': 'VA_SF', 'notes': 'Apparent Power Phase A'},
        {'field': 'VAphB', 'type': 'int16', 'offset': 23, 'units': 'VA', 'scale': 'VA_SF', 'notes': 'Apparent Power Phase B'},
        {'field': 'VAphC', 'type': 'int16', 'offset': 24, 'units': 'VA', 'scale': 'VA_SF', 'notes': 'Apparent Power Phase C'},
        {'field': 'VA_SF', 'type': 'sunssf', 'offset': 25, 'notes': 'Scale factor'},
        {'field': 'VAR', 'type': 'int16', 'offset': 26, 'units': 'VAr', 'scale': 'VAR_SF', 'notes': 'AC Reactive Power'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'VARphA', 'type': 'int16', 'offset': 27, 'units': 'VAr', 'scale': 'VAR_SF', 'notes': 'Reactive Power Phase A'},
        {'field': 'VARphB', 'type': 'int16', 'offset': 28, 'units': 'VAr', 'scale': 'VAR_SF', 'notes': 'Reactive Power Phase B'},
        {'field': 'VARphC', 'type': 'int16', 'offset': 29, 'units': 'VAr', 'scale': 'VAR_SF', 'notes': 'Reactive Power Phase C'},
        {'field': 'VAR_SF', 'type': 'sunssf', 'offset': 30, 'notes': 'Scale factor'},
        {'field': 'PF', 'type': 'int16', 'offset': 31, 'units': '%', 'scale': 'PF_SF', 'notes': 'Power Factor'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'PFphA', 'type': 'int16', 'offset': 32, 'units': '%', 'scale': 'PF_SF', 'notes': 'Power Factor Phase A'},
        {'field': 'PFphB', 'type': 'int16', 'offset': 33, 'units': '%', 'scale': 'PF_SF', 'notes': 'Power Factor Phase B'},
        {'field': 'PFphC', 'type': 'int16', 'offset': 34, 'units': '%', 'scale': 'PF_SF', 'notes': 'Power Factor Phase C'},
        {'field': 'PF_SF', 'type': 'sunssf', 'offset': 35, 'notes': 'Scale factor'},
        {'field': 'TotWhExp', 'type': 'acc32', 'offset': 36, 'units': 'Wh', 'scale': 'TotWh_SF', 'notes': 'Total Watt-hours Exported'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'TotWhImp', 'type': 'acc32', 'offset': 44, 'units': 'Wh', 'scale': 'TotWh_SF', 'notes': 'Total Watt-hours Imported'}, # speichern P_SM_Netz S_SM_F2 S_SM_F3 S_SM_WP
        {'field': 'TotWh_SF', 'type': 'sunssf', 'offset': 52, 'notes': 'Scale factor'},
    ]
}

# Aliases für Meter-Modelle
MODELS[201] = MODELS[203]
MODELS[202] = MODELS[203]
