import contextlib
from pathlib import Path

from crawlee.crawlers import PlaywrightCrawlingContext, PlaywrightPreNavCrawlingContext
from playwright.async_api import Download
from yarl import URL

from spa_crawler.constants import MAX_QUERY_LEN_FOR_FS_MAPPING
from spa_crawler.js_scripts import load_js
from spa_crawler.utils import (
    raw_query_from_url,
    safe_relative_path_for_page,
    safe_relative_path_for_query,
)


async def _dismiss_overlays(ctx: PlaywrightCrawlingContext) -> None:
    """
    Best-effort UI cleanup:
      - Press Escape.
      - Click the top-left corner.
      - Run an overlay-hiding script (mutation observer + overflow reset).
    """
    with contextlib.suppress(Exception):
        await ctx.page.keyboard.press("Escape")
    with contextlib.suppress(Exception):
        await ctx.page.mouse.click(0, 0)
    with contextlib.suppress(Exception):
        await ctx.page.evaluate(load_js("dismiss_overlays.js"))


def maybe_attach_download_hook(
    ctx: PlaywrightCrawlingContext | PlaywrightPreNavCrawlingContext, verbose: bool
) -> None:
    """Log downloads triggered by the page (useful for debugging)."""
    with contextlib.suppress(Exception):
        if getattr(ctx.page, "_download_hook_attached", False):
            return
        ctx.page._download_hook_attached = True  # type: ignore[attr-defined]

        def _on_download(download: Download) -> None:
            if verbose:
                ctx.log.info(f"[download] {download.url}")

        ctx.page.on("download", _on_download)


async def save_html(ctx: PlaywrightCrawlingContext, out_dir: Path, verbose: bool) -> None:
    """Save the current DOM snapshot as pages/<path>/index.html."""
    loaded_url = ctx.request.loaded_url or ctx.request.url
    url = URL(loaded_url)
    relative_path = safe_relative_path_for_page(url)
    raw_q = raw_query_from_url(loaded_url)

    if raw_q:
        query_rel = safe_relative_path_for_query(raw_q, max_len=MAX_QUERY_LEN_FOR_FS_MAPPING)
        if query_rel is None:
            ctx.log.warning(f"[save-skipped-unsafe-query] {url!s}")
            return
        html_path = out_dir / "pages_q" / relative_path / query_rel / "index.html"
    else:
        html_path = out_dir / "pages" / relative_path / "index.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        html_path.write_text(await ctx.page.content(), encoding="utf-8")
    except Exception:
        ctx.log.exception(f"[save-failed] {url!s} -> {html_path}")
        return

    if verbose:
        ctx.log.info(f"[saved] {url!s} -> {html_path}")


async def wait_for_stable_page(
    ctx: PlaywrightCrawlingContext,
    dom_content_loaded_timeout: int,
    network_idle_timeout: int,
    rerender_timeout: int | None = None,
) -> None:
    """Wait for DOMContentLoaded + networkidle (and optional extra delay)."""
    with contextlib.suppress(Exception):
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=dom_content_loaded_timeout)
    with contextlib.suppress(Exception):
        await ctx.page.wait_for_load_state("networkidle", timeout=network_idle_timeout)
    if rerender_timeout:
        with contextlib.suppress(Exception):
            await ctx.page.wait_for_timeout(rerender_timeout)


async def close_page(ctx: PlaywrightCrawlingContext) -> None:
    """Best-effort page close (prevents browser context buildup)."""
    with contextlib.suppress(Exception):
        await ctx.page.close()


async def soft_interaction_pass(ctx: PlaywrightCrawlingContext) -> None:
    """
    A light "poke" to encourage SPA content to load:
      - Run infinite scroll.
      - Dismiss overlays.
      - Run infinite scroll again.
    """
    with contextlib.suppress(Exception):
        await ctx.infinite_scroll()
    await _dismiss_overlays(ctx)
    with contextlib.suppress(Exception):
        await ctx.infinite_scroll()
