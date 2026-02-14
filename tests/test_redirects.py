import asyncio
from collections import Counter
from pathlib import Path

from yarl import URL

from spa_crawler.redirects import (
    RedirectCollector,
    _normalize_redirect_url,
    _relative_redirect_target,
    _render_redirect_html,
)


class _StatusResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _NavRequest:
    def __init__(
        self, url: str, *, status: int | None, redirected_from: "_NavRequest | None" = None
    ) -> None:
        self.url = url
        self.redirected_from = redirected_from
        self._status = status

    async def response(self) -> _StatusResponse | None:
        if self._status is None:
            return None
        return _StatusResponse(self._status)


class _NavResponse:
    def __init__(self, request: _NavRequest) -> None:
        self.request = request


def test_normalize_redirect_url_filters() -> None:
    base = URL("https://example.com")
    api_prefixes = ["/api"]

    assert (
        _normalize_redirect_url("https://example.com/problems/#frag", base, api_prefixes)
        == "https://example.com/problems"
    )
    assert (
        _normalize_redirect_url("https://example.com/", base, api_prefixes) == "https://example.com"
    )
    assert _normalize_redirect_url("https://cdn.example.com/a", base, api_prefixes) is None
    assert _normalize_redirect_url("https://example.com/api/v1", base, api_prefixes) is None
    assert _normalize_redirect_url("mailto:test@example.com", base, api_prefixes) is None
    assert _normalize_redirect_url("not-a-url", base, api_prefixes) is None
    assert _normalize_redirect_url("http://[::1", base, api_prefixes) is None


def test_private_helpers_edge_cases() -> None:
    assert _relative_redirect_target(URL("foo?x=1")) == "/foo?x=1"
    html = _render_redirect_html("/a?x=1&y=2")
    assert 'window.location.replace("/a?x=1&y=2")' in html
    assert "url=/a?x=1&amp;y=2" in html
    assert RedirectCollector._confidence(Counter(), "x") == 0.0


def test_write_server_redirect_rules_from_http_observations(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])

    source = _NavRequest("https://example.com/", status=302)
    target = _NavRequest(
        "https://example.com/problems/?from=home", status=200, redirected_from=source
    )
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(target)))
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(target)))

    caddy_path = collector.write_server_redirect_rules(tmp_path)
    caddy = caddy_path.read_text(encoding="utf-8")

    assert caddy_path == tmp_path / "redirects.caddy"
    assert "redir / /problems 302" in caddy
    assert "rules_written: 1" in caddy
    assert "skipped_query_sources: 0" in caddy


def test_write_server_redirect_rules_prefers_http_in_tie(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])

    source = _NavRequest("https://example.com/", status=301)
    target = _NavRequest("https://example.com/http", status=200, redirected_from=source)
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(target)))
    collector.observe_client_redirect("https://example.com/", "https://example.com/client")

    caddy_path = collector.write_server_redirect_rules(tmp_path, max_confidence_for_not_export=0.0)
    caddy = caddy_path.read_text(encoding="utf-8")

    assert "redir / /http 301" in caddy
    assert "/client" not in caddy


def test_write_server_redirect_rules_skips_query_sources(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])

    collector.observe_client_redirect(
        "https://example.com/search?q=1", "https://example.com/problems"
    )
    caddy_path = collector.write_server_redirect_rules(tmp_path, max_confidence_for_not_export=0.0)
    caddy = caddy_path.read_text(encoding="utf-8")

    assert "redir /search" not in caddy
    assert "rules_written: 0" in caddy
    assert "skipped_query_sources: 1" in caddy


def test_observe_http_redirects_ignores_invalid_shapes(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])

    class _NoRequestResponse:
        request = None

    # response.request is missing.
    asyncio.run(collector.observe_http_redirects_from_response(_NoRequestResponse()))

    # Chain length is 1.
    asyncio.run(
        collector.observe_http_redirects_from_response(
            _NavResponse(_NavRequest("https://example.com", status=200))
        )
    )

    # Source and target normalize to the same URL.
    src_same = _NavRequest("https://example.com/", status=302)
    dst_same = _NavRequest("https://example.com", status=200, redirected_from=src_same)
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(dst_same)))

    # Source response is missing.
    src_no_resp = _NavRequest("https://example.com/start", status=None)
    dst_no_resp = _NavRequest("https://example.com/end", status=200, redirected_from=src_no_resp)
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(dst_no_resp)))

    # Source status is not in 3xx range.
    src_bad_status = _NavRequest("https://example.com/a", status=200)
    dst_bad_status = _NavRequest(
        "https://example.com/b", status=200, redirected_from=src_bad_status
    )
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(dst_bad_status)))

    # Source status type is invalid.
    src_weird_status = _NavRequest("https://example.com/c", status="302")  # type: ignore[arg-type]
    dst_weird_status = _NavRequest(
        "https://example.com/d", status=200, redirected_from=src_weird_status
    )
    asyncio.run(collector.observe_http_redirects_from_response(_NavResponse(dst_weird_status)))

    caddy_path = collector.write_server_redirect_rules(tmp_path, max_confidence_for_not_export=0.0)
    caddy = caddy_path.read_text(encoding="utf-8")
    assert "rules_written: 0" in caddy


def test_export_skips_low_confidence_candidates(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])
    # Same source/target must be ignored.
    collector.observe_client_redirect("https://example.com/", "https://example.com")
    collector.observe_client_redirect("https://example.com/", "https://example.com/a")
    collector.observe_client_redirect("https://example.com/", "https://example.com/b")

    caddy_path = collector.write_server_redirect_rules(tmp_path)
    caddy = caddy_path.read_text(encoding="utf-8")
    assert "rules_written: 0" in caddy


def test_write_html_redirect_pages(tmp_path: Path) -> None:
    collector = RedirectCollector(URL("https://example.com"), ["/api"])

    collector.observe_client_redirect("https://example.com/", "https://example.com/problems")
    collector.observe_client_redirect(
        "https://example.com/search?q=1", "https://example.com/problems"
    )

    existing = tmp_path / "pages" / "about" / "index.html"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("existing", encoding="utf-8")
    collector.observe_client_redirect("https://example.com/about", "https://example.com/problems")
    collector.observe_client_redirect(
        "https://example.com/unsafe?a//b", "https://example.com/problems"
    )

    stats = collector.write_html_redirect_pages(tmp_path, max_confidence_for_not_export=0.0)
    assert stats == {"created": 2, "skipped_existing": 1, "skipped_unsafe_query": 1}

    root_html = (tmp_path / "pages" / "index.html").read_text(encoding="utf-8")
    query_html = (tmp_path / "pages_q" / "search" / "q=1" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'window.location.replace("/problems")' in root_html
    assert 'meta http-equiv="refresh" content="0; url=/problems"' in root_html
    assert 'window.location.replace("/problems")' in query_html
    assert existing.read_text(encoding="utf-8") == "existing"
