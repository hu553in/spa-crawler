import contextlib
import hashlib
import json
import logging
import mimetypes
import re
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from crawlee import Request
from crawlee.crawlers import (
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
    PlaywrightPreNavCrawlingContext,
)
from crawlee.http_clients import ImpitHttpClient
from crawlee.sessions import SessionPool
from playwright.async_api import Download, Route
from playwright.async_api import Error as PWError
from playwright.async_api import Request as PWRequest
from yarl import URL

from spa_crawler.config import CrawlConfig

_OK_STATUS = 200
_SUCCESS_RANGE = range(_OK_STATUS, 400)
_REDIRECT_RANGE = range(300, 400)

_UNICODE_ESCAPE_REGEX = re.compile(r"\\u([0-9a-fA-F]{4})")

_ABSOLUTE_URL_REGEX = re.compile(r"https?://[^\s\"'<>]+")
_PROTOCOL_RELATIVE_URL_REGEX = re.compile(r"//[^\s\"'<>]+")
_QUOTED_ABSOLUTE_PATH_REGEX = re.compile(r'["\'](/[^"\']+)["\']')

_NEXT_DATA_JSON_REGEX = re.compile(
    r'<script[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)

_MAX_URL_LEN = 2048


def _unescape_slashes(s: str) -> str:
    return s.rstrip("\\").replace("\\/", "/").replace("\\\\", "\\")


def _unescape_unicode(s: str) -> str:
    return _UNICODE_ESCAPE_REGEX.sub(lambda m: chr(int(m.group(1), 16)), s)


def _has_allowed_prefix(s: str | None) -> bool:
    return bool(s and (s.startswith("http://") or s.startswith("https://") or s.startswith("/")))


def _has_known_extension(path: str | Path) -> bool:
    p = Path(path)
    return bool(p.suffix and mimetypes.guess_type(p.name, strict=False)[0])


def _looks_like_asset(path: str) -> bool:
    return "/_next/" in path or _has_known_extension(path)


def _looks_like_api(path: str) -> bool:
    return "/api/" in path


def _safe_path_from_url(url: URL) -> Path | None:
    path = url.path_safe.lstrip("/")
    if not path or path.endswith("/"):
        return None
    return Path(path)


def _canonicalize_page_url(u: URL) -> URL:
    u = u.with_fragment(None)
    path = u.path or "/"
    if path != "/" and path.endswith("/"):
        u = u.with_path(path.rstrip("/"))
    return u


def _destination_for_asset(url: URL, base_url: URL, out_dir: Path) -> Path | None:
    if url.origin() != base_url.origin():
        return None

    path = url.path
    if _looks_like_api(path) or not _looks_like_asset(path):
        return None

    relative_path = _safe_path_from_url(url)
    if not relative_path:
        return None
    return out_dir / "assets" / relative_path


def _normalize_candidate_url(raw: str, base: URL) -> str | None:
    s = (raw or "").strip().strip(" \t\r\n'\"`")
    if not _has_allowed_prefix(s):
        return None

    s = _unescape_unicode(_unescape_slashes(s))

    if len(s) > _MAX_URL_LEN:
        return None

    try:
        u = base.join(URL(s))
    except Exception:
        return None

    if u.scheme not in ("http", "https") or u.origin() != base.origin():
        return None

    path = u.path or "/"
    if _looks_like_api(path) or _looks_like_asset(path):
        return None

    return str(_canonicalize_page_url(u))


def _iter_string_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for v in value.values():
            yield from _iter_string_values(v)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for v in value:
            yield from _iter_string_values(v)


def _extract_urls_from_json_bytes(data: bytes, base_url: URL) -> list[str]:
    if not data:
        return []

    try:
        parsed: Any = json.loads(data)
    except Exception:
        return []

    found = {
        normalized
        for s in _iter_string_values(parsed)
        if s and (normalized := _normalize_candidate_url(s, base_url))
    }
    return sorted(found)


def _extract_next_data_json_from_html(html: str) -> str | None:
    if not html:
        return None
    if m := _NEXT_DATA_JSON_REGEX.search(html):
        return m.group(1).strip() or None
    return None


def _extract_urls_from_text(text: str, base_url: URL) -> list[str]:
    if not text:
        return []

    found = {
        normalized
        for regex in (
            _ABSOLUTE_URL_REGEX,
            _PROTOCOL_RELATIVE_URL_REGEX,
            _QUOTED_ABSOLUTE_PATH_REGEX,
        )
        for raw in regex.findall(_unescape_slashes(text))
        if (normalized := _normalize_candidate_url(raw, base_url))
    }
    return sorted(found)


def _write_asset_dedup(path: Path, data: bytes) -> Path | None:
    if not data:
        return None

    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_bytes(data)
        return path

    try:
        existing = path.read_bytes()
    except Exception:
        existing = b""

    if existing == data:
        return None

    h = hashlib.sha256(data).hexdigest()[:10]
    alt = path.with_name(f"{path.stem}.{h}{path.suffix}")
    if alt.exists():
        return None

    alt.write_bytes(data)
    return alt


async def _attach_route_mirror(
    ctx: PlaywrightCrawlingContext | PlaywrightPreNavCrawlingContext,
    base_url: URL,
    out_dir: Path,
    verbose: bool,
) -> None:
    if getattr(ctx.page, "_route_mirror_attached", False):
        return
    ctx.page._route_mirror_attached = True  # type: ignore[attr-defined]

    async def handle_route(route: Route, request: PWRequest) -> None:
        url = URL(request.url)
        destination = _destination_for_asset(url, base_url, out_dir)

        if request.resource_type == "document" or not destination:
            await route.continue_()
            return

        try:
            response = await route.fetch()

            if response.status in _REDIRECT_RANGE:
                await route.fulfill(response=response)
                return

            if response.status not in _SUCCESS_RANGE:
                await route.fulfill(response=response)
                return

            body = await response.body()

            written_path = None
            with contextlib.suppress(Exception):
                written_path = _write_asset_dedup(destination, body)

            if verbose and written_path:
                with contextlib.suppress(Exception):
                    ctx.log.info(f"[asset] {url!s} -> {written_path}")

            with contextlib.suppress(Exception):
                path = url.path or ""
                if "/_next/data/" in path and path.endswith(".json") and body:
                    urls = _extract_urls_from_json_bytes(body, base_url)
                    if urls:
                        await ctx.add_requests(urls)

            await route.fulfill(response=response)
        except Exception as e:
            if verbose:
                with contextlib.suppress(Exception):
                    ctx.log.warning(f"[route-error] {request.url} ({request.resource_type}): {e!r}")
            await route.continue_()

    await ctx.page.route("**/*", handle_route)


def _maybe_attach_download_hook(
    ctx: PlaywrightCrawlingContext | PlaywrightPreNavCrawlingContext, verbose: bool
) -> None:
    with contextlib.suppress(Exception):
        if getattr(ctx.page, "_download_hook_attached", False):
            return
        ctx.page._download_hook_attached = True  # type: ignore[attr-defined]

        def _on_download(download: Download) -> None:
            if verbose:
                with contextlib.suppress(Exception):
                    ctx.log.info(f"[download] {download.url}")

        ctx.page.on("download", _on_download)


async def _dismiss_overlays(ctx: PlaywrightCrawlingContext) -> None:
    with contextlib.suppress(Exception):
        await ctx.page.keyboard.press("Escape")
    with contextlib.suppress(Exception):
        await ctx.page.mouse.click(0, 0)
    with contextlib.suppress(Exception):
        await ctx.page.evaluate(
            """
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
                  } catch {}
                });
                window.__spaCrawlerModalObserver.observe(document.documentElement, {
                  childList: true,
                  subtree: true,
                });
              }
            };
            """
        )


async def _save_html(ctx: PlaywrightCrawlingContext, out_dir: Path, verbose: bool) -> None:
    url = URL(ctx.request.loaded_url or ctx.request.url)
    relative_path = _safe_path_from_url(url)

    if not relative_path:
        html_path = out_dir / "pages" / "index.html"
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


async def _wait_for_stable_page(
    ctx: PlaywrightCrawlingContext,
    dom_content_loaded_timeout: int,
    network_idle_timeout: int,
    rerender_timeout: int | None = None,
) -> None:
    with contextlib.suppress(Exception):
        await ctx.page.wait_for_load_state("domcontentloaded", timeout=dom_content_loaded_timeout)
    with contextlib.suppress(Exception):
        await ctx.page.wait_for_load_state("networkidle", timeout=network_idle_timeout)
    if rerender_timeout:
        with contextlib.suppress(Exception):
            await ctx.page.wait_for_timeout(rerender_timeout)


async def _close_page(ctx: PlaywrightCrawlingContext) -> None:
    with contextlib.suppress(Exception):
        await ctx.page.close()


async def _soft_interaction_pass(ctx: PlaywrightCrawlingContext) -> None:
    with contextlib.suppress(Exception):
        await ctx.infinite_scroll()
    await _dismiss_overlays(ctx)
    with contextlib.suppress(Exception):
        await ctx.infinite_scroll()


def _apply_quiet() -> None:
    logging.getLogger().setLevel(logging.ERROR)

    mgr = logging.root.manager
    for logger in mgr.loggerDict.values():
        if isinstance(logger, logging.PlaceHolder):
            continue
        logger.setLevel(logging.ERROR)


type TransformEnqueueRequestArgs = dict[str, Any]
type TransformEnqueueRequestResult = TransformEnqueueRequestArgs | Literal["skip", "unchanged"]


def _transform_enqueue_request(
    base_url: URL,
) -> Callable[[TransformEnqueueRequestArgs], TransformEnqueueRequestResult]:
    def _fn(opts: TransformEnqueueRequestArgs) -> TransformEnqueueRequestResult:
        raw = opts.get("url")
        if not isinstance(raw, str):
            return "skip"

        try:
            normalized = _normalize_candidate_url(raw, base_url)
        except Exception:
            return "skip"

        if not normalized:
            return "skip"

        opts["url"] = normalized
        opts["unique_key"] = normalized
        return opts

    return _fn


async def crawl(config: CrawlConfig) -> None:
    if config.quiet:
        _apply_quiet()

    crawler = PlaywrightCrawler(
        http_client=ImpitHttpClient(),
        headless=config.headless,
        concurrency_settings=config.concurrency_settings,
        session_pool=SessionPool(
            max_pool_size=1,
            create_session_settings={
                "max_usage_count": 999_999,
                "max_age": timedelta(hours=999_999),
                "max_error_score": 100,
            },
        ),
        browser_launch_options={"ignore_https_errors": True},
        browser_new_context_options={"accept_downloads": True},
        use_session_pool=True,
        max_session_rotations=0,
        retry_on_blocked=True,
        ignore_http_error_status_codes=config.ignore_http_error_status_codes,
    )

    async def _discover_and_enqueue_from_html(ctx: PlaywrightCrawlingContext, html: str) -> None:
        urls: set[str] = set()

        next_data = _extract_next_data_json_from_html(html)
        if next_data:
            with contextlib.suppress(Exception):
                urls.update(
                    _extract_urls_from_json_bytes(
                        next_data.encode("utf-8", errors="ignore"), config.base_url
                    )
                )

        with contextlib.suppress(Exception):
            urls.update(_extract_urls_from_text(html, config.base_url))

        if urls:
            await ctx.add_requests(sorted(urls))

    async def _with_page(
        ctx: PlaywrightCrawlingContext, tag: str, fn: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            if config.verbose and not config.quiet:
                ctx.log.info(f"[{tag}] {ctx.request.url}")
            await fn()
        finally:
            await _close_page(ctx)

    transform_enqueue_request = _transform_enqueue_request(config.base_url)

    async def _handle_page(ctx: PlaywrightCrawlingContext) -> None:
        await _wait_for_stable_page(
            ctx=ctx,
            dom_content_loaded_timeout=config.dom_content_loaded_timeout,
            network_idle_timeout=config.network_idle_timeout,
        )

        await _soft_interaction_pass(ctx)

        await _save_html(ctx, config.out_dir, verbose=config.verbose and not config.quiet)

        with contextlib.suppress(Exception):
            html = await ctx.page.content()
            await _discover_and_enqueue_from_html(ctx, html)

        await ctx.enqueue_links(
            strategy="same-hostname",
            include=config.include_links,
            exclude=config.exclude_links,
            transform_request_function=transform_enqueue_request,
        )

    async def _handle_login(ctx: PlaywrightCrawlingContext) -> None:
        await _wait_for_stable_page(
            ctx=ctx,
            dom_content_loaded_timeout=config.dom_content_loaded_timeout,
            network_idle_timeout=config.network_idle_timeout,
            rerender_timeout=config.rerender_timeout,
        )

        if not URL(ctx.page.url).path.startswith(config.login_path):
            await ctx.add_requests([str(_canonicalize_page_url(config.base_url))])
            return

        login_element = ctx.page.locator(config.login_input_selector).first
        await login_element.click()
        await login_element.type(config.login, delay=config.typing_delay)

        password_element = ctx.page.locator(config.password_input_selector).first
        await password_element.click()
        await password_element.type(config.password, delay=config.typing_delay)
        await password_element.press("Enter")

        await ctx.page.wait_for_url(
            lambda u: not URL(u).path.startswith(config.login_path),
            timeout=config.success_login_redirect_timeout,
        )

        await ctx.add_requests([str(_canonicalize_page_url(config.base_url))])

    async def _pre_nav(ctx: PlaywrightPreNavCrawlingContext) -> None:
        verbose = config.verbose and not config.quiet
        with contextlib.suppress(Exception):
            await _attach_route_mirror(ctx, config.base_url, config.out_dir, verbose)
        _maybe_attach_download_hook(ctx, verbose)

    crawler.pre_navigation_hook(_pre_nav)

    @crawler.router.default_handler
    async def handler(ctx: PlaywrightCrawlingContext) -> None:
        try:
            if ctx.request.label == "login":
                await _with_page(ctx, "login", lambda: _handle_login(ctx))
            else:
                await _with_page(ctx, "page", lambda: _handle_page(ctx))
        except PWError as e:
            if "Download is starting" in str(e):
                if config.verbose and not config.quiet:
                    ctx.log.info(f"[goto-download] {ctx.request.url}")
            else:
                raise

    entrypoints: list[str | Request] = [
        str(_canonicalize_page_url(config.base_url)),
        *[str(_canonicalize_page_url(URL(u))) for u in config.additional_crawl_entrypoint_urls],
    ]
    if config.login_required:
        entrypoints.insert(
            0,
            Request.from_url(
                str(_canonicalize_page_url(URL(f"{config.base_url!s}{config.login_path}"))),
                label="login",
            ),
        )

    await crawler.run(entrypoints)
