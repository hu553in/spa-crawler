import asyncio
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

import typer
from crawlee import ConcurrencySettings, Glob
from yarl import URL

from spa_crawler.config import CrawlConfig
from spa_crawler.main import crawl

_INCLUDE_LINKS_HELP = "{base_url}/** glob is used if no include links globs/regexes are provided."
_EXCLUDE_LINKS_HELP = (
    ".*{login_path}.* and .*/api.* regexes are used if no exclude links globs/regexes are provided."
)
_DESIRED_CONCURRENCY_HELP = (
    "Must be greater than or equal to '--min-concurrency' "
    "and less than or equal to '--max-concurrency'."
)
_OUT_DIR_HELP = "If changed, it must also be updated in Dockerfile, Makefile, and .gitignore."


def _strip_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    return v.strip() or None


def _clean_base_url(v: str) -> str:
    raw = v.strip()
    if not raw:
        raise typer.BadParameter("non-blank value is required.")

    try:
        u = URL(raw)
    except Exception as e:
        raise typer.BadParameter("valid URL is required.") from e

    if u.scheme not in {"http", "https"}:
        raise typer.BadParameter("http or https scheme is required.")
    if not u.host:
        raise typer.BadParameter("host is required.")

    u = u.with_fragment(None).with_user(None).with_password(None).with_query(None)
    if u.path == "/" and str(u).endswith("/"):
        u = u.with_path("")

    return str(u)


def _clean_login_options(
    login_required: bool,
    login_path: str | None,
    login: str | None,
    password: str | None,
    login_input_selector: str | None,
    password_input_selector: str | None,
) -> tuple[str, str, str, str, str]:
    if not login_required:
        return (
            _strip_or_none(login_path) or "",
            _strip_or_none(login) or "",
            _strip_or_none(password) or "",
            _strip_or_none(login_input_selector) or "",
            _strip_or_none(password_input_selector) or "",
        )

    login_path = _strip_or_none(login_path) or _strip_or_none(typer.prompt("Login path"))
    if not login_path:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login-path"]
        )

    login = _strip_or_none(login) or _strip_or_none(typer.prompt("Login"))
    if not login:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login"]
        )

    password = _strip_or_none(password) or _strip_or_none(typer.prompt("Password", hide_input=True))
    if not password:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--password"]
        )

    login_input_selector = _strip_or_none(login_input_selector) or _strip_or_none(
        typer.prompt("Login input selector")
    )
    if not login_input_selector:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login-input-selector"]
        )

    password_input_selector = _strip_or_none(password_input_selector) or _strip_or_none(
        typer.prompt("Password input selector")
    )
    if not password_input_selector:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.",
            param_hint=["--password-input-selector"],
        )

    return login_path, login, password, login_input_selector, password_input_selector


def _clean_concurrency_settings(min_c: int, max_c: int, desired_c: int) -> ConcurrencySettings:
    max_c = max(max_c, min_c)
    desired_c = min(max(desired_c, min_c), max_c)
    return ConcurrencySettings(
        min_concurrency=min_c, max_concurrency=max_c, desired_concurrency=desired_c
    )


def _compile_patterns(regexes: Iterable[str] | None) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for raw in regexes or []:
        s = _strip_or_none(raw)
        if s:
            out.append(re.compile(s))
    return out


def _compile_globs(globs: Iterable[str] | None) -> list[Glob]:
    out: list[Glob] = []
    for raw in globs or []:
        s = _strip_or_none(raw)
        if s:
            out.append(Glob(s))
    return out


def _clean_include_exclude_links(
    base_url: str,
    login_required: bool,
    login_path: str,
    include_links_regexes: list[str] | None,
    exclude_links_regexes: list[str] | None,
    include_links_globs: list[str] | None,
    exclude_links_globs: list[str] | None,
) -> tuple[list[re.Pattern[str] | Glob], list[re.Pattern[str] | Glob]]:
    include_links: list[re.Pattern[str] | Glob] = [
        *_compile_patterns(include_links_regexes),
        *_compile_globs(include_links_globs),
    ]
    exclude_links: list[re.Pattern[str] | Glob] = [
        *_compile_patterns(exclude_links_regexes),
        *_compile_globs(exclude_links_globs),
    ]

    if not include_links:
        include_links = [Glob(f"{base_url}/**")]
    if not exclude_links:
        exclude_links = [re.compile(r".*/api.*")]
        if login_required:
            exclude_links.append(re.compile(f".*{re.escape(login_path)}.*"))

    return include_links, exclude_links


def _clean_additional_crawl_entrypoint_urls(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        s = _strip_or_none(v)
        if s:
            out.append(s)
    return out


def main(
    base_url: Annotated[str, typer.Option(prompt="Base URL", callback=_clean_base_url)],
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
) -> None:
    login_path_s, login_s, password_s, login_input_selector_s, password_input_selector_s = (
        _clean_login_options(
            login_required,
            login_path,
            login,
            password,
            login_input_selector,
            password_input_selector,
        )
    )

    include_links, exclude_links = _clean_include_exclude_links(
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
        _clean_concurrency_settings(min_concurrency, max_concurrency, desired_concurrency),
        out_dir,
        typing_delay,
        include_links,
        exclude_links,
        dom_content_loaded_timeout,
        network_idle_timeout,
        rerender_timeout,
        success_login_redirect_timeout,
        _clean_additional_crawl_entrypoint_urls(additional_crawl_entrypoint_url),
        verbose,
        quiet,
    )

    if not quiet:
        typer.echo(f"Configuration: {config}")

    asyncio.run(crawl(config))


def _is_cli_param_error(e: BaseException) -> bool:
    mod = e.__class__.__module__
    return mod.startswith("typer") or mod.startswith("click")


if __name__ == "__main__":
    try:
        typer.run(main)
    except Exception as e:
        if _is_cli_param_error(e):
            raise
        typer.echo(f"Fatal error: {e!r}", err=True)
        raise typer.Exit(1) from e
