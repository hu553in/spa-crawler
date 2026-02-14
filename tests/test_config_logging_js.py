import logging
import re
from pathlib import Path

from crawlee import ConcurrencySettings, Glob
from yarl import URL

from spa_crawler import config, js_scripts
from spa_crawler.logging import setup_logging


def test_pattern_or_glob_as_str() -> None:
    assert config._pattern_or_glob_as_str(re.compile(r"/x")) == "/x"
    assert (
        config._pattern_or_glob_as_str(Glob("https://example.com/**")) == "https://example.com/**"
    )


def test_crawl_config_pretty_str_masks_secrets() -> None:
    cfg = config.CrawlConfig(
        base_url=URL("https://example.com"),
        login_required=True,
        login_path="/login",
        login="user",
        password="pass",
        login_input_selector="#u",
        password_input_selector="#p",
        headless=True,
        concurrency_settings=ConcurrencySettings(1, 2, desired_concurrency=1),
        out_dir=Path("out"),
        typing_delay=10,
        include_links=[Glob("https://example.com/**")],
        exclude_links=[re.compile(r".*/api.*")],
        dom_content_loaded_timeout=1,
        network_idle_timeout=1,
        rerender_timeout=1,
        success_login_redirect_timeout=1,
        additional_crawl_entrypoint_urls=["https://example.com/a"],
        verbose=False,
        quiet=False,
        ignore_http_error_status_codes=[404],
        api_path_prefixes=["/api"],
    )
    rendered = cfg.pretty_str()
    assert "***" in rendered
    assert "user" not in rendered
    assert "'password': 'pass'" not in rendered
    assert "'password': '***'" in rendered
    assert "https://example.com/**" in rendered


def test_setup_logging_sets_levels_and_effective_verbose() -> None:
    named = logging.getLogger("spa-crawler-test")
    root = logging.getLogger()
    root.setLevel(logging.ERROR)
    named.setLevel(logging.ERROR)

    assert setup_logging(verbose=False, quiet=False) is False
    assert root.level == logging.WARNING
    assert named.level == logging.WARNING

    assert setup_logging(verbose=True, quiet=False) is True
    assert root.level == logging.INFO
    assert named.level == logging.INFO

    assert setup_logging(verbose=True, quiet=True) is False
    assert root.level == logging.CRITICAL
    assert named.level == logging.CRITICAL


def test_load_js_and_cache() -> None:
    js_scripts.load_js.cache_clear()
    content1 = js_scripts.load_js("dismiss_overlays.js")
    content2 = js_scripts.load_js("dismiss_overlays.js")
    assert content1
    assert content1 == content2
    assert js_scripts.load_js.cache_info().hits >= 1
