import re
from collections.abc import Callable

import typer
from crawlee import ConcurrencySettings, Glob
from yarl import URL

from spa_crawler.utils import (
    clean_absolute_http_url,
    clean_path_prefix,
    map_nonblank,
    strip_or_none,
    unique_preserve_order,
)

INCLUDE_LINKS_HELP = "{base_url}/** glob is used if no include links globs/regexes are provided."
EXCLUDE_LINKS_HELP = (
    ".*{login_path}.* and .*/api.* regexes are used if no exclude links globs/regexes are provided."
)
DESIRED_CONCURRENCY_HELP = (
    "Must be greater than or equal to '--min-concurrency' "
    "and less than or equal to '--max-concurrency'."
)
OUT_DIR_HELP = "If changed, it must also be updated in Dockerfile, Makefile, and .gitignore."
IGNORE_HTTP_ERROR_STATUS_CODE_HELP = "Defaults are 400, 404, 405, and 410."
API_PATH_PREFIX_HELP = "Default is '/api'."


def _clean_with_param_hint[T](v: str, *, param_hint: str, cleaner: Callable[[str], T]) -> T:
    """Run a cleaner and convert any error into ``typer.BadParameter``."""
    try:
        return cleaner(v)
    except Exception as e:
        raise typer.BadParameter(str(e), param_hint=[param_hint]) from e


def _pattern_or_glob_key(v: re.Pattern[str] | Glob) -> tuple[str, str, int] | tuple[str, str]:
    """Return a hashable key for regex/glob deduplication."""
    if isinstance(v, re.Pattern):
        return ("re", v.pattern, v.flags)
    return ("glob", v.glob)


def _unique_patterns_or_globs(values: list[re.Pattern[str] | Glob]) -> list[re.Pattern[str] | Glob]:
    """Preserve order while removing duplicate regex/glob filters."""
    out: list[re.Pattern[str] | Glob] = []
    seen: set[tuple[str, str, int] | tuple[str, str]] = set()
    for v in values:
        key = _pattern_or_glob_key(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _clean_regex(v: str, *, param_hint: str) -> re.Pattern[str]:
    """Compile a regex value with CLI-aware validation errors."""
    return _clean_with_param_hint(v, param_hint=param_hint, cleaner=re.compile)


def _clean_glob(v: str, *, param_hint: str) -> Glob:
    """Build a Crawlee ``Glob`` value with CLI-aware validation errors."""
    return _clean_with_param_hint(v, param_hint=param_hint, cleaner=Glob)


def _default_include_glob(base_url: str) -> Glob:
    """Build the default include glob for the configured base URL."""
    return Glob(f"{base_url.rstrip('/')}/**")


def clean_base_url(v: str) -> str:
    """Validate and normalize ``--base-url``."""
    return str(_clean_with_param_hint(v, param_hint="--base-url", cleaner=clean_absolute_http_url))


def clean_login_options(
    login_required: bool,
    login_path: str | None,
    login: str | None,
    password: str | None,
    login_input_selector: str | None,
    password_input_selector: str | None,
) -> tuple[str, str, str, str, str]:
    """Validate login-related CLI options and prompt for missing required values."""
    if not login_required:
        return ("", "", "", "", "")

    login_path = strip_or_none(login_path) or strip_or_none(typer.prompt("Login path"))
    if not login_path:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login-path"]
        )
    login_path = _clean_with_param_hint(
        login_path, param_hint="--login-path", cleaner=clean_path_prefix
    )
    if login_path == "/":
        raise typer.BadParameter(
            "'/' is not supported when '--login-required' is true.", param_hint=["--login-path"]
        )

    login = strip_or_none(login) or strip_or_none(typer.prompt("Login"))
    if not login:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login"]
        )

    password = strip_or_none(password) or strip_or_none(typer.prompt("Password", hide_input=True))
    if not password:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--password"]
        )

    login_input_selector = strip_or_none(login_input_selector) or strip_or_none(
        typer.prompt("Login input selector")
    )
    if not login_input_selector:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.", param_hint=["--login-input-selector"]
        )

    password_input_selector = strip_or_none(password_input_selector) or strip_or_none(
        typer.prompt("Password input selector")
    )
    if not password_input_selector:
        raise typer.BadParameter(
            "it is required when '--login-required' is true.",
            param_hint=["--password-input-selector"],
        )

    return login_path, login, password, login_input_selector, password_input_selector


def clean_concurrency_settings(min_c: int, max_c: int, desired_c: int) -> ConcurrencySettings:
    """Clamp concurrency settings into a valid Crawlee configuration."""
    max_c = max(max_c, min_c)
    desired_c = min(max(desired_c, min_c), max_c)
    return ConcurrencySettings(
        min_concurrency=min_c, max_concurrency=max_c, desired_concurrency=desired_c
    )


def clean_include_exclude_links(
    base_url: str,
    login_required: bool,
    login_path: str,
    include_links_regexes: list[str] | None,
    exclude_links_regexes: list[str] | None,
    include_links_globs: list[str] | None,
    exclude_links_globs: list[str] | None,
) -> tuple[list[re.Pattern[str] | Glob], list[re.Pattern[str] | Glob]]:
    """Build include/exclude link filters from CLI values and defaults."""
    include_links: list[re.Pattern[str] | Glob] = [
        *map_nonblank(
            include_links_regexes, lambda s: _clean_regex(s, param_hint="--include-links-regex")
        ),
        *map_nonblank(
            include_links_globs, lambda s: _clean_glob(s, param_hint="--include-links-glob")
        ),
    ]
    exclude_links: list[re.Pattern[str] | Glob] = [
        *map_nonblank(
            exclude_links_regexes, lambda s: _clean_regex(s, param_hint="--exclude-links-regex")
        ),
        *map_nonblank(
            exclude_links_globs, lambda s: _clean_glob(s, param_hint="--exclude-links-glob")
        ),
    ]

    if not include_links:
        include_links = [_default_include_glob(base_url)]
    if not exclude_links:
        exclude_links = [re.compile(r".*/api.*")]
        if login_required:
            exclude_links.append(re.compile(f".*{re.escape(login_path)}.*"))

    return _unique_patterns_or_globs(include_links), _unique_patterns_or_globs(exclude_links)


def clean_additional_crawl_entrypoint_urls(base_url: str, values: list[str] | None) -> list[str]:
    """Validate and deduplicate additional crawl entrypoints."""
    base_origin = URL(base_url).origin()
    urls = map_nonblank(
        values,
        lambda s: _clean_with_param_hint(
            s, param_hint="--additional-crawl-entrypoint-url", cleaner=clean_absolute_http_url
        ),
    )

    out: list[str] = []
    for u in urls:
        if u.origin() != base_origin:
            raise typer.BadParameter(
                "must have same origin as '--base-url'.",
                param_hint=["--additional-crawl-entrypoint-url"],
            )

        out.append(str(u))
    return unique_preserve_order(out)


def clean_ignore_http_error_status_codes(values: list[int] | None) -> list[int]:
    """Return deduplicated ignored HTTP status codes with project defaults."""
    if values:
        return unique_preserve_order(values)
    return [400, 404, 405, 410]


def clean_api_path_prefixes(values: list[str] | None) -> list[str]:
    """Validate and deduplicate API path prefixes."""
    out = map_nonblank(
        values,
        lambda s: _clean_with_param_hint(
            s, param_hint="--api-path-prefix", cleaner=clean_path_prefix
        ),
    )
    return unique_preserve_order(out) or ["/api"]


def is_cli_param_error(e: BaseException) -> bool:
    """Return ``True`` when an exception is a Typer/Click parameter error."""
    mod = e.__class__.__module__
    return mod.startswith("typer") or mod.startswith("click")
