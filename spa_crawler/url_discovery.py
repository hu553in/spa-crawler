import json
import mimetypes
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from crawlee import RequestOptions
from crawlee.crawlers import PlaywrightCrawlingContext
from yarl import URL

from spa_crawler.js_scripts import load_js
from spa_crawler.utils import (
    canonicalize_page_url,
    clean_candidate_url_text,
    is_absolute_http_url,
    path_has_prefix,
)

type RequestTransformAction = Literal["skip", "unchanged"]


def _has_known_extension(path: str | Path) -> bool:
    """Return ``True`` if the path has a recognized file extension."""
    p = Path(path)
    return bool(p.suffix and mimetypes.guess_type(p.name, strict=False)[0])


def _normalize_candidate_url(
    raw: str,
    base: URL,
    api_path_prefixes: Sequence[str],
    max_url_len: int,
    candidate_url_trim_chars: str,
) -> str | None:
    """
    Normalize a candidate URL into a canonical same-origin *page* URL.

    Rules:
      - Allow only HTTP/HTTPS after resolving relative URLs.
      - Keep same origin only.
      - Drop fragments and normalize trailing slashes.
      - Reject obvious assets (``/_next/`` or known extensions).
      - Reject configured API prefixes.
      - Reject non-navigational schemes (``mailto:``, ``data:``, etc.).
    """
    s = clean_candidate_url_text(raw, candidate_url_trim_chars)
    if not s:
        return None

    # Pure fragment links are not crawl targets.
    if s.startswith("#"):
        return None

    # Skip non-navigation / unsupported schemes.
    if s.startswith(
        (
            "mailto:",
            "tel:",
            "javascript:",
            "data:",
            "blob:",
            "ws:",
            "wss:",
            "file:",
            "about:",
            "urn:",
            "chrome:",
            "chrome-extension:",
            "moz-extension:",
            "safari-extension:",
            "edge:",
            "intent:",
            "view-source:",
        )
    ):
        return None

    if len(s) > max_url_len:
        return None

    try:
        u = base.join(URL(s))
    except Exception:
        return None

    if not is_absolute_http_url(u):
        return None
    if u.origin() != base.origin():
        return None

    path = u.path or "/"
    if looks_like_api_path(path, api_path_prefixes):
        return None

    # Assets are handled by the route mirror, not by page crawling.
    if "/_next/" in path or _has_known_extension(path):
        return None

    return str(canonicalize_page_url(u))


def _filter_and_normalize_many(
    raw_urls: list[Any],
    base_url: URL,
    api_path_prefixes: Sequence[str],
    max_url_len: int,
    candidate_url_trim_chars: str,
) -> list[str]:
    """Normalize a list of raw URL strings into canonical page URLs (dedup + sort)."""
    found: set[str] = set()

    for raw in raw_urls or []:
        if not isinstance(raw, str):
            continue
        if normalized := _normalize_candidate_url(
            raw, base_url, api_path_prefixes, max_url_len, candidate_url_trim_chars
        ):
            found.add(normalized)

    return sorted(found)


def extract_urls_from_json_bytes(
    data: bytes,
    base_url: URL,
    api_path_prefixes: Sequence[str],
    max_url_len: int,
    candidate_url_trim_chars: str,
) -> list[str]:
    """
    Extract crawlable page URLs from a JSON payload by walking all string values.

    Container types:
      - Mapping: walk values
      - Sequence (except bytes/str): walk items
    """
    if not data:
        return []

    try:
        parsed: Any = json.loads(data)
    except Exception:
        return []

    found: set[str] = set()
    stack: list[Any] = [parsed]

    while stack:
        v = stack.pop()
        if v is None:
            continue

        if isinstance(v, str):
            if normalized := _normalize_candidate_url(
                v, base_url, api_path_prefixes, max_url_len, candidate_url_trim_chars
            ):
                found.add(normalized)
            continue

        if isinstance(v, Mapping):
            stack.extend(v.values())
            continue

        if isinstance(v, Sequence) and not isinstance(v, (str, bytes, bytearray)):
            stack.extend(v)
            continue

    return sorted(found)


async def extract_page_urls_via_js(
    ctx: PlaywrightCrawlingContext,
    base_url: URL,
    api_path_prefixes: Sequence[str],
    max_url_len: int,
    candidate_url_trim_chars: str,
) -> list[str]:
    """
    Extract candidate URLs from the page via JS:
      - ``a[href]`` and preload/prefetch links.
      - ``__NEXT_DATA__`` strings.
      - Common asset tags and ``srcset``.
    """
    raw_urls: list[Any] = await ctx.page.evaluate(load_js("extract_page_urls.js"))

    return _filter_and_normalize_many(
        raw_urls, base_url, api_path_prefixes, max_url_len, candidate_url_trim_chars
    )


def transform_enqueue_request(
    base_url: URL, api_path_prefixes: Sequence[str], max_url_len: int, candidate_url_trim_chars: str
) -> Callable[[RequestOptions], RequestTransformAction | RequestOptions]:
    """
    Crawlee enqueue transform:
      - Normalize URL.
      - Use normalized URL as ``unique_key`` for dedup.
    """

    def _fn(opts: RequestOptions) -> RequestTransformAction | RequestOptions:
        raw = opts.get("url")
        if not isinstance(raw, str):
            return "skip"

        normalized = _normalize_candidate_url(
            raw, base_url, api_path_prefixes, max_url_len, candidate_url_trim_chars
        )
        if not normalized:
            return "skip"

        opts["url"] = normalized
        opts["unique_key"] = normalized
        return opts

    return _fn


def looks_like_api_path(path: str, api_path_prefixes: Sequence[str]) -> bool:
    """Return ``True`` if the path matches any configured API prefix."""
    return any(prefix and path_has_prefix(path, prefix) for prefix in api_path_prefixes)
