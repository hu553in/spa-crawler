import asyncio
from pathlib import Path
from typing import Annotated

import typer
from yarl import URL

from spa_crawler.cli import (
    clean_additional_crawl_entrypoint_urls,
    clean_api_path_prefixes,
    clean_base_url,
    clean_concurrency_settings,
    clean_ignore_http_error_status_codes,
    clean_include_exclude_links,
    clean_login_options,
    clean_max_confidence_for_not_export,
    is_cli_param_error,
)
from spa_crawler.config import CrawlConfig
from spa_crawler.constants import DEFAULT_IGNORED_HTTP_ERROR_STATUS_CODES
from spa_crawler.crawler import crawl

_HTTP_STATUS_CLIENT_ERROR_MIN = 400
_HTTP_STATUS_SERVER_ERROR_MAX = 599


def main(
    base_url: Annotated[
        str,
        typer.Option(
            prompt="Base URL",
            callback=clean_base_url,
            help="Base URL used as the starting point for crawling.",
        ),
    ],
    login_required: Annotated[
        bool, typer.Option(help="Whether authentication is required.")
    ] = True,
    login_path: Annotated[
        str, typer.Option(help="Login path relative to the base URL.")
    ] = "/login",
    login: Annotated[str, typer.Option(envvar="SPA_CRAWLER_LOGIN", help="Login username.")] = "",
    password: Annotated[
        str, typer.Option(envvar="SPA_CRAWLER_PASSWORD", help="Login password.")
    ] = "",
    login_input_selector: Annotated[
        str, typer.Option(help="CSS selector for the login input field.")
    ] = "input[name='login']:visible",
    password_input_selector: Annotated[
        str, typer.Option(help="CSS selector for the password input field.")
    ] = "input[name='password']:visible",
    headless: Annotated[bool, typer.Option(help="Use a headless browser.")] = True,
    min_concurrency: Annotated[
        int, typer.Option(min=1, clamp=True, help="Minimum crawler concurrency.")
    ] = 1,
    max_concurrency: Annotated[
        int, typer.Option(min=1, clamp=True, help="Maximum crawler concurrency.")
    ] = 100,
    desired_concurrency: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help=(
                "Desired crawler concurrency. Must be greater than or equal to '--min-concurrency' "
                "and less than or equal to '--max-concurrency'."
            ),
        ),
    ] = 10,
    out_dir: Annotated[
        Path,
        typer.Option(
            writable=True,
            help=(
                "Output directory. If changed, it must also be updated "
                "in the Dockerfile, Makefile, and .gitignore."
            ),
        ),
    ] = Path("out"),
    typing_delay: Annotated[
        int,
        typer.Option(
            min=0, clamp=True, help="Delay (in milliseconds) between keystrokes when typing."
        ),
    ] = 50,
    include_links_regex: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "Regular expressions to include links. If none are provided, "
                "'{base_url}/**' glob is used by default."
            )
        ),
    ] = None,
    exclude_links_regex: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "Regular expressions to exclude links. If '--login-required' is true and "
                "no exclude patterns are provided, '.*{login_path}.*' is used by default."
            )
        ),
    ] = None,
    include_links_glob: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "Glob patterns to include links. If none are provided, "
                "'{base_url}/**' glob is used by default."
            )
        ),
    ] = None,
    exclude_links_glob: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "Glob patterns to exclude links. If '--login-required' is true and "
                "no exclude patterns are provided, '.*{login_path}.*' is used by default."
            )
        ),
    ] = None,
    dom_content_loaded_timeout: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help="Timeout (in milliseconds) for waiting for the 'domcontentloaded' event.",
        ),
    ] = 30_000,
    network_idle_timeout: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help="Timeout (in milliseconds) for waiting for the 'networkidle' event.",
        ),
    ] = 20_000,
    rerender_timeout: Annotated[
        int,
        typer.Option(
            min=1, clamp=True, help="Timeout (in milliseconds) for waiting for page re-rendering."
        ),
    ] = 1200,
    success_login_redirect_timeout: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help="Timeout (in milliseconds) for waiting to be redirected from the login path.",
        ),
    ] = 60_000,
    additional_crawl_entrypoint_url: Annotated[
        list[str] | None, typer.Option(help="Additional URLs to include as crawler entrypoints.")
    ] = None,
    verbose: Annotated[bool, typer.Option(help="Enable verbose output.")] = False,
    quiet: Annotated[bool, typer.Option(help="Suppress non-error output.")] = False,
    ignore_http_error_status_code: Annotated[
        list[int] | None,
        typer.Option(
            min=_HTTP_STATUS_CLIENT_ERROR_MIN,
            max=_HTTP_STATUS_SERVER_ERROR_MAX,
            help=(
                "HTTP error status codes to ignore. Defaults: "
                + ", ".join(str(code) for code in DEFAULT_IGNORED_HTTP_ERROR_STATUS_CODES)
                + "."
            ),
        ),
    ] = None,
    api_path_prefix: Annotated[list[str] | None, typer.Option(help="API path prefixes.")] = None,
    route_fetch_timeout: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help="Timeout (in milliseconds) for the 'route.fetch(...)' operation.",
        ),
    ] = 60_000,
    max_query_len_for_fs_mapping: Annotated[
        int,
        typer.Option(
            min=1, clamp=True, help="Maximum query length allowed for mapping to a filesystem path."
        ),
    ] = 8000,
    default_server_redirect_status: Annotated[
        int,
        typer.Option(
            min=300,
            max=399,
            help=(
                "Default HTTP redirect status code used for redirects that do not have "
                "their own HTTP status code (e.g., window.location changes)."
            ),
        ),
    ] = 302,
    max_confidence_for_not_export: Annotated[
        float,
        typer.Option(
            min=0.0,
            clamp=True,
            callback=clean_max_confidence_for_not_export,
            help="Maximum confidence threshold below which a redirect is not exported.",
        ),
    ] = 0.5,
    min_redirect_chain_len: Annotated[
        int,
        typer.Option(
            min=1,
            clamp=True,
            help="Minimum redirect chain length to export to the crawling result.",
        ),
    ] = 2,
    max_url_len: Annotated[
        int, typer.Option(min=1, clamp=True, help="Maximum allowed URL length.")
    ] = 2048,
    candidate_url_trim_chars: Annotated[
        str,
        typer.Option(
            help="Characters to trim from candidate URLs before processing.",
            show_default=" \\t\\r\\n'\"`",
        ),
    ] = " \t\r\n'\"`",
) -> None:
    """Parse CLI options, build ``CrawlConfig``, and run the crawler."""
    login_path_s, login_s, password_s, login_input_selector_s, password_input_selector_s = (
        clean_login_options(
            login_required,
            login_path,
            login,
            password,
            login_input_selector,
            password_input_selector,
        )
    )

    include_links, exclude_links = clean_include_exclude_links(
        base_url,
        login_required,
        login_path_s,
        include_links_regex,
        exclude_links_regex,
        include_links_glob,
        exclude_links_glob,
    )

    config = CrawlConfig(
        URL(base_url),
        login_required,
        login_path_s,
        login_s,
        password_s,
        login_input_selector_s,
        password_input_selector_s,
        headless,
        clean_concurrency_settings(min_concurrency, max_concurrency, desired_concurrency),
        out_dir,
        typing_delay,
        include_links,
        exclude_links,
        dom_content_loaded_timeout,
        network_idle_timeout,
        rerender_timeout,
        success_login_redirect_timeout,
        clean_additional_crawl_entrypoint_urls(base_url, additional_crawl_entrypoint_url),
        verbose,
        quiet,
        clean_ignore_http_error_status_codes(ignore_http_error_status_code),
        clean_api_path_prefixes(api_path_prefix),
        route_fetch_timeout,
        max_query_len_for_fs_mapping,
        default_server_redirect_status,
        max_confidence_for_not_export,
        min_redirect_chain_len,
        max_url_len,
        candidate_url_trim_chars,
    )

    if not quiet:
        typer.echo(f"\n{config.pretty_str()}")

    asyncio.run(crawl(config))


if __name__ == "__main__":
    try:
        typer.run(main)
    except Exception as e:
        if is_cli_param_error(e):
            raise
        typer.echo(f"Fatal error: {e!r}", err=True)
        raise typer.Exit(1) from e
