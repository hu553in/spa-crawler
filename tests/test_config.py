import re
from pathlib import Path

from crawlee import ConcurrencySettings, Glob
from yarl import URL

from spa_crawler import config


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
        password="pass",  # nosec B106
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
        route_fetch_timeout=60_000,
        max_query_len_for_fs_mapping=8000,
        default_server_redirect_status=302,
        max_confidence_for_not_export=0.5,
        min_redirect_chain_len=2,
        max_url_len=2048,
        candidate_url_trim_chars=" \t\r\n'\"`",
    )
    rendered = cfg.pretty_str()
    assert "***" in rendered
    assert "user" not in rendered
    assert "'password': 'pass'" not in rendered
    assert "'password': '***'" in rendered
    assert "https://example.com/**" in rendered
