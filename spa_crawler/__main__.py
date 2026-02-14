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
    is_cli_param_error,
)
from spa_crawler.config import CrawlConfig
from spa_crawler.constants import DEFAULT_IGNORED_HTTP_ERROR_STATUS_CODES
from spa_crawler.crawler import crawl

_HTTP_STATUS_CLIENT_ERROR_MIN = 400
_HTTP_STATUS_SERVER_ERROR_MAX = 599

_INCLUDE_LINKS_HELP = "{base_url}/** glob is used if no include links globs/regexes are provided."
_EXCLUDE_LINKS_HELP = (
    ".*{login_path}.* and .*/api.* regexes are used if no exclude links globs/regexes are provided."
)
_DESIRED_CONCURRENCY_HELP = (
    "Must be greater than or equal to '--min-concurrency' "
    "and less than or equal to '--max-concurrency'."
)
_OUT_DIR_HELP = "If changed, it must also be updated in Dockerfile, Makefile, and .gitignore."
_IGNORE_HTTP_ERROR_STATUS_CODE_HELP = (
    "Defaults are " + ", ".join(str(code) for code in DEFAULT_IGNORED_HTTP_ERROR_STATUS_CODES) + "."
)
_API_PATH_PREFIX_HELP = "Default is '/api'."


def main(
    base_url: Annotated[str, typer.Option(prompt="Base URL", callback=clean_base_url)],
    login_required: Annotated[bool, typer.Option()] = True,
    login_path: Annotated[str, typer.Option()] = "/login",
    login: Annotated[str, typer.Option(envvar="SPA_CRAWLER_LOGIN")] = "",
    password: Annotated[str, typer.Option(envvar="SPA_CRAWLER_PASSWORD")] = "",
    login_input_selector: Annotated[str, typer.Option()] = "input[name='login']:visible",
    password_input_selector: Annotated[str, typer.Option()] = "input[name='password']:visible",
    headless: Annotated[bool, typer.Option()] = True,
    min_concurrency: Annotated[int, typer.Option(min=1)] = 1,
    max_concurrency: Annotated[int, typer.Option(min=1)] = 100,
    desired_concurrency: Annotated[int, typer.Option(min=1, help=_DESIRED_CONCURRENCY_HELP)] = 10,
    out_dir: Annotated[Path, typer.Option(help=_OUT_DIR_HELP)] = Path("out"),
    typing_delay: Annotated[int, typer.Option(min=0)] = 50,
    include_links_regex: Annotated[list[str] | None, typer.Option(help=_INCLUDE_LINKS_HELP)] = None,
    exclude_links_regex: Annotated[list[str] | None, typer.Option(help=_EXCLUDE_LINKS_HELP)] = None,
    include_links_glob: Annotated[list[str] | None, typer.Option(help=_INCLUDE_LINKS_HELP)] = None,
    exclude_links_glob: Annotated[list[str] | None, typer.Option(help=_EXCLUDE_LINKS_HELP)] = None,
    dom_content_loaded_timeout: Annotated[int, typer.Option(min=1)] = 30_000,
    network_idle_timeout: Annotated[int, typer.Option(min=1)] = 20_000,
    rerender_timeout: Annotated[int, typer.Option(min=1)] = 1200,
    success_login_redirect_timeout: Annotated[int, typer.Option(min=1)] = 60_000,
    additional_crawl_entrypoint_url: Annotated[list[str] | None, typer.Option()] = None,
    verbose: Annotated[bool, typer.Option()] = False,
    quiet: Annotated[bool, typer.Option()] = False,
    ignore_http_error_status_code: Annotated[
        list[int] | None,
        typer.Option(
            min=_HTTP_STATUS_CLIENT_ERROR_MIN,
            max=_HTTP_STATUS_SERVER_ERROR_MAX,
            help=_IGNORE_HTTP_ERROR_STATUS_CODE_HELP,
        ),
    ] = None,
    api_path_prefix: Annotated[list[str] | None, typer.Option(help=_API_PATH_PREFIX_HELP)] = None,
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
