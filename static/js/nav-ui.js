/* nav-ui.js — gemeinsame Seiten-Schublade + Kalender-Picker.
 *
 * PVNavUI.initDrawer(opts)
 *   opts.pagesSelector : Selektor des Containers mit den Seiten-Links, der in
 *                        die Schublade verschoben wird (z. B. '.pv-pages').
 *   opts.barSelector   : Navigationsleiste, in die der Hamburger eingefügt wird.
 *   opts.title         : Überschrift der Schublade.
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
    var DEFAULT_PAGES = [
        { href: '/flow', label: 'Flow' },
        { href: '/monitoring', label: 'Monitoring' },
        { sep: true },
        { href: '/erzeuger', label: 'Analyse · Erzeuger' },
        { href: '/verbraucher', label: 'Analyse · Verbraucher' },
        { href: '/analyse/pv', label: 'PV-Übersicht' },
        { href: '/analyse/haushalt', label: 'Haushalt' },
        { href: '/analyse/amortisation', label: 'Amortisation' },
        { href: '/analyse/primaerenergie', label: '🌍 Primärenergie', stale: true },
        { sep: true },
        { href: '/netzqualitaet', label: 'Netzqualität' },
        { href: '/maschinenraum', label: 'Maschinenraum' },
    ];

    function navQuery() {
        try {
            if (window.PVNavContext) {
                var st = PVNavContext.parse(window.location.search);
                if (st.hasContext && !st.isExpired) return '?' + PVNavContext.buildQuery(st.context);
            }
        } catch (e) { /* ignore */ }
        return '';
    }

    function buildPages(pages) {
        var q = navQuery();
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
            var a = document.createElement('a');
            var base = p.href.replace(/\/$/, '') || '/';
            a.href = p.href + (p.noctx ? '' : q);
            a.textContent = p.label;
            if (p.stale && primaerStale()) {
                a.textContent += '  ⚠';
                a.title = 'Datenstand veraltet – Aktualisierung fällig';
            }
            if (base === here) a.classList.add('active');
            wrap.appendChild(a);
        });
        return wrap;
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
        head.innerHTML = '<span>' + (opts.title || 'Navigation') + '</span>';
        var close = document.createElement('button');
        close.className = 'pv-drawer-close';
        close.setAttribute('aria-label', 'Schließen');
        close.innerHTML = '×';
        head.appendChild(close);
        drawer.appendChild(head);
        drawer.appendChild(buildPages(opts.pages || DEFAULT_PAGES));

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);

        function open() { drawer.classList.add('open'); backdrop.classList.add('open'); }
        function shut() { drawer.classList.remove('open'); backdrop.classList.remove('open'); }
        burger.addEventListener('click', open);
        close.addEventListener('click', shut);
        backdrop.addEventListener('click', shut);
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') shut(); });
    }

    function attachCalendar(triggerEl, kind, getCurrent, onPick) {
        if (!triggerEl) return;
        const input = document.createElement('input');
        input.type = kind === 'month' ? 'month' : 'date';
        input.className = 'pv-cal-input';
        (triggerEl.parentNode || document.body).appendChild(input);
        triggerEl.classList.add('pv-cal-trigger');

        input.addEventListener('change', function () {
            if (input.value) onPick(input.value);
        });
        triggerEl.addEventListener('click', function (ev) {
            ev.preventDefault();
            try { input.value = getCurrent() || ''; } catch (e) { /* ignore */ }
            if (typeof input.showPicker === 'function') {
                try { input.showPicker(); return; } catch (e) { /* fallback */ }
            }
            input.focus();
            input.click();
        });
    }

    window.PVNavUI = { initDrawer: initDrawer, attachCalendar: attachCalendar };
})();
