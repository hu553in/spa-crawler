from pathlib import Path

import pytest
from yarl import URL

from spa_crawler import utils


def test_strip_or_none() -> None:
    assert utils.strip_or_none(None) is None
    assert utils.strip_or_none("   \n\t  ") is None
    assert utils.strip_or_none("  x  ") == "x"


def test_map_nonblank_and_unique_preserve_order() -> None:
    assert utils.map_nonblank(["  a ", "", " b ", "   "], str.upper) == ["A", "B"]
    assert utils.unique_preserve_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("/api", "/api", True),
        ("/api/v1", "/api", True),
        ("/api-v1", "/api", False),
        ("///api///v1//", "/api", True),
        ("/", "/", True),
        ("/x", "/", True),
    ],
)
def test_path_has_prefix(path: str, prefix: str, expected: bool) -> None:
    assert utils.path_has_prefix(path, prefix) is expected


def test_is_absolute_http_url() -> None:
    assert utils.is_absolute_http_url(URL("https://example.com"))
    assert utils.is_absolute_http_url(URL("http://example.com/path"))
    assert not utils.is_absolute_http_url(URL("/relative/path"))
    assert not utils.is_absolute_http_url(URL("ftp://example.com"))


def test_clean_candidate_url_text() -> None:
    trim_chars = " \t\r\n'\"`"
    assert utils.clean_candidate_url_text(None, trim_chars) is None
    assert utils.clean_candidate_url_text("   ", trim_chars) is None
    assert utils.clean_candidate_url_text("  'https://e.com/x'  ", trim_chars) == "https://e.com/x"
    assert utils.clean_candidate_url_text('  "https://e.com/x"  ', trim_chars) == "https://e.com/x"


def test_clean_path_prefix_valid() -> None:
    assert utils.clean_path_prefix("api") == "/api"
    assert utils.clean_path_prefix("/api/") == "/api"
    assert utils.clean_path_prefix("///api///v1//") == "/api/v1"
    assert utils.clean_path_prefix("/") == "/"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        r"/api\test",
        "http://[",
        "https://example.com/api",
        "/api?x=1",
        "/api#frag",
        "../api",
        "./api",
        "/./api",
        "/a/../b",
    ],
)
def test_clean_path_prefix_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        utils.clean_path_prefix(raw)


def test_clean_absolute_http_url() -> None:
    cleaned = utils.clean_absolute_http_url(" https://u:p@example.com/?x=1#f ")
    assert str(cleaned) == "https://example.com"

    keep_query = utils.clean_absolute_http_url("https://example.com/a/?x=1", drop_query=False)
    assert str(keep_query) == "https://example.com/a/?x=1"


@pytest.mark.parametrize(
    "raw", ["", "   ", "http://[", "/relative", "ftp://example.com", "mailto:a@b.com", "https://"]
)
def test_clean_absolute_http_url_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        utils.clean_absolute_http_url(raw)


def test_raw_query_from_url() -> None:
    assert utils.raw_query_from_url("https://example.com/a?x=1&y=2") == "x=1&y=2"
    assert utils.raw_query_from_url("https://example.com/a") == ""


def test_safe_relative_paths() -> None:
    assert utils.safe_relative_path_for_page(URL("https://e.com/")) == Path(".")
    assert utils.safe_relative_path_for_page(URL("https://e.com/a/b")) == Path("a/b")
    assert utils.safe_relative_path_for_asset(URL("https://e.com/")) == Path("index")
    assert utils.safe_relative_path_for_asset(URL("https://e.com/a/")) == Path("a/index")
    assert utils.safe_relative_path_for_asset(URL("https://e.com/a/b")) == Path("a/b")


def test_canonicalize_page_url() -> None:
    assert str(utils.canonicalize_page_url(URL("https://e.com/a/#f"))) == "https://e.com/a"
    assert str(utils.canonicalize_page_url(URL("https://e.com/#f"))) == "https://e.com/"


def test_safe_relative_path_for_query_valid() -> None:
    assert utils.safe_relative_path_for_query("x=1", max_len=100) == Path("x=1")
    assert utils.safe_relative_path_for_query("a/b/c", max_len=100) == Path("a/b/c")


@pytest.mark.parametrize(
    "raw_q", ["", "/x=1", "a//b", "a/./b", "a/../b", r"a\b", "x=%2F", "a\x00b", "a\x1fb", "a\x7fb"]
)
def test_safe_relative_path_for_query_invalid(raw_q: str) -> None:
    assert utils.safe_relative_path_for_query(raw_q, max_len=100) is None


def test_safe_relative_path_for_query_invalid_when_too_long() -> None:
    assert utils.safe_relative_path_for_query("a" * 101, max_len=100) is None
