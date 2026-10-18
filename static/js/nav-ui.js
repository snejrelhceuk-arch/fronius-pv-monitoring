/* nav-ui.js — gemeinsame Seiten-Schublade + Kalender-Picker.
 *
 * PVNavUI.initDrawer(opts)
 *   opts.pagesSelector : Selektor des Containers mit den Seiten-Links, der in
 *                        die Schublade verschoben wird (z. B. '.pv-pages').
 *   opts.barSelector   : Navigationsleiste, in die der Hamburger eingefügt wird.
 *   opts.title         : (veraltet, ohne Wirkung).
 *
 * PVNavUI.attachCalendar(triggerEl, kind, getCurrent, onPick)
 *   kind: 'day' (Tag/Monat/Jahr) | 'month' (Gesamt)
 *   getCurrent(): String 'YYYY-MM-DD' bzw. 'YYYY-MM' (Vorbelegung)
 *   onPick(value): Callback mit gewähltem Wert.
 */
(function () {
    // Datenstand der manuell gepflegten Primärenergie-Seite (synchron zu
    // config.PRIMAERENERGIE_STAND). Nach ~1 Quartal Marker am Menüpunkt.
    var PRIMAER_STAND = '2026-06-20';
    var PRIMAER_STALE_DAYS = 92;
    function primaerStale() {
        try {
            var d = new Date(PRIMAER_STAND + 'T00:00:00');
            return (Date.now() - d.getTime()) > PRIMAER_STALE_DAYS * 86400000;
        } catch (e) { return false; }
    }

    // Vollständiges Seiten-Menü als aufklappbare Rollup-Gruppen. Reihenfolge =
    // Anzeige. Zeitkontext wird via PVNavContext als Query angehängt, damit der
    // Zeitraum über Seitenwechsel erhalten bleibt.
    // Typen: {group,items[]} aufklappbares Untermenü (beliebig verschachtelbar)
    //        {href,label} Link · {sep} Trennlinie.
    // Flow liegt bewusst NICHT im Menü — es hat einen eigenen Schnellzugriff-Button.
    var DEFAULT_PAGES = [
        { group: 'Monitoring', items: [
            { href: '/monitoring', label: 'Produktion' },
            { href: '/monitoring?view=verbrauch', label: 'Verbrauch' },
            { href: '/erzeuger', label: 'Erzeuger' },
            { href: '/verbraucher', label: 'Lasten' },
            { href: '/analyse/batterie', label: 'Batterie' },
        ] },
        { group: 'Analyse', items: [
            { href: '/analyse/pv', label: 'PV-Übersicht' },
            { href: '/analyse/haushalt', label: 'Haushalt' },
            { href: '/analyse/amortisation', label: 'Amortisation' },
            { href: '/analyse/speicherausbau', label: '🔋 Speicher-Ausbau' },
            { href: '/analyse/primaerenergie', label: '🌍 Primärenergie', stale: true },
        ] },
        { group: 'Netzqualität', items: [
            { href: '/pac4200', label: 'PAC4200' },
            { href: '/netzqualitaet/live', label: 'PAC-Screens' },
            { href: '/netzqualitaet', label: 'Netzkriterien' },
            { href: '/netzqualitaet/chart', label: 'Event-Chart' },
            { group: 'Spektralanalyse', items: [
                { href: '/netzqualitaet/analyse', label: 'Einführung' },
                { href: '/netzqualitaet/analyse/harmonische', label: 'Oberschwingungen' },
                { href: '/netzqualitaet/analyse/periodogramm', label: 'Periodogramm' },
                { href: '/netzqualitaet/analyse/psd', label: 'Leistungsdichte' },
                { href: '/netzqualitaet/analyse/spektrogramm', label: 'Spektrogramm' },
                { href: '/netzqualitaet/analyse/reflexion', label: 'Reflexionen 🛰️' },
            ] },
            { href: '/netzqualitaet/energievergleich', label: 'Energievergleich' },
        ] },
        { group: 'Darstellung aller Einzelwerte', items: [
            { href: '/maschinenraum', label: 'PV-System' },
            { href: '/maschinenraum?db=nq', label: 'PAC4200', noctx: true },
        ] },
    ];

    function navQuery() {
        try {
            if (window.PVNavContext && PVNavContext.currentQuery) {
                var q = PVNavContext.currentQuery();
                return q ? '?' + q : '';
            }
        } catch (e) { /* ignore */ }
        return '';
    }

    function makeLink(p, here) {
        var a = document.createElement('a');
        var base = p.href.replace(/\/$/, '') || '/';
        a.dataset.base = p.href;
        if (p.noctx) a.dataset.noctx = '1';
        a.href = p.href;
        a.textContent = p.label;
        a.classList.add('nav-link');
        if (p.stale && primaerStale()) {
            a.textContent += '  ⚠';
            a.title = 'Datenstand veraltet – Aktualisierung fällig';
        }
        if (base === here) a.classList.add('active');
        return a;
    }

    // Rendert eine aufklappbare Gruppe (Rollup-Untermenü). Gibt {el, active}
    // zurück — active = enthält die aktuelle Seite → Gruppe initial geöffnet
    // (inkl. übergeordneter Gruppen bei Verschachtelung).
    function makeGroup(node, here, depth) {
        var wrap = document.createElement('div');
        wrap.className = 'nav-group' + (depth ? ' nav-group-sub' : '');

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nav-group-toggle';
        var caret = document.createElement('span');
        caret.className = 'nav-caret';
        caret.textContent = '▸';
        var lbl = document.createElement('span');
        lbl.className = 'nav-group-label';
        lbl.textContent = node.group;
        btn.appendChild(caret);
        btn.appendChild(lbl);

        var panel = document.createElement('div');
        panel.className = 'nav-group-items';

        var hasActive = false;
        (node.items || []).forEach(function (child) {
            if (child.group) {
                var sub = makeGroup(child, here, depth + 1);
                if (sub.active) hasActive = true;
                panel.appendChild(sub.el);
            } else {
                var a = makeLink(child, here);
                if (a.classList.contains('active')) hasActive = true;
                panel.appendChild(a);
            }
        });

        if (hasActive) { wrap.classList.add('open'); btn.classList.add('open'); }
        btn.addEventListener('click', function () {
            var isOpen = wrap.classList.toggle('open');
            btn.classList.toggle('open', isOpen);
        });

        wrap.appendChild(btn);
        wrap.appendChild(panel);
        return { el: wrap, active: hasActive };
    }

    function buildPages(pages) {
        var here = window.location.pathname.replace(/\/$/, '') || '/';
        var wrap = document.createElement('div');
        wrap.className = 'pv-pages';
        pages.forEach(function (p) {
            if (p.sep) {
                var s = document.createElement('div');
                s.className = 'nav-separator';
                wrap.appendChild(s);
            } else if (p.group) {
                wrap.appendChild(makeGroup(p, here, 0).el);
            } else if (p.href) {
                wrap.appendChild(makeLink(p, here));
            }
        });
        return wrap;
    }

    function normalizePath(href) {
        return (String(href || '').split('?')[0].replace(/\/$/, '') || '/');
    }

    function hrefMatchesCurrent(href, herePath, hereParams) {
        var raw = String(href || '');
        var qIdx = raw.indexOf('?');
        var hrefPath = normalizePath(raw);
        if (hrefPath !== herePath) return false;
        if (qIdx < 0) return true;

        var expected = new URLSearchParams(raw.slice(qIdx + 1));
        var matched = true;
        expected.forEach(function (v, k) {
            if (hereParams.get(k) !== v) matched = false;
        });
        return matched;
    }

    function findActiveTrail(nodes, herePath, hereParams, prefix) {
        prefix = prefix || [];
        for (var i = 0; i < (nodes || []).length; i++) {
            var node = nodes[i];
            if (!node || node.sep) continue;
            if (node.group) {
                var deep = findActiveTrail(node.items || [], herePath, hereParams, prefix.concat(node.group));
                if (deep) return deep;
                continue;
            }
            if (node.href && hrefMatchesCurrent(node.href, herePath, hereParams)) {
                return prefix.concat(node.label);
            }
        }
        return null;
    }

    function hasDateNavigation(bar) {
        if (!bar) return false;
        var selectors = [
            '.pv-cal-trigger',
            '#currentDateDisplay', '#currentMonthDisplay', '#currentYearDisplay',
            '#tagDateDisplay', '#monatDateDisplay', '#jahrDateDisplay',
            '#dateLabel', '#dateDisplay',
            '.date-label',
            '#btnPeriodTag', '#btnPeriodMonat', '#btnPeriodJahr', '#btnPeriodGesamt',
            '#navPrev', '#navNext', '#navNow'
        ];
        return !!bar.querySelector(selectors.join(','));
    }

    function ensureMenuHeading(opts, bar) {
        if (!bar) return;
        if (opts && opts.showMenuHeading === false) return;
        if (hasDateNavigation(bar)) return;
        if (bar.querySelector('.pv-menu-heading-inline')) return;

        var herePath = window.location.pathname.replace(/\/$/, '') || '/';
        var hereParams = new URLSearchParams(window.location.search || '');
        var pages = (opts && opts.pages) || DEFAULT_PAGES;
        var trail = findActiveTrail(pages, herePath, hereParams, []);
        if (!trail || trail.length < 2) return;

        var h = document.createElement('span');
        h.className = 'pv-menu-heading-inline';
        h.textContent = trail.join('/');
        h.title = trail.join(' / ');

        var after = bar.querySelector('.pv-flow-quick') || bar.querySelector('.pv-burger');
        if (after && after.nextSibling) {
            bar.insertBefore(h, after.nextSibling);
        } else {
            bar.appendChild(h);
        }
    }

    // Zeit-Kontext-Query bei jedem Öffnen frisch an die Seitenlinks hängen,
    // damit der zuletzt gewählte Zeitraum über Seitenwechsel erhalten bleibt.
    function refreshPageLinks(wrap) {
        if (!wrap) return;
        var q = navQuery();
        wrap.querySelectorAll('a[data-base]').forEach(function (a) {
            var base = a.dataset.base;
            a.href = base + (a.dataset.noctx ? '' : q);
        });
    }

    function initDrawer(opts) {
        opts = opts || {};
        var bar = document.querySelector(opts.barSelector || '.top-nav-bar, .top-nav');
        if (!bar) return;
        if (document.querySelector('.pv-drawer')) return; // einmalig

        var burger = document.createElement('button');
        burger.className = 'pv-burger';
        burger.setAttribute('aria-label', 'Navigation öffnen');
        burger.innerHTML = '☰';
        bar.insertBefore(burger, bar.firstChild);

        // Direkter Flow-Schnellzugriff neben dem Menü-Button (nicht auf /flow selbst).
        var herePath = window.location.pathname.replace(/\/$/, '') || '/';
        if (herePath !== '/flow') {
            var flowBtn = document.createElement('a');
            flowBtn.className = 'pv-flow-quick';
            flowBtn.href = '/flow';
            flowBtn.setAttribute('aria-label', 'Flow-Ansicht öffnen');
            flowBtn.title = 'Flow-Ansicht';
            flowBtn.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"'
                + ' stroke-linecap="round" stroke-linejoin="round">'
                + '<path d="M4 9 H15 M12 6 L15 9 L12 12"/>'
                + '<path d="M20 15 H9 M12 12 L9 15 L12 18"/></svg><span>Flow</span>';
            bar.insertBefore(flowBtn, burger.nextSibling);
        }

        var backdrop = document.createElement('div');
        backdrop.className = 'pv-drawer-backdrop';

        var drawer = document.createElement('div');
        drawer.className = 'pv-drawer';
        var head = document.createElement('div');
        head.className = 'pv-drawer-head';
        var close = document.createElement('button');
        close.className = 'pv-drawer-close';
        close.setAttribute('aria-label', 'Schließen');
        close.innerHTML = '×';
        head.appendChild(close);
        drawer.appendChild(head);
        var pagesWrap = buildPages(opts.pages || DEFAULT_PAGES);
        drawer.appendChild(pagesWrap);

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);

        function open() {
            refreshPageLinks(pagesWrap);
            drawer.classList.add('open');
            backdrop.classList.add('open');
        }
        function shut() { drawer.classList.remove('open'); backdrop.classList.remove('open'); }
        burger.addEventListener('click', open);
        close.addEventListener('click', shut);
        backdrop.addEventListener('click', shut);
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') shut(); });

        ensureMenuHeading(opts, bar);
    }

    function attachCalendar(triggerEl, kind, getCurrent, onPick, opts) {
        if (!triggerEl) return;
        opts = opts || {};
        const input = document.createElement('input');
        input.type = kind === 'month' ? 'month' : 'date';
        input.className = 'pv-cal-input';
        if (opts.min) input.min = opts.min;
        if (opts.max) input.max = opts.max;
        (triggerEl.parentNode || document.body).appendChild(input);
        triggerEl.classList.add('pv-cal-trigger');

        input.addEventListener('change', function () {
            if (input.value) onPick(input.value);
        });

        function manualFallback(currentValue) {
            var hint = kind === 'month' ? 'YYYY-MM' : 'YYYY-MM-DD';
            var entered = window.prompt('Datum eingeben (' + hint + '):', currentValue || '');
            if (!entered) return;
            var value = String(entered).trim();
            var ok = kind === 'month'
                ? /^\d{4}-(0[1-9]|1[0-2])$/.test(value)
                : /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(value);
            if (!ok) {
                window.alert('Ungültiges Format. Bitte ' + hint + ' verwenden.');
                return;
            }
            if (opts.min && value < opts.min) {
                window.alert('Frühestes erlaubtes Datum: ' + opts.min);
                return;
            }
            if (opts.max && value > opts.max) {
                window.alert('Spätestes erlaubtes Datum: ' + opts.max);
                return;
            }
            onPick(value);
        }

        triggerEl.addEventListener('click', function (ev) {
            ev.preventDefault();
            var currentValue = '';
            try { currentValue = getCurrent() || ''; input.value = currentValue; } catch (e) { /* ignore */ }
            if (typeof input.showPicker === 'function') {
                try { input.showPicker(); return; } catch (e) { /* fallback */ }
            }
            try {
                input.focus();
                input.click();
            } catch (e) {
                manualFallback(currentValue);
                return;
            }

            // Browser ohne funktionalen nativen Picker: manuelle Eingabe anbieten.
            setTimeout(function () {
                if (document.activeElement !== input) manualFallback(currentValue);
            }, 0);
        });
    }

    window.PVNavUI = { initDrawer: initDrawer, attachCalendar: attachCalendar };

    // ── Responsive Chart-Helfer (ECharts) ──────────────────────────────
    // Gemeinsame Logik für dynamische X-Achsen-Beschriftung und tooltips,
    // die auf kleinen Bildschirmen im Viewport bleiben und nicht überlaufen.
    function isSmallScreen() {
        return window.innerWidth <= 600
            || (window.innerHeight <= 500 && window.matchMedia('(orientation: landscape)').matches);
    }

    // axisLabel-Konfiguration für Kategorie-X-Achsen. Desktop unverändert
    // (alle Labels), kleine Screens dünnen automatisch aus + verbergen Overlap.
    function xAxisLabel(labelCount, extra) {
        var small = isSmallScreen();
        var cfg = {
            interval: small ? 'auto' : 0,
            hideOverlap: true,
            rotate: (small || labelCount > 15) ? 45 : 0,
            fontSize: small ? 9 : 11
        };
        if (extra) Object.keys(extra).forEach(function (k) { cfg[k] = extra[k]; });
        return cfg;
    }

    // Tooltip-Eigenschaften: im Container halten (confine) und auf kleinen
    // Screens Größe begrenzen + ohne sichtbaren Scrollbalken scrollbar machen
    // (Klasse pv-echarts-tip, Scrollbar in nav-ui.css ausgeblendet).
    // Schwach transparenter Tooltip-"Skin": der Chart scheint dezent durch (Blur),
    // damit die Kurve unter dem Tooltip lesbar bleibt. Formatter/trigger/axisPointer
    // des Aufrufers bleiben erhalten; Hintergrund/Rahmen werden vereinheitlicht.
    function tooltipResponsive(base) {
        var cfg = base || {};
        cfg.confine = true;
        cfg.className = 'pv-echarts-tip';
        cfg.backgroundColor = 'rgba(15,23,42,0.60)';
        cfg.borderColor = 'rgba(148,163,184,0.35)';
        cfg.borderWidth = cfg.borderWidth || 1;
        cfg.textStyle = Object.assign({ color: '#e2e8f0' }, cfg.textStyle || {});
        var skin = 'backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);'
            + 'box-shadow:0 6px 20px rgba(0,0,0,0.30);border-radius:8px;';
        if (isSmallScreen()) {
            cfg.extraCssText = 'max-width:88vw;max-height:58vh;overflow-y:auto;white-space:normal;'
                + skin + (cfg.extraCssText || '');
            cfg.textStyle = Object.assign({ fontSize: 11 }, cfg.textStyle);
        } else {
            cfg.extraCssText = skin + (cfg.extraCssText || '');
        }
        return cfg;
    }

    // Obergrenze der Werteachse so, dass ein Peak-/Extremwert-Marker (Pin + Label
    // ueber dem Datenpunkt) IMMER innerhalb des Rahmens bleibt. dataMax = groesster
    // gezeichneter Serienwert; peakVal = Wert, auf dem der Marker sitzt (kann dataMax
    // uebersteigen, z. B. eine nicht gezeichnete Summenkurve). opts: {floor, cap,
    // round, headroom}. Der cap wird nur so weit angewandt, dass der Marker sichtbar bleibt.
    function peakHeadroomMax(dataMax, peakVal, opts) {
        opts = opts || {};
        var round = opts.round || 1000;
        var floor = opts.floor || 0;
        var headroom = opts.headroom != null ? opts.headroom : 0.15;
        var dMax = Number.isFinite(dataMax) ? dataMax : 0;
        var hasPeak = Number.isFinite(peakVal) && peakVal > 0;
        var top = Math.max(dMax, hasPeak ? peakVal : 0);
        top = Math.ceil((top * (1 + headroom)) / round) * round;   // Luft fuer Pin + Label
        top = Math.max(top, floor);
        if (opts.cap != null && isFinite(opts.cap)) {
            // Deckel nur so weit, dass der Peak samt Luft sichtbar bleibt.
            var needed = hasPeak ? Math.ceil((peakVal * (1 + headroom)) / round) * round : floor;
            top = Math.max(needed, Math.min(top, opts.cap));
        }
        return top;
    }

    // Erzeugungs-Marker (nur Lasten-Ansichten): kleines grünes Dreieck links am
    // Balken, dessen Spitze waagerecht auf die Höhe der PV-Erzeugung des
    // Intervalls zeigt — so ist in der gestapelten Last-Summe ablesbar, bis zu
    // welcher Höhe die Erzeugung reicht bzw. ab wann sie überschritten wird.
    // Liefert eine fertige ECharts-Scatter-Serie; `points` = [{idx: Kategorie-
    // Index, value: Erzeugung_kWh}]. Größe responsiv (Screen + Balkenanzahl).
    // Nicht in der Legende (immer sichtbar).
    function erzeugungMarkerSeries(points, opts) {
        opts = opts || {};
        var data = (points || [])
            .filter(function (p) { return p && p.value != null && p.value > 0; })
            .map(function (p) { return { value: [p.idx, p.value] }; });
        var small = isSmallScreen();
        var n = opts.count || data.length || 12;
        var size = opts.symbolSize;
        if (size == null) {
            size = small ? (n > 20 ? 6 : 8) : (n > 24 ? 8 : 10);
        }
        return {
            name: opts.name || 'Erzeugung ▶',
            type: 'scatter',
            symbol: 'triangle',
            // Spitze waagerecht nach rechts auf den Balken (Apex = Erzeugungshöhe).
            symbolRotate: opts.symbolRotate != null ? opts.symbolRotate : -90,
            symbolSize: size,
            // knapp links neben die Balkenmitte, Spitze zeigt in den Balken hinein
            symbolOffset: opts.symbolOffset || ['-110%', 0],
            itemStyle: { color: opts.color || '#2e7d32', borderColor: '#1b5e20', borderWidth: 0.5 },
            z: opts.z || 12,
            legendHoverLink: false,
            silent: opts.silent != null ? opts.silent : true,
            tooltip: { show: false },  // Achsen-Tooltip des Charts zeigt Erzeugung bereits
            data: data
        };
    }

    window.PVChart = {
        isSmallScreen: isSmallScreen,
        xAxisLabel: xAxisLabel,
        tooltipResponsive: tooltipResponsive,
        peakHeadroomMax: peakHeadroomMax,
        erzeugungMarkerSeries: erzeugungMarkerSeries
    };
})();

// ── Netzausfall-Marker (ECharts) ───────────────────────────────────────
// Datengetriebene Erkennung von Daten-Luecken (= Stromausfall ohne
// Notstrom: es liegen KEINE Messwerte vor). Liefert fertige Overlays fuer
// jeden Tages-Chart: zwei Marker-Linien (Netzausfall / Wiederkehr) + eine
// schattierte Flaeche dazwischen, in der NICHTS dargestellt wird. Zusaetzlich
// trennt breakSeriesAtGaps() Linien-Serien an der Luecke auf, damit ECharts
// NICHT ueber den Ausfall hinweg interpoliert.
(function () {
    var COL = '#d9534f';                       // Ausfall-Rot
    var AREA = 'rgba(217, 83, 79, 0.10)';      // dezente Schattierung

    function _hhmm(tsSec) {
        var d = new Date(tsSec * 1000);
        return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    }

    // Erkennt Luecken > thresholdSec zwischen aufeinanderfolgenden Punkten.
    // datapoints: Array mit epoch-Sekunden im Feld tsField (Default 'timestamp').
    function detectOutages(datapoints, opts) {
        opts = opts || {};
        var tsField = opts.tsField || 'timestamp';
        var thr = opts.thresholdSec || 1200;   // ab 20 min = Ausfall
        var pts = (datapoints || []).filter(function (d) { return d && d[tsField] != null; });
        var gaps = [];
        for (var i = 1; i < pts.length; i++) {
            var a = +pts[i - 1][tsField], b = +pts[i][tsField];
            if (b - a > thr) gaps.push({ startTs: a, endTs: b });
        }
        return { gaps: gaps, markLine: outageMarkLine(gaps), markArea: outageMarkArea(gaps) };
    }

    // Zwei vertikale Marker-Linien je Luecke: Netzausfall (Start) + Wiederkehr (Ende).
    function outageMarkLine(gaps) {
        var data = [];
        (gaps || []).forEach(function (g) {
            data.push({
                xAxis: g.startTs * 1000,
                label: { show: true, formatter: 'Netzausfall\n' + _hhmm(g.startTs), position: 'insideStartTop', color: COL, fontSize: 10 }
            });
            data.push({
                xAxis: g.endTs * 1000,
                label: { show: true, formatter: 'Wiederkehr\n' + _hhmm(g.endTs), position: 'insideEndTop', color: COL, fontSize: 10 }
            });
        });
        return {
            silent: true, symbol: 'none',
            lineStyle: { color: COL, type: 'dashed', width: 1.5, opacity: 0.9 },
            emphasis: { disabled: true },
            data: data
        };
    }

    // Schattierte Flaeche zwischen Ausfall und Wiederkehr (hier keine Daten).
    function outageMarkArea(gaps) {
        return {
            silent: true,
            itemStyle: { color: AREA },
            data: (gaps || []).map(function (g) {
                return [{ xAxis: g.startTs * 1000 }, { xAxis: g.endTs * 1000 }];
            })
        };
    }

    // #rrggbb → rgba(r,g,b,a) fuer die klassenspezifische Flaechen-Schattierung.
    function _hexA(hex, a) {
        var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
        if (!m) return AREA;
        return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')';
    }

    // Server-klassifizierte Ausfall-Events (cls/label/color/confidence/detail).
    // Ersetzt die blinde Luecken-Heuristik: Beschriftung + Farbe je Klasse
    // (Netzausfall rot, Insel/Notstrom orange, Systemunterbrechung amber,
    // unbestaetigt grau). breakSeriesAtGaps() nutzt weiter die gaps-Liste.
    function outagesFromServer(events) {
        var evs = events || [];
        var gaps = evs.map(function (e) { return { startTs: +e.start_ts, endTs: +e.end_ts }; });
        var lineData = [];
        var areaData = [];
        evs.forEach(function (e) {
            var col = e.color || COL;
            var lbl = e.label || 'Ausfall';
            if (e.confidence && e.confidence !== 'hoch') lbl += ' (?)';
            lineData.push({
                xAxis: (+e.start_ts) * 1000, lineStyle: { color: col },
                label: { show: true, formatter: lbl + '\n' + _hhmm(+e.start_ts), position: 'insideStartTop', color: col, fontSize: 10 }
            });
            lineData.push({
                xAxis: (+e.end_ts) * 1000, lineStyle: { color: col },
                label: { show: true, formatter: 'Wiederkehr\n' + _hhmm(+e.end_ts), position: 'insideEndTop', color: col, fontSize: 10 }
            });
            areaData.push([{ xAxis: (+e.start_ts) * 1000, itemStyle: { color: _hexA(col, 0.10) } }, { xAxis: (+e.end_ts) * 1000 }]);
        });
        return {
            gaps: gaps,
            markLine: {
                silent: true, symbol: 'none',
                lineStyle: { color: COL, type: 'dashed', width: 1.5, opacity: 0.9 },
                emphasis: { disabled: true },
                data: lineData
            },
            markArea: { silent: true, data: areaData }
        };
    }

    // Trennt eine [ts_ms, value]-Serie an den Luecken auf (null einfuegen),
    // damit die Linie ueber den Ausfall NICHT verbunden wird.
    function breakSeriesAtGaps(series, gaps) {
        if (!gaps || !gaps.length || !series || !series.length) return series;
        var out = series.slice();
        gaps.forEach(function (g) {
            out.push([(g.startTs + (g.endTs - g.startTs) / 2) * 1000, null]);
        });
        out.sort(function (p, q) { return p[0] - q[0]; });
        return out;
    }

    Object.assign(window.PVChart, {
        detectOutages: detectOutages,
        outagesFromServer: outagesFromServer,
        breakSeriesAtGaps: breakSeriesAtGaps
    });
})();
