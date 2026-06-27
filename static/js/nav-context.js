(function() {
    const VALID_PERIODS = new Set(['tag', 'monat', 'jahr', 'gesamt']);
    const MAX_AGE_MS = 60 * 60 * 1000;
    const CONTEXT_KEYS = ['period', 'view', 'date', 'year', 'month', 'nav_ts'];

    function formatDateISO(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    // Tag-im-Monat begrenzen (z. B. 31. -> 28./30. beim Monatswechsel).
    function clampDayOfMonth(year, month1, day) {
        const daysInMonth = new Date(year, month1, 0).getDate();
        return Math.min(Math.max(day, 1), daysInMonth);
    }

    // Einheitliches Anker-Modell: hält date/year/month konsistent zu EINEM Zeitpunkt,
    // damit ein Auflösungswechsel (Tag<->Monat<->Jahr) den Zeitraum behält.
    // anchor = { date: Date, year: Number, month: Number }
    function syncAnchorFrom(anchor, source) {
        if (source === 'date') {
            anchor.year = anchor.date.getFullYear();
            anchor.month = anchor.date.getMonth() + 1;
        } else {
            // 'month' oder 'year': abgeleitetes Datum auf den Anker-Tag im Monat setzen
            const day = clampDayOfMonth(anchor.year, anchor.month, anchor.date.getDate());
            anchor.date = new Date(anchor.year, anchor.month - 1, day, 12, 0, 0);
        }
        return anchor;
    }

    function createContext(period, currentDate, currentYear, currentMonth) {
        const context = { period: VALID_PERIODS.has(period) ? period : 'tag' };

        if (context.period === 'tag') {
            context.date = formatDateISO(currentDate || new Date());
        } else if (context.period === 'monat') {
            context.year = Number(currentYear) || new Date().getFullYear();
            context.month = Number(currentMonth) || (new Date().getMonth() + 1);
        } else if (context.period === 'jahr') {
            context.year = Number(currentYear) || new Date().getFullYear();
        }

        return context;
    }

    function buildQuery(context, nowMs = Date.now()) {
        const normalized = createContext(
            context && context.period,
            context && context.date ? new Date(`${context.date}T12:00:00`) : new Date(),
            context && context.year,
            context && context.month
        );
        const params = new URLSearchParams();
        params.set('period', normalized.period);

        if (normalized.period === 'tag') {
            params.set('date', normalized.date);
        } else if (normalized.period === 'monat') {
            params.set('year', String(normalized.year));
            params.set('month', String(normalized.month));
        } else if (normalized.period === 'jahr') {
            params.set('year', String(normalized.year));
        }

        params.set('nav_ts', String(Math.trunc(nowMs)));
        return params.toString();
    }

    function parse(search = window.location.search, nowMs = Date.now()) {
        const params = search instanceof URLSearchParams ? search : new URLSearchParams(search);
        const period = params.get('period') || params.get('view');
        if (!VALID_PERIODS.has(period)) {
            return { hasContext: false, isExpired: false, context: null };
        }

        const navTsRaw = params.get('nav_ts');
        const navTs = navTsRaw === null ? null : Number(navTsRaw);
        const isExpired = Number.isFinite(navTs) && Math.abs(nowMs - navTs) > MAX_AGE_MS;
        const now = new Date(nowMs);
        const context = { period };

        if (period === 'tag') {
            const date = params.get('date');
            context.date = /^\d{4}-\d{2}-\d{2}$/.test(date || '') ? date : formatDateISO(now);
        } else if (period === 'monat') {
            context.year = parseInt(params.get('year'), 10) || now.getFullYear();
            context.month = parseInt(params.get('month'), 10) || (now.getMonth() + 1);
        } else if (period === 'jahr') {
            context.year = parseInt(params.get('year'), 10) || now.getFullYear();
        }

        return { hasContext: true, isExpired, context, navTs };
    }

    function applyToLinks(links, context) {
        const query = buildQuery(context);
        Object.entries(links).forEach(([id, base]) => {
            const el = document.getElementById(id);
            if (el) {
                el.href = query ? `${base}?${query}` : base;
            }
        });
    }

    function stripFromCurrentUrl(preserveKeys = []) {
        const url = new URL(window.location.href);
        const preserved = new URLSearchParams();
        const preserve = new Set(preserveKeys);

        url.searchParams.forEach((value, key) => {
            if (preserve.has(key)) {
                preserved.append(key, value);
            }
        });

        const nextSearch = preserved.toString();
        const nextUrl = `${url.pathname}${nextSearch ? `?${nextSearch}` : ''}${url.hash}`;
        window.history.replaceState(null, '', nextUrl);
    }

    // ── Zentraler Zeit-Navigations-Speicher ─────────────────────────────
    // Eine Quelle der Wahrheit für period/date/year/month über alle Charts:
    // commit() schreibt URL (replaceState) + localStorage; getState() liest
    // URL zuerst, dann localStorage. Verfall nach MAX_AGE_MS (1 h Inaktivität).
    const STORAGE_KEY = 'pvNavState';

    function readStorage(nowMs) {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const obj = JSON.parse(raw);
            if (!obj || !obj.context || !obj.savedAt) return null;
            if (Math.abs(nowMs - obj.savedAt) > MAX_AGE_MS) return null;
            if (!VALID_PERIODS.has(obj.context.period)) return null;
            return obj.context;
        } catch (e) {
            return null;
        }
    }

    // Liefert den aktuell gültigen Kontext { context, source } oder null.
    // Priorität: URL-Query (frisch) > localStorage (frisch) > null (=> Default).
    function getState(nowMs = Date.now()) {
        const fromUrl = parse(window.location.search, nowMs);
        if (fromUrl.hasContext && !fromUrl.isExpired) {
            return { context: fromUrl.context, source: 'url' };
        }
        const fromStore = readStorage(nowMs);
        if (fromStore) return { context: fromStore, source: 'storage' };
        return null;
    }

    // Schreibt den Zeit-Navigations-Kontext zentral: localStorage + URL.
    // Hält Schubladen-Links, Seitenwechsel und Reload konsistent.
    function commit(context, opts = {}) {
        const normalized = createContext(
            context && context.period,
            context && context.date ? new Date(`${context.date}T12:00:00`) : new Date(),
            context && context.year,
            context && context.month
        );
        const savedAt = Date.now();
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({ context: normalized, savedAt }));
        } catch (e) { /* localStorage evtl. nicht verfügbar */ }

        if (opts.updateUrl !== false) {
            try {
                const url = new URL(window.location.href);
                const preserve = new Set(opts.preserveKeys || ['embed']);
                const params = new URLSearchParams();
                // Nicht-Kontext-Parameter bewahren (z. B. embed).
                url.searchParams.forEach((value, key) => {
                    if (preserve.has(key) && !CONTEXT_KEYS.includes(key)) params.append(key, value);
                });
                // Kontext-Query anhängen.
                new URLSearchParams(buildQuery(normalized, savedAt)).forEach((value, key) => {
                    params.set(key, value);
                });
                const search = params.toString();
                window.history.replaceState(null, '', `${url.pathname}${search ? `?${search}` : ''}${url.hash}`);
            } catch (e) { /* ignore */ }
        }
        return normalized;
    }

    // Query-String (ohne '?') aus dem aktuell gültigen Kontext, sonst ''.
    function currentQuery(nowMs = Date.now()) {
        const st = getState(nowMs);
        return st ? buildQuery(st.context, nowMs) : '';
    }

    window.PVNavContext = {
        MAX_AGE_MS,
        buildQuery,
        createContext,
        parse,
        applyToLinks,
        stripFromCurrentUrl,
        formatDateISO,
        clampDayOfMonth,
        syncAnchorFrom,
        commit,
        getState,
        currentQuery,
        contextKeys: CONTEXT_KEYS.slice(),
    };
})();