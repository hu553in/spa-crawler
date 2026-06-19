import contextlib
import mimetypes
from collections.abc import Sequence
from email.message import Message
from http.client import BAD_REQUEST, MULTIPLE_CHOICES, OK
from pathlib import Path
from weakref import WeakSet

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

_ATTACHED_ROUTE_MIRROR_PAGES: WeakSet[object] = WeakSet()


def _media_type_from_content_type(content_type: str | None) -> str | None:
    """Parse and normalize media type from a Content-Type header."""
    if not content_type:
        return None
    try:
        msg = Message()
        msg["content-type"] = content_type
        media_type = msg.get_content_type()
    except Exception:
        return None
    return media_type.lower() if media_type else None


def _is_html_content_type(content_type: str | None) -> bool:
    """Return ``True`` for HTML document content types."""
    return _media_type_from_content_type(content_type) in {"text/html", "application/xhtml+xml"}


def _guess_extension_from_content_type(content_type: str | None) -> str:
    """Best-effort extension from Content-Type header (empty if unknown)."""
    ct = _media_type_from_content_type(content_type)
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
    max_query_len_for_fs_mapping: int,
) -> Path | None:
    """
    Resolve a destination path for a mirrored response.

    Selection (what is mirrored vs skipped) is handled by ``attach_route_mirror``.
    This function only maps an already-selected response URL to the filesystem,
    and still skips configured API path prefixes defensively.

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
        query_rel = safe_relative_path_for_query(raw_q, max_len=max_query_len_for_fs_mapping)
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
    route_fetch_timeout: int,
    max_query_len_for_fs_mapping: int,
    max_url_len: int,
    candidate_url_trim_chars: str,
) -> None:
    """
    Attach a Playwright route handler that mirrors responses to disk.

    Main behavior mirrors non-document responses. For ``document`` requests,
    mirroring is decided by response ``Content-Type``: HTML documents are skipped,
    non-HTML payloads are mirrored.
    """
    if ctx.page in _ATTACHED_ROUTE_MIRROR_PAGES:
        return
    _ATTACHED_ROUTE_MIRROR_PAGES.add(ctx.page)
    mirrored_urls: set[str] = set()
    inflight_urls: set[str] = set()

    async def handle_route(route: Route, request: PWRequest) -> None:
        url = URL(request.url)
        raw_q = raw_query_from_url(request.url)
        url_key = str(url)

        # Mirror only same-origin assets; pass third-party resources through unchanged.
        if url.origin() != base_url.origin():
            await route.continue_()
            return

        # Skip API endpoints early when such prefixes are configured.
        if looks_like_api_path(url.path or "/", api_path_prefixes):
            await route.continue_()
            return

        # If this URL was already mirrored (or is being mirrored right now), do not fetch it again.
        if url_key in mirrored_urls or url_key in inflight_urls:
            await route.continue_()
            return

        if request.resource_type != "document":
            destination = _destination_for_asset(
                url,
                base_url,
                out_dir,
                raw_query=raw_q,
                content_type=None,
                api_path_prefixes=api_path_prefixes,
                max_query_len_for_fs_mapping=max_query_len_for_fs_mapping,
            )
            if destination is None:
                await route.continue_()
                return

            if destination.exists():
                mirrored_urls.add(url_key)
                await route.continue_()
                return

        inflight_urls.add(url_key)
        try:
            response = await route.fetch(timeout=route_fetch_timeout)

            # Keep redirects and non-success responses untouched.
            if response.status in range(
                MULTIPLE_CHOICES, BAD_REQUEST
            ) or response.status not in range(OK, BAD_REQUEST):
                await route.fulfill(response=response)
                return

            body = await response.body()

            content_type: str | None = None
            with contextlib.suppress(Exception):
                content_type = response.headers.get("content-type")

            # HTML documents are saved from DOM via save_html(), not via route mirror.
            if request.resource_type == "document" and _is_html_content_type(content_type):
                await route.fulfill(response=response)
                return

            destination = _destination_for_asset(
                url,
                base_url,
                out_dir,
                raw_query=raw_q,
                content_type=content_type,
                api_path_prefixes=api_path_prefixes,
                max_query_len_for_fs_mapping=max_query_len_for_fs_mapping,
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
                    urls = extract_urls_from_json_bytes(
                        body, base_url, api_path_prefixes, max_url_len, candidate_url_trim_chars
                    )
                    if urls:
                        await ctx.add_requests(urls)

            await route.fulfill(response=response)

        except Exception as e:
            ctx.log.warning(f"[route-error] {request.url} ({request.resource_type}): {e!r}")
            await route.continue_()
        finally:
            inflight_urls.discard(url_key)

    await ctx.page.route("**/*", handle_route)
