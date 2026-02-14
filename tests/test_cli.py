import re

import pytest
import typer
from crawlee import Glob

from spa_crawler import cli


def test_clean_base_url() -> None:
    assert cli.clean_base_url(" https://example.com/?x=1 ") == "https://example.com"
    with pytest.raises(typer.BadParameter):
        cli.clean_base_url("not a url")


def test_clean_login_options_not_required() -> None:
    assert cli.clean_login_options(False, None, None, None, None, None) == ("", "", "", "", "")


def test_clean_login_options_with_values() -> None:
    result = cli.clean_login_options(
        True, "/login/", " user ", " pass ", " input[name='l'] ", " input[name='p'] "
    )
    assert result == ("/login", "user", "pass", "input[name='l']", "input[name='p']")


def test_clean_login_options_uses_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["/login", "u", "p", "#u", "#p"])

    def fake_prompt(*_args: object, **_kwargs: object) -> str:
        return next(answers)

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    result = cli.clean_login_options(True, None, None, None, None, None)
    assert result == ("/login", "u", "p", "#u", "#p")


def test_clean_login_options_rejects_root_login_path() -> None:
    with pytest.raises(typer.BadParameter):
        cli.clean_login_options(True, "/", "u", "p", "#u", "#p")


def test_clean_login_options_missing_login_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(typer, "prompt", lambda *_a, **_k: "   ")
    with pytest.raises(typer.BadParameter):
        cli.clean_login_options(True, None, "u", "p", "#u", "#p")


def test_clean_concurrency_settings_clamps() -> None:
    s = cli.clean_concurrency_settings(min_c=5, max_c=1, desired_c=100)
    assert s.min_concurrency == 5  # noqa: PLR2004
    assert s.max_concurrency == 5  # noqa: PLR2004
    assert s.desired_concurrency == 5  # noqa: PLR2004


def test_clean_include_exclude_links_defaults() -> None:
    include, exclude = cli.clean_include_exclude_links(
        "https://example.com",
        login_required=True,
        login_path="/login",
        include_links_regexes=None,
        exclude_links_regexes=None,
        include_links_globs=None,
        exclude_links_globs=None,
    )
    assert include and isinstance(include[0], Glob)
    assert include[0].glob == "https://example.com/**"
    patterns = [p.pattern for p in exclude if isinstance(p, re.Pattern)]
    assert any(p == ".*/api.*" for p in patterns)
    assert any("/login" in p for p in patterns)


def test_clean_include_exclude_links_defaults_no_double_slash_for_path_base() -> None:
    include, _ = cli.clean_include_exclude_links(
        "https://example.com/app/",
        login_required=False,
        login_path="/login",
        include_links_regexes=None,
        exclude_links_regexes=None,
        include_links_globs=None,
        exclude_links_globs=None,
    )
    assert include and isinstance(include[0], Glob)
    assert include[0].glob == "https://example.com/app/**"


def test_clean_include_exclude_links_custom_and_dedup() -> None:
    include, exclude = cli.clean_include_exclude_links(
        "https://example.com",
        login_required=False,
        login_path="/login",
        include_links_regexes=["^https://example.com/a", " ^https://example.com/a "],
        exclude_links_regexes=["^https://example.com/x"],
        include_links_globs=["https://example.com/**", "https://example.com/**"],
        exclude_links_globs=["https://example.com/private/**"],
    )
    assert len(include) == 2  # noqa: PLR2004
    assert len(exclude) == 2  # noqa: PLR2004


def test_clean_include_exclude_links_bad_include_regex_is_cli_error() -> None:
    with pytest.raises(typer.BadParameter) as e:
        cli.clean_include_exclude_links(
            "https://example.com",
            login_required=False,
            login_path="/login",
            include_links_regexes=["["],
            exclude_links_regexes=None,
            include_links_globs=None,
            exclude_links_globs=None,
        )
    assert e.value.param_hint and "--include-links-regex" in e.value.param_hint


def test_clean_include_exclude_links_bad_exclude_regex_is_cli_error() -> None:
    with pytest.raises(typer.BadParameter) as e:
        cli.clean_include_exclude_links(
            "https://example.com",
            login_required=False,
            login_path="/login",
            include_links_regexes=None,
            exclude_links_regexes=["("],
            include_links_globs=None,
            exclude_links_globs=None,
        )
    assert e.value.param_hint and "--exclude-links-regex" in e.value.param_hint


def test_clean_additional_crawl_entrypoint_urls() -> None:
    values = ["https://example.com/a/", " https://example.com/a/ ", "https://example.com/b", "   "]
    assert cli.clean_additional_crawl_entrypoint_urls("https://example.com", values) == [
        "https://example.com/a/",
        "https://example.com/b",
    ]


def test_clean_additional_crawl_entrypoint_urls_rejects_other_origin() -> None:
    with pytest.raises(typer.BadParameter):
        cli.clean_additional_crawl_entrypoint_urls(
            "https://example.com", ["https://other.example.com/a"]
        )


def test_clean_ignore_http_error_status_codes() -> None:
    assert cli.clean_ignore_http_error_status_codes(None) == [400, 404, 405, 410]
    assert cli.clean_ignore_http_error_status_codes([404, 404, 410]) == [404, 410]


def test_clean_api_path_prefixes() -> None:
    assert cli.clean_api_path_prefixes(None) == ["/api"]
    assert cli.clean_api_path_prefixes(["api", "/api", " /v1/ "]) == ["/api", "/v1"]


def test_clean_api_path_prefixes_bad_value() -> None:
    with pytest.raises(typer.BadParameter) as e:
        cli.clean_api_path_prefixes([r"/api\test"])
    assert e.value.param_hint and "--api-path-prefix" in e.value.param_hint


def test_is_cli_param_error() -> None:
    assert cli.is_cli_param_error(typer.BadParameter("x"))
    assert not cli.is_cli_param_error(RuntimeError("x"))
