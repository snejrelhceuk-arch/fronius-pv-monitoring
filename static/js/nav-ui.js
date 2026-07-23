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

    // Vollständiges Seiten-Menü (Reihenfolge = Anzeige). Zeitkontext wird via
    // PVNavContext als Query angehängt, damit der Zeitraum erhalten bleibt.
    // Typen: {href,label} Link · {heading} fette Überschrift · {href,label,sub}
    // eingerückter Unterpunkt · {sep} Trennlinie.
    var DEFAULT_PAGES = [
        { href: '/flow', label: 'Flow' },
        { href: '/monitoring', label: 'Monitoring' },
        { sep: true },
        { heading: 'Analyse' },
        { href: '/erzeuger', label: 'Erzeuger', sub: true },
        { href: '/verbraucher', label: 'Verbraucher', sub: true },
        { href: '/analyse/pv', label: 'PV-Übersicht', sub: true },
        { href: '/analyse/haushalt', label: 'Haushalt', sub: true },
        { href: '/analyse/amortisation', label: 'Amortisation', sub: true },
        { href: '/analyse/primaerenergie', label: '🌍 Primärenergie', sub: true, stale: true },
        { sep: true },
        { href: '/maschinenraum', label: 'Darstellung aller Einzelwerte' },
        { href: '/maschinenraum', label: 'PV-System', sub: true },
        { href: '/maschinenraum?db=nq', label: 'PAC4200', sub: true, noctx: true },
        { href: '/netzqualitaet/chart', label: 'NQ-Event-Chart', sub: true },
        { href: '/netzqualitaet/live', label: 'NQ-Screens', sub: true },
        { href: '/pac4200', label: 'PAC4200-Klon', sub: true },
        { href: '/netzqualitaet', label: 'Netzkriterien', sub: true },
        { href: '/netzqualitaet/analyse', label: 'Netzmusteranalyse', sub: true },
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

    function buildPages(pages) {
        var here = window.location.pathname.replace(/\/$/, '') || '/';
        var wrap = document.createElement('div');
        wrap.className = 'pv-pages';
        pages.forEach(function (p) {
            if (p.sep) {
                var s = document.createElement('div');
                s.className = 'nav-separator';
                wrap.appendChild(s);
                return;
            }
            if (p.heading) {
                var h = document.createElement('div');
                h.className = 'nav-heading';
                h.textContent = p.heading;
                wrap.appendChild(h);
                return;
            }
            var a = document.createElement('a');
            var base = p.href.replace(/\/$/, '') || '/';
            a.dataset.base = p.href;
            if (p.noctx) a.dataset.noctx = '1';
            a.href = p.href;
            a.textContent = p.label;
            if (p.sub) a.classList.add('nav-subitem');
            if (p.stale && primaerStale()) {
                a.textContent += '  ⚠';
                a.title = 'Datenstand veraltet – Aktualisierung fällig';
            }
            if (base === here) a.classList.add('active');
            wrap.appendChild(a);
        });
        return wrap;
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
    function tooltipResponsive(base) {
        var cfg = base || {};
        cfg.confine = true;
        cfg.className = 'pv-echarts-tip';
        if (isSmallScreen()) {
            cfg.extraCssText = 'max-width:88vw;max-height:58vh;overflow-y:auto;white-space:normal;'
                + (cfg.extraCssText || '');
            cfg.textStyle = Object.assign({ fontSize: 11 }, cfg.textStyle || {});
        }
        return cfg;
    }

    window.PVChart = {
        isSmallScreen: isSmallScreen,
        xAxisLabel: xAxisLabel,
        tooltipResponsive: tooltipResponsive
    };
})();
