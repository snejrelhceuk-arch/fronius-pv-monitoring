(function() {
    const VALID_PERIODS = new Set(['tag', 'monat', 'jahr', 'gesamt']);
    const MAX_AGE_MS = 60 * 60 * 1000;
    const CONTEXT_KEYS = ['period', 'view', 'date', 'year', 'month', 'nav_ts'];

    function formatDateISO(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
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

    window.PVNavContext = {
        MAX_AGE_MS,
        buildQuery,
        createContext,
        parse,
        applyToLinks,
        stripFromCurrentUrl,
        formatDateISO,
        contextKeys: CONTEXT_KEYS.slice(),
    };
})();