/* nq-analyse.js — gemeinsame Helfer der NQ-Spektralanalyse-Einzelseiten.
 *
 * Stellt window.NQA bereit:
 *   NQA.ec(id)              ECharts-Instanz (dark) je Container, mit Resize.
 *   NQA.days                gemeinsamer Zeitraum (Tage), in sessionStorage.
 *   NQA.win()               {start,end} Unix-s aus NQA.days.
 *   NQA.initRange(onChange) verdrahtet die 7/30/90/365-Tage-Buttons der Leiste.
 *   NQA.fmtFreq/fmtPeriod/fmtFreqAxis   Frequenz-/Perioden-Formatierung.
 *   NQA.statCard/avg        Kennzahl-Karten.
 *   NQA.extrema(hint,fmt)   markPoint-Konfig (Max/Min) mit Erläuterungs-Tooltip.
 *
 * Nutzt PVNavUI.initDrawer() (Hamburger) + PVChart (responsive), falls geladen. */
(function () {
    const charts = {};
    function ec(id) {
        const el = document.getElementById(id);
        if (!el) return null;
        if (!charts[id]) charts[id] = echarts.init(el, 'dark');
        return charts[id];
    }
    window.addEventListener('resize', () => Object.values(charts).forEach(c => c && c.resize()));

    // ── Zeitraum-Status (über die Einzelseiten hinweg gemerkt) ──
    const RKEY = 'nqAnalyseDays';
    let days = parseInt(sessionStorage.getItem(RKEY) || '30', 10) || 30;

    function win() { const e = Math.floor(Date.now() / 1000); return { start: e - days * 86400, end: e }; }

    function initRange(onChange) {
        const bar = document.getElementById('rangeGroup');
        if (!bar) return;
        bar.querySelectorAll('button[data-days]').forEach(b => {
            if (parseInt(b.dataset.days, 10) === days) b.classList.add('active');
            b.addEventListener('click', () => {
                days = parseInt(b.dataset.days, 10) || 30;
                sessionStorage.setItem(RKEY, String(days));
                bar.querySelectorAll('button[data-days]').forEach(x => x.classList.remove('active'));
                b.classList.add('active');
                if (typeof onChange === 'function') onChange();
            });
        });
    }

    // ── Zahl-/Frequenz-Formatierung ──
    function trimNum(x, dec) { return parseFloat(Number(x).toFixed(dec)).toString(); }
    function fmtFreq(f) {
        if (!isFinite(f) || f <= 0) return '0';
        let v, u;
        if (f >= 1) { v = f; u = 'Hz'; }
        else if (f >= 1e-3) { v = f * 1e3; u = 'mHz'; }
        else if (f >= 1e-6) { v = f * 1e6; u = 'µHz'; }
        else { v = f * 1e9; u = 'nHz'; }
        const dec = v >= 100 ? 0 : (v >= 10 ? 1 : 2);
        return trimNum(v, dec) + ' ' + u;
    }
    function fmtPeriod(sec) {
        if (!isFinite(sec) || sec <= 0) return '—';
        const units = [[31557600, 'a'], [2629800, 'Mon'], [604800, 'Wo'],
                       [86400, 'd'], [3600, 'h'], [60, 'min'], [1, 's']];
        for (const [s, u] of units) {
            if (sec >= s * 0.999) {
                const v = sec / s; const dec = v >= 100 ? 0 : (v >= 10 ? 1 : 2);
                return trimNum(v, dec) + ' ' + u;
            }
        }
        return trimNum(sec, 2) + ' s';
    }
    function fmtFreqAxis(f) { return fmtFreq(f) + '\n' + fmtPeriod(1 / f); }

    function statCard(label, val, unit) {
        let v;
        if (val === null || val === undefined) v = '—';
        else if (typeof val === 'number') {
            if (!isFinite(val)) v = '—';
            else if (Math.abs(val) >= 1e6) v = val.toExponential(1);
            else v = Math.abs(val) < 1 ? val.toFixed(3) : val.toFixed(2);
        } else v = val;
        return `<div class="stat-card"><div class="stat-label">${label}</div>
                <div class="stat-value">${v}<span class="stat-unit">${unit || ''}</span></div></div>`;
    }
    function avg(a) { return a.length ? Math.round(a.reduce((s, x) => s + x, 0) / a.length * 1000) / 1000 : null; }

    // ── Max/Min-Marker mit Erläuterungs-Tooltip (Thesen an den Extrema) ──
    // hint = {max:'…', min:'…'}; fmtVal(value)->String für die Wertanzeige.
    function extrema(hint, fmtVal) {
        hint = hint || {};
        fmtVal = fmtVal || (v => (Array.isArray(v) ? v[1] : v));
        return {
            symbol: 'pin', symbolSize: 44, silent: false,
            label: { show: true, fontSize: 9, color: '#0f172a', fontWeight: 700,
                     formatter: p => (p.data.type === 'max' ? '▲' : '▼') },
            data: [
                { type: 'max', name: 'Maximum', itemStyle: { color: '#fca5a5' } },
                { type: 'min', name: 'Minimum', itemStyle: { color: '#93c5fd' } },
            ],
            tooltip: {
                confine: true, className: 'pv-echarts-tip',
                formatter: p => {
                    const note = p.data.type === 'max' ? (hint.max || '') : (hint.min || '');
                    return `<b>${p.name}</b> · ${fmtVal(p.value)}`
                        + (note ? `<br/><span style="color:#94a3b8">${note}</span>` : '');
                }
            }
        };
    }

    window.NQA = {
        ec, win, initRange,
        get days() { return days; },
        trimNum, fmtFreq, fmtPeriod, fmtFreqAxis, statCard, avg, extrema,
    };

    if (window.PVNavUI && PVNavUI.initDrawer) {
        document.addEventListener('DOMContentLoaded', () => PVNavUI.initDrawer());
    }
})();
