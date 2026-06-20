/* ─────────────────────────────────────────────────────────────
 * extremes.js — geteilte Perioden-Extremwerte für Tooltips
 * Konsistente Anzeige in Monitoring (tag_view) und Analyse
 * (erzeuger_view/verbraucher_view). Daten: /api/period_extremes.
 *
 * PVExtremes.fetchFor(period, ctx) -> Promise<{by_key, overall}|null>
 * PVExtremes.lines(entry, {mobile, period}) -> HTML-Zeilen (Monat/Jahr/Gesamt)
 * PVExtremes.tagLines(overall, {mobile}) -> HTML-Zeilen (Tag)
 *
 * Bewusst OHNE Icons (keine bunt/grau-Mischung). Werte mit Datum/Uhrzeit.
 * ───────────────────────────────────────────────────────────── */
(function () {
    function de(n, dec) {
        return Number(n).toFixed(dec).replace('.', ',');
    }
    function fmtKwh(kwh) {
        if (kwh == null) return '–';
        if (kwh >= 1000) return de(kwh / 1000, 2) + ' MWh';
        if (kwh >= 100) return de(kwh, 0) + ' kWh';
        if (kwh >= 10) return de(kwh, 1) + ' kWh';
        return de(kwh, 2) + ' kWh';
    }

    function isMobile() {
        return window.innerWidth < 600 || window.innerHeight < 500;
    }
    function lbl(s) { return s ? ' (' + s + ')' : ''; }

    // Range-Zeile "min … max" mit optionalen Zeit-/Datums-Labels.
    function rangeLine(name, e, unit, dec, mobile) {
        if (!e) return null;
        var u = unit ? ' ' + unit : '';
        if (mobile) return name + ': ' + de(e.min, dec) + u + ' – ' + de(e.max, dec) + u;
        return name + ': ' + de(e.min, dec) + u + lbl(e.min_label) + ' – ' + de(e.max, dec) + u + lbl(e.max_label);
    }

    // Extremwert-Block für einen Balken (Monat=Tag, Jahr=Monat, Gesamt=Jahr).
    // Auf kleinen Bildschirmen kompakter (V/f/cosφ einzeilig, kürzere Labels).
    function lines(entry, opts) {
        opts = opts || {};
        var mobile = opts.mobile != null ? opts.mobile : isMobile();
        var period = opts.period || '';
        if (!entry) return '';
        var out = [];

        var yl = period === 'gesamt'
            ? ['Ertragreichster Monat', 'Ertragärmster Monat']
            : ['Größter Tagesertrag', 'Kleinster Tagesertrag'];
        if (entry.yield_max) out.push(yl[0] + ': ' + fmtKwh(entry.yield_max.kwh) + lbl(entry.yield_max.label));
        if (entry.yield_min) out.push(yl[1] + ': ' + fmtKwh(entry.yield_min.kwh) + lbl(entry.yield_min.label));

        if (entry.power) out.push('Peak-Leistung: ' + de(entry.power.kw, 2) + ' kW' + lbl(entry.power.label));

        var v = rangeLine('Spannung', entry.voltage, 'V', mobile ? 0 : 1, mobile);
        var f = rangeLine('Frequenz', entry.frequency, 'Hz', mobile ? 2 : 3, mobile);
        var pf = entry.powerfactor
            ? (mobile
                ? 'cos φ: ' + de(entry.powerfactor.min, 2) + ' – ' + de(entry.powerfactor.max, 2)
                : 'cos φ: ' + de(entry.powerfactor.min, 2) + lbl(entry.powerfactor.min_label) + ' – ' + de(entry.powerfactor.max, 2) + lbl(entry.powerfactor.max_label))
            : null;
        [v, f, pf].forEach(function (x) { if (x) out.push(x); });

        if (!out.length) return '';
        return '<hr style="border:none;border-top:1px solid #ccc;margin:6px 0;"/>' + out.join('<br/>');
    }

    // Tages-Extremwerte (Peak + Spannung/Frequenz/cosφ mit Uhrzeit).
    function tagLines(overall, opts) {
        opts = opts || {};
        var mobile = opts.mobile != null ? opts.mobile : isMobile();
        if (!overall) return '';
        var out = [];
        if (overall.power) out.push('Peak-Leistung: ' + de(overall.power.kw, 2) + ' kW' + lbl(overall.power.label));
        var v = rangeLine('Spannung', overall.voltage, 'V', mobile ? 0 : 1, mobile);
        var f = rangeLine('Frequenz', overall.frequency, 'Hz', mobile ? 2 : 3, mobile);
        var pf = overall.powerfactor
            ? (mobile
                ? 'cos φ: ' + de(overall.powerfactor.min, 2) + ' – ' + de(overall.powerfactor.max, 2)
                : 'cos φ: ' + de(overall.powerfactor.min, 2) + lbl(overall.powerfactor.min_label) + ' – ' + de(overall.powerfactor.max, 2) + lbl(overall.powerfactor.max_label))
            : null;
        [v, f, pf].forEach(function (x) { if (x) out.push(x); });
        if (!out.length) return '';
        return out.join('<br/>');
    }

    function fetchFor(period, ctx) {
        var p = new URLSearchParams();
        p.set('period', period);
        if (ctx) {
            if (ctx.date) p.set('date', ctx.date);
            if (ctx.year) p.set('year', ctx.year);
            if (ctx.month) p.set('month', ctx.month);
        }
        return fetch('/api/period_extremes?' + p.toString())
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
    }

    window.PVExtremes = { fetchFor: fetchFor, lines: lines, tagLines: tagLines, fmtKwh: fmtKwh, isMobile: isMobile, de: de };
})();
