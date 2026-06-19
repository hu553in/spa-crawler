import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from spa_crawler import page_ops


class _Keyboard:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        if self.fail:
            raise RuntimeError("keyboard fail")
        self.presses.append(key)


class _Mouse:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        if self.fail:
            raise RuntimeError("mouse fail")
        self.clicks.append((x, y))


class _Locator:
    async def click(self) -> None:
        return None

    async def type(self, _text: str, delay: int) -> None:  # noqa: ARG002
        return None

    async def press(self, _key: str) -> None:
        return None

    @property
    def first(self) -> "_Locator":
        return self


class _Page:
    def __init__(
        self,
        url: str,
        html: str = "<html>ok</html>",
        content_exc: Exception | None = None,
        wait_exc: Exception | None = None,
        close_exc: Exception | None = None,
        eval_exc: Exception | None = None,
        keyboard_fail: bool = False,
        mouse_fail: bool = False,
    ) -> None:
        self.url = url
        self._html = html
        self._content_exc = content_exc
        self._wait_exc = wait_exc
        self._close_exc = close_exc
        self._eval_exc = eval_exc
        self.keyboard = _Keyboard(fail=keyboard_fail)
        self.mouse = _Mouse(fail=mouse_fail)
        self.evaluate_calls: list[str] = []
        self.wait_calls: list[tuple[str, int]] = []
        self.timeout_calls: list[int] = []
        self.closed = 0
        self.events: dict[str, object] = {}

    async def evaluate(self, script: str) -> None:
        if self._eval_exc:
            raise self._eval_exc
        self.evaluate_calls.append(script)

    async def content(self) -> str:
        if self._content_exc:
            raise self._content_exc
        return self._html

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        if self._wait_exc:
            raise self._wait_exc
        self.wait_calls.append((state, timeout))

    async def wait_for_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)

    async def close(self) -> None:
        if self._close_exc:
            raise self._close_exc
        self.closed += 1

    def on(self, event: str, callback: object) -> None:
        self.events[event] = callback

    def locator(self, _selector: str) -> _Locator:
        return _Locator()


class _Req:
    def __init__(self, url: str, loaded_url: str | None = None) -> None:
        self.url = url
        self.loaded_url = loaded_url


class _Log:
    def __init__(self) -> None:
        self.info_msgs: list[str] = []
        self.warning_msgs: list[str] = []
        self.exception_msgs: list[str] = []

    def info(self, msg: str) -> None:
        self.info_msgs.append(msg)

    def warning(self, msg: str) -> None:
        self.warning_msgs.append(msg)

    def exception(self, msg: str) -> None:
        self.exception_msgs.append(msg)


class _Ctx:
    def __init__(self, page: _Page, request: _Req) -> None:
        self.page = page
        self.request = request
        self.log = _Log()
        self.scroll_calls = 0

    async def infinite_scroll(self) -> None:
        self.scroll_calls += 1


def test_maybe_attach_download_hook_and_dedup() -> None:
    page = _Page("https://example.com")
    ctx = _Ctx(page, _Req("https://example.com"))

    page_ops.maybe_attach_download_hook(cast(Any, ctx), verbose=True)
    assert "download" in page.events
    page_ops.maybe_attach_download_hook(cast(Any, ctx), verbose=True)
    assert len(page.events) == 1

    download_callback = cast(Callable[[object], None], page.events["download"])
    download = type("D", (), {"url": "https://example.com/file"})()
    download_callback(download)
    assert ctx.log.info_msgs and "download" in ctx.log.info_msgs[0]


def test_dismiss_overlays_swallows_errors() -> None:
    page = _Page(
        "https://example.com", eval_exc=RuntimeError("eval"), keyboard_fail=True, mouse_fail=True
    )
    ctx = _Ctx(page, _Req("https://example.com"))
    asyncio.run(page_ops._dismiss_overlays(cast(Any, ctx)))


def test_save_html_without_query(tmp_path: Path) -> None:
    page = _Page("https://example.com", html="<html>ok</html>")
    ctx = _Ctx(page, _Req("https://example.com"))
    asyncio.run(
        page_ops.save_html(
            cast(Any, ctx), tmp_path, verbose=True, max_query_len_for_fs_mapping=8000
        )
    )
    assert (tmp_path / "pages/index.html").read_text(encoding="utf-8") == "<html>ok</html>"
    assert ctx.log.info_msgs


def test_save_html_with_query(tmp_path: Path) -> None:
    page = _Page("https://example.com/a")
    ctx = _Ctx(page, _Req("https://example.com/a?x=1"))
    asyncio.run(
        page_ops.save_html(
            cast(Any, ctx), tmp_path, verbose=False, max_query_len_for_fs_mapping=8000
        )
    )
    assert (tmp_path / "pages_q/a/x=1/index.html").exists()


def test_save_html_skips_unsafe_query(tmp_path: Path) -> None:
    page = _Page("https://example.com/a")
    ctx = _Ctx(page, _Req("https://example.com/a?a//b"))
    asyncio.run(
        page_ops.save_html(
            cast(Any, ctx), tmp_path, verbose=False, max_query_len_for_fs_mapping=8000
        )
    )
    assert not (tmp_path / "pages_q").exists()
    assert ctx.log.warning_msgs


def test_save_html_logs_exception_on_write_failure(tmp_path: Path) -> None:
    page = _Page("https://example.com", content_exc=RuntimeError("fail"))
    ctx = _Ctx(page, _Req("https://example.com"))
    asyncio.run(
        page_ops.save_html(
            cast(Any, ctx), tmp_path, verbose=True, max_query_len_for_fs_mapping=8000
        )
    )
    assert ctx.log.exception_msgs


def test_wait_for_stable_page_and_close() -> None:
    page = _Page("https://example.com")
    ctx = _Ctx(page, _Req("https://example.com"))
    asyncio.run(page_ops.wait_for_stable_page(cast(Any, ctx), 1000, 2000, 3000))
    assert ("domcontentloaded", 1000) in page.wait_calls
    assert ("networkidle", 2000) in page.wait_calls
    assert page.timeout_calls == [3000]
    asyncio.run(page_ops.close_page(cast(Any, ctx)))
    assert page.closed == 1


def test_wait_for_stable_page_and_close_swallow_errors() -> None:
    page = _Page(
        "https://example.com", wait_exc=RuntimeError("wait"), close_exc=RuntimeError("close")
    )
    ctx = _Ctx(page, _Req("https://example.com"))
    asyncio.run(page_ops.wait_for_stable_page(cast(Any, ctx), 1, 2, 3))
    asyncio.run(page_ops.close_page(cast(Any, ctx)))


def test_soft_interaction_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _Page("https://example.com")
    ctx = _Ctx(page, _Req("https://example.com"))
    called = {"dismiss": 0}

    async def fake_dismiss(_ctx: _Ctx) -> None:
        called["dismiss"] += 1

    monkeypatch.setattr(page_ops, "_dismiss_overlays", fake_dismiss)
    asyncio.run(page_ops.soft_interaction_pass(cast(Any, ctx)))
    assert ctx.scroll_calls == 2  # noqa: PLR2004
    assert called["dismiss"] == 1
