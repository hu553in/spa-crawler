() => {
    const tryUnscroll = () => {
        for (const el of [document.documentElement, document.body]) {
            if (!el) continue;
            el.style.setProperty("overflow", "auto", "important");
            el.style.setProperty("overflow-x", "auto", "important");
            el.style.setProperty("overflow-y", "auto", "important");
            el.style.setProperty("position", "static", "important");
        }
    };

    const tryHideOverlays = () => {
        document.querySelectorAll("html *").forEach((el) => {
            if (!(el instanceof HTMLElement)) return;
            const style = getComputedStyle(el);
            if (style.position === "fixed" && Number(style.zIndex) >= 999) {
                const r = el.getBoundingClientRect();
                if (
                    r.width >= window.innerWidth * 0.9 &&
                    r.height >= window.innerHeight * 0.9
                ) {
                    el.style.setProperty("display", "none", "important");
                    el.style.setProperty("pointer-events", "none", "important");
                }
            }
        });
    };

    tryUnscroll();
    tryHideOverlays();

    if (!window.__spaCrawlerModalObserver) {
        window.__spaCrawlerModalObserver = new MutationObserver(() => {
            try {
                tryUnscroll();
                tryHideOverlays();
            } catch {
                // Best-effort cleanup: ignore observer callback failures.
            }
        });
        window.__spaCrawlerModalObserver.observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
    }
};
