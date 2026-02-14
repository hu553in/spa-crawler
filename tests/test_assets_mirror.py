import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, cast

import pytest
from yarl import URL

from spa_crawler import assets_mirror


class _Req:
    def __init__(self, url: str, resource_type: str) -> None:
        self.url = url
        self.resource_type = resource_type


class _Resp:
    def __init__(
        self, status: int, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


class _Route:
    def __init__(self, response: _Resp | None = None, fetch_exc: Exception | None = None) -> None:
        self._response = response
        self._fetch_exc = fetch_exc
        self.continued = 0
        self.fulfilled: list[_Resp] = []

    async def continue_(self) -> None:
        self.continued += 1

    async def fetch(self, **_kwargs: Any) -> _Resp:
        if self._fetch_exc:
            raise self._fetch_exc
        assert self._response is not None
        return self._response

    async def fulfill(self, response: _Resp) -> None:
        self.fulfilled.append(response)


class _Log:
    def __init__(self) -> None:
        self.info_msgs: list[str] = []
        self.warning_msgs: list[str] = []

    def info(self, msg: str) -> None:
        self.info_msgs.append(msg)

    def warning(self, msg: str) -> None:
        self.warning_msgs.append(msg)


class _Page:
    def __init__(self) -> None:
        self.route_handler: Awaitable[Any] | None = None

    async def route(self, _pattern: str, handler) -> None:
        self.route_handler = handler


class _Ctx:
    def __init__(self) -> None:
        self.page = _Page()
        self.log = _Log()
        self.added_requests: list[list[str]] = []

    async def add_requests(self, urls: list[str]) -> None:
        self.added_requests.append(urls)


def test_guess_extension_from_content_type() -> None:
    assert assets_mirror._guess_extension_from_content_type(None) == ""
    assert assets_mirror._guess_extension_from_content_type("text/css; charset=utf-8") == ".css"


def test_destination_for_asset() -> None:
    out = Path("out")
    base = URL("https://example.com")

    assert (
        assets_mirror._destination_for_asset(
            URL("https://other.example.com/a"),
            base,
            out,
            content_type="text/css",
            api_path_prefixes=["/api"],
        )
        is None
    )
    assert (
        assets_mirror._destination_for_asset(
            URL("https://example.com/api"),
            base,
            out,
            content_type="application/json",
            api_path_prefixes=["/api"],
        )
        is None
    )

    no_suffix = assets_mirror._destination_for_asset(
        URL("https://example.com/static/app"),
        base,
        out,
        content_type="text/css",
        api_path_prefixes=["/api"],
    )
    assert no_suffix == out / "assets/static/app.css"

    unknown_suffix = assets_mirror._destination_for_asset(
        URL("https://example.com/static/file"),
        base,
        out,
        content_type="application/x-unknown",
        api_path_prefixes=["/api"],
    )
    assert unknown_suffix == out / "assets/static/file.bin"

    with_suffix = assets_mirror._destination_for_asset(
        URL("https://example.com/static/app.js"),
        base,
        out,
        content_type="text/plain",
        api_path_prefixes=["/api"],
    )
    assert with_suffix == out / "assets/static/app.js"

    with_query = assets_mirror._destination_for_asset(
        URL("https://example.com/static/app"),
        base,
        out,
        raw_query="v=1",
        content_type="text/css",
        api_path_prefixes=["/api"],
    )
    assert with_query == out / "assets_q/static/app/v=1"

    root_with_query = assets_mirror._destination_for_asset(
        URL("https://example.com/"),
        base,
        out,
        raw_query="v=1",
        content_type="text/css",
        api_path_prefixes=["/api"],
    )
    assert root_with_query == out / "assets_q/v=1"

    dir_with_query = assets_mirror._destination_for_asset(
        URL("https://example.com/static/"),
        base,
        out,
        raw_query="v=1",
        content_type="text/css",
        api_path_prefixes=["/api"],
    )
    assert dir_with_query == out / "assets_q/static/v=1"

    unsafe_query = assets_mirror._destination_for_asset(
        URL("https://example.com/static/app"),
        base,
        out,
        raw_query="a//b",
        content_type="text/css",
        api_path_prefixes=["/api"],
    )
    assert unsafe_query is None


def test_write_asset_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "a/b/file.bin"
    assert assets_mirror._write_asset_overwrite(path, b"abc")
    assert path.read_bytes() == b"abc"
    assert not assets_mirror._write_asset_overwrite(path, b"")

    blocked = tmp_path / "blocked"
    blocked.mkdir()
    assert not assets_mirror._write_asset_overwrite(blocked, b"x")


def test_attach_route_mirror_document_and_api_paths(tmp_path: Path) -> None:
    ctx = _Ctx()
    asyncio.run(
        assets_mirror.attach_route_mirror(
            cast(Any, ctx),
            URL("https://example.com"),
            tmp_path,
            verbose=True,
            api_path_prefixes=["/api"],
        )
    )
    assert callable(ctx.page.route_handler)

    # Re-attaching should do nothing.
    route_handler_before = ctx.page.route_handler
    asyncio.run(
        assets_mirror.attach_route_mirror(
            cast(Any, ctx),
            URL("https://example.com"),
            tmp_path,
            verbose=True,
            api_path_prefixes=["/api"],
        )
    )
    assert ctx.page.route_handler is route_handler_before

    # Document requests are skipped via ``continue_``.
    r1 = _Route(_Resp(200, b"ok"))
    asyncio.run(ctx.page.route_handler(r1, _Req("https://example.com/", "document")))
    assert r1.continued == 1

    # API requests are skipped via ``continue_``.
    r2 = _Route(_Resp(200, b"ok"))
    asyncio.run(ctx.page.route_handler(r2, _Req("https://example.com/api", "xhr")))
    assert r2.continued == 1

    # Cross-origin requests are passed through without route.fetch mirroring.
    r3 = _Route(fetch_exc=RuntimeError("must not fetch"))
    asyncio.run(ctx.page.route_handler(r3, _Req("https://cdn.example.com/a.js", "script")))
    assert r3.continued == 1


def test_attach_route_mirror_redirect_and_success_and_error(tmp_path: Path) -> None:
    ctx = _Ctx()
    asyncio.run(
        assets_mirror.attach_route_mirror(
            cast(Any, ctx),
            URL("https://example.com"),
            tmp_path,
            verbose=True,
            api_path_prefixes=["/api"],
        )
    )
    handler = ctx.page.route_handler
    assert callable(handler)

    # Redirect response: fulfill without writes.
    redirect_resp = _Resp(302, b"", {})
    redirect_route = _Route(redirect_resp)
    asyncio.run(handler(redirect_route, _Req("https://example.com/r", "fetch")))
    assert redirect_route.fulfilled == [redirect_resp]

    # Successful Next.js JSON response: write and enqueue discovered URLs.
    next_payload = json.dumps({"u": "/page"}).encode("utf-8")
    ok_resp = _Resp(200, next_payload, {"content-type": "application/json"})
    ok_route = _Route(ok_resp)
    asyncio.run(handler(ok_route, _Req("https://example.com/_next/data/a.json", "fetch")))
    assert ok_route.fulfilled == [ok_resp]
    assert ctx.added_requests == [["https://example.com/page"]]
    assert ctx.log.info_msgs

    # Fetch exception: warn and continue.
    err_route = _Route(fetch_exc=RuntimeError("boom"))
    asyncio.run(handler(err_route, _Req("https://example.com/a.js", "script")))
    assert err_route.continued == 1
    assert ctx.log.warning_msgs


def test_attach_route_mirror_warnings_without_verbose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _Ctx()
    asyncio.run(
        assets_mirror.attach_route_mirror(
            cast(Any, ctx),
            URL("https://example.com"),
            tmp_path,
            verbose=False,
            api_path_prefixes=["/api"],
        )
    )
    handler = ctx.page.route_handler
    assert callable(handler)

    monkeypatch.setattr(assets_mirror, "_write_asset_overwrite", lambda *_a, **_k: False)
    ok_resp = _Resp(200, b"abc", {"content-type": "application/javascript"})
    ok_route = _Route(ok_resp)
    asyncio.run(handler(ok_route, _Req("https://example.com/a.js", "script")))
    assert any("asset-write-failed" in msg for msg in ctx.log.warning_msgs)

    err_route = _Route(fetch_exc=RuntimeError("boom"))
    asyncio.run(handler(err_route, _Req("https://example.com/b.js", "script")))
    assert any("route-error" in msg for msg in ctx.log.warning_msgs)


def test_attach_route_mirror_dedups_same_url_per_run(tmp_path: Path) -> None:
    ctx = _Ctx()
    asyncio.run(
        assets_mirror.attach_route_mirror(
            cast(Any, ctx),
            URL("https://example.com"),
            tmp_path,
            verbose=False,
            api_path_prefixes=["/api"],
        )
    )
    handler = ctx.page.route_handler
    assert callable(handler)

    first = _Route(_Resp(200, b"abc", {"content-type": "application/javascript"}))
    asyncio.run(handler(first, _Req("https://example.com/a.js", "script")))
    assert first.fulfilled

    # The second request for the same URL should bypass route.fetch and continue directly.
    second = _Route(fetch_exc=RuntimeError("must not fetch"))
    asyncio.run(handler(second, _Req("https://example.com/a.js", "script")))
    assert second.continued == 1
