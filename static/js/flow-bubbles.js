/* flow-bubbles.js — Kontext-Rollup je Flow-Bubble.
 *
 * Rollen-Reinheit (siehe AGENTS.md): Die Web-UI (Rolle B) bleibt strikt read-only.
 *  - [I] Info  : reine Navigations-/Monitoring-Links (kein Schreibpfad)      → P1.0
 *  - [D] Hinweis: reiner Guard-/Status-Hinweis (kein Link, kein Schreibpfad) → P1.3-Ansatz
 *
 * Es gibt bewusst KEINEN Schaltpfad aus dieser Datei — weder direkter POST an
 * einen Aktor noch Deep-Link in ein schaltendes Cockpit. Aus der Web-API sind
 * keinerlei Schreibvorgänge ins System erlaubt (nur lesende Navigation).
 *
 * Interaktion:
 *  - Desktop (hover): Zeiger über eine Bubble → Rollup fadet ein.
 *  - Touch (kein hover): Long-Press (~520 ms) öffnet das Rollup; ein kurzer Tap
 *    behält die bestehende Schnell-Navigation der Haupt-Bubbles bei.
 */
(function () {
    'use strict';

    var INVERTER_URLS = window.PV_INVERTER_URLS || {};

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
    // KEINE Schalt-/Schreibpfade aus den Bubbles (Rolle B read-only): weder Steuerbox-
    // Schalter noch Maschinenraum-Deep-Links. Externe http(s)-Links (z. B. WR-Direkt-API)
    // öffnen in einem neuen Tab.
    var MENU = {
        netz: { title: 'Netz', i: [
                ['Verbrauch-Monitoring', '/monitoring?view=verbrauch', true],
                ['PAC4200 · Netzqualität', '/pac4200'],
                ['Energievergleich (iMSys/SM/PAC)', '/netzqualitaet/energievergleich'],
                ['Netzkriterien', '/netzqualitaet']] },
        pv: { title: 'PV Gesamt', i: [
                ['PV-Erzeugung · Monitoring', '/monitoring?view=ertrag', true],
                ['Erzeuger-Monitoring', '/erzeuger'],
                ['PV-Übersicht', '/analyse/pv']] },
        battery: { title: 'Batterie',
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
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['⚠ Multi-Master (F1 / HA / go-e-App)', null, false,
                 'Schaltwünsche nur über Cockpit/Steuerbox — kein paralleler WebSocket-Client.']] },
        heatpump: { title: 'Wärmepumpe (WP)',
            i: [['Verbraucher-Monitoring', '/verbraucher', true],
                ['WP §14a (Leistungsnachweis)', '/verbraucher/wp-leistung']] },
        heizpatrone: { title: 'Heizpatrone (HP)',
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['Hard-Guard aktiv', null, false,
                 'HP wird bei niedrigem SOC bzw. Übertemperatur hart AUS geschaltet.']] },
        klima: { title: 'Klimaanlage',
            i: [['Verbraucher-Monitoring', '/verbraucher', true]],
            d: [['Schaltfrequenz-Cooldown', null, false,
                 'Ein aktiver Cooldown überstimmt einen Komfort-EIN-Wunsch.']] },
        f1: { title: 'F1 · steuert Wattpilot', i: [
                ['WR-Direkt (F1)', INVERTER_URLS.f1 || null, false, 'Weboberfläche/Solar-API des Wechselrichters F1.'],
                ['Erzeuger-Monitoring', '/erzeuger', true]],
            d: [['Hinweis: F1 steuert den Wattpilot', null, false, 'Nur Information — keine eigene Steuerung.']] },
        f2: { title: 'F2', i: [
                ['WR-Direkt (F2)', INVERTER_URLS.f2 || null, false, 'Weboberfläche/Solar-API des Wechselrichters F2.'],
                ['Erzeuger-Monitoring', '/erzeuger', true]] },
        f3: { title: 'F3', i: [
                ['WR-Direkt (F3)', INVERTER_URLS.f3 || null, false, 'Weboberfläche/Solar-API des Wechselrichters F3.'],
                ['Erzeuger-Monitoring', '/erzeuger', true]] }
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
                if (/^https?:/i.test(href)) { row.target = '_blank'; row.rel = 'noopener'; }
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
