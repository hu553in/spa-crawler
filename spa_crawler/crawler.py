import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from crawlee import Request
from crawlee.crawlers import (
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
    PlaywrightPreNavCrawlingContext,
)
from crawlee.http_clients import ImpitHttpClient
from crawlee.sessions import SessionPool
from playwright.async_api import Error as PWError
from yarl import URL

from spa_crawler.assets_mirror import attach_route_mirror
from spa_crawler.config import CrawlConfig
from spa_crawler.logging import setup_logging
from spa_crawler.page_ops import (
    close_page,
    maybe_attach_download_hook,
    save_html,
    soft_interaction_pass,
    wait_for_stable_page,
)
from spa_crawler.redirects import RedirectCollector
from spa_crawler.url_discovery import extract_page_urls_via_js, transform_enqueue_request
from spa_crawler.utils import canonicalize_page_url, path_has_prefix, unique_preserve_order


async def crawl(config: CrawlConfig) -> None:
    """Run the crawler with a single persistent session and Playwright route mirroring."""
    if config.login_required and config.login_path == "/":
        raise ValueError("login_path '/' is not supported when login_required is true.")

    verbose = setup_logging(verbose=config.verbose, quiet=config.quiet)
    redirect_collector = RedirectCollector(
        config.base_url,
        config.api_path_prefixes,
        config.max_query_len_for_fs_mapping,
        config.default_server_redirect_status,
        config.max_confidence_for_not_export,
        config.min_redirect_chain_len,
    )

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

    async def _discover_and_enqueue_from_page(ctx: PlaywrightCrawlingContext) -> None:
        urls = await extract_page_urls_via_js(
            ctx,
            config.base_url,
            config.api_path_prefixes,
            config.max_url_len,
            config.candidate_url_trim_chars,
        )
        if urls:
            await ctx.add_requests(urls)

    async def _with_page(
        ctx: PlaywrightCrawlingContext, tag: str, fn: Callable[[], Awaitable[None]]
    ) -> None:
        """Run a page handler with standard logging and guaranteed page close."""
        try:
            if verbose:
                ctx.log.info(f"[{tag}] {ctx.request.url}")
            await fn()

            try:
                await redirect_collector.observe_http_redirects_from_response(ctx.response)
            except Exception as e:
                ctx.log.warning(f"[redirect-http-observe-error] {ctx.request.url}: {e!r}")

            try:
                source = ctx.request.loaded_url or ctx.request.url
                redirect_collector.observe_client_redirect(source, ctx.page.url)
            except Exception as e:
                ctx.log.warning(f"[redirect-client-observe-error] {ctx.request.url}: {e!r}")
        finally:
            await close_page(ctx)

    enqueue_transform = transform_enqueue_request(
        config.base_url,
        config.api_path_prefixes,
        config.max_url_len,
        config.candidate_url_trim_chars,
    )

    post_login_entrypoints: list[str | Request] = unique_preserve_order(
        [
            str(canonicalize_page_url(config.base_url)),
            *[str(canonicalize_page_url(URL(u))) for u in config.additional_crawl_entrypoint_urls],
        ]
    )

    async def _handle_page(ctx: PlaywrightCrawlingContext) -> None:
        await wait_for_stable_page(
            ctx=ctx,
            dom_content_loaded_timeout=config.dom_content_loaded_timeout,
            network_idle_timeout=config.network_idle_timeout,
        )

        await soft_interaction_pass(ctx)

        await save_html(
            ctx,
            config.out_dir,
            verbose=verbose,
            max_query_len_for_fs_mapping=config.max_query_len_for_fs_mapping,
        )

        # Extra discovery pass: extract links from DOM/Next.js data.
        try:
            await _discover_and_enqueue_from_page(ctx)
        except Exception as e:
            ctx.log.warning(f"[discover-error] {ctx.request.url}: {e!r}")

        # Crawlee-native enqueue (filtered and normalized via transform function).
        await ctx.enqueue_links(
            strategy="same-hostname",
            include=config.include_links,
            exclude=config.exclude_links,
            transform_request_function=enqueue_transform,
        )

    async def _handle_login(ctx: PlaywrightCrawlingContext) -> None:
        await wait_for_stable_page(
            ctx=ctx,
            dom_content_loaded_timeout=config.dom_content_loaded_timeout,
            network_idle_timeout=config.network_idle_timeout,
            rerender_timeout=config.rerender_timeout,
        )

        # If we're already past login page, enqueue post-login entrypoints and stop.
        if not path_has_prefix(URL(ctx.page.url).path, config.login_path):
            await ctx.add_requests(post_login_entrypoints)
            return

        login_element = ctx.page.locator(config.login_input_selector).first
        await login_element.click()
        await login_element.type(config.login, delay=config.typing_delay)

        password_element = ctx.page.locator(config.password_input_selector).first
        await password_element.click()
        await password_element.type(config.password, delay=config.typing_delay)
        await password_element.press("Enter")

        await ctx.page.wait_for_url(
            lambda u: not path_has_prefix(URL(u).path, config.login_path),
            timeout=config.success_login_redirect_timeout,
        )

        await ctx.add_requests(post_login_entrypoints)

    async def _pre_nav(ctx: PlaywrightPreNavCrawlingContext) -> None:
        """Attach route mirroring + download hook once per page."""
        # Do not wait for the full "load" event. Many SPAs keep loading assets for a long time.
        ctx.goto_options.setdefault("wait_until", "domcontentloaded")

        try:
            await attach_route_mirror(
                ctx,
                config.base_url,
                config.out_dir,
                verbose,
                config.api_path_prefixes,
                config.route_fetch_timeout,
                config.max_query_len_for_fs_mapping,
                config.max_url_len,
                config.candidate_url_trim_chars,
            )
        except Exception as e:
            ctx.log.warning(f"[route-mirror-attach-error] {ctx.request.url}: {e!r}")

        maybe_attach_download_hook(ctx, verbose)

    crawler.pre_navigation_hook(_pre_nav)

    @crawler.router.default_handler
    async def handler(ctx: PlaywrightCrawlingContext) -> None:
        try:
            if ctx.request.label == "login":
                await _with_page(ctx, "login", lambda: _handle_login(ctx))
            else:
                await _with_page(ctx, "page", lambda: _handle_page(ctx))
        except PWError as e:
            # Playwright throws a special error when navigation results in a download.
            if "Download is starting" in str(e):
                if verbose:
                    ctx.log.info(f"[goto-download] {ctx.request.url}")
            else:
                raise

    # Entrypoints: start from login when authentication is required.
    if config.login_required:
        entrypoints: list[str | Request] = [
            Request.from_url(
                str(canonicalize_page_url(config.base_url.join(URL(config.login_path)))),
                label="login",
            )
        ]
    else:
        entrypoints = post_login_entrypoints

    await crawler.run(entrypoints)

    logger = logging.getLogger(__name__)

    try:
        caddy_path = redirect_collector.write_server_redirect_rules(config.out_dir)
        if verbose:
            logger.info(f"[redirect-rules] caddy={caddy_path}")
    except Exception as e:
        logger.warning(f"[redirect-rules-save-error] {e!r}")

    try:
        html_stats = redirect_collector.write_html_redirect_pages(config.out_dir)
        if verbose:
            logger.info(
                "[redirect-pages] "
                f"created={html_stats['created']} "
                f"skipped_existing={html_stats['skipped_existing']} "
                f"skipped_unsafe_query={html_stats['skipped_unsafe_query']}"
            )
    except Exception as e:
        logger.warning(f"[redirect-pages-save-error] {e!r}")
