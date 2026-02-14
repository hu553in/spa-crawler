import asyncio
import json
from typing import Any, cast

import pytest
from crawlee import RequestOptions
from yarl import URL

from spa_crawler import url_discovery


class _EvalPage:
    def __init__(self, result: object = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def evaluate(self, _script: str) -> object:
        if self._exc:
            raise self._exc
        return self._result


class _Ctx:
    def __init__(self, page: _EvalPage) -> None:
        self.page = page


def test_looks_like_api_path() -> None:
    assert url_discovery.looks_like_api_path("/api", ["/api"])
    assert url_discovery.looks_like_api_path("/api/v1", ["/api"])
    assert not url_discovery.looks_like_api_path("/api-v1", ["/api"])


def test_has_known_extension() -> None:
    assert url_discovery._has_known_extension("/a.js")
    assert url_discovery._has_known_extension("/a.css")
    assert not url_discovery._has_known_extension("/a.unknownext")
    assert not url_discovery._has_known_extension("/a")


def test_normalize_candidate_url_valid_and_canonicalized() -> None:
    base = URL("https://example.com")
    assert (
        url_discovery._normalize_candidate_url(" /docs/ ", base, ["/api"])
        == "https://example.com/docs"
    )
    assert (
        url_discovery._normalize_candidate_url("https://example.com/docs/#x", base, ["/api"])
        == "https://example.com/docs"
    )


def test_normalize_candidate_url_rejects_bad_inputs() -> None:
    base = URL("https://example.com")
    too_long = "x" * 2050
    candidates = [
        "",
        "   ",
        "#section",
        "mailto:a@b.com",
        "javascript:void(0)",
        "ftp://example.com/a",
        "http://[",
        too_long,
        "https://other.example.com/x",
        "https://example.com/api",
        "https://example.com/_next/chunk.js",
        "https://example.com/static/logo.png",
    ]
    for candidate in candidates:
        assert url_discovery._normalize_candidate_url(candidate, base, ["/api"]) is None


def test_filter_and_normalize_many_sorts_and_dedups() -> None:
    base = URL("https://example.com")
    raw = ["/b", "/a/", "/a", 123, None, "https://other.example.com/x"]
    assert url_discovery._filter_and_normalize_many(raw, base, ["/api"]) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_extract_urls_from_json_bytes() -> None:
    payload = {
        "a": "/one",
        "nested": [{"url": "/two/"}, {"bad": "mailto:x@y.com"}, {"n": 1}, None],
        "also": "https://example.com/three#frag",
    }
    data = json.dumps(payload).encode("utf-8")
    out = url_discovery.extract_urls_from_json_bytes(data, URL("https://example.com"), ["/api"])
    assert out == [
        "https://example.com/one",
        "https://example.com/three",
        "https://example.com/two",
    ]


def test_extract_urls_from_json_bytes_invalid_json() -> None:
    assert (
        url_discovery.extract_urls_from_json_bytes(b"{not-json", URL("https://example.com"), ["/"])
        == []
    )
    assert url_discovery.extract_urls_from_json_bytes(b"", URL("https://example.com"), ["/"]) == []


def test_extract_page_urls_via_js_success() -> None:
    ctx = _Ctx(_EvalPage(result=["/a", "/b/", "/a"]))
    out = asyncio.run(
        url_discovery.extract_page_urls_via_js(cast(Any, ctx), URL("https://example.com"), ["/api"])
    )
    assert out == ["https://example.com/a", "https://example.com/b"]


def test_extract_page_urls_via_js_failure() -> None:
    ctx = _Ctx(_EvalPage(exc=RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            url_discovery.extract_page_urls_via_js(
                cast(Any, ctx), URL("https://example.com"), ["/api"]
            )
        )


def test_transform_enqueue_request() -> None:
    transform = url_discovery.transform_enqueue_request(URL("https://example.com"), ["/api"])

    assert transform(cast(RequestOptions, {"url": "mailto:a@b.com"})) == "skip"
    assert transform(cast(RequestOptions, {"url": "https://other.example.com"})) == "skip"

    opts = cast(RequestOptions, {"url": "/docs/"})
    result = transform(opts)
    assert result == {"url": "https://example.com/docs", "unique_key": "https://example.com/docs"}
