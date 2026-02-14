import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from crawlee import ConcurrencySettings, Glob
from rich.console import Console
from yarl import URL


def _pattern_or_glob_as_str(pattern_or_glob: re.Pattern | Glob) -> str:
    """Render a regex/glob matcher as a human-readable string."""
    if isinstance(pattern_or_glob, re.Pattern):
        return pattern_or_glob.pattern
    return pattern_or_glob.glob


@dataclass(frozen=True, slots=True)
class CrawlConfig:
    """Runtime crawler configuration normalized from CLI input."""

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
    ignore_http_error_status_codes: list[int]
    api_path_prefixes: list[str]

    def pretty_str(self) -> str:
        """Render config for console output with sensitive values masked."""
        formatted = replace(
            self,
            base_url=str(self.base_url),
            login="***",
            password="***",
            concurrency_settings={
                "min_concurrency": self.concurrency_settings.min_concurrency,
                "max_concurrency": self.concurrency_settings.max_concurrency,
                "desired_concurrency": self.concurrency_settings.desired_concurrency,
            },
            include_links=[_pattern_or_glob_as_str(link) for link in self.include_links],
            exclude_links=[_pattern_or_glob_as_str(link) for link in self.exclude_links],
            out_dir=str(self.out_dir),
        )
        console = Console()
        with console.capture() as capture:
            console.print(asdict(formatted))
        return capture.get()
