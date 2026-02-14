import contextlib
import mimetypes
from collections.abc import Sequence
from pathlib import Path

from crawlee.crawlers import PlaywrightCrawlingContext, PlaywrightPreNavCrawlingContext
from playwright.async_api import Request as PWRequest
from playwright.async_api import Route
from yarl import URL

from spa_crawler.url_discovery import extract_urls_from_json_bytes, looks_like_api_path
from spa_crawler.utils import (
    raw_query_from_url,
    safe_relative_path_for_asset,
    safe_relative_path_for_page,
    safe_relative_path_for_query,
)

_OK_STATUS = 200
_SUCCESS_RANGE = range(_OK_STATUS, 400)
_REDIRECT_RANGE = range(300, 400)

_MAX_QUERY_LEN = 8000
_ROUTE_FETCH_TIMEOUT_MS = 60_000


def _guess_extension_from_content_type(content_type: str | None) -> str:
    """Best-effort extension from Content-Type header (empty if unknown)."""
    if not content_type:
        return ""
    ct = content_type.split(";", 1)[0].strip().lower()
    if not ct:
        return ""
    ext = mimetypes.guess_extension(ct, strict=False) or ""
    # ``mimetypes`` may return ``.jpe``; normalize to the common ``.jpg``.
    return ".jpg" if ext == ".jpe" else ext


def _destination_for_asset(
    url: URL,
    base_url: URL,
    out_dir: Path,
    *,
    raw_query: str | None = None,
    content_type: str | None,
    api_path_prefixes: Sequence[str],
) -> Path | None:
    """
    Resolve a destination path for an asset response.

    We aim for a "complete SPA scrape":
      - Save all same-origin non-document responses.
      - Skip API responses (configurable via ``api_path_prefixes``).

    Query strategy (needed for Caddy mapping without rewriting HTML):
      - Query assets -> ``out_dir/assets_q/<path>/<raw_query>`` (no extension rewriting).
      - Non-query assets -> ``out_dir/assets/<path>[.<ext or .bin>]``.
    """
    if url.origin() != base_url.origin():
        return None

    path = url.path or "/"
    if looks_like_api_path(path, api_path_prefixes):
        return None

    rel = safe_relative_path_for_asset(url)
    raw_q = raw_query if raw_query is not None else url.raw_query_string

    if raw_q:
        # Important: do not change the query string; Caddy looks up ``{query}`` verbatim.
        # If query is unsafe/unmappable, skip saving this asset entirely.
        query_rel = safe_relative_path_for_query(raw_q, max_len=_MAX_QUERY_LEN)
        if query_rel is None:
            return None

        return out_dir / "assets_q" / safe_relative_path_for_page(url) / query_rel

    # Non-query assets -> normal assets tree. Add extension only if URL path had none;
    # Caddy can fall back to ".bin" in that case.
    target = out_dir / "assets" / rel
    if not target.suffix:
        target = target.with_suffix(_guess_extension_from_content_type(content_type) or ".bin")
    return target


def _write_asset_overwrite(path: Path, data: bytes) -> bool:
    """
    Write bytes to disk using a stable filename (Caddy-mappable).

    No dedup, no hashed alternatives:
      - Always write to the resolved path.
      - If write fails, return ``False`` (asset will not exist).
    """
    if not data:
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True
    except Exception:
        return False


async def attach_route_mirror(
    ctx: PlaywrightCrawlingContext | PlaywrightPreNavCrawlingContext,
    base_url: URL,
    out_dir: Path,
    verbose: bool,
    api_path_prefixes: Sequence[str],
) -> None:
    """
    Attach a Playwright route handler that mirrors all non-document responses to disk.

    This is the main mechanism for "download all assets" without parsing HTML.
    """
    if getattr(ctx.page, "_route_mirror_attached", False):
        return
    ctx.page._route_mirror_attached = True  # type: ignore[attr-defined]
    mirrored_urls: set[str] = set()
    inflight_urls: set[str] = set()

    async def handle_route(route: Route, request: PWRequest) -> None:
        # HTML documents are saved from DOM via save_html().
        if request.resource_type == "document":
            await route.continue_()
            return

        url = URL(request.url)
        raw_q = raw_query_from_url(request.url)
        url_key = str(url)

        # Mirror only same-origin assets; pass third-party resources through unchanged.
        if url.origin() != base_url.origin():
            await route.continue_()
            return

        # Skip API endpoints early (avoid downloading huge JSON responses).
        if looks_like_api_path(url.path or "/", api_path_prefixes):
            await route.continue_()
            return

        # If this URL was already mirrored (or is being mirrored right now), do not fetch it again.
        if url_key in mirrored_urls or url_key in inflight_urls:
            await route.continue_()
            return

        destination_hint = _destination_for_asset(
            url,
            base_url,
            out_dir,
            raw_query=raw_q,
            content_type=None,
            api_path_prefixes=api_path_prefixes,
        )
        if destination_hint is None:
            await route.continue_()
            return

        if destination_hint.exists():
            mirrored_urls.add(url_key)
            await route.continue_()
            return

        inflight_urls.add(url_key)
        try:
            response = await route.fetch(timeout=_ROUTE_FETCH_TIMEOUT_MS)

            # Keep redirects and non-success responses untouched.
            if response.status in _REDIRECT_RANGE or response.status not in _SUCCESS_RANGE:
                await route.fulfill(response=response)
                return

            body = await response.body()

            content_type: str | None = None
            with contextlib.suppress(Exception):
                content_type = response.headers.get("content-type")

            destination = _destination_for_asset(
                url,
                base_url,
                out_dir,
                raw_query=raw_q,
                content_type=content_type,
                api_path_prefixes=api_path_prefixes,
            )

            written = False
            if destination and body:
                written = _write_asset_overwrite(destination, body)
                if not written:
                    ctx.log.warning(f"[asset-write-failed] {url!s} -> {destination}")
                else:
                    mirrored_urls.add(url_key)

            if verbose and written and destination:
                ctx.log.info(f"[asset] {url!s} -> {destination}")

            # Preserve original behavior: extract crawlable page URLs from Next.js data JSON.
            with contextlib.suppress(Exception):
                path = url.path or ""
                if "/_next/data/" in path and path.endswith(".json") and body:
                    urls = extract_urls_from_json_bytes(body, base_url, api_path_prefixes)
                    if urls:
                        await ctx.add_requests(urls)

            await route.fulfill(response=response)

        except Exception as e:
            ctx.log.warning(f"[route-error] {request.url} ({request.resource_type}): {e!r}")
            await route.continue_()
        finally:
            inflight_urls.discard(url_key)

    await ctx.page.route("**/*", handle_route)
