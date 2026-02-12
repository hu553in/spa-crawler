import re
from dataclasses import dataclass
from pathlib import Path

from crawlee import ConcurrencySettings, Glob
from yarl import URL


@dataclass(frozen=True, slots=True)
class CrawlConfig:
    base_url: URL
    login_required: bool
    login_path: str
    login: str
    password: str
    login_input_selector: str
    password_input_selector: str
    headless: bool
    concurrency_settings: ConcurrencySettings
    out_dir: Path
    typing_delay: int
    include_links: list[re.Pattern | Glob]
    exclude_links: list[re.Pattern | Glob]
    dom_content_loaded_timeout: int
    network_idle_timeout: int
    rerender_timeout: int
    success_login_redirect_timeout: int
    additional_crawl_entrypoint_urls: list[str]
    verbose: bool
    quiet: bool
