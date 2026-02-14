() => {
    const urls = new Set();

    const add = (v) => {
        if (!v) return;
        if (typeof v === "string") {
            const s = v.trim();
            if (!s) return;
            if (
                s.startsWith("/") ||
                s.startsWith("http://") ||
                s.startsWith("https://") ||
                s.startsWith("//")
            ) {
                urls.add(s);
            }
        } else if (Array.isArray(v)) {
            v.forEach(add);
        } else if (typeof v === "object") {
            Object.values(v).forEach(add);
        }
    };

    // 1. DOM links.
    document
        .querySelectorAll('a[href], link[rel="preload"], link[rel="prefetch"]')
        .forEach((el) => add(el.getAttribute("href")));

    // 2. Next.js data.
    add(window.__NEXT_DATA__ || null);

    // 3. Common asset sources.
    document
        .querySelectorAll(
            'script[src], link[rel="stylesheet"][href], img[src], source[src], video[src], audio[src]',
        )
        .forEach((el) =>
            add(el.getAttribute("src") || el.getAttribute("href")),
        );

    // 4. Elements with srcset.
    document.querySelectorAll("source[srcset], img[srcset]").forEach((el) => {
        const srcset = el.getAttribute("srcset");
        if (!srcset) return;
        srcset.split(",").forEach((part) => {
            const url = part.trim().split(/\s+/)[0];
            add(url);
        });
    });

    return Array.from(urls).sort();
};
