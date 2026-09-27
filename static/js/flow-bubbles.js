/* flow-bubbles.js — Kontext-Rollup je Flow-Bubble.
 *
 * Rollen-Reinheit (siehe AGENTS.md): Die Web-UI (Rolle B) bleibt read-only.
 *  - [I] Info  : reine Navigations-/Monitoring-Links (kein Schreibpfad)      → P1.0
 *  - [K] Komfort: Deep-Link auf das Steuerbox-Cockpit (Schicht E)             → P1.1 / H1
 *  - [D] Deep  : Maschinenraum/pv-config bzw. reiner Hinweis (mit Rückfrage)  → P1.3-Ansatz
 *
 * Es gibt bewusst KEINEN direkten POST an einen Aktor aus dieser Datei. Komfort
 * wirkt ausschließlich über die bestehende, gehärtete Steuerbox (mTLS/Allowlist).
 *
 * Interaktion:
 *  - Desktop (hover): Zeiger über eine Bubble → Rollup fadet ein.
 *  - Touch (kein hover): Long-Press (~520 ms) öffnet das Rollup; ein kurzer Tap
 *    behält die bestehende Schnell-Navigation der Haupt-Bubbles bei.
 */
(function () {
    'use strict';

    var COCKPIT = (window.PV_STEUERBOX_URL || '').replace(/\/$/, '');
    function cockpit(hash) { return COCKPIT ? (COCKPIT + '/' + (hash || '')) : null; }

    // Zeit-Kontext-Query an Info-Links hängen (Zeitraum über Seitenwechsel halten).
    function withCtx(href) {
        if (!href || href.indexOf('http') === 0) return href;
        try {
            if (window.PVNavContext && PVNavContext.currentQuery) {
                var q = PVNavContext.currentQuery();
                if (q) return href + (href.indexOf('?') >= 0 ? '&' : '?') + q;
            }
        } catch (e) { /* ignore */ }
        return href;
    }

    // Menü-Katalog je Bubble.
    //  · i-Eintrag  = [Label, href|null, sameTab?, hint?]  (read-only Navigation)
    //  · d-Eintrag  = [Label, href|null, sameTab?, hint?]  (reiner Guard-Hinweis)
    //  · sw-Eintrag = { label, opts:[[Segment, cockpit-Anker], …] }  (Komfort-Mini-Schalter,
    //                 Optik wie das Steuerbox-Cockpit; jedes Segment ist ein Deep-Link ins
    //                 Cockpit (Schicht E) — die Web-UI (B) schaltet NICHT selbst.)
    // KEINE Maschinenraum-Deep-Links mehr aus den Bubbles (bewusst entfernt).
    var MENU = {
        netz: { title: 'Netz', i: [
                ['Verbrauch-Monitoring', '/monitoring?view=verbrauch', true],
                ['PAC4200 · Netzqualität', '/pac4200'],
                ['Energievergleich (iMSys/SM/PAC)', '/netzqualitaet/energievergleich'],
                ['Netzkriterien', '/netzqualitaet']] },
        pv: { title: 'PV Gesamt', i: [
                ['Erzeuger-Monitoring', '/erzeuger', true],
                ['PV-Übersicht', '/analyse/pv']] },
        battery: { title: 'Batterie',
            sw: [{ label: 'Modus', opts: [['AUTO', '#card-battery'], ['KOMFORT', '#card-battery']] }],
            i: [['Batterie-Analyse & Stress', '/analyse/batterie', true],
                ['Speicher-Ausbau', '/analyse/speicherausbau']],
            d: [['SOC-Matrix ändern (pv-config)', null, false,
                 'SOC-Grenzen nur über pv-config/Parametermatrix — keine Software-Ratenlimits.']] },
        consumption: { title: 'Verbrauch', i: [
                ['Verbraucher-Monitoring', '/verbraucher', true],
                ['Haushalt / Grundlast', '/analyse/haushalt']] },
        household: { title: 'Haushalt', i: [
                ['Haushalt-Analyse', '/analyse/haushalt', true],
                ['Verbraucher-Monitoring', '/verbraucher']] },
        wattpilot: { title: 'Wattpilot (Wallbox)',
            sw: [
                { label: 'Laden', opts: [['START', '#card-wattpilot'], ['STOP', '#card-wattpilot']] },
                { label: 'Modus', opts: [['ECO', '#card-wattpilot'], ['DEFAULT', '#card-wattpilot']] },
                { label: 'Ladestrom', opts: [['8A', '#card-wattpilot'], ['16A', '#card-wattpilot'], ['24A', '#card-wattpilot']] }],
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['⚠ Multi-Master (F1 / HA / go-e-App)', null, false,
                 'Schaltwünsche nur über Cockpit/Steuerbox — kein paralleler WebSocket-Client.']] },
        heatpump: { title: 'Wärmepumpe (WP)',
            sw: [{ label: 'Modus', opts: [['MIN', '#card-wp'], ['STD', '#card-wp'], ['MAX', '#card-wp']] }],
            i: [['WP-Leistung', '/wp_leistung', true]] },
        heizpatrone: { title: 'Heizpatrone (HP)',
            sw: [{ label: 'Schalten', opts: [['AUS', '#card-toggles'], ['AN', '#card-toggles']] }],
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['Hard-Guard aktiv', null, false,
                 'HP wird bei niedrigem SOC bzw. Übertemperatur hart AUS geschaltet.']] },
        klima: { title: 'Klimaanlage',
            sw: [{ label: 'Schalten', opts: [['AUS', '#card-toggles'], ['AN', '#card-toggles']] }],
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['Schaltfrequenz-Cooldown', null, false,
                 'Ein aktiver Cooldown überstimmt einen Komfort-EIN-Wunsch.']] },
        f1: { title: 'F1 · steuert Wattpilot', i: [['Erzeuger-Monitoring', '/erzeuger', true]],
            d: [['Hinweis: F1 steuert den Wattpilot', null, false, 'Nur Information — keine eigene Steuerung.']] },
        f2: { title: 'F2', i: [['Erzeuger-Monitoring', '/erzeuger', true]] },
        f3: { title: 'F3', i: [['Erzeuger-Monitoring', '/erzeuger', true]] }
    };

    var GROUP_META = {
        i: { cls: 'fb-i', label: 'Info' },
        d: { cls: 'fb-d', label: 'Hinweis' }
    };

    var overlay = null;         // aktuelles Rollup-DOM
    var openFor = null;         // Bubble-Key des offenen Rollups
    var openTimer = null, closeTimer = null;
    var suppressClickUntil = 0; // Long-Press unterdrückt den folgenden Navigations-Klick

    function clearTimers() {
        if (openTimer) { clearTimeout(openTimer); openTimer = null; }
        if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    }

    function closeRollup() {
        clearTimers();
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        overlay = null;
        openFor = null;
    }

    function makeGroup(kind, entries) {
        var meta = GROUP_META[kind];
        var g = document.createElement('div');
        g.className = 'fb-group ' + meta.cls;
        var h = document.createElement('div');
        h.className = 'fb-group-h';
        h.textContent = meta.label;
        g.appendChild(h);
        entries.forEach(function (e) {
            var label = e[0], href = e[1], hint = e[3];
            var row;
            if (href) {
                row = document.createElement('a');
                row.href = withCtx(href);
                if (hint) row.title = hint;
            } else {
                // Reiner Hinweis (kein Link) — z. B. Guard-Info.
                row = document.createElement('div');
                row.className = 'fb-note';
                if (hint) row.title = hint;
            }
            row.classList.add('fb-item');
            row.textContent = label;
            g.appendChild(row);
        });
        return g;
    }

    // Komfort-Mini-Schalter (Optik wie das Steuerbox-Cockpit). Jedes Segment ist
    // ein Deep-Link auf die passende Cockpit-Karte (Schicht E), Ziel-Tab
    // 'pv-cockpit'. Die Web-UI (Rolle B) schaltet bewusst NICHT selbst — sie
    // verlinkt nur; der Schreibpfad bleibt exklusiv bei der gehärteten Steuerbox.
    function makeSwitchRow(sw) {
        var row = document.createElement('div');
        row.className = 'fb-switch';
        var h = document.createElement('span');
        h.className = 'fb-switch-h';
        h.textContent = sw.label;
        row.appendChild(h);
        var seg = document.createElement('div');
        seg.className = 'fb-switch-seg';
        sw.opts.forEach(function (o) {
            var url = cockpit(o[1]);
            var b;
            if (url) {
                b = document.createElement('a');
                b.href = url;
                b.target = 'pv-cockpit';
                b.rel = 'noopener';
                b.title = sw.label + ' im Steuerbox-Cockpit schalten';
            } else {
                b = document.createElement('span');
                b.title = 'Steuerbox-Cockpit nicht erreichbar konfiguriert.';
            }
            b.className = 'fb-seg';
            b.textContent = o[0];
            seg.appendChild(b);
        });
        row.appendChild(seg);
        return row;
    }

    function makeSwitchGroup(switches) {
        var g = document.createElement('div');
        g.className = 'fb-group fb-k';
        var h = document.createElement('div');
        h.className = 'fb-group-h';
        h.textContent = 'Komfort · Cockpit';
        g.appendChild(h);
        switches.forEach(function (sw) { g.appendChild(makeSwitchRow(sw)); });
        return g;
    }

    function buildRollup(key) {
        var cfg = MENU[key];
        if (!cfg) return null;
        var box = document.createElement('div');
        box.className = 'fb-rollup';
        box.setAttribute('role', 'menu');

        var title = document.createElement('div');
        title.className = 'fb-rollup-title';
        title.textContent = cfg.title;
        box.appendChild(title);

        if (cfg.sw && cfg.sw.length) box.appendChild(makeSwitchGroup(cfg.sw));

        ['i', 'd'].forEach(function (kind) {
            var entries = cfg[kind];
            if (!entries || !entries.length) return;
            box.appendChild(makeGroup(kind, entries));
        });

        // Interaktion innerhalb des Rollups hält es offen.
        box.addEventListener('mouseenter', clearTimers);
        box.addEventListener('mouseleave', scheduleClose);
        return box;
    }

    function positionRollup(box, anchorEl) {
        var r = anchorEl.getBoundingClientRect();
        box.style.visibility = 'hidden';
        document.body.appendChild(box);
        var bw = box.offsetWidth, bh = box.offsetHeight;
        var margin = 8;
        // Bevorzugt rechts neben der Bubble; sonst links; vertikal an Bubble zentriert.
        var left = r.right + margin;
        if (left + bw > window.innerWidth - margin) left = r.left - bw - margin;
        if (left < margin) left = Math.max(margin, (window.innerWidth - bw) / 2);
        var top = r.top + r.height / 2 - bh / 2;
        top = Math.max(margin, Math.min(top, window.innerHeight - bh - margin));
        box.style.left = Math.round(left) + 'px';
        box.style.top = Math.round(top) + 'px';
        box.style.visibility = 'visible';
    }

    function openRollup(key, anchorEl) {
        if (openFor === key && overlay) return;
        closeRollup();
        var box = buildRollup(key);
        if (!box) return;
        overlay = box;
        openFor = key;
        positionRollup(box, anchorEl);
        requestAnimationFrame(function () { if (overlay) overlay.classList.add('fb-show'); });
    }

    function scheduleOpen(key, anchorEl) {
        clearTimers();
        openTimer = setTimeout(function () { openRollup(key, anchorEl); }, 130);
    }
    function scheduleClose() {
        clearTimers();
        closeTimer = setTimeout(closeRollup, 260);
    }

    function bind(el) {
        var key = el.getAttribute('data-bubble');
        if (!key || !MENU[key]) return;
        var hoverCapable = window.matchMedia && window.matchMedia('(hover: hover)').matches;

        if (hoverCapable) {
            el.addEventListener('mouseenter', function () { scheduleOpen(key, el); });
            el.addEventListener('mouseleave', scheduleClose);
        }

        // Touch: Long-Press öffnet das Rollup; kurzer Tap → bestehende Navigation.
        var lpTimer = null, startX = 0, startY = 0, moved = false;
        el.addEventListener('touchstart', function (ev) {
            var t = ev.touches[0]; startX = t.clientX; startY = t.clientY; moved = false;
            lpTimer = setTimeout(function () {
                lpTimer = null;
                suppressClickUntil = Date.now() + 900;
                openRollup(key, el);
            }, 520);
        }, { passive: true });
        el.addEventListener('touchmove', function (ev) {
            var t = ev.touches[0];
            if (Math.abs(t.clientX - startX) > 10 || Math.abs(t.clientY - startY) > 10) {
                moved = true;
                if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
            }
        }, { passive: true });
        el.addEventListener('touchend', function () {
            if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
        });
    }

    // Long-Press-Navigations-Klick unterdrücken (Capture-Phase, vor den Bubble-Handlern).
    document.addEventListener('click', function (ev) {
        if (Date.now() < suppressClickUntil) {
            var b = ev.target && ev.target.closest ? ev.target.closest('[data-bubble]') : null;
            if (b) { ev.preventDefault(); ev.stopPropagation(); }
        }
    }, true);

    // Außerhalb schließen / Escape.
    document.addEventListener('click', function (ev) {
        if (!overlay) return;
        if (ev.target.closest && (ev.target.closest('.fb-rollup') || ev.target.closest('[data-bubble]'))) return;
        closeRollup();
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeRollup(); });
    window.addEventListener('resize', closeRollup);

    function init() {
        var els = document.querySelectorAll('#flow-svg [data-bubble]');
        els.forEach(bind);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.PVFlowBubbles = { close: closeRollup };
})();
