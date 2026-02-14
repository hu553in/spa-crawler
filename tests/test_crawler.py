import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from crawlee import ConcurrencySettings, Glob
from yarl import URL

from spa_crawler import crawler as crawler_mod
from spa_crawler.config import CrawlConfig


class _FakeRequest:
    def __init__(self, url: str, label: str | None = None) -> None:
        self.url = url
        self.label = label
        self.loaded_url = None

    @staticmethod
    def from_url(url: str, label: str | None = None) -> "_FakeRequest":
        return _FakeRequest(url, label=label)


class _FakeElement:
    def __init__(self) -> None:
        self.clicked = 0
        self.typed: list[tuple[str, int]] = []
        self.pressed: list[str] = []

    async def click(self) -> None:
        self.clicked += 1

    async def type(self, text: str, delay: int) -> None:
        self.typed.append((text, delay))

    async def press(self, key: str) -> None:
        self.pressed.append(key)

    @property
    def first(self) -> "_FakeElement":
        return self


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.login_el = _FakeElement()
        self.password_el = _FakeElement()
        self.wait_calls: list[int] = []

    def locator(self, selector: str) -> _FakeElement:
        if "login" in selector:
            return self.login_el
        return self.password_el

    async def wait_for_url(self, predicate: Callable[[str], bool], timeout: int) -> None:
        self.wait_calls.append(timeout)
        assert predicate("https://example.com/home")


class _FakeLog:
    def __init__(self) -> None:
        self.info_msgs: list[str] = []
        self.warning_msgs: list[str] = []

    def info(self, msg: str) -> None:
        self.info_msgs.append(msg)

    def warning(self, msg: str) -> None:
        self.warning_msgs.append(msg)


class _FakeCtx:
    def __init__(self, req: _FakeRequest, page_url: str) -> None:
        self.request = req
        self.page = _FakePage(page_url)
        self.goto_options: dict[str, str] = {}
        self.log = _FakeLog()
        self.added_requests: list[list[str | _FakeRequest]] = []
        self.enqueued = 0

    async def add_requests(self, reqs: list[str | _FakeRequest]) -> None:
        self.added_requests.append(reqs)

    async def enqueue_links(self, **kwargs: Any) -> None:
        self.enqueued += 1
        transform = kwargs["transform_request_function"]
        assert callable(transform)
        transform({"url": "/q"})


class _FakeRouter:
    def __init__(self) -> None:
        self.handler: Callable[[_FakeCtx], Awaitable[None]] | None = None

    def default_handler(self, fn: Callable[[_FakeCtx], Awaitable[None]]):
        self.handler = fn
        return fn


class _FakePlaywrightCrawler:
    page_url_by_label: ClassVar[dict[str | None, str]] = {}
    last_instance: "_FakePlaywrightCrawler | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.router = _FakeRouter()
        self.pre_nav: Callable[[_FakeCtx], Awaitable[None]] | None = None
        self.run_entrypoints: list[str | _FakeRequest] | None = None
        self.contexts: list[_FakeCtx] = []
        _FakePlaywrightCrawler.last_instance = self

    def pre_navigation_hook(self, fn: Callable[[_FakeCtx], Awaitable[None]]) -> None:
        self.pre_nav = fn

    async def run(self, entrypoints: list[str | _FakeRequest]) -> None:
        self.run_entrypoints = entrypoints
        for ep in entrypoints:
            req = ep if isinstance(ep, _FakeRequest) else _FakeRequest(str(ep), label=None)
            page_url = self.page_url_by_label.get(req.label, req.url)
            ctx = _FakeCtx(req, page_url)
            self.contexts.append(ctx)
            if self.pre_nav:
                await self.pre_nav(ctx)
            if self.router.handler:
                await self.router.handler(ctx)


def _make_config(**overrides: Any) -> CrawlConfig:
    base = CrawlConfig(
        base_url=URL("https://example.com"),
        login_required=False,
        login_path="/login",
        login="user",
        password="pass",
        login_input_selector="input[name='login']",
        password_input_selector="input[name='password']",
        headless=True,
        concurrency_settings=ConcurrencySettings(1, 2, desired_concurrency=1),
        out_dir=Path("out"),
        typing_delay=50,
        include_links=[Glob("https://example.com/**")],
        exclude_links=[re.compile(r".*/api.*")],
        dom_content_loaded_timeout=1,
        network_idle_timeout=1,
        rerender_timeout=1,
        success_login_redirect_timeout=1,
        additional_crawl_entrypoint_urls=["https://example.com/a/"],
        verbose=True,
        quiet=False,
        ignore_http_error_status_codes=[404],
        api_path_prefixes=["/api"],
    )
    return replace(base, **overrides)


def test_crawl_page_flow_and_quiet(monkeypatch) -> None:
    setup_calls: list[tuple[bool, bool]] = []
    close_calls = {"n": 0}
    pre_nav_calls = {"route": 0, "download": 0}

    async def noop(*_a, **_k) -> None:
        return None

    async def fake_extract(*_a: Any, **_k: Any) -> list[str]:
        return ["https://example.com/discovered"]

    def fake_transform(*_a: Any, **_k: Any) -> Callable[[dict[str, str]], dict[str, str]]:
        def _fn(opts: dict[str, str]) -> dict[str, str]:
            opts["unique_key"] = "k"
            return opts

        return _fn

    async def fake_close(_ctx: _FakeCtx) -> None:
        close_calls["n"] += 1

    async def fake_route(*_a, **_k) -> None:
        pre_nav_calls["route"] += 1

    def fake_download(*_a, **_k) -> None:
        pre_nav_calls["download"] += 1

    def fake_setup_logging(*, verbose: bool, quiet: bool) -> bool:
        setup_calls.append((verbose, quiet))
        return False

    monkeypatch.setattr(crawler_mod, "PlaywrightCrawler", _FakePlaywrightCrawler)
    monkeypatch.setattr(crawler_mod, "Request", _FakeRequest)
    monkeypatch.setattr(crawler_mod, "ImpitHttpClient", object)
    monkeypatch.setattr(crawler_mod, "SessionPool", lambda *_a, **_k: object())
    monkeypatch.setattr(crawler_mod, "setup_logging", fake_setup_logging)
    monkeypatch.setattr(crawler_mod, "wait_for_stable_page", noop)
    monkeypatch.setattr(crawler_mod, "soft_interaction_pass", noop)
    monkeypatch.setattr(crawler_mod, "save_html", noop)
    monkeypatch.setattr(crawler_mod, "close_page", fake_close)
    monkeypatch.setattr(crawler_mod, "extract_page_urls_via_js", fake_extract)
    monkeypatch.setattr(crawler_mod, "transform_enqueue_request", fake_transform)
    monkeypatch.setattr(crawler_mod, "attach_route_mirror", fake_route)
    monkeypatch.setattr(crawler_mod, "maybe_attach_download_hook", fake_download)

    cfg = _make_config(login_required=False, quiet=True)
    asyncio.run(crawler_mod.crawl(cfg))

    inst = _FakePlaywrightCrawler.last_instance
    assert inst is not None
    assert setup_calls == [(True, True)]
    assert inst.run_entrypoints is not None
    assert len(inst.run_entrypoints) == 2  # noqa: PLR2004
    assert close_calls["n"] == 2  # noqa: PLR2004
    assert pre_nav_calls["route"] == 2  # noqa: PLR2004
    assert pre_nav_calls["download"] == 2  # noqa: PLR2004
    assert inst.contexts[0].enqueued == 1
    assert inst.contexts[0].added_requests


def test_crawl_login_flow(monkeypatch) -> None:
    _FakePlaywrightCrawler.page_url_by_label = {"login": "https://example.com/login"}

    async def noop(*_a, **_k) -> None:
        return None

    async def fake_extract(*_a: Any, **_k: Any) -> list[str]:
        return []

    monkeypatch.setattr(crawler_mod, "PlaywrightCrawler", _FakePlaywrightCrawler)
    monkeypatch.setattr(crawler_mod, "Request", _FakeRequest)
    monkeypatch.setattr(crawler_mod, "ImpitHttpClient", object)
    monkeypatch.setattr(crawler_mod, "SessionPool", lambda *_a, **_k: object())
    monkeypatch.setattr(crawler_mod, "wait_for_stable_page", noop)
    monkeypatch.setattr(crawler_mod, "soft_interaction_pass", noop)
    monkeypatch.setattr(crawler_mod, "save_html", noop)
    monkeypatch.setattr(crawler_mod, "close_page", noop)
    monkeypatch.setattr(crawler_mod, "extract_page_urls_via_js", fake_extract)
    monkeypatch.setattr(crawler_mod, "transform_enqueue_request", lambda *_a, **_k: lambda x: x)
    monkeypatch.setattr(crawler_mod, "attach_route_mirror", noop)
    monkeypatch.setattr(crawler_mod, "maybe_attach_download_hook", lambda *_a, **_k: None)

    cfg = _make_config(login_required=True, quiet=False)
    asyncio.run(crawler_mod.crawl(cfg))

    inst = _FakePlaywrightCrawler.last_instance
    assert inst is not None
    assert inst.run_entrypoints is not None
    assert len(inst.run_entrypoints) == 1
    ctx = inst.contexts[0]
    assert ctx.page.login_el.clicked == 1
    assert ctx.page.password_el.clicked == 1
    assert ctx.page.wait_calls == [cfg.success_login_redirect_timeout]
    assert ctx.added_requests


def test_crawl_pwerror_download_is_swallowed(monkeypatch) -> None:
    async def noop(*_a, **_k) -> None:
        return None

    async def fail_save(*_a, **_k) -> None:
        raise crawler_mod.PWError("Download is starting")

    async def fake_extract(*_a: Any, **_k: Any) -> list[str]:
        return []

    monkeypatch.setattr(crawler_mod, "PlaywrightCrawler", _FakePlaywrightCrawler)
    monkeypatch.setattr(crawler_mod, "Request", _FakeRequest)
    monkeypatch.setattr(crawler_mod, "ImpitHttpClient", object)
    monkeypatch.setattr(crawler_mod, "SessionPool", lambda *_a, **_k: object())
    monkeypatch.setattr(crawler_mod, "wait_for_stable_page", noop)
    monkeypatch.setattr(crawler_mod, "soft_interaction_pass", noop)
    monkeypatch.setattr(crawler_mod, "save_html", fail_save)
    monkeypatch.setattr(crawler_mod, "close_page", noop)
    monkeypatch.setattr(crawler_mod, "extract_page_urls_via_js", fake_extract)
    monkeypatch.setattr(crawler_mod, "transform_enqueue_request", lambda *_a, **_k: lambda x: x)
    monkeypatch.setattr(crawler_mod, "attach_route_mirror", noop)
    monkeypatch.setattr(crawler_mod, "maybe_attach_download_hook", lambda *_a, **_k: None)

    cfg = _make_config(login_required=False, quiet=False, verbose=True)
    asyncio.run(crawler_mod.crawl(cfg))
    inst = _FakePlaywrightCrawler.last_instance
    assert inst is not None
    assert any("goto-download" in msg for msg in inst.contexts[0].log.info_msgs)


def test_crawl_logs_discover_and_route_attach_errors(monkeypatch) -> None:
    async def noop(*_a, **_k) -> None:
        return None

    async def fail_extract(*_a: Any, **_k: Any) -> list[str]:
        raise RuntimeError("discover boom")

    async def fail_route(*_a, **_k) -> None:
        raise RuntimeError("route boom")

    monkeypatch.setattr(crawler_mod, "PlaywrightCrawler", _FakePlaywrightCrawler)
    monkeypatch.setattr(crawler_mod, "Request", _FakeRequest)
    monkeypatch.setattr(crawler_mod, "ImpitHttpClient", object)
    monkeypatch.setattr(crawler_mod, "SessionPool", lambda *_a, **_k: object())
    monkeypatch.setattr(crawler_mod, "wait_for_stable_page", noop)
    monkeypatch.setattr(crawler_mod, "soft_interaction_pass", noop)
    monkeypatch.setattr(crawler_mod, "save_html", noop)
    monkeypatch.setattr(crawler_mod, "close_page", noop)
    monkeypatch.setattr(crawler_mod, "extract_page_urls_via_js", fail_extract)
    monkeypatch.setattr(crawler_mod, "transform_enqueue_request", lambda *_a, **_k: lambda x: x)
    monkeypatch.setattr(crawler_mod, "attach_route_mirror", fail_route)
    monkeypatch.setattr(crawler_mod, "maybe_attach_download_hook", lambda *_a, **_k: None)

    cfg = _make_config(login_required=False, quiet=False, verbose=False)
    asyncio.run(crawler_mod.crawl(cfg))

    inst = _FakePlaywrightCrawler.last_instance
    assert inst is not None
    warning_msgs = [msg for ctx in inst.contexts for msg in ctx.log.warning_msgs]
    assert any("route-mirror-attach-error" in msg for msg in warning_msgs)
    assert any("discover-error" in msg for msg in warning_msgs)


def test_crawl_rejects_root_login_path() -> None:
    cfg = _make_config(login_required=True, login_path="/")
    with pytest.raises(ValueError, match="login_path '/' is not supported"):
        asyncio.run(crawler_mod.crawl(cfg))
